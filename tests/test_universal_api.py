from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_DIR = REPO_ROOT / "inference-service"
if str(INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(INFERENCE_DIR))

from api.routes.universal import UniversalHooks, build_router  # noqa: E402
from core.universal import MemoryKV, SiteRegistry, UniversalEngine  # noqa: E402
from core.universal.cors import SdkCorsMiddleware  # noqa: E402

SITE_ORIGIN = "https://launchpad.example"
OTHER_ORIGIN = "https://evil.example"


async def _allow_ws(_websocket) -> bool:
    return True


@pytest.fixture
def setup():
    kv = MemoryKV()
    registry = SiteRegistry(kv)
    site, secret = registry.create("local", "Example launchpad", [SITE_ORIGIN], mode="enforce",
                                   preset="rewards-campaign")
    engine = UniversalEngine(kv)
    shadowed: list[dict] = []
    published: list[dict] = []
    roles: dict[str, set[str] | None] = {"value": None}
    hooks = UniversalHooks(
        hash_secret="test-secret",
        tenant_of=lambda request: "local",
        roles_of=lambda request: roles["value"],
        client_ip=lambda request: "203.0.113.50",
        authorize_websocket=_allow_ws,
        websocket_tenant=lambda websocket: "local",
        on_shadow=lambda verdict, ip: shadowed.append(verdict),
        publish=published.append,
    )
    app = FastAPI()
    # The service-wide CORS policy does not list the customer site; SDK CORS handles it.
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(build_router(engine, registry, hooks))
    app.add_middleware(SdkCorsMiddleware, origin_allowed=registry.origin_allowed_anywhere)
    return {"client": TestClient(app), "site": site, "secret": secret, "shadowed": shadowed,
            "published": published, "roles": roles, "registry": registry}


def _claim(session: str = "session-0001", entity: str = "wallet-1", telemetry: dict | None = None) -> dict:
    event = {
        "session_id": session,
        "entity": {"id": entity, "type": "human"},
        "action": "reward.claim",
        "resource": {"id": "campaign-7", "type": "campaign"},
        "value": {"amount": 10},
    }
    if telemetry is not None:
        event["telemetry"] = telemetry
    return event


def test_browser_key_works_only_from_registered_origin(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    ok = client.post("/api/v1/sdk/events", json={"events": [_claim()]},
                     headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == SITE_ORIGIN
    denied = client.post("/api/v1/sdk/events", json={"events": [_claim()]},
                         headers={"X-NeuroSOC-Key": pk, "Origin": OTHER_ORIGIN})
    assert denied.status_code == 403
    assert "access-control-allow-origin" not in denied.headers
    missing = client.post("/api/v1/sdk/events", json={"events": [_claim()]})
    assert missing.status_code == 401


def test_beacon_style_simple_request_is_accepted(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    import json as _json
    response = client.post(f"/api/v1/sdk/events?key={pk}", content=_json.dumps({"events": [_claim()]}),
                           headers={"Content-Type": "text/plain;charset=UTF-8", "Origin": SITE_ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == SITE_ORIGIN
    garbage = client.post(f"/api/v1/sdk/events?key={pk}", content="not json",
                          headers={"Content-Type": "text/plain", "Origin": SITE_ORIGIN})
    assert garbage.status_code == 422


def test_preflight_is_answered_for_registered_origins_only(setup):
    client = setup["client"]
    headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type, x-neurosoc-key"}
    ok = client.options("/api/v1/sdk/events", headers={**headers, "Origin": SITE_ORIGIN})
    assert ok.status_code == 204
    assert ok.headers["access-control-allow-origin"] == SITE_ORIGIN
    assert "x-neurosoc-key" in ok.headers["access-control-allow-headers"]
    bad = client.options("/api/v1/sdk/events", headers={**headers, "Origin": OTHER_ORIGIN})
    assert bad.status_code == 403


def test_browser_sees_only_the_response_not_the_reasons(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    bot = {"events": [{"type": "keydown", "timestamp": 1000 + i * 40, "key": "char"} for i in range(20)]}
    body = client.post("/api/v1/sdk/events", json={"events": [_claim(telemetry=bot)]},
                       headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN}).json()
    verdict = body["verdicts"][0]
    assert verdict["action"] == "shadow"
    assert set(verdict) == {"verdict_id", "session_id", "event_id", "action", "enforced"}
    assert setup["shadowed"], "enforce-mode shadow verdicts are mirrored to the sandbox"
    assert setup["published"][0]["event_type"] == "behavior.event"


def test_secret_key_routes_reject_browser_keys(setup):
    client, pk, sk = setup["client"], setup["site"]["publishable_key"], setup["secret"]
    client.post("/api/v1/sdk/events", json={"events": [_claim(session="session-abc1")]},
                headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN})
    assert client.get("/api/v1/sdk/sessions/session-abc1/verdict",
                      headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN}).status_code == 401
    server_side = client.get("/api/v1/sdk/sessions/session-abc1/verdict", headers={"X-NeuroSOC-Key": sk})
    assert server_side.status_code == 200
    assert server_side.json()["verdict"] in {"ok", "review", "suspected_bot"}
    assert "reasons" in server_side.json()
    unknown = client.get("/api/v1/sdk/sessions/session-never/verdict", headers={"X-NeuroSOC-Key": sk})
    assert unknown.json()["verdict"] == "unknown"


def test_guard_returns_full_verdict_for_agents(setup):
    client, sk = setup["client"], setup["secret"]
    event = {
        "session_id": "agent-run-0001",
        "entity": {"id": "flows-agent-1", "type": "agent"},
        "action": "token.transfer",
        "resource": {"id": "treasury", "type": "wallet", "sensitivity": "critical"},
        "value": {"amount": 5000, "asset": "SOL", "destination": "unknown-wallet"},
        "agent": {"tool": "transfer", "instruction_source": "external_content"},
    }
    response = client.post("/api/v1/sdk/guard", json=event, headers={"X-NeuroSOC-Key": sk})
    assert response.status_code == 200
    assert "reasons" in response.json() and "scores" in response.json()


def test_idempotent_events_are_scored_once(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    event = {**_claim(session="session-idem"), "event_id": "11111111-2222-3333-4444-555555555555"}
    headers = {"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN}
    first = client.post("/api/v1/sdk/events", json={"events": [event]}, headers=headers).json()
    second = client.post("/api/v1/sdk/events", json={"events": [event]}, headers=headers).json()
    assert first["verdicts"][0]["verdict_id"] == second["verdicts"][0]["verdict_id"]


def test_config_serves_mode_and_rules(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    config = client.get(f"/api/v1/sdk/config?key={pk}", headers={"Origin": SITE_ORIGIN}).json()
    assert config["mode"] == "enforce"
    assert any(rule["action"] == "task.complete" for rule in config["rules"])


def test_invalid_events_are_rejected(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    bad = {**_claim(), "action": "drain.everything"}
    response = client.post("/api/v1/sdk/events", json={"events": [bad]},
                           headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN})
    assert response.status_code == 422


def test_site_management_requires_operator_role(setup):
    client = setup["client"]
    setup["roles"]["value"] = {"analyst"}
    denied = client.post("/api/v1/universal/sites", json={"name": "New", "allowed_origins": ["https://new.example"]})
    assert denied.status_code == 403
    setup["roles"]["value"] = {"operator"}
    created = client.post("/api/v1/universal/sites", json={"name": "New", "allowed_origins": ["https://new.example"],
                                                            "preset": "cyrene"})
    assert created.status_code == 201
    body = created.json()
    assert body["secret_key"].startswith("sk_")
    assert "secret_key_digest" not in body["site"]
    assert body["site"]["rules"], "the Cyrene preset loads its rules"


def test_analyst_views_and_override(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    bot = {"events": [{"type": "keydown", "timestamp": 1000 + i * 40, "key": "char"} for i in range(20)]}
    verdict_id = client.post("/api/v1/sdk/events", json={"events": [_claim(session="session-ov1", telemetry=bot)]},
                             headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN}).json()["verdicts"][0]["verdict_id"]
    latest = client.get("/api/v1/universal/verdicts/latest").json()["verdicts"]
    assert latest[0]["verdict_id"] == verdict_id
    integrity = client.get("/api/v1/universal/resources/campaign-7/integrity").json()
    assert integrity["claims"]["withheld"] == 1
    restored = client.post(f"/api/v1/universal/verdicts/{verdict_id}/override", json={"decision": "restore"})
    assert restored.status_code == 200
    assert restored.json()["override"]["decision"] == "restore"
    assert any(item.get("event_type") == "behavior.label" for item in setup["published"])


def test_universal_stream_sends_live_verdicts(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    with client.websocket_connect("/api/v1/universal/ws") as websocket:
        assert websocket.receive_json()["type"] == "universal.snapshot"
        client.post("/api/v1/sdk/events", json={"events": [_claim(session="session-ws01")]},
                    headers={"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN})
        message = websocket.receive_json()
        assert message["type"] == "universal.verdict"
        assert message["data"]["session_id"] == "session-ws01"


def test_main_exposes_no_sdk_routes_when_flag_is_off():
    import main as inference_main

    assert inference_main.ENABLE_UNIVERSAL_ENGINE is False
    paths = {getattr(route, "path", "") for route in inference_main.app.routes}
    assert not any(path.startswith(("/api/v1/sdk", "/api/v1/universal")) for path in paths)


def test_extension_origins_need_an_explicit_opt_in(setup):
    client, registry = setup["client"], setup["registry"]
    lens_site, _ = registry.create("local", "Observed site", ["https://observed.example", "chrome-extension://*"])
    extension = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    ok = client.post(f"/api/v1/sdk/events?key={lens_site['publishable_key']}", json={"events": [_claim()]},
                     headers={"Origin": extension})
    assert ok.status_code == 200
    # The example site did not opt in, so the extension cannot use its key.
    denied = client.post(f"/api/v1/sdk/events?key={setup['site']['publishable_key']}", json={"events": [_claim()]},
                         headers={"Origin": extension})
    assert denied.status_code == 403


def test_a_shadowed_session_is_mirrored_to_the_sandbox_once(setup):
    client, pk = setup["client"], setup["site"]["publishable_key"]
    bot = {"events": [{"type": "keydown", "timestamp": 1000 + i * 40, "key": "char"} for i in range(20)]}
    headers = {"X-NeuroSOC-Key": pk, "Origin": SITE_ORIGIN}
    for _ in range(4):
        client.post("/api/v1/sdk/events", json={"events": [_claim(session="session-mirror", telemetry=bot)]}, headers=headers)
    mirrored = [v for v in setup["shadowed"] if v["session_id"] == "session-mirror"]
    assert len(mirrored) == 1
