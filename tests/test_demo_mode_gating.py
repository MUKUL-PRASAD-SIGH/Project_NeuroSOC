"""NEUROSOC_DEMO_MODE is read when main.py is imported, so each case runs in a fresh interpreter."""
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
    import json
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app, client=("127.0.0.1", 50000))
    session = {"X-Demo-Session": "session-gating-1"}
    results = {
        "config": client.get("/api/v1/demo/config").status_code,
        "account": client.get("/api/v1/demo/account", headers=session).status_code,
        "chat": client.post("/api/v1/demo/agent/chat", json={"message": "hi"}, headers=session).status_code,
        "simulate": client.post("/api/v1/demo/simulate", json={"type": "prompt_injection"}, headers=session).status_code,
        "connect": client.post("/api/v1/demo/connect", json={"secret_key": "sk_not_a_real_key"}).status_code,
        "sdk_still_routed": client.get("/api/v1/sdk/config").status_code,
    }
    body = client.get("/api/v1/demo/config")
    results["config_has_secret"] = "sk_" in body.text
    print("RESULT" + json.dumps(results))
    """
)


def run(env_extra: dict[str, str], tmp_path: Path):
    sites = tmp_path / "sites.json"
    sites.write_text("[]", encoding="utf-8")
    env = {**os.environ, "APP_ENV": "test", "ENABLE_UNIVERSAL_ENGINE": "true", "UNIVERSAL_SITES_FILE": str(sites),
           "REDIS_URL": "", "DATABASE_URL": "", "PYTHONWARNINGS": "ignore", **env_extra}
    env.pop("API_KEY", None) if "API_KEY" not in env_extra else None
    return subprocess.run([sys.executable, "-c", SCRIPT], cwd=INFERENCE_DIR, env=env, capture_output=True,
                          text=True, timeout=300)


def results_of(completed):
    line = next((l for l in completed.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line is not None, completed.stderr[-3000:]
    return json.loads(line[len("RESULT"):])


def test_demo_routes_do_not_exist_unless_demo_mode_is_on(tmp_path):
    results = results_of(run({"NEUROSOC_DEMO_MODE": "false"}, tmp_path))
    assert [results[k] for k in ("config", "account", "chat", "simulate", "connect")] == [404] * 5
    assert results["sdk_still_routed"] == 401   # the SDK routes are there (no key -> 401), only the demo is absent


def test_demo_routes_exist_in_demo_mode_and_never_expose_a_secret(tmp_path):
    results = results_of(run({"NEUROSOC_DEMO_MODE": "true"}, tmp_path))
    assert results["config"] == 200 and results["account"] == 200
    assert results["chat"] == 409 and results["simulate"] == 409      # mounted, but no application connected yet
    assert results["connect"] == 403 and results["config_has_secret"] is False


def test_demo_mode_without_the_universal_engine_mounts_nothing(tmp_path):
    results = results_of(run({"NEUROSOC_DEMO_MODE": "true", "ENABLE_UNIVERSAL_ENGINE": "false"}, tmp_path))
    assert results["config"] == 404


def test_production_refuses_to_start_with_demo_mode_on(tmp_path):
    completed = run({"NEUROSOC_DEMO_MODE": "true", "APP_ENV": "production"}, tmp_path)
    assert "NEUROSOC_DEMO_MODE cannot be enabled in staging or production" in completed.stderr
    assert not any(l.startswith("RESULT") for l in completed.stdout.splitlines())
