"""The flag-on wiring in main.py, exercised in a fresh interpreter.

Other test modules import main.py once with ENABLE_UNIVERSAL_ENGINE unset, and the flag is read
at import time, so the enabled path runs in a subprocess with its own environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_DIR = REPO_ROOT / "inference-service"

SCRIPT = textwrap.dedent(
    """
    import json, sys
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    origin = "https://launchpad.example"
    event = {"session_id": "session-main-1", "entity": {"id": "wallet-9", "type": "human"},
             "action": "page.view", "resource": {"id": "home", "type": "page"}}
    results = {
        "health": client.get("/health").status_code,
        # The service API key still guards existing routes...
        "existing_without_key": client.get("/api/v1/stats").status_code,
        # ...while SDK routes authenticate with site keys instead.
        "sdk_with_site_key": client.post("/api/v1/sdk/events", json={"events": [event]},
                                         headers={"X-NeuroSOC-Key": "pk_test_main", "Origin": origin}).status_code,
        "sdk_without_site_key": client.post("/api/v1/sdk/events", json={"events": [event]},
                                            headers={"Origin": origin}).status_code,
        "sdk_preflight": client.options("/api/v1/sdk/events", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST"}).status_code,
        # Analyst routes stay behind the existing auth (the service API key here).
        "analyst_without_key": client.get("/api/v1/universal/verdicts/latest").status_code,
        "analyst_with_key": client.get("/api/v1/universal/verdicts/latest",
                                       headers={"X-API-Key": "service-key-for-tests"}).status_code,
        # The dashboard's own CORS policy is unchanged.
        "dashboard_preflight": client.options("/api/v1/stats", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}).status_code,
    }
    print("RESULT" + json.dumps(results))
    """
)


def test_flag_on_wires_sdk_routes_without_loosening_existing_auth(tmp_path):
    sites = tmp_path / "sites.json"
    sites.write_text(json.dumps([{
        "site_id": "main-test-site", "tenant_id": "local", "name": "Main wiring test",
        "publishable_key": "pk_test_main", "secret_key": "sk_test_main_secret",
        "allowed_origins": ["https://launchpad.example"], "mode": "observe", "rules": [],
    }]), encoding="utf-8")
    env = {
        **os.environ,
        "APP_ENV": "test",
        "ENABLE_UNIVERSAL_ENGINE": "true",
        "UNIVERSAL_SITES_FILE": str(sites),
        "API_KEY": "service-key-for-tests",
        "REDIS_URL": "",
        "DATABASE_URL": "",
        "PYTHONWARNINGS": "ignore",
    }
    completed = subprocess.run([sys.executable, "-c", SCRIPT], cwd=INFERENCE_DIR, env=env,
                               capture_output=True, text=True, timeout=300)
    line = next((l for l in completed.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line is not None, completed.stderr[-3000:]
    results = json.loads(line[len("RESULT"):])
    assert results == {
        "health": 200,
        "existing_without_key": 401,
        "sdk_with_site_key": 200,
        "sdk_without_site_key": 401,
        "sdk_preflight": 204,
        "analyst_without_key": 401,
        "analyst_with_key": 200,
        "dashboard_preflight": 200,
    }
