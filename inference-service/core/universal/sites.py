"""Site registry: every website or agent platform that installs the SDK is a site.

A site belongs to one tenant and holds:
  - a publishable key (``pk_``): safe to put in a page; can only send events and read its config
  - a secret key (``sk_``): server-side only; also reads session verdicts and guards agent actions
  - the origins allowed to send browser events with its publishable key
  - a mode (``observe`` or ``enforce``), its rules file, and webhook targets

Secret keys are stored as SHA-256 digests; the plain value is shown once, at creation.
Sites can be seeded at startup from ``UNIVERSAL_SITES_FILE`` (a JSON list) for local demos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit

from .store import get_json, set_json
from .taxonomy import ACTIONS

log = logging.getLogger(__name__)

MODES = {"observe", "enforce"}
APP_TYPES = {"web", "agent", "both"}
MAX_AGENTS = 20
MAX_TOOLS = 50
MAX_RESOURCES = 50
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,62}$")
TOOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
RESOURCE_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
PRESETS_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "sdk" / "presets",
    Path("/sdk/presets"),
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


EXTENSION_WILDCARD = "chrome-extension://*"


def canonical_origin(value: str) -> str | None:
    value = value.strip()
    if value == EXTENSION_WILDCARD:
        return value
    if value.startswith("chrome-extension://"):
        extension_id = value[len("chrome-extension://"):].rstrip("/")
        return value.rstrip("/") if extension_id.isalnum() else None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def normalize_agents(agents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate and canonicalize a site's agent registry.

    Each agent is ``{agent_id, name, tools[], sensitive_actions[], authorized_resources[],
    max_sensitive_per_minute?}``. The guard treats an empty ``tools`` or ``authorized_resources`` list as
    "not restricted", and a site with no agents at all as "no policy" (the anomaly detectors still run).
    """
    if agents is None:
        return []
    if len(agents) > MAX_AGENTS:
        raise ValueError(f"A site can register at most {MAX_AGENTS} agents")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in agents:
        agent_id = str(raw.get("agent_id", "")).strip()
        if not AGENT_ID_RE.match(agent_id):
            raise ValueError(f"Invalid agent id: {agent_id!r}")
        if agent_id in seen:
            raise ValueError(f"Duplicate agent id: {agent_id}")
        seen.add(agent_id)

        def _names(field: str, pattern: re.Pattern[str], limit: int) -> list[str]:
            values = [str(v).strip() for v in raw.get(field) or []]
            if len(values) > limit:
                raise ValueError(f"{field} allows at most {limit} entries")
            bad = [v for v in values if not pattern.match(v)]
            if bad:
                raise ValueError(f"Invalid {field} entry: {bad[0]!r}")
            return list(dict.fromkeys(values))

        sensitive = _names("sensitive_actions", re.compile(r"^[a-z]+(\.[a-z_]+)+$"), MAX_TOOLS)
        unknown = [a for a in sensitive if a not in ACTIONS]
        if unknown:
            raise ValueError(f"sensitive_actions must be NeuroSOC taxonomy actions; unknown: {unknown[0]}")
        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "name": str(raw.get("name") or agent_id)[:128],
            "tools": _names("tools", TOOL_RE, MAX_TOOLS),
            "sensitive_actions": sensitive,
            "authorized_resources": _names("authorized_resources", RESOURCE_RE, MAX_RESOURCES),
        }
        limit = raw.get("max_sensitive_per_minute")
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
                raise ValueError("max_sensitive_per_minute must be an integer from 1 to 1000")
            entry["max_sensitive_per_minute"] = limit
        out.append(entry)
    return out


def _clean_url(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or len(url) > 256:
        raise ValueError("url must be an http(s) URL of at most 256 characters")
    return url.strip()


def load_preset(name: str) -> list[dict[str, Any]]:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    for directory in PRESETS_DIR_CANDIDATES:
        path = directory / f"{safe}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("rules", [])
    raise ValueError(f"Unknown rules preset: {name}")


class SiteRegistry:
    def __init__(self, kv: Any) -> None:
        self.kv = kv

    # ── lookups ─────────────────────────────────────────────────────────────
    def get(self, site_id: str) -> dict[str, Any] | None:
        return get_json(self.kv, f"site:{site_id}")

    def by_publishable_key(self, key: str) -> dict[str, Any] | None:
        site_id = self.kv.get(f"sitekey:pk:{key}") if key.startswith("pk_") else None
        return self.get(site_id) if site_id else None

    def by_secret_key(self, key: str) -> dict[str, Any] | None:
        if not key.startswith("sk_"):
            return None
        site_id = self.kv.get(f"sitekey:sk:{_digest(key)}")
        site = self.get(site_id) if site_id else None
        if site and hmac.compare_digest(site["secret_key_digest"], _digest(key)):
            return site
        return None

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        sites = [self.get(site_id) for site_id in sorted(self.kv.smembers(f"sites:{tenant_id}"))]
        return [self.public_view(site) for site in sites if site]

    def origin_allowed_anywhere(self, origin: str) -> bool:
        canonical = canonical_origin(origin)
        return bool(canonical) and bool(self.kv.smembers(f"origin:{canonical}"))

    @staticmethod
    def origin_allowed(site: dict[str, Any], origin: str | None) -> bool:
        canonical = canonical_origin(origin or "")
        allowed = site.get("allowed_origins", [])
        if not canonical:
            return False
        # A site may opt in to the NeuroSOC Lens extension (observe-only demos on sites we do not own).
        if canonical.startswith("chrome-extension://") and EXTENSION_WILDCARD in allowed:
            return True
        return canonical in allowed

    @staticmethod
    def public_view(site: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in site.items() if key not in {"secret_key_digest", "webhooks"}} | {
            "webhooks": [{"url": hook["url"]} for hook in site.get("webhooks", [])]}

    # ── writes ──────────────────────────────────────────────────────────────
    def _save(self, site: dict[str, Any]) -> None:
        set_json(self.kv, f"site:{site['site_id']}", site)
        self.kv.sadd(f"sites:{site['tenant_id']}", site["site_id"])
        for origin in site.get("allowed_origins", []):
            self.kv.sadd(f"origin:{origin}", site["site_id"])

    def create(self, tenant_id: str, name: str, allowed_origins: list[str], mode: str = "observe",
               rules: list[dict[str, Any]] | None = None, preset: str | None = None,
               publishable_key: str | None = None, secret_key: str | None = None,
               site_id: str | None = None, agents: list[dict[str, Any]] | None = None,
               app_type: str = "web", url: str | None = None, demo: bool = False) -> tuple[dict[str, Any], str]:
        if mode not in MODES:
            raise ValueError("mode must be observe or enforce")
        if app_type not in APP_TYPES:
            raise ValueError("app_type must be web, agent or both")
        agents = normalize_agents(agents)
        url = _clean_url(url)
        origins = []
        for origin in allowed_origins:
            canonical = canonical_origin(origin)
            if canonical is None:
                raise ValueError(f"Invalid origin: {origin}")
            origins.append(canonical)
        secret = secret_key or "sk_" + secrets.token_urlsafe(32)
        site = {
            "site_id": site_id or uuid.uuid4().hex[:16],
            "tenant_id": tenant_id,
            "name": name,
            "publishable_key": publishable_key or "pk_" + secrets.token_urlsafe(24),
            "secret_key_digest": _digest(secret),
            "allowed_origins": origins,
            "mode": mode,
            "preset": preset,
            "rules": rules if rules is not None else (load_preset(preset) if preset else []),
            "agents": agents,
            "app_type": app_type,
            "url": url,
            "demo": bool(demo),
            "webhooks": [],
            "created_at": time.time(),
        }
        self._save(site)
        self.kv.set(f"sitekey:pk:{site['publishable_key']}", site["site_id"])
        self.kv.set(f"sitekey:sk:{site['secret_key_digest']}", site["site_id"])
        return site, secret

    def update(self, site_id: str, *, rules: list[dict[str, Any]] | None = None, mode: str | None = None,
               allowed_origins: list[str] | None = None, agents: list[dict[str, Any]] | None = None,
               app_type: str | None = None, url: str | None = None) -> dict[str, Any] | None:
        site = self.get(site_id)
        if site is None:
            return None
        if agents is not None:
            site["agents"] = normalize_agents(agents)
        if app_type is not None:
            if app_type not in APP_TYPES:
                raise ValueError("app_type must be web, agent or both")
            site["app_type"] = app_type
        if url is not None:
            site["url"] = _clean_url(url)
        if rules is not None:
            site["rules"] = rules
        if mode is not None:
            if mode not in MODES:
                raise ValueError("mode must be observe or enforce")
            site["mode"] = mode
        if allowed_origins is not None:
            canonical = [canonical_origin(origin) for origin in allowed_origins]
            if any(origin is None for origin in canonical):
                raise ValueError("Invalid origin")
            for origin in site["allowed_origins"]:
                self.kv.srem(f"origin:{origin}", site_id)
            site["allowed_origins"] = canonical
        self._save(site)
        return site

    def mark_demo(self, site_id: str, demo: bool = True) -> dict[str, Any] | None:
        """Flag a site as the connected NovaTrust demo application (set only by the demo router)."""
        site = self.get(site_id)
        if site is None:
            return None
        site["demo"] = bool(demo)
        self._save(site)
        return site

    def add_webhook(self, site_id: str, url: str) -> tuple[dict[str, Any], str] | None:
        site = self.get(site_id)
        if site is None:
            return None
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Webhook URL must be http or https")
        signing_secret = "whsec_" + secrets.token_urlsafe(24)
        site.setdefault("webhooks", []).append({"url": url, "secret": signing_secret})
        self._save(site)
        return site, signing_secret

    def seed_from_file(self, path: str) -> int:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        seeded = 0
        for entry in entries:
            if self.get(entry["site_id"]) is not None:
                continue
            self.create(
                tenant_id=entry["tenant_id"], name=entry["name"], allowed_origins=entry.get("allowed_origins", []),
                mode=entry.get("mode", "observe"), rules=entry.get("rules"), preset=entry.get("preset"),
                publishable_key=entry.get("publishable_key"), secret_key=entry.get("secret_key"),
                site_id=entry["site_id"], agents=entry.get("agents"), app_type=entry.get("app_type", "web"),
                url=entry.get("url"), demo=bool(entry.get("demo", False)),
            )
            seeded += 1
        return seeded


def deliver_webhooks(site: dict[str, Any], verdict: dict[str, Any]) -> None:
    """POST a non-ok verdict to the site's webhooks in the background, signed with HMAC-SHA256."""
    hooks = site.get("webhooks") or []
    if not hooks or verdict.get("verdict") == "ok":
        return
    body = json.dumps({"type": "neurosoc.verdict", "data": verdict}).encode("utf-8")

    def _send() -> None:
        for hook in hooks:
            signature = hmac.new(hook["secret"].encode("utf-8"), body, hashlib.sha256).hexdigest()
            request = urllib_request.Request(hook["url"], data=body, method="POST", headers={
                "Content-Type": "application/json", "X-NeuroSOC-Signature": f"sha256={signature}"})
            try:
                with urllib_request.urlopen(request, timeout=5):
                    pass
            except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, ValueError) as exc:
                log.warning("Webhook delivery to %s failed: %s", urlsplit(hook["url"]).hostname, type(exc).__name__)

    threading.Thread(target=_send, daemon=True).start()
