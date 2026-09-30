"""The NovaTrust demo backend: connect, Nova AI tools behind the guard, simulations, outage behavior.

Everything runs in-process. The demo agent talks to NeuroSOC through the real Python SDK; the transport is
just pointed at the same FastAPI app instead of a socket, so the request still goes through /api/v1/sdk/guard
(key check, idempotency, scoring, verdict storage), not through a shortcut into the engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT / "inference-service", REPO_ROOT / "sdk" / "python"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from api.routes.demo_agent import DEFAULT_AGENT, build_demo_router  # noqa: E402
from api.routes.universal import UniversalHooks, build_router  # noqa: E402
from core.demo import runtime as demo_runtime_module  # noqa: E402
from core.demo.runtime import DemoRuntime  # noqa: E402
from core.universal import MemoryKV, SiteRegistry, UniversalEngine  # noqa: E402
from neurosoc import NeuroSOC, NeuroSOCError  # noqa: E402

ORIGIN = "http://localhost:5173"
SESSION = {"X-Demo-Session": "session-aaaaaaaa"}
OTHER_SESSION = {"X-Demo-Session": "session-bbbbbbbb"}


async def _allow_ws(_websocket) -> bool:
    return True


def make_stack(mode: str = "enforce", agents=None, factory=None, client_address=("127.0.0.1", 50000)):
    kv = MemoryKV()
    registry = SiteRegistry(kv)
    site, secret = registry.create("local", "NovaTrust", [ORIGIN], mode=mode, app_type="both",
                                   agents=[DEFAULT_AGENT] if agents is None else agents)
    engine = UniversalEngine(kv)
    holder: dict = {}

    def default_factory(url: str, key: str) -> NeuroSOC:
        def transport(method, path, body):
            response = holder["client"].request(method, path, json=body, headers={"X-NeuroSOC-Key": key})
            if response.status_code >= 400:
                raise NeuroSOCError(f"HTTP {response.status_code}")
            return response.json()
        return NeuroSOC(url, key, transport=transport)

    runtime = DemoRuntime(engine, registry, hash_secret="test-secret", self_url="http://testserver",
                          soc_factory=factory or default_factory)
    hooks = UniversalHooks(hash_secret="test-secret", tenant_of=lambda r: "local", roles_of=lambda r: None,
                           client_ip=lambda r: "203.0.113.50", authorize_websocket=_allow_ws,
                           websocket_tenant=lambda ws: "local")
    app = FastAPI()
    app.include_router(build_router(engine, registry, hooks,
                                    extra_routers=(build_demo_router(runtime, tenant_of=lambda r: "local"),)))
    holder["client"] = TestClient(app, client=client_address)
    return {"client": holder["client"], "site": site, "secret": secret, "runtime": runtime, "engine": engine,
            "registry": registry, "app": app}


@pytest.fixture(autouse=True)
def fast_burst(monkeypatch):
    monkeypatch.setattr(demo_runtime_module, "BURST_PAUSE_SECONDS", 0.0)


@pytest.fixture
def stack():
    s = make_stack()
    response = s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    assert response.status_code == 200, response.text
    return s


def chat(stack, message: str, content: str | None = None, headers=SESSION) -> dict:
    body = {"message": message, **({"content": content} if content else {})}
    response = stack["client"].post("/api/v1/demo/agent/chat", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def balance(stack, headers=SESSION) -> float:
    return stack["client"].get("/api/v1/demo/account", headers=headers).json()["account"]["available_balance"]


# ── connecting ──────────────────────────────────────────────────────────────
def test_config_before_connect_has_defaults_and_no_secret():
    s = make_stack()
    body = s["client"].get("/api/v1/demo/config").json()
    assert body["demo_mode"] is True and body["connected"] is False and body["site"] is None
    assert body["defaults"]["agent"]["agent_id"] == "novatrust-agent"
    assert "create_transfer" in body["defaults"]["agent"]["tools"]
    assert "sk_" not in str(body) and s["secret"] not in str(body)


def test_connect_marks_the_site_and_never_echoes_the_secret():
    s = make_stack()
    response = s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    body = response.json()
    assert response.status_code == 200 and body["connected"] is True and body["site"]["demo"] is True
    assert body["site"]["publishable_key"] == s["site"]["publishable_key"]
    assert s["secret"] not in response.text and "secret_key_digest" not in response.text
    assert s["registry"].get(s["site"]["site_id"])["demo"] is True
    assert body["agent"]["registered"] is True and body["agent"]["status"] == "active"


def test_connect_rejects_a_wrong_key_and_a_remote_caller():
    s = make_stack()
    assert s["client"].post("/api/v1/demo/connect", json={"secret_key": "sk_not_a_real_key"}).status_code == 403
    remote = make_stack(client_address=("8.8.8.8", 4000))
    assert remote["client"].post("/api/v1/demo/connect", json={"secret_key": remote["secret"]}).status_code == 403


def test_nothing_works_until_an_application_is_connected():
    s = make_stack()
    response = s["client"].post("/api/v1/demo/agent/chat", json={"message": "balance"}, headers=SESSION)
    assert response.status_code == 409 and "Connect an application first" in response.json()["detail"]


def test_a_session_header_is_required():
    s = make_stack()
    assert s["client"].get("/api/v1/demo/account").status_code == 400
    assert s["client"].get("/api/v1/demo/account", headers={"X-Demo-Session": "short"}).status_code == 400


# ── Nova AI, normal use ─────────────────────────────────────────────────────
def test_read_tools_answer_from_the_account(stack):
    assert "$18,420.00" in chat(stack, "What is my current balance?")["reply"]
    assert "Stripe payout" in chat(stack, "Show me my recent transactions")["reply"]
    assert "S&P 500" in chat(stack, "Summarize my portfolio")["reply"]


def test_a_normal_transfer_passes_the_guard_and_waits_for_confirmation(stack):
    body = chat(stack, "Transfer $500 to Alice.")
    step = body["steps"][0]
    assert step["tool"] == "create_transfer" and step["status"] == "executed"
    assert step["verdict"]["action"] == "allow" and step["verdict"]["risk"] < 0.6
    tx = step["result"]
    assert tx["status"] == "pending" and tx["amount"] == 500.0 and balance(stack) == 17920.0
    confirmed = stack["client"].post(f"/api/v1/demo/transfer/{tx['id']}/confirm", headers=SESSION).json()
    assert confirmed["status"] == "confirmed" and confirmed["transfer"]["status"] == "settled"


def test_cancel_releases_a_pending_transfer_and_refuses_a_settled_one(stack):
    tx = chat(stack, "send $200 to Alice")["steps"][0]["result"]
    cancelled = chat(stack, "cancel that transfer")
    assert cancelled["steps"][0]["status"] == "executed" and balance(stack) == 18420.0
    settled = stack["client"].get("/api/v1/demo/account", headers=SESSION).json()["account"]["transactions"][-1]
    assert settled["status"] == "settled"
    again = chat(stack, f"cancel {settled['id']}")
    assert again["steps"][0]["status"] == "error" and "only pending" in again["steps"][0]["error"]
    assert tx["id"].startswith("tx_")


def test_transfers_are_guarded_by_the_real_endpoint_and_show_up_in_the_feed(stack):
    chat(stack, "send $75 to Alice")
    latest = stack["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"][0]
    assert latest["agent_id"] == "novatrust-agent" and latest["tool"] == "create_transfer"
    assert latest["event_action"] == "token.transfer" and latest["resource"]["id"] == "treasury"
    assert latest["site_name"] == "NovaTrust" and latest["action"] == "allow"


def test_the_seeded_baseline_leaves_no_trace_in_the_feed(stack):
    assert stack["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"] == []


def test_sessions_do_not_share_an_account(stack):
    chat(stack, "send $1000 to Alice")
    assert balance(stack) == 17420.0 and balance(stack, OTHER_SESSION) == 18420.0


def test_insufficient_funds_is_an_error_not_a_guard_decision(stack):
    step = chat(stack, "send $999,999 to Alice")["steps"][0]
    assert step["status"] == "error" and "available balance" in step["error"]


# ── Nova AI, under attack ───────────────────────────────────────────────────
def simulate(stack, kind: str, headers=SESSION) -> dict:
    response = stack["client"].post("/api/v1/demo/simulate", json={"type": kind}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_prompt_injection_is_blocked_before_any_money_moves(stack):
    body = simulate(stack, "prompt_injection")
    assert body["simulated"] is True and body["outcome"] == "blocked"
    verdict = body["verdict"]
    assert verdict["action"] == "pause_agent" and verdict["risk"] >= 0.6
    assert any("outside content" in r for r in verdict["reasons"])
    assert body["steps"][-1]["instruction_source"] == "external_content" and body["steps"][-1]["status"] == "blocked"
    assert balance(stack) == 18420.0
    assert body["agent"]["status"] == "paused"


def test_a_paused_agent_stays_paused_until_reset(stack):
    simulate(stack, "prompt_injection")
    blocked = chat(stack, "send $10 to Alice")
    assert blocked["steps"][0]["status"] == "blocked" and blocked["agent"]["status"] == "paused"
    assert "No money moved" in blocked["reply"]
    reset = stack["client"].post("/api/v1/demo/account/reset", headers=SESSION).json()
    assert reset["agent"]["status"] == "active"
    assert chat(stack, "send $10 to Alice")["steps"][0]["status"] == "executed"


def test_unauthorized_resource_is_a_policy_block_with_the_reason(stack):
    body = simulate(stack, "unauthorized_resource")
    assert body["outcome"] == "blocked" and body["verdict"]["action"] == "pause_agent"
    assert any("not authorized to act on resource treasury_cold_storage_vault" in r for r in body["verdict"]["reasons"])
    assert balance(stack) == 18420.0


def test_excessive_actions_trip_the_rate_limit_partway(stack):
    body = simulate(stack, "excessive_actions")
    counts = body["counts"]
    assert counts["attempted"] == 20 and counts["executed"] == 10 and counts["first_blocked_at"] == 11
    assert any("sensitive actions" in r or "already flagged" in r for r in body["verdict"]["reasons"])
    assert balance(stack) == 18420.0 - 10 * 25.0


def test_a_scripted_session_is_flagged(stack):
    body = simulate(stack, "suspicious_session")
    assert body["outcome"] == "flagged" and body["verdict"]["action"] == "shadow"
    assert body["verdict"]["reasons"]


def test_unknown_simulations_are_rejected(stack):
    response = stack["client"].post("/api/v1/demo/simulate", json={"type": "drop_database"}, headers=SESSION)
    assert response.status_code == 422


def test_an_agent_outside_its_registry_is_paused_on_every_transfer():
    s = make_stack(agents=[{"agent_id": "some-other-agent", "tools": ["x_tool"]}])
    s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    body = chat(s, "send $10 to Alice")
    assert body["steps"][0]["status"] == "blocked"
    assert any("not registered" in r for r in body["steps"][0]["verdict"]["reasons"])
    assert body["agent"]["registered"] is False


# ── Monitor vs Protect ──────────────────────────────────────────────────────
def test_a_monitor_application_records_the_decision_but_lets_the_call_through():
    s = make_stack(mode="observe")
    s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    body = simulate(s, "prompt_injection")
    step = body["steps"][-1]
    assert step["status"] == "executed"                       # Monitor does not stop it
    assert step["verdict"]["action"] == "pause_agent" and step["verdict"]["enforced"] is False
    assert s["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"][0]["action"] == "pause_agent"


# ── NeuroSOC unavailable ────────────────────────────────────────────────────
def _down_factory(url: str, key: str) -> NeuroSOC:
    def down(method, path, body):
        raise NeuroSOCError("connection refused")
    return NeuroSOC(url, key, transport=down)


def test_outage_fails_closed_for_money_and_keeps_reads_working():
    s = make_stack(factory=_down_factory)
    s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    sent = chat(s, "send $100 to Alice")
    assert sent["steps"][0]["status"] == "unavailable" and "temporarily unavailable" in sent["reply"]
    assert balance(s) == 18420.0                              # not sent
    assert "$18,420.00" in chat(s, "what's my balance?")["reply"]   # reads are not guarded


def test_outage_on_the_transfer_page_does_not_send_money():
    s = make_stack(factory=_down_factory)
    s["client"].post("/api/v1/demo/connect", json={"secret_key": s["secret"]})
    body = s["client"].post("/api/v1/demo/transfer", json={"to": "Bob", "amount": 50}, headers=SESSION).json()
    assert body["status"] == "unavailable" and balance(s) == 18420.0


# ── the Transfer page (a person, not the agent) ─────────────────────────────
def test_a_person_sending_a_small_transfer_is_allowed(stack):
    body = stack["client"].post("/api/v1/demo/transfer", json={"to": "Bob", "amount": 120, "purpose": "rent"},
                                headers=SESSION).json()
    assert body["status"] == "sent" and body["transfer"]["status"] == "settled"
    assert body["verdict"]["action"] == "allow" and balance(stack) == 18300.0


def test_transfer_input_is_validated(stack):
    for bad in ({"to": "", "amount": 5}, {"to": "Bob", "amount": 0}, {"to": "Bob", "amount": -5},
                {"to": "Bob; DROP", "amount": 5}, {"to": "Bob", "amount": 5, "extra": 1}):
        assert stack["client"].post("/api/v1/demo/transfer", json=bad, headers=SESSION).status_code == 422
