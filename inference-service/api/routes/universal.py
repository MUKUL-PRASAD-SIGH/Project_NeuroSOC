"""
api/routes/universal.py

Routes for the NeuroSOC SDK and the universal behavioral engine. Mounted by main.py only when
ENABLE_UNIVERSAL_ENGINE=true; no existing route is changed.

SDK routes (site keys, not Keycloak; CORS per registered site):
  POST /api/v1/sdk/events                      - one batch of behavior events -> verdicts   (pk or sk)
  POST /api/v1/sdk/guard                       - score one pending action before it runs   (sk)
  GET  /api/v1/sdk/sessions/{session}/verdict  - server-side check before paying/executing (sk)
  GET  /api/v1/sdk/config                      - the site's mode and rules, for the script (pk)

Analyst routes (Keycloak via the existing middleware, tenant from the token):
  GET  /api/v1/universal/verdicts/latest
  GET  /api/v1/universal/entities/{entity_type}/{entity_id}
  GET  /api/v1/universal/resources/{resource_id}/integrity
  POST /api/v1/universal/verdicts/{verdict_id}/override
  GET  /api/v1/universal/sites        POST /api/v1/universal/sites
  PUT  /api/v1/universal/sites/{site_id}
  POST /api/v1/universal/sites/{site_id}/webhooks
  WS   /api/v1/universal/ws           - live universal verdicts (separate from /ws/alerts)
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.universal.engine import UniversalEngine
from core.universal.ingest import SdkBatch, SdkEvent, normalize, schema_view
from core.universal.sites import SiteRegistry, deliver_webhooks, load_preset

log = logging.getLogger(__name__)

IDEMPOTENCY_TTL = 3600
SITE_ADMIN_ROLES = {"operator", "admin", "platform-admin"}


@dataclass
class UniversalHooks:
    hash_secret: str
    tenant_of: Callable[[Request], str]
    roles_of: Callable[[Request], set[str] | None]
    client_ip: Callable[[Request], str | None]
    authorize_websocket: Callable[[WebSocket], Awaitable[bool]]
    websocket_tenant: Callable[[WebSocket], str]
    on_shadow: Callable[[dict[str, Any], str | None], None] | None = None
    publish: Callable[[dict[str, Any]], None] | None = None
    audit: Callable[[Request, str, str, dict[str, Any]], Awaitable[bool]] | None = None


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["restore", "confirm"]
    note: str | None = Field(default=None, max_length=500)


class AgentSpec(BaseModel):
    """One AI agent registered to a site. The guard pauses an agent that steps outside this."""
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=2, max_length=63)
    name: str | None = Field(default=None, max_length=128)
    tools: list[str] = Field(default_factory=list, max_length=50)
    sensitive_actions: list[str] = Field(default_factory=list, max_length=50)
    authorized_resources: list[str] = Field(default_factory=list, max_length=50)
    max_sensitive_per_minute: int | None = Field(default=None, ge=1, le=1000)


class SiteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["observe", "enforce"] = "observe"
    preset: str | None = Field(default=None, max_length=64)
    rules: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    app_type: Literal["web", "agent", "both"] = "web"
    url: str | None = Field(default=None, max_length=256)
    agents: list[AgentSpec] = Field(default_factory=list, max_length=20)


class SiteUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["observe", "enforce"] | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=20)
    rules: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    preset: str | None = Field(default=None, max_length=64)
    app_type: Literal["web", "agent", "both"] | None = None
    url: str | None = Field(default=None, max_length=256)
    agents: list[AgentSpec] | None = Field(default=None, max_length=20)


class WebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=512)


class _Stream:
    def __init__(self) -> None:
        self.clients: list[tuple[WebSocket, str]] = []

    async def broadcast(self, tenant: str, message: dict[str, Any]) -> None:
        for websocket, client_tenant in list(self.clients):
            if client_tenant != tenant:
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                self.clients.remove((websocket, client_tenant))


def build_router(engine: UniversalEngine, registry: SiteRegistry, hooks: UniversalHooks,
                 extra_routers: tuple[APIRouter, ...] = ()) -> APIRouter:
    """``extra_routers`` are mounted as-is; main.py uses this for the demo router, only in demo mode."""
    router = APIRouter()
    stream = _Stream()

    # ── helpers ─────────────────────────────────────────────────────────────
    def site_for_key(key: str | None, request: Request, *, secret_only: bool = False) -> tuple[dict[str, Any], str]:
        if not key:
            raise HTTPException(status_code=401, detail="Missing X-NeuroSOC-Key.")
        site = registry.by_secret_key(key)
        if site is not None:
            return site, "sk"
        if secret_only:
            raise HTTPException(status_code=401, detail="A secret key is required for this route.")
        site = registry.by_publishable_key(key)
        if site is None:
            raise HTTPException(status_code=401, detail="Unknown NeuroSOC key.")
        # Browsers omit Origin on same-origin GETs (the demo serves the page and the API from one host), so fall
        # back to the Referer's origin. Both headers are only a browser-side control, not authentication.
        origin = request.headers.get("origin")
        if not origin:
            referer = urlsplit(request.headers.get("referer") or "")
            origin = f"{referer.scheme}://{referer.netloc}" if referer.scheme and referer.netloc else None
        if not registry.origin_allowed(site, origin):
            raise HTTPException(status_code=403, detail="This origin is not registered for this key.")
        return site, "pk"

    def require_site_admin(request: Request) -> None:
        roles = hooks.roles_of(request)
        if roles is not None and not roles & SITE_ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Managing sites requires the operator or admin role.")

    def site_in_tenant(site_id: str, request: Request) -> dict[str, Any]:
        site = registry.get(site_id)
        if site is None or site["tenant_id"] != hooks.tenant_of(request):
            raise HTTPException(status_code=404, detail="Site not found.")
        return site

    def enrich(verdict: dict[str, Any]) -> dict[str, Any]:
        """Add the application's current name (read at response time, so renames show up immediately)."""
        site = registry.get(verdict["site_id"]) if verdict.get("site_id") else None
        return {**verdict, "site_name": site["name"] if site else None}

    async def score(raw: SdkEvent, site: dict[str, Any], request: Request, source: str) -> dict[str, Any]:
        tenant = site["tenant_id"]
        client_ip = hooks.client_ip(request)
        event = normalize(raw, site=site, client_ip=client_ip, origin=request.headers.get("origin"),
                          hash_secret=hooks.hash_secret, source=source)
        idempotency_key = f"{tenant}:idem:{event['idempotency_key']}"
        cached_id = engine.kv.get(idempotency_key)
        if cached_id:
            cached = engine.verdict(tenant, cached_id)
            if cached:
                return enrich(cached)
        previous = engine.session_verdict(tenant, event["session_id"])
        already_shadowed = bool(previous and previous.get("action") == "shadow")
        verdict = await run_in_threadpool(engine.process, event, mode=site.get("mode", "observe"),
                                          agent_policy=site.get("agents") or None)
        engine.kv.set(idempotency_key, verdict["verdict_id"], ttl=IDEMPOTENCY_TTL)

        if hooks.publish is not None:
            try:
                hooks.publish(schema_view(event))
            except Exception as exc:
                log.warning("Could not publish behavior event: %s", type(exc).__name__)
        # Mirror a session into the sandbox once, when it first becomes shadowed, not on every event.
        if verdict["action"] == "shadow" and verdict["enforced"] and not already_shadowed and hooks.on_shadow is not None:
            await run_in_threadpool(hooks.on_shadow, verdict, client_ip)
        verdict = enrich(verdict)
        deliver_webhooks(site, verdict)
        await stream.broadcast(tenant, {"type": "universal.verdict", "data": verdict})
        return verdict

    # ── SDK routes ──────────────────────────────────────────────────────────
    @router.post("/api/v1/sdk/events")
    async def sdk_events(request: Request, key: str | None = Query(default=None, max_length=128),
                         x_neurosoc_key: str | None = Header(default=None)) -> dict[str, Any]:
        # Browsers send this as a CORS "simple request" (text/plain body, key in the query) so it
        # needs no preflight and also works from navigator.sendBeacon when a page closes.
        site, key_kind = site_for_key(x_neurosoc_key or key, request)
        try:
            batch = SdkBatch.model_validate_json(await request.body())
        except ValidationError:
            raise HTTPException(status_code=422, detail="Request validation failed.") from None
        source = "sdk-js" if key_kind == "pk" else "sdk-py"
        verdicts = [await score(raw, site, request, source) for raw in batch.events]
        if key_kind == "pk":
            verdicts = [_browser_verdict(v) for v in verdicts]
        return {"verdicts": verdicts, "mode": site.get("mode", "observe")}

    @router.post("/api/v1/sdk/guard")
    async def sdk_guard(raw: SdkEvent, request: Request,
                        x_neurosoc_key: str | None = Header(default=None)) -> dict[str, Any]:
        site, _ = site_for_key(x_neurosoc_key, request, secret_only=True)
        return await score(raw, site, request, "sdk-py")

    @router.get("/api/v1/sdk/sessions/{session_id}/verdict")
    async def sdk_session_verdict(session_id: str, request: Request,
                                  x_neurosoc_key: str | None = Header(default=None)) -> dict[str, Any]:
        site, _ = site_for_key(x_neurosoc_key, request, secret_only=True)
        verdict = engine.session_verdict(site["tenant_id"], session_id[:128])
        if verdict is None:
            return {"session_id": session_id, "verdict": "unknown", "action": "allow", "risk": 0.0, "reasons": []}
        return {"session_id": session_id, **verdict}

    @router.get("/api/v1/sdk/config")
    async def sdk_config(request: Request, key: str | None = Query(default=None, max_length=128),
                         x_neurosoc_key: str | None = Header(default=None)) -> dict[str, Any]:
        site, _ = site_for_key(x_neurosoc_key or key, request)
        return {"site_id": site["site_id"], "mode": site.get("mode", "observe"), "rules": site.get("rules", [])}

    # ── analyst routes ──────────────────────────────────────────────────────
    @router.get("/api/v1/universal/verdicts/latest")
    async def latest(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"verdicts": [enrich(v) for v in engine.latest_verdicts(hooks.tenant_of(request), limit)]}

    @router.get("/api/v1/universal/entities/{entity_type}/{entity_id}")
    async def entity(entity_type: str, entity_id: str, request: Request) -> dict[str, Any]:
        profile = engine.entity_profile(hooks.tenant_of(request), entity_type[:32], entity_id[:256])
        if profile is None:
            raise HTTPException(status_code=404, detail="Entity not found.")
        return profile

    @router.get("/api/v1/universal/resources/{resource_id}/integrity")
    async def integrity(resource_id: str, request: Request) -> dict[str, Any]:
        return engine.resource_integrity(hooks.tenant_of(request), resource_id[:256])

    @router.post("/api/v1/universal/verdicts/{verdict_id}/override")
    async def override(verdict_id: str, body: OverrideRequest, request: Request) -> dict[str, Any]:
        identity = getattr(request.state, "identity", None) or {}
        result = engine.override(hooks.tenant_of(request), verdict_id[:64], body.decision, identity.get("sub"))
        if result is None:
            raise HTTPException(status_code=404, detail="Verdict not found.")
        if hooks.audit is not None:
            await hooks.audit(request, "security.response_action", "succeeded",
                              {"universal_override": body.decision, "verdict_id": verdict_id[:64]})
        if hooks.publish is not None:
            try:
                hooks.publish({"event_type": "behavior.label", "tenant_id": result["tenant_id"],
                               "verdict_id": verdict_id, "verdict": result["verdict"], "decision": body.decision})
            except Exception as exc:
                log.warning("Could not publish override label: %s", type(exc).__name__)
        return result

    @router.get("/api/v1/universal/sites")
    async def list_sites(request: Request) -> dict[str, Any]:
        return {"sites": registry.list(hooks.tenant_of(request))}

    @router.post("/api/v1/universal/sites", status_code=201)
    async def create_site(body: SiteCreateRequest, request: Request) -> dict[str, Any]:
        require_site_admin(request)
        try:
            site, secret = registry.create(hooks.tenant_of(request), body.name, body.allowed_origins,
                                           mode=body.mode, rules=body.rules, preset=body.preset,
                                           agents=[a.model_dump(exclude_none=True) for a in body.agents],
                                           app_type=body.app_type, url=body.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"site": registry.public_view(site), "secret_key": secret,
                "note": "Store the secret key now; it is not shown again."}

    @router.put("/api/v1/universal/sites/{site_id}")
    async def update_site(site_id: str, body: SiteUpdateRequest, request: Request) -> dict[str, Any]:
        require_site_admin(request)
        site_in_tenant(site_id, request)
        try:
            rules = load_preset(body.preset) if body.preset else body.rules
            site = registry.update(
                site_id, rules=rules, mode=body.mode, allowed_origins=body.allowed_origins, app_type=body.app_type,
                url=body.url,
                agents=None if body.agents is None else [a.model_dump(exclude_none=True) for a in body.agents])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"site": registry.public_view(site)}

    @router.post("/api/v1/universal/sites/{site_id}/webhooks", status_code=201)
    async def add_webhook(site_id: str, body: WebhookRequest, request: Request) -> dict[str, Any]:
        require_site_admin(request)
        site_in_tenant(site_id, request)
        try:
            site, signing_secret = registry.add_webhook(site_id, body.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"site": registry.public_view(site), "signing_secret": signing_secret}

    @router.websocket("/api/v1/universal/ws")
    async def universal_ws(websocket: WebSocket) -> None:
        if not await hooks.authorize_websocket(websocket):
            return
        tenant = hooks.websocket_tenant(websocket)
        await websocket.accept()
        stream.clients.append((websocket, tenant))
        try:
            await websocket.send_json({"type": "universal.snapshot",
                                       "data": [enrich(v) for v in engine.latest_verdicts(tenant, 50)]})
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if (websocket, tenant) in stream.clients:
                stream.clients.remove((websocket, tenant))

    for extra in extra_routers:
        router.include_router(extra)

    return router


def _browser_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    """What a browser may see: only the response to render. Scores, reasons and linked accounts
    would tell a bot what gave it away, so they stay server-side (secret key, webhooks, dashboard)."""
    return {key: verdict[key] for key in ("verdict_id", "session_id", "event_id", "action", "enforced")}
