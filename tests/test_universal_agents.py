"""Agent registry, guard authorization, verdict context and the Monitor/Protect flag."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for extra in (REPO_ROOT / "inference-service", REPO_ROOT / "sdk" / "python"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from api.routes.universal import UniversalHooks, build_router  # noqa: E402
from core.universal import MemoryKV, SiteRegistry, UniversalEngine  # noqa: E402
from core.universal.ingest import SdkEvent, normalize  # noqa: E402
from neurosoc import ActionBlocked, NeuroSOC  # noqa: E402

ORIGIN = "http://localhost:5173"
AGENTS = [
    {"agent_id": aid, "name": aid, "tools": ["get_balance", "create_transfer"],
     "sensitive_actions": ["token.transfer"], "authorized_resources": ["treasury"]}
    for aid in ("nova-allowed", "nova-tool", "nova-resource", "nova-session", "nova-monitor")
] + [{"agent_id": "nova-rate", "tools": ["create_transfer"], "sensitive_actions": ["token.transfer"],
      "authorized_resources": ["treasury"], "max_sensitive_per_minute": 5}]


async def _allow_ws(_websocket) -> bool:
    return True


def _hooks(roles=None) -> UniversalHooks:
    return UniversalHooks(
        hash_secret="test-secret", tenant_of=lambda request: "local", roles_of=lambda request: roles,
        client_ip=lambda request: "203.0.113.50", authorize_websocket=_allow_ws, websocket_tenant=lambda ws: "local")


@pytest.fixture
def stack():
    kv = MemoryKV()
    registry = SiteRegistry(kv)
    protected, protected_secret = registry.create("local", "NovaTrust", [ORIGIN], mode="enforce", agents=AGENTS,
                                                  app_type="both", url=f"{ORIGIN}/demo")
    monitor, monitor_secret = registry.create("local", "NovaTrust (monitor)", [ORIGIN], mode="observe", agents=AGENTS)
    bare, bare_secret = registry.create("local", "No registry", [ORIGIN], mode="enforce")
    engine = UniversalEngine(kv)
    app = FastAPI()
    app.include_router(build_router(engine, registry, _hooks()))
    client = TestClient(app)
    return {"client": client, "registry": registry, "engine": engine,
            "protected": (protected, protected_secret), "monitor": (monitor, monitor_secret),
            "bare": (bare, bare_secret)}


def agent_event(agent_id: str, *, session: str | None = None, action: str = "token.transfer",
                resource: str = "treasury", amount: float = 250.0, to: str = "Alice",
                tool: str = "create_transfer", source: str = "owner") -> dict:
    return {"session_id": session or f"sess-{agent_id}-0001", "entity": {"id": agent_id, "type": "agent"},
            "action": action, "resource": {"id": resource, "type": "treasury_account", "sensitivity": "high"},
            "value": {"amount": amount, "destination": to},
            "agent": {"tool": tool, "instruction_source": source, "owner_id": "act_alex"}}


def guard(stack, kind: str, event: dict) -> dict:
    response = stack["client"].post("/api/v1/sdk/guard", json=event, headers={"X-NeuroSOC-Key": stack[kind][1]})
    assert response.status_code == 200, response.text
    return response.json()


# ── registry ────────────────────────────────────────────────────────────────
def test_site_create_roundtrip_stores_agents_and_hides_secrets(stack):
    body = {"name": "Acme", "allowed_origins": [ORIGIN], "mode": "enforce", "app_type": "both",
            "url": f"{ORIGIN}/demo", "agents": [AGENTS[0]]}
    created = stack["client"].post("/api/v1/universal/sites", json=body)
    assert created.status_code == 201
    payload = created.json()
    site = payload["site"]
    assert payload["secret_key"].startswith("sk_")
    assert site["agents"][0]["agent_id"] == "nova-allowed"
    assert site["app_type"] == "both" and site["url"] == f"{ORIGIN}/demo" and site["demo"] is False
    assert "secret_key_digest" not in site and payload["secret_key"] not in str(site)
    listed = stack["client"].get("/api/v1/universal/sites").json()["sites"]
    assert any(s["site_id"] == site["site_id"] and s["agents"] for s in listed)


@pytest.mark.parametrize("agents", [
    [{"agent_id": "a"}],                                                       # too short
    [{"agent_id": "has space"}],                                               # bad characters
    [{"agent_id": "dup-agent"}, {"agent_id": "dup-agent"}],                    # duplicate
    [{"agent_id": "ok-agent", "sensitive_actions": ["not.a.real.action"]}],    # not in the taxonomy
    [{"agent_id": "ok-agent", "max_sensitive_per_minute": 0}],                 # out of range
])
def test_site_create_rejects_bad_agent_specs(stack, agents):
    response = stack["client"].post("/api/v1/universal/sites", json={"name": "Bad", "agents": agents})
    assert response.status_code == 422


def test_site_update_replaces_agents_and_keeps_keys(stack):
    site, secret = stack["bare"]
    response = stack["client"].put(f"/api/v1/universal/sites/{site['site_id']}", json={"agents": [AGENTS[0]]})
    assert response.status_code == 200
    assert response.json()["site"]["agents"][0]["agent_id"] == "nova-allowed"
    assert stack["registry"].by_secret_key(secret) is not None  # the secret key still works


def test_existing_sites_without_agent_fields_still_load(stack):
    site = stack["registry"].get(stack["bare"][0]["site_id"])
    assert site["agents"] == [] and site["app_type"] == "web" and site["url"] is None


# ── guard authorization ─────────────────────────────────────────────────────
def test_registered_agent_acting_within_its_policy_is_allowed(stack):
    verdict = guard(stack, "protected", agent_event("nova-allowed"))
    assert verdict["action"] == "allow" and verdict["risk"] < 0.6


def test_unregistered_agent_is_paused_with_a_clear_reason(stack):
    verdict = guard(stack, "protected", agent_event("intruder-agent"))
    assert verdict["action"] == "pause_agent" and verdict["verdict"] == "agent_anomaly"
    assert any("not registered" in r for r in verdict["reasons"])


def test_tool_outside_the_agents_list_is_paused(stack):
    verdict = guard(stack, "protected", agent_event("nova-tool", tool="delete_everything"))
    assert verdict["action"] == "pause_agent"
    assert any("tool delete_everything is not permitted" in r for r in verdict["reasons"])


def test_unauthorized_resource_is_paused(stack):
    verdict = guard(stack, "protected", agent_event("nova-resource", resource="treasury_cold_storage_vault"))
    assert verdict["action"] == "pause_agent"
    assert any("not authorized to act on resource treasury_cold_storage_vault" in r for r in verdict["reasons"])


def test_the_same_event_is_not_judged_on_policy_when_a_site_has_no_registry(stack):
    verdict = guard(stack, "bare", agent_event("nova-resource", resource="treasury_cold_storage_vault"))
    assert verdict["action"] == "allow"  # no registry -> no policy; the anomaly detectors alone stay below 0.6


def test_sensitive_action_burst_trips_the_rate_limit_then_sticks(stack):
    actions = [guard(stack, "protected", agent_event("nova-rate"))["action"] for _ in range(8)]
    assert actions[:5] == ["allow"] * 5                      # within the 5/minute limit
    assert actions[5] == "pause_agent"                       # 6th sensitive action in a minute
    assert set(actions[5:]) == {"pause_agent"}               # and the pause sticks
    last = guard(stack, "protected", agent_event("nova-rate"))
    assert any("limited to 5" in r or "already flagged" in r or "session was already flagged" in r for r in last["reasons"])


def test_restoring_a_paused_agent_clears_its_flag_and_window(stack):
    blocked = guard(stack, "protected", agent_event("nova-session", resource="treasury_cold_storage_vault"))
    assert blocked["action"] == "pause_agent"
    restored = stack["client"].post(f"/api/v1/universal/verdicts/{blocked['verdict_id']}/override",
                                    json={"decision": "restore"})
    assert restored.status_code == 200
    again = guard(stack, "protected", agent_event("nova-session", session="sess-nova-session-0002"))
    assert again["action"] == "allow"


# ── verdict context ─────────────────────────────────────────────────────────
def test_verdicts_carry_application_agent_and_tool(stack):
    site, _ = stack["protected"]
    verdict = guard(stack, "protected", agent_event("nova-allowed"))
    assert verdict["site_id"] == site["site_id"] and verdict["site_name"] == "NovaTrust"
    assert verdict["agent_id"] == "nova-allowed" and verdict["tool"] == "create_transfer"
    latest = stack["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"]
    assert latest[0]["site_name"] == "NovaTrust" and latest[0]["agent_id"] == "nova-allowed"


def test_site_rename_shows_up_in_existing_verdicts(stack):
    site, _ = stack["protected"]
    guard(stack, "protected", agent_event("nova-allowed"))
    stack["registry"].update(site["site_id"])  # no-op write must not break enrichment
    site_doc = stack["registry"].get(site["site_id"])
    site_doc["name"] = "NovaTrust Renamed"
    stack["registry"]._save(site_doc)
    assert stack["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"][0]["site_name"] == "NovaTrust Renamed"


def test_browser_key_responses_still_hide_everything_but_the_action(stack):
    site, _ = stack["protected"]
    response = stack["client"].post(
        f"/api/v1/sdk/events?key={site['publishable_key']}", headers={"Origin": ORIGIN},
        json={"events": [{"session_id": "browser-session-1", "entity": {"id": "act_alex", "type": "human"},
                          "action": "page.view", "resource": {"id": "demo", "type": "page"}}]})
    assert response.status_code == 200
    assert set(response.json()["verdicts"][0]) == {"verdict_id", "session_id", "event_id", "action", "enforced"}


def test_record_false_teaches_the_baseline_but_leaves_no_feed_entry(stack):
    site, _ = stack["protected"]
    raw = SdkEvent(**agent_event("nova-allowed", session="seed-session-0001"))
    event = normalize(raw, site=site, client_ip=None, origin=None, hash_secret="x", source="server")
    before = len(stack["engine"].latest_verdicts("local", 50))
    stack["engine"].process(event, mode="enforce", agent_policy=site["agents"], record=False)
    assert len(stack["engine"].latest_verdicts("local", 50)) == before
    assert stack["engine"].session_verdict("local", "seed-session-0001") is None
    profile = stack["engine"].entity_profile("local", "agent", "nova-allowed")
    assert profile is not None and profile["event_count"] == 1  # the baseline did learn from it


# ── Monitor vs Protect in the Python SDK ────────────────────────────────────
def _soc(stack, kind: str) -> NeuroSOC:
    client, secret = stack["client"], stack[kind][1]

    def transport(method: str, path: str, body):
        return client.request(method, path, json=body, headers={"X-NeuroSOC-Key": secret}).json()

    return NeuroSOC("http://testserver", secret, transport=transport)


def _transfer_tool(soc: NeuroSOC, agent_id: str, **options):
    ran: list[float] = []

    @soc.guard_tool(agent_id=agent_id, action="token.transfer", resource="treasury_cold_storage_vault",
                    resource_type="treasury_account", sensitivity="high", **options)
    def create_transfer(to: str, amount: float, instruction_source: str = "owner"):
        ran.append(amount)
        return "sent"

    return create_transfer, ran


def test_guard_tool_blocks_in_both_modes_by_default(stack):
    for kind, agent in (("protected", "nova-tool"), ("monitor", "nova-monitor")):
        tool, ran = _transfer_tool(_soc(stack, kind), agent)
        with pytest.raises(ActionBlocked):
            tool(to="Alice", amount=250.0)
        assert ran == []


def test_block_only_when_enforced_lets_monitor_sites_through_but_records_the_decision(stack):
    seen = []
    tool, ran = _transfer_tool(_soc(stack, "monitor"), "nova-monitor", block_only_when_enforced=True,
                               on_verdict=seen.append)
    assert tool(to="Alice", amount=250.0) == "sent" and ran == [250.0]
    assert seen[0].action == "pause_agent" and seen[0].raw["enforced"] is False   # flagged, not enforced
    assert stack["client"].get("/api/v1/universal/verdicts/latest").json()["verdicts"][0]["action"] == "pause_agent"


def test_block_only_when_enforced_still_blocks_protect_sites(stack):
    tool, ran = _transfer_tool(_soc(stack, "protected"), "nova-resource", block_only_when_enforced=True)
    with pytest.raises(ActionBlocked):
        tool(to="Alice", amount=250.0)
    assert ran == []


def test_unreachable_neurosoc_still_fails_closed(stack):
    def down(method, path, body):
        from neurosoc import NeuroSOCError
        raise NeuroSOCError("connection refused")

    soc = NeuroSOC("http://testserver", stack["protected"][1], transport=down)
    tool, ran = _transfer_tool(soc, "nova-allowed", block_only_when_enforced=True)
    with pytest.raises(ActionBlocked) as blocked:
        tool(to="Alice", amount=1.0)
    assert blocked.value.verdict.verdict == "unavailable" and ran == []
