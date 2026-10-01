# NovaTrust demo test report

Results of a real run on 2026-10-01 against the code on `main` after PR #13 plus follow-up changes made after that merge and committed separately (an *Install the SDK* block in the Add Application wizard, the Vite WebSocket proxy fix and the Referer fallback for same-origin key checks). Nothing is mocked: `node scripts/e2e_novatrust.mjs` drives headless Chrome through the dashboard and the NovaTrust app against a live API (uvicorn on :8010, demo mode on, in-memory store, no Docker) and the Vite dev server (:5173). The browser runs the real JavaScript SDK, Nova AI's backend calls NeuroSOC through the real Python SDK over HTTP, and the outage step cuts that HTTP connection. The full technical description is Volume 4 of the technical documentation.

## Browser end-to-end (19/19 passed, fresh API start)

| # | Test | Status | Evidence (from the run) |
|---|---|---|---|
| 01 | dashboard starts with no applications | PASS | - |
| 02 | Add Application wizard: NovaTrust, Both, Protect, agent novatrust-agent | PASS | tools=5, sensitive=token.transfer, resource=treasury |
| 03 | keys: public key shown, secret masked until revealed, confirmation required | PASS | pk=pk_R_qCVMr… |
| 04 | integration snippets for script tag, module and Python use the public key only | PASS | - |
| 05 | secret key not in browser storage; SDK bundle is served | PASS | - |
| 06 | Launch NovaTrust connects the backend and opens /demo | PASS | - |
| 07 | consent banner shown and SDK dormant (zero /sdk requests) before Accept | PASS | sdk requests before consent: 0 |
| 08 | 'Not now' keeps the SDK dormant, also after reload | PASS | - |
| 09 | Accept (Security page) starts real SDK events | PASS | 2 SDK request(s) after Accept |
| 10 | normal human transfer is allowed | PASS | - |
| 11 | Nova AI: balance, then a prepared transfer that the owner confirms | PASS | - |
| 12 | prompt injection is blocked with a reason | PASS | Prompt injection / Blocked / I did not send that. NeuroSOC paused the action: sends value to a destination never used before (attacker-9x7). No money moved. / Decision: pause_agent · risk 1.00 / sends value to  |
| 13 | unauthorized resource (token.transfer on the vault) is blocked | PASS | Unauthorized resource / Blocked / I did not send that. NeuroSOC paused the action: agent novatrust-agent is not authorized to act on resource treasury_cold_storage_vault. No money moved. / Decision: pause_agent |
| 14 | excessive actions: agent paused part-way through ~20 transfers | PASS | paused at attempt 11 of 20 |
| 15 | suspicious new session is flagged | PASS | Suspicious session / Flagged / A scripted signup (perfectly regular keystrokes, a straight mouse path, a whole form in about a second) was flagged: typing rhythm is machine-regular (variation 0.00, people ~0.3+ |
| 16 | dashboard live feed shows the events with all eight fields | PASS | 32 rows |
| 17 | NeuroSOC unreachable: transfer fails closed with a clear message | PASS | balance unchanged; dashboard still readable |
| 18 | recovery: NeuroSOC answers again with a real decision (not 'unavailable') | PASS | transfer sent |
| 19 | no uncaught page errors | PASS | - |

Screenshots from this run are in `docs/demo-screenshots/`: the empty Applications list, the agent step, the keys step (public key, show-once secret and the *Install the SDK* block with `pip install neurosoc`), the consent banner, Nova AI, the prompt-injection block, the live feed and the outage notice.

## Automated suites (same day, same code)

| Suite | Result |
|---|---|
| SDK, agent guard and demo pytest files (`test_universal_agents`, `test_demo_backend`, `test_demo_mode_gating`, `test_demo_claude_planner`, `test_dashboard_snippets`, `test_dashboard_sdk_sync`, `test_requirements_compat`, `test_verdict_snapshot_response`, `02_integration/test_python_sdk`) | 73 passed, 1 skipped (the opt-in PyPI install check) |
| `npm test` in `sdk/js` | 6 passed |
| `vite build` in `dashboard` | builds |
| `NEUROSOC_TEST_PYPI=1 pytest tests/test_dashboard_snippets.py` | passes: the wizard's Python snippet runs against the package installed from PyPI (0.1.2) |
| `pytest tests` (the whole folder) | 375 passed, 1 skipped (after the test-layout fix described below) |

**Earlier whole-folder failures were a test-layout bug, since fixed.** When the tests were moved into `tests/01_unit/`, `02_integration/` and `03_e2e/`, files that find the repository root with `parents[1]` ended up one level too shallow, so a run of `tests/` showed 25 failures and 24 errors that had nothing to do with the code under test. Changing them to `parents[2]` made the whole suite pass (375 passed, 1 skipped).

## What the runs showed

- **A real SDK bug, found and fixed earlier by the outage step:** with NeuroSOC hanging up mid-reply, the Python SDK raised a raw `RemoteDisconnected` instead of `NeuroSOCError`, so the fail-closed path was skipped. `_http` now wraps every transport error; the regression test is `test_connection_dropped_mid_reply_is_a_neurosoc_error_and_fails_closed`. Released in `neurosoc` 0.1.2.
- **Live feed stuck on "Connecting" in development:** the Vite proxy did not forward the WebSocket at `/api/v1/universal/ws`. Fixed with `ws: true` on `/api`.
- **403 on `/api/v1/sdk/config` for a same-origin page load:** browsers send no `Origin` header on same-origin GETs. The key check now falls back to the Referer's origin; a stranger's Referer and a request with neither header are still refused (`test_publishable_key_config_accepts_same_origin_get_via_referer_but_not_a_stranger`).
- **Headless Chrome can be flagged as a bot.** Playwright's scripted mouse and keys are machine-regular, so the real detector sometimes judges the test account a bot, and the flag is stored for 7 days. In earlier runs the recovery step ended with *stopped: account was already flagged*; in this run it ended with *transfer sent*. Step 18 therefore asserts that NeuroSOC answers with a real decision rather than that the transfer was sent.
- **Start the API fresh before every run.** Applications and flags live in memory, so a second run against the same server fails step 01 (applications already exist) and can fail step 10 (flagged account).
- **Excessive actions** tripped at attempt 11 of 20 (limit: 10 sensitive actions per 60 s).

## Not covered

The optional Claude planner against the live API (it is covered only by unit tests with a stubbed client), Keycloak/OIDC-enabled runs, the Docker stack, and any measurement of the browser SDK's overhead.
