from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
# Put the in-repo SDK first, ahead of any `neurosoc` installed from PyPI, so the tests exercise this checkout.
for path in (REPO_ROOT / "inference-service", REPO_ROOT / "sdk" / "python"):
    if str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))

from api.routes.universal import UniversalHooks, build_router  # noqa: E402
from core.universal import MemoryKV, SiteRegistry, UniversalEngine  # noqa: E402
from neurosoc import ActionBlocked, NeuroSOC, NeuroSOCError  # noqa: E402


async def _allow(_websocket) -> bool:
    return True


@pytest.fixture
def soc():
    kv = MemoryKV()
    registry = SiteRegistry(kv)
    _, secret = registry.create("local", "Agent platform", [], mode="enforce")
    app = FastAPI()
    app.include_router(build_router(UniversalEngine(kv), registry, UniversalHooks(
        hash_secret="test", tenant_of=lambda r: "local", roles_of=lambda r: None,
        client_ip=lambda r: "198.51.100.7", authorize_websocket=_allow, websocket_tenant=lambda w: "local")))
    http = TestClient(app)

    def transport(method: str, path: str, body):
        response = http.request(method, path, json=body, headers={"X-NeuroSOC-Key": secret})
        if response.status_code >= 400:
            raise NeuroSOCError(f"HTTP {response.status_code}")
        return response.json()

    return NeuroSOC("http://testserver", secret, transport=transport)


def test_guarded_tool_runs_normally_then_blocks_a_hijacked_transfer(soc):
    executed: list[tuple[str, float]] = []

    @soc.guard_tool(agent_id="flows-agent-1", action="token.transfer", resource="treasury",
                    resource_type="wallet", sensitivity="critical")
    def transfer(to: str, amount: float, instruction_source: str = "owner") -> str:
        executed.append((to, amount))
        return "sent"

    for index in range(25):
        assert transfer("pool-A" if index % 2 else "pool-B", 10 + index % 4) == "sent"

    with pytest.raises(ActionBlocked) as blocked:
        transfer("attacker-wallet", 5000, instruction_source="external_content")
    assert blocked.value.verdict.action == "pause_agent"
    assert any("outside content" in reason for reason in blocked.value.verdict.reasons)
    assert ("attacker-wallet", 5000) not in executed, "the tool body never ran"


def test_unreachable_neurosoc_fails_closed_by_default():
    def down(method, path, body):
        raise NeuroSOCError("unreachable")

    soc = NeuroSOC("http://nowhere", "sk_test", transport=down)

    @soc.guard_tool(agent_id="agent-2", action="token.transfer", resource="treasury")
    def transfer(to: str, amount: float):
        return "sent"

    with pytest.raises(ActionBlocked):
        transfer("pool-A", 1)

    @soc.guard_tool(agent_id="agent-2", action="api.call", resource="search", fail_open=True)
    def search(query: str):
        return "results"

    assert search("docs") == "results"


def test_backend_session_check(soc):
    verdict = soc.track(entity_id="wallet-5", action="reward.claim", resource_id="campaign-9",
                        resource_type="campaign", session_id="session-backend-1")
    assert verdict.verdict in {"ok", "review", "suspected_bot"}
    looked_up = soc.session_verdict("session-backend-1")
    assert looked_up.verdict == verdict.verdict
    assert soc.session_verdict("session-that-never-existed").verdict == "unknown"


def test_publishable_keys_are_refused_on_servers():
    with pytest.raises(ValueError):
        NeuroSOC("http://localhost:8000", "pk_browser_key")


def test_async_tools_are_guarded_without_blocking_and_blocked_calls_never_run(soc):
    import asyncio

    executed: list[str] = []

    @soc.guard_tool(agent_id="async-agent", action="token.transfer", resource="treasury",
                    resource_type="wallet", sensitivity="critical")
    async def transfer(to: str, amount: float, instruction_source: str = "owner") -> str:
        executed.append(to)
        return "sent"

    async def scenario() -> None:
        for index in range(25):
            assert await transfer("pool-A" if index % 2 else "pool-B", 10 + index % 4) == "sent"
        with pytest.raises(ActionBlocked):
            await transfer("attacker-wallet", 5000, instruction_source="external_content")

    # A worker thread has its own event-loop state, so other tests' loop setup is untouched.
    import threading

    errors: list[BaseException] = []

    def run() -> None:
        try:
            asyncio.run(scenario())
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread below
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()
    if errors:
        raise errors[0]
    assert "attacker-wallet" not in executed


def test_http_sends_a_user_agent_and_retries_transient_failures_but_not_client_errors():
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[tuple[str, str]] = []
    plan = {"/api/v1/sdk/sessions/a/verdict": [503, 200], "/api/v1/sdk/sessions/b/verdict": [401, 200]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append((self.path, self.headers.get("User-Agent", "")))
            status = plan[self.path].pop(0)
            body = _json.dumps({"verdict": "ok", "action": "allow"} if status == 200 else {"detail": "x"}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = NeuroSOC(f"http://127.0.0.1:{server.server_port}", "sk_test", retries=1)
        assert client.session_verdict("a").action == "allow"
        assert len([p for p, _ in seen if p.endswith("/a/verdict")]) == 2, "retried the 503 once"
        with pytest.raises(NeuroSOCError) as refused:
            client.session_verdict("b")
        assert refused.value.status == 401
        assert len([p for p, _ in seen if p.endswith("/b/verdict")]) == 1, "a 401 is not retried"
        assert all(agent.startswith("neurosoc-python/") for _, agent in seen)
    finally:
        server.shutdown()


def test_endpoint_must_be_a_url():
    with pytest.raises(ValueError):
        NeuroSOC("localhost:8000", "sk_test")
