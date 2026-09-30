from __future__ import annotations

import json
import random
import sys
import time
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_DIR = REPO_ROOT / "inference-service"
if str(INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(INFERENCE_DIR))

from core.universal import MemoryKV, UniversalEngine  # noqa: E402
from core.universal.ingest import SdkEvent, normalize  # noqa: E402
from core.universal.taxonomy import ACTIONS  # noqa: E402

SITE = {"site_id": "site-test", "tenant_id": "local", "mode": "enforce"}


def human_telemetry(seed: int) -> dict:
    """Irregular typing with corrections, curved mouse paths, ~20 seconds long (ms timestamps).
    Each seed is a different person: typing speed differs from person to person."""
    rng = random.Random(seed)
    base = 70 + (seed % 9) * 35
    t = 1_000_000.0
    events = []
    for index in range(40):
        t += rng.uniform(base, base * 4)
        key = "backspace" if index % 13 == 7 else ("space" if index % 6 == 5 else "char")
        events.append({"type": "keydown", "timestamp": t, "key": key})
        events.append({"type": "keyup", "timestamp": t + rng.uniform(60, 160), "key": key})
    x, y = 100.0, 100.0
    for step in range(60):
        t += rng.uniform(12, 40)
        x += 6 + 4 * rng.uniform(-1, 1) + 3 * (step % 7)
        y += 5 * rng.uniform(-1, 1) + 2 * ((step % 11) - 5)
        events.append({"type": "mousemove", "timestamp": t, "x": x, "y": y})
    events.append({"type": "click", "timestamp": t + 900})
    return {"events": events}


def bot_telemetry() -> dict:
    """Constant-rhythm typing, one straight mouse path, the whole form in about a second."""
    t = 1_000_000.0
    events = []
    for _ in range(20):
        t += 40
        events.append({"type": "keydown", "timestamp": t, "key": "char"})
        events.append({"type": "keyup", "timestamp": t + 20, "key": "char"})
    events.append({"type": "mousemove", "timestamp": t + 10, "x": 0, "y": 0})
    events.append({"type": "mousemove", "timestamp": t + 20, "x": 100, "y": 100})
    events.append({"type": "mousemove", "timestamp": t + 30, "x": 200, "y": 200})
    events.append({"type": "click", "timestamp": t + 40})
    return {"events": events}


def make_event(entity_id: str, action: str, *, entity_type: str = "human", resource: str = "campaign-7",
               session: str | None = None, ts: float | None = None, context: dict | None = None,
               telemetry: dict | None = None, value: dict | None = None, agent: dict | None = None,
               result: str = "success", ip: str = "203.0.113.10") -> dict:
    raw = SdkEvent(
        session_id=session or f"sess-{entity_id}",
        entity={"id": entity_id, "type": entity_type},
        action=action,
        resource={"id": resource, "type": "campaign"},
        result=result,
        context=context,
        telemetry=telemetry,
        value=value,
        agent=agent,
    )
    event = normalize(raw, site=SITE, client_ip=ip, origin="https://example.test", hash_secret="test-secret",
                      source="sdk-js")
    if ts is not None:
        # Simulated history spans far more than the live clock-skew window normalize() allows.
        event["timestamp"] = ts
    return event


@pytest.fixture
def engine() -> UniversalEngine:
    return UniversalEngine(MemoryKV())


def test_taxonomy_matches_schema_v1_3():
    schema = json.loads((REPO_ROOT / "schemas" / "security-event-v1.3.schema.json").read_text(encoding="utf-8"))
    assert set(schema["$defs"]["behaviorEvent"]["properties"]["action"]["enum"]) == set(ACTIONS)


def test_normalized_event_validates_against_schema_v1_3():
    schema = json.loads((REPO_ROOT / "schemas" / "security-event-v1.3.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    event = make_event("user-1", "reward.claim", context={"device_hash": "dev-1", "wallet": "w1"},
                       telemetry={"session_vector": [1.0] * 20}, value={"amount": 5, "asset": "SOL"})
    validator.validate(event)
    assert event["context"]["ip_hash"] != "203.0.113.10"  # raw IPs are never stored


def test_v1_2_network_events_still_validate_unchanged():
    v12 = json.loads((REPO_ROOT / "schemas" / "security-event-v1.2.schema.json").read_text(encoding="utf-8"))
    v13 = json.loads((REPO_ROOT / "schemas" / "security-event-v1.3.schema.json").read_text(encoding="utf-8"))
    for name in ("networkPacket", "networkFlow"):
        old = dict(v12["$defs"][name]["properties"])
        new = dict(v13["$defs"][name]["properties"])
        old.pop("schema_version")
        new.pop("schema_version")
        assert old == new


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError):
        make_event("user-1", "bank.wire_everything")


def test_real_person_completing_a_campaign_is_allowed(engine):
    now = time.time()
    verdict = None
    for step, action in enumerate(["wallet.connect", "campaign.join", "task.complete", "reward.claim"]):
        verdict = engine.process(make_event("alice", action, ts=now + step * 30,
                                            context={"device_hash": "dev-alice", "funded_by": "fund-alice"},
                                            telemetry=human_telemetry(step)))
    assert verdict["verdict"] == "ok"
    assert verdict["action"] == "allow"
    assert verdict["scores"]["humanity"] > 0.6


def test_scripted_claim_is_shadowed(engine):
    verdict = engine.process(make_event("bot-solo", "reward.claim", context={"device_hash": "dev-solo"},
                                        telemetry=bot_telemetry()))
    assert verdict["verdict"] == "suspected_bot"
    assert verdict["action"] == "shadow"
    assert verdict["scores"]["humanity"] < 0.35
    assert verdict["reasons"]


def test_farm_sharing_a_funding_wallet_is_linked_and_shadowed(engine):
    now = time.time()
    verdicts = []
    for index in range(8):
        # Human-looking telemetry on purpose: the farm is caught by what the accounts share.
        verdicts.append(engine.process(make_event(
            f"farm-{index}", "reward.claim", ts=now + index,
            context={"device_hash": f"dev-{index}", "funded_by": "fund-master"},
            telemetry=human_telemetry(100 + index), value={"amount": 10}, ip=f"198.51.100.{index + 1}")))
    assert verdicts[0]["verdict"] == "ok"
    assert verdicts[-1]["verdict"] == "bot_farm"
    assert verdicts[-1]["scores"]["cluster_size"] == 8
    assert verdicts[-1]["linked_by"]["funded_by"] == 8

    integrity = engine.resource_integrity("local", "campaign-7")
    assert integrity["participants"] == 8
    assert integrity["flagged"] == 8
    assert integrity["claims"]["withheld"] >= 4

    # Early farm members were paid before the farm was visible; their next attempt is caught.
    again = engine.process(make_event("farm-0", "reward.claim", ts=now + 60,
                                      context={"device_hash": "dev-0", "funded_by": "fund-master"},
                                      session="sess-farm-0-b"))
    assert again["verdict"] == "bot_farm"


def test_scripted_accounts_on_one_ip_block_are_a_farm(engine):
    # Different devices and wallets, but one IP block and the same replayed script.
    now = time.time()
    verdicts = [engine.process(make_event(
        f"script-{index}", "task.complete", ts=now + index,
        context={"device_hash": f"dev-s{index}", "funded_by": f"fund-s{index}"},
        telemetry=human_telemetry(7), ip=f"198.51.100.{index + 10}")) for index in range(6)]
    assert verdicts[-1]["verdict"] == "bot_farm"
    assert "ip_block_and_input_timing" in verdicts[-1]["linked_by"]


def test_unrelated_people_on_the_same_campaign_are_not_a_farm(engine):
    now = time.time()
    verdicts = [engine.process(make_event(
        f"person-{index}", "reward.claim", ts=now + index,
        context={"device_hash": f"dev-p{index}", "funded_by": f"fund-p{index}"},
        telemetry=human_telemetry(200 + index), value={"amount": 10}, ip=f"192.0.2.{index + 1}" if index < 4 else f"203.0.{index}.9"))
        for index in range(8)]
    assert all(v["verdict"] == "ok" for v in verdicts)


def test_hijacked_agent_is_paused(engine):
    now = time.time()
    for index in range(30):
        verdict = engine.process(make_event(
            "flows-agent-1", "token.transfer", entity_type="agent", resource="treasury", ts=now + index * 60,
            value={"amount": 10 + (index % 5), "asset": "SOL", "destination": "pool-A" if index % 2 else "pool-B"},
            agent={"tool": "transfer", "instruction_source": "owner"}, session="agent-run-1"))
        assert verdict["verdict"] == "ok", verdict
    hijack = engine.process(make_event(
        "flows-agent-1", "token.transfer", entity_type="agent", resource="treasury", ts=now + 31 * 60,
        value={"amount": 5000, "asset": "SOL", "destination": "attacker-wallet"},
        agent={"tool": "transfer", "instruction_source": "external_content"}, session="agent-run-1"))
    assert hijack["verdict"] == "agent_anomaly"
    assert hijack["action"] == "pause_agent"
    assert any("never used before" in reason for reason in hijack["reasons"])
    assert any("outside content" in reason for reason in hijack["reasons"])


def test_flagged_behaviour_does_not_teach_the_baseline(engine):
    now = time.time()
    engine.process(make_event("bot-x", "reward.claim", ts=now, telemetry=bot_telemetry()))
    baseline_doc = engine.kv.get("local:entity:human:bot-x:baseline")
    assert json.loads(baseline_doc)["n"] == 0


def test_session_verdict_is_sticky_and_override_restores(engine):
    now = time.time()
    first = engine.process(make_event("bot-y", "reward.claim", ts=now, telemetry=bot_telemetry(), session="session-y-1"))
    assert first["action"] == "shadow"
    # A later clean-looking event in the same session keeps the shadow.
    later = engine.process(make_event("bot-y", "page.view", ts=now + 5, session="session-y-1"))
    assert later["action"] == "shadow"
    assert engine.session_verdict("local", "session-y-1")["action"] == "shadow"

    restored = engine.override("local", first["verdict_id"], "restore", "analyst-1")
    assert restored["override"]["decision"] == "restore"
    assert engine.session_verdict("local", "session-y-1") is None
    clean = engine.process(make_event("bot-y", "page.view", ts=now + 10, session="session-y-2"))
    assert clean["verdict"] == "ok"


def test_tenants_are_isolated(engine):
    event = make_event("bot-z", "reward.claim", telemetry=bot_telemetry(), session="session-z-1")
    engine.process(event)
    other = dict(event, tenant_id="other-tenant", event_id=str(uuid.uuid4()), telemetry=None)
    verdict = engine.process(other)
    assert verdict["verdict"] == "ok"
    assert engine.session_verdict("other-tenant", "session-z-1")["verdict"] == "ok"
