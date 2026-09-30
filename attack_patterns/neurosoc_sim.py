"""Shared helpers for the NeuroSOC SDK demo scripts (human_seed, bot_farm, agent_hijack).

These scripts talk to the SDK API the same way the browser SDK does, so they need no browser.
Human sessions get irregular, person-specific input timing; bots get machine-regular timing and
share one device fingerprint, as a farm run from one machine does.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from urllib import request as urllib_request

ENDPOINT = "http://localhost:8000"
CAMPAIGN_URL = "http://localhost:5500"
CAMPAIGN_ORIGIN = "http://localhost:5500"
CAMPAIGN_KEY = "pk_local_example_campaign"
CAMPAIGN_ID = "early-access"


def wallet_address(rng: random.Random) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(rng.choice(alphabet) for _ in range(44))


def fingerprint(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


def human_telemetry(rng: random.Random, words: int = 12) -> dict:
    """A person filling a short form: irregular typing with pauses and corrections, curved mouse paths."""
    base = rng.uniform(90, 260)
    t = time.time() * 1000 - 25_000
    events = []
    for index in range(words * 5):
        t += rng.uniform(base * 0.5, base * 2.5) + (rng.uniform(300, 900) if index % 5 == 4 else 0)
        key = "backspace" if rng.random() < 0.06 else ("space" if index % 5 == 4 else "char")
        events.append({"type": "keydown", "timestamp": t, "key": key})
        events.append({"type": "keyup", "timestamp": t + rng.uniform(50, 140), "key": key})
    x, y = rng.uniform(200, 600), rng.uniform(150, 400)
    for step in range(rng.randint(40, 90)):
        t += rng.uniform(14, 45)
        x += rng.uniform(-8, 14) + 4 * ((step % 9) - 4) / 4
        y += rng.uniform(-9, 9) + 3 * ((step % 13) - 6) / 6
        events.append({"type": "mousemove", "timestamp": t, "x": round(x), "y": round(y)})
    events.append({"type": "click", "timestamp": t + rng.uniform(200, 700)})
    return {"events": events, "event_count": len(events) + rng.randint(40, 200)}


def bot_telemetry() -> dict:
    """A script: fields filled at a fixed rhythm, one straight pointer move, done in about a second."""
    t = time.time() * 1000 - 1_500
    events = []
    for _ in range(24):
        t += 35
        events.append({"type": "keydown", "timestamp": t, "key": "char"})
        events.append({"type": "keyup", "timestamp": t + 15, "key": "char"})
    for step in range(3):
        events.append({"type": "mousemove", "timestamp": t + 10 * (step + 1), "x": 100 * step, "y": 100 * step})
    events.append({"type": "click", "timestamp": t + 50})
    return {"events": events, "event_count": len(events)}


def post(url: str, payload: dict, headers: dict | None = None, timeout: float = 10) -> dict:
    req = urllib_request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "text/plain;charset=UTF-8", **(headers or {})})
    with urllib_request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def sdk_event(session: str, entity: str, action: str, resource: dict, context: dict,
              telemetry: dict | None = None, value: dict | None = None) -> dict:
    event = {"event_id": str(uuid.uuid4()), "timestamp": time.time(), "session_id": session,
             "entity": {"id": entity, "type": "human"}, "action": action, "resource": resource,
             "result": "success", "context": context}
    if telemetry:
        event["telemetry"] = telemetry
    if value:
        event["value"] = value
    return event


def send(events: list[dict], endpoint: str = ENDPOINT, key: str = CAMPAIGN_KEY, origin: str = CAMPAIGN_ORIGIN) -> list[dict]:
    body = post(f"{endpoint}/api/v1/sdk/events?key={key}", {"events": events}, {"Origin": origin})
    return body["verdicts"]


def campaign_run(entity: str, session: str, context: dict, telemetry_fn, endpoint: str = ENDPOINT,
                 campaign_url: str = CAMPAIGN_URL) -> str:
    """Walk the example campaign like the page does: connect, profile, three tasks, claim, then ask the
    campaign's backend for the payout (which checks the verdict with its secret key)."""
    campaign = {"id": CAMPAIGN_ID, "type": "campaign"}
    send([sdk_event(session, entity, "session.start", {"id": "localhost", "type": "site"}, context, {"event_count": 0}),
          sdk_event(session, entity, "page.view", {"id": "/", "type": "page"}, context)], endpoint)
    send([sdk_event(session, entity, "wallet.connect", campaign, context, telemetry_fn())], endpoint)
    send([sdk_event(session, entity, "campaign.join", campaign, context, telemetry_fn())], endpoint)
    for _task in range(3):
        send([sdk_event(session, entity, "task.complete", campaign, context, telemetry_fn())], endpoint)
    send([sdk_event(session, entity, "reward.claim", {**campaign, "sensitivity": "medium"}, context, telemetry_fn(),
                    {"amount": 25})], endpoint)
    result = post(f"{campaign_url}/claim", {"session": session, "wallet": entity}, {"Content-Type": "application/json"})
    return result.get("status", "unknown")


def new_session() -> str:
    return "ses_" + uuid.uuid4().hex
