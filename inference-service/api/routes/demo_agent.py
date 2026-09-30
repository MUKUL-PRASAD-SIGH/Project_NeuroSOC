"""
api/routes/demo_agent.py

Routes for the NovaTrust demo application (the customer site and its Nova AI agent). Mounted by main.py
ONLY when NEUROSOC_DEMO_MODE=true (and the universal engine is on); otherwise none of these paths exist
and every one answers 404. main.py refuses to start in staging or production with demo mode enabled.

  GET  /api/v1/demo/config                 demo mode, connected application (never a secret), agent state
  POST /api/v1/demo/connect                hand the wizard-created application's secret key to the demo backend
  GET  /api/v1/demo/account                this browser session's fake account
  POST /api/v1/demo/account/reset          fresh account and a fresh (un-paused) agent
  POST /api/v1/demo/agent/chat             one message to Nova AI; tool calls pass the NeuroSOC guard
  POST /api/v1/demo/transfer               a person sending money from the Transfer page (also guarded)
  POST /api/v1/demo/transfer/{id}/confirm  confirm an agent-prepared transfer
  POST /api/v1/demo/transfer/{id}/cancel   cancel one
  POST /api/v1/demo/simulate               run a labelled security simulation on the demo's own fake data

Browser sessions are told apart by the X-Demo-Session header (a random id the page keeps in sessionStorage).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool  # noqa: F401  (handlers below are sync and run in the pool)
from pydantic import BaseModel, ConfigDict, Field

from core.demo.runtime import SIMULATIONS, DemoRuntime, NotConnected
from core.demo.tools import AGENT_ID, TOOL_NAMES, TREASURY

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

DEFAULT_AGENT = {
    "agent_id": AGENT_ID,
    "name": "Nova AI",
    "tools": list(TOOL_NAMES),
    "sensitive_actions": ["token.transfer"],
    "authorized_resources": [TREASURY],
}


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret_key: str = Field(min_length=8, max_length=128)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="", max_length=1000)
    content: str | None = Field(default=None, max_length=4000)


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.@-]*$")
    amount: float = Field(gt=0, le=1_000_000)
    purpose: str = Field(default="", max_length=256)


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(max_length=64)


def _trusted_client(request: Request) -> bool:
    """`connect` hands over a secret key, so it only accepts callers on this machine or a private network."""
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def build_demo_router(runtime: DemoRuntime, *, tenant_of: Callable[[Request], str]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/demo")

    def session_key(value: str | None) -> str:
        if not value or not _SESSION_RE.match(value):
            raise HTTPException(status_code=400, detail="X-Demo-Session must be 8-64 letters, digits, _ or -.")
        return value

    def connected(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except NotConnected as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    def config_body() -> dict[str, Any]:
        site = runtime.site()
        public = runtime.registry.public_view(site) if site else None
        return {"demo_mode": True, "planner": runtime.planner.name, "connected": site is not None, "site": public,
                "agent": runtime.agent_status(site), "defaults": {"agent": DEFAULT_AGENT},
                "simulations": list(SIMULATIONS)}

    @router.get("/config")
    def get_config() -> dict[str, Any]:
        return config_body()

    @router.post("/connect")
    def connect(body: ConnectRequest, request: Request) -> dict[str, Any]:
        if not _trusted_client(request):
            raise HTTPException(status_code=403, detail="The demo can only be connected from this machine or a private network.")
        try:
            runtime.connect(body.secret_key, tenant_of(request))
        except NotConnected as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        return config_body()

    @router.get("/account")
    def get_account(x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        key = session_key(x_demo_session)
        site = runtime.site()
        return {"account": runtime.sessions.get(key).snapshot(), "agent": runtime.agent_status(site)}

    @router.post("/account/reset")
    def reset_account(x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        key = session_key(x_demo_session)
        account = runtime.reset(key)
        return {"account": account.snapshot(), "agent": runtime.agent_status(runtime.site())}

    @router.post("/agent/chat")
    def chat(body: ChatRequest, x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        key = session_key(x_demo_session)
        return connected(lambda: runtime.chat(key, body.message, body.content))

    @router.post("/transfer")
    def transfer(body: TransferRequest, x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        key = session_key(x_demo_session)
        return connected(lambda: runtime.human_transfer(key, body.to, body.amount, body.purpose))

    @router.post("/transfer/{tx_id}/confirm")
    def confirm(tx_id: str, x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        return runtime.confirm(session_key(x_demo_session), tx_id[:32])

    @router.post("/transfer/{tx_id}/cancel")
    def cancel(tx_id: str, x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        return runtime.cancel(session_key(x_demo_session), tx_id[:32])

    @router.post("/simulate")
    def simulate(body: SimulateRequest, x_demo_session: str | None = Header(default=None)) -> dict[str, Any]:
        key = session_key(x_demo_session)
        if body.type not in SIMULATIONS:
            raise HTTPException(status_code=422, detail=f"type must be one of {', '.join(SIMULATIONS)}")
        return connected(lambda: runtime.simulate(key, body.type))

    return router
