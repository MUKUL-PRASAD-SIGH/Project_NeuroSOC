"""Start the NeuroSOC SDK demo locally without Docker, in one command.

    python scripts/run_sdk_demo.py            # engine :8000, example campaign :5500, dashboard :3000
    python scripts/run_sdk_demo.py --seed     # also seed 20 people so baselines exist

Then, in another terminal:
    python attack_patterns/bot_farm.py --count 30
    python attack_patterns/agent_hijack.py --normal 20

Needs: the inference-service Python requirements, Node 20+, and one-time builds
(`cd sdk/js && npm install && npm run build`, `cd dashboard && npm install --legacy-peer-deps`).
Storage is in memory (no Redis/Postgres/Kafka), so restarting clears the demo. Ctrl+C stops everything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wait_for(url: str, seconds: int = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", action="store_true", help="seed 20 people after start")
    parser.add_argument("--no-dashboard", action="store_true")
    args = parser.parse_args()

    if not (ROOT / "sdk/js/dist/neurosoc.min.js").exists():
        sys.exit("Build the SDK first: cd sdk/js && npm install && npm run build")

    engine_env = {
        **os.environ,
        "APP_ENV": "local",
        "ENABLE_UNIVERSAL_ENGINE": "true",
        "UNIVERSAL_SITES_FILE": str(ROOT / "sdk/sites.local.json"),
        # Every simulated user comes from this machine's IP, so the per-IP limit is raised.
        "API_RATE_LIMIT_PER_MINUTE": os.getenv("API_RATE_LIMIT_PER_MINUTE", "100000"),
        "REDIS_URL": "",
        "DATABASE_URL": "",
        "KAFKA_BOOTSTRAP": os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:1"),
        "CONSUMER_RETRY_SECONDS": "60",
    }
    processes: list[subprocess.Popen] = []
    try:
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
            cwd=ROOT / "inference-service", env=engine_env))
        if not wait_for("http://127.0.0.1:8000/health"):
            sys.exit("The engine did not start on :8000 (see its output above).")
        print("engine      http://localhost:8000   (SDK engine on, in-memory)", flush=True)

        processes.append(subprocess.Popen([sys.executable, str(ROOT / "sdk/examples/rewards-campaign/server.py")],
                                          env={**os.environ, "NEUROSOC_ENDPOINT": "http://127.0.0.1:8000"}))
        wait_for("http://127.0.0.1:5500/")
        print("campaign    http://localhost:5500   (example site with the script tag)", flush=True)

        if not args.no_dashboard:
            npx = shutil.which("npx") or shutil.which("npx.cmd")
            if npx:
                processes.append(subprocess.Popen(
                    [npx, "vite", "--port", "3000", "--strictPort"], cwd=ROOT / "dashboard",
                    env={**os.environ, "VITE_UNIVERSAL_ENABLED": "true", "VITE_USE_MOCKS": "false",
                         "VITE_API_URL": "http://localhost:8000"}))
                print("dashboard   http://localhost:3000/protection", flush=True)
            else:
                print("dashboard   skipped (npx not found)", flush=True)

        if args.seed:
            subprocess.call([sys.executable, str(ROOT / "attack_patterns/human_seed.py"), "--count", "20", "--speed", "100",
                             "--endpoint", "http://127.0.0.1:8000", "--campaign", "http://127.0.0.1:5500"])

        print("\nReady. Ctrl+C to stop.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
