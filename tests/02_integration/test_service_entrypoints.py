"""Services must start the way their Docker images start them: `python main.py`.

A `uvicorn.run("main:app")` entrypoint imports main.py a second time, registers the Prometheus
metrics twice and crashes before serving; this caught the sandbox and inference containers.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# The sandbox needs PostgreSQL to finish starting (by design), so without a database this checks
# that it gets past import and uvicorn starts serving; inference must answer /health.
@pytest.mark.parametrize(
    "service, port_env, needs_health",
    [("sandbox-service", "SANDBOX_PORT", False), ("inference-service", "INFERENCE_PORT", True)],
)
def test_service_starts_with_python_main(service: str, port_env: str, needs_health: bool, tmp_path: Path) -> None:
    port = _free_port()
    env = {
        **os.environ,
        "APP_ENV": "test",
        port_env: str(port),
        "SANDBOX_HOST": "127.0.0.1",
        "INFERENCE_HOST": "127.0.0.1",
        "REDIS_URL": "",
        "DATABASE_URL": "",
        "KAFKA_BOOTSTRAP": "127.0.0.1:1",
        "CONSUMER_RETRY_SECONDS": "60",
        "PYTHONWARNINGS": "ignore",
    }
    log_path = tmp_path / "service.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "main.py"], cwd=REPO_ROOT / service, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + 120
            healthy = False
            while time.time() < deadline and process.poll() is None:
                if not needs_health and "Started server process" in log_path.read_text(encoding="utf-8", errors="replace"):
                    time.sleep(2)
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                        healthy = response.status == 200
                        break
                except OSError:
                    time.sleep(1)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
    output = log_path.read_text(encoding="utf-8", errors="replace")
    assert "Duplicated timeseries" not in output
    if needs_health:
        assert healthy, output[-2000:]
    else:
        assert "Started server process" in output, output[-2000:]
