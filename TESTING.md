# NeuroSOC Local Testing Guide

This guide provides instructions for sequentially testing the entire NeuroSOC platform locally using the CLI. The test suite has been structured for progressive validation.

## Prerequisites

Ensure you have the following installed and configured:
- Python 3.9+
- Docker & Docker Compose
- Node.js (for frontend testing)
- `pytest` for running Python test suites

## Test Directory Structure

The `tests/` directory is organized into logical, sequential stages:

1. **`01_unit/`**: Core functions, models, and stateless logic.
2. **`02_integration/`**: Cross-service communication, database models, Kafka queues.
3. **`03_e2e/`**: Full platform workflows and end-to-end API tests.

Tests for the SDK, the agent guard and the NovaTrust demo (`test_universal_agents.py`, `test_demo_*.py`, `test_dashboard_*.py`, `test_requirements_compat.py`, `test_verdict_snapshot_response.py`) sit directly in `tests/`. They need no Docker, Kafka, Redis or database.

## Running Tests Locally

To validate the platform, run these steps in order.

### Step 1: Unit Tests
Validate the core logic and standalone functions.
```bash
pytest tests/01_unit/ -v
```

### Step 2: Integration Tests
Ensure services like Kafka, Redis, and internal APIs communicate correctly. 
*Note: Make sure your local Docker services (Redis, Kafka, DB) are running.*
```bash
docker-compose up -d redis kafka postgres
pytest tests/02_integration/ -v
```

### Step 3: End-to-End (E2E) Tests
Test complete end-to-end user journeys and system interactions.
```bash
# Ensure all services are up
docker-compose up -d
pytest tests/03_e2e/ -v
```

### Run All Tests
To run the entire test suite sequentially:
```bash
pytest tests/ -v --order-dependencies
```

## SDK, Agent Guard and Demo Tests

These run in a few seconds with an in-memory store, with only Python (the repo's virtual environment) and Node installed:

```bash
pytest tests/test_universal_agents.py tests/test_demo_backend.py tests/test_demo_mode_gating.py \
       tests/test_demo_claude_planner.py tests/test_dashboard_snippets.py tests/test_dashboard_sdk_sync.py \
       tests/test_requirements_compat.py tests/test_verdict_snapshot_response.py \
       tests/02_integration/test_python_sdk.py -v          # 73 passed, 1 skipped
cd sdk/js && npm test                                      # browser SDK, 6 passed
cd dashboard && npx vite build                             # the dashboard builds
```

| Suite | What it covers |
| --- | --- |
| `test_universal_agents.py` | Agent registry validation, authorization and rate checks with their reasons, Monitor vs Protect, key and origin handling |
| `test_demo_backend.py`, `test_demo_mode_gating.py`, `test_demo_claude_planner.py` | The NovaTrust demo backend: tools behind the guard, simulations, outage behavior, demo-mode gating, the optional Claude planner (against a stubbed client) |
| `test_dashboard_snippets.py` | The wizard's snippets parse and run. One test installs the published package from PyPI and is skipped unless you set `NEUROSOC_TEST_PYPI=1` (needs network) |
| `test_dashboard_sdk_sync.py` | The dashboard's copy of the browser SDK matches `sdk/js` (re-sync with `python scripts/sync_dashboard_sdk.py`) |
| `02_integration/test_python_sdk.py` | The Python SDK, including failing closed when the server hangs up |

### Browser end-to-end run

`scripts/e2e_novatrust.mjs` drives headless Chrome through the whole demo (onboarding, consent, Nova AI, four attacks, live feed, outage) against a real API and the Vite dev server, with no mocks and no Docker. The commands to start both servers are in the header of that file. It needs `google-chrome-stable` and the `playwright-core` package already present in `dashboard/node_modules`.

```bash
node scripts/e2e_novatrust.mjs          # 19 steps; results are written to /tmp/ns_e2e/results.json
```

Start the API fresh before every run: applications and bot flags are kept in memory, so a second run against the same server fails its first step. The detector is real, so a scripted browser can be flagged as a bot; the recovery step therefore checks that NeuroSOC returns a real decision, not that a transfer was sent. The latest results are in [`docs/DEMO_TEST_REPORT.md`](docs/DEMO_TEST_REPORT.md).

## The whole suite

```bash
pytest tests -q          # 375 passed, 1 skipped (the opt-in PyPI install check)
```

It needs no Docker, Kafka, Redis or database. Files in `tests/01_unit/`, `02_integration/` and `03_e2e/` locate the repository root with
`Path(__file__).resolve().parents[2]` (two levels up); files directly in `tests/` use `parents[1]`. Keep that in mind when moving a test.

## Deployment tests

```bash
pytest tests/test_deploy_preflight.py -q    # secret generation and every preflight check
deployment/test_nginx_edge.sh                   # 15 checks of the nginx rules against real containers (needs Docker)
python3 deployment/preflight.py check           # on the deployment machine, before every deploy
```

`test_nginx_edge.sh` starts two throw-away nginx containers on a private subnet and removes them afterwards; it can run next to a live stack.
See [`deployment/README.md`](deployment/README.md).

## Troubleshooting
- **Missing modules**: Make sure you activate your virtual environment and run `pip install -r requirements.txt`.
- **Connection Refused**: Ensure `docker-compose up -d` has successfully started the required backing services before running integration and E2E tests.
