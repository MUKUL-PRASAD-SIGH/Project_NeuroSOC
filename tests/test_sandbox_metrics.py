from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_DIR = REPO_ROOT / "sandbox-service"


def _load_sandbox_main():
    module_name = "neurosoc_sandbox_main_for_tests"
    spec = importlib.util.spec_from_file_location(module_name, SANDBOX_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(SANDBOX_DIR))
    spec.loader.exec_module(module)
    return module


sandbox_main = _load_sandbox_main()
client = TestClient(sandbox_main.app)


def test_metrics_endpoint_is_exempt_from_the_sandbox_token_middleware():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_exposes_the_sandbox_series():
    body = client.get("/metrics").text
    for series in (
        "neurosoc_sandbox_sessions_created_total",
        "neurosoc_sandbox_sessions_active",
        "neurosoc_sandbox_actions_total",
        "neurosoc_sandbox_honeypot_hits_total",
    ):
        assert series in body


def test_log_action_increments_actions_and_honeypot_counters(monkeypatch):
    monkeypatch.setattr(sandbox_main.manager.repository, "log_action", lambda **_kwargs: None)
    monkeypatch.setattr(sandbox_main.manager.repository, "record_honeypot_hit", lambda **_kwargs: None)

    before_actions = sandbox_main.ACTIONS_LOGGED._value.get()
    before_hits = sandbox_main.HONEYPOT_HITS.labels(trigger_type="HONEYPOT_ENDPOINT")._value.get()

    sandbox_main.manager.log_action(
        sandbox_token="sbx-test",
        request_data={"path": "/api/admin", "method": "GET", "headers_json": {}, "body": None},
        response_data={"status_code": 200},
        triggers=[sandbox_main.TriggerEvent(trigger_type="HONEYPOT_ENDPOINT", severity="CRITICAL", details="hit")],
    )

    assert sandbox_main.ACTIONS_LOGGED._value.get() == before_actions + 1
    assert sandbox_main.HONEYPOT_HITS.labels(trigger_type="HONEYPOT_ENDPOINT")._value.get() == before_hits + 1
