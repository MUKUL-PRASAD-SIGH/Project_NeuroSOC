"""Builds NeuroSOC Technical Specification Volume 4 (Word) in the style of Volumes 1 to 3.

    python3 scripts/docs/build_volume4.py [output.docx]

Default output: ~/Documents/NeuroSOC_Documentation_Volume_4_Universal_SDK_and_Agent_Guard.docx
Every figure in this document comes from the code (inference-service/core/universal, api/routes, sdk/) or from a
test run; the numbers in section 10 are the results of the run named there.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docx_style import (bullets, callout, caption, code, h1, h2, header_footer, link_table, new_document, para,  # noqa: E402
                        spec_table, table, title_block)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Documents" / "NeuroSOC_Documentation_Volume_4_Universal_SDK_and_Agent_Guard.docx"
W = 9360

doc = new_document()
header_footer(doc)

title_block(doc, "TECHNICAL SPECIFICATION SERIES — VOLUME 4",
            "NeuroSOC: Universal SDK & Agent Guard Blueprint",
            "SDKs, Application and Agent Registry, the Universal Engine API and the NovaTrust Customer Demo")
spec_table(doc, [
    ("Document ID", "NEUROSOC-DOC-VOL-04"),
    ("Version / Release", "v1.2.0 (documents SDK release 0.1.2)"),
    ("Target System", "NeuroSOC Universal Behavioral Engine, SDKs and Agent Guard"),
    ("Service Languages", "Python 3.11 (FastAPI engine), Python 3.9+ (SDK, standard library only), TypeScript (browser SDK), React 18 (dashboard)"),
    ("Document Scope", "SDKs, registry, agent authorization, detection pipeline, APIs, demo application, verification, and the measured accuracy of the three models (section 14). Builds on Volumes 1 to 3; section 12 records the revisions made to them."),
    ("Classification", "Technical Specification / Implementation Reference"),
    ("Target Audience", "Application developers, AI-agent developers, security engineers, SOC operators, DevOps / SecOps"),
])

callout(doc, "NOTE", "DOCUMENT ABSTRACT & EXECUTIVE SUMMARY",
        "Volume 4 documents the part of NeuroSOC that protects other people's applications. A customer installs the SDK in a website, "
        "a backend or an AI agent; NeuroSOC scores every action against the behavior of the person, wallet or agent that performed it "
        "and returns a verdict: allow, step up, shadow, or pause the agent. It covers the two SDKs, the application registry with its keys "
        "and modes, the agent registry and authorization guard that stops a prompt-injected agent before its tool runs, the universal "
        "engine's detectors and API, the dashboard workflow, and NovaTrust, a complete customer application used to demonstrate and test the "
        "whole loop end to end.")

h2(doc, "Document Overview & Structure")
para(doc, "This is Volume 4 of the NeuroSOC technical documentation suite. The series is now:")
bullets(doc, [
    ("Volume 1", "System architecture, operations and infrastructure."),
    ("Volume 2", "The SNN and LNN detection engine, behavioral biometrics and retraining."),
    ("Volume 3", "Microservices, deception engineering, frontends and the Inference Service API."),
    ("Volume 4 (this document)", "The Universal SDK, the application and agent registry, the universal engine and Agent Guard, and the NovaTrust customer demo."),
])
callout(doc, "IMPORTANT", "Two things called NovaTrust",
        "Volumes 1 to 3 describe the NovaTrust Bank Simulation Portal (simulation_portal/, port 3001), a red-team testbed for the network "
        "detection path. This volume describes the NovaTrust Customer Demo, a separate application served at /demo inside the analyst dashboard "
        "that exercises the SDK. They share a name and a fictional bank, and nothing else. In this volume 'the demo' always means the customer demo.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "1. Executive Summary & Mission")
para(doc, "The platform described in Volumes 1 to 3 watches network traffic. Most modern abuse does not look like network traffic: it is a script "
          "signing up thousands of accounts to claim a reward, a ring of wallets funded from one source, or an AI agent tricked by a hidden "
          "instruction into sending funds to a stranger. The universal engine scores those behaviors where they happen, inside an application, "
          "with a verdict returned in the same request. Industry reports on alert fatigue, account-takeover fraud, breach cost and the UEBA market, "
          "which motivate this work, are listed with links in section 13.7; they are third-party sources and their figures are theirs, not NeuroSOC measurements.")
callout(doc, "IMPORTANT", "The Core Value Proposition",
        "Problem: bots, bot farms and manipulated AI agents look like normal traffic to rules written in advance.\n"
        "Solution: score every action against that entity's own baseline, then return a plain-language verdict the application can act on.\n"
        "Outcome: a customer adds one package and a few lines of code, and a hijacked agent is stopped before its tool executes, outside the language model.")

h2(doc, "1.1 Network Pipeline vs. Universal Engine")
caption(doc, "Table: How the Universal Engine Differs from the Network Detection Path")
table(doc, ["Dimension", "Network path (Volumes 1 to 3)", "Universal engine (this volume)"], [
    ["Input", "Packets and flows, a fixed vector of flow features, over Kafka.", "One normalized behavior event per action, sent by an SDK over HTTPS."],
    ["Entities", "IP addresses and sessions.", "People, wallets, AI agents and services (entity types human, wallet, agent, service)."],
    ["Models", "SNN, LNN and XGBoost fused by the Decision Engine.", "Per-entity statistical baselines with three detectors; a learned SNN/LNN scorer can be plugged in through one setting."],
    ["Verdicts", "HACKER, FORGETFUL_USER, LEGITIMATE; P1 to P4 alerts.", "ok, review, suspected_bot, bot_farm, agent_anomaly, each with a recommended response."],
    ["Response", "Honeypot diversion and analyst review.", "allow, step_up, shadow, pause_agent, applied by the customer's application or SDK."],
    ["Storage", "PostgreSQL and Kafka.", "A key-value store: Redis when REDIS_URL is set, otherwise in-process memory."],
    ["Dependency", "Feature Service, models, Kafka.", "None of those: the engine imports only read-only behavioral signal extractors and runs when ENABLE_UNIVERSAL_ENGINE=true."],
], [1700, 3600, 4060])

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "2. System Architecture")
h2(doc, "2.1 Components")
bullets(doc, [
    ("Browser SDK (@neurosoc/sdk)", "Runs in the customer's page. Collects timing and movement (never typed text), maps clicks to actions with the site's rules, sends batches with the publishable key. Dormant until the visitor consents when configured to wait."),
    ("Python SDK (neurosoc)", "Runs in the customer's backend or agent. Sends events and synchronous guards with the secret key. guard_tool() wraps an agent tool so it can only run after NeuroSOC allows it."),
    ("SDK API (/api/v1/sdk/*)", "Authenticates the key, normalizes the event, deduplicates by idempotency key and calls the engine."),
    ("Universal Engine (core/universal)", "Computes features, compares them with baselines, runs the detectors, stores the verdict and keeps account and session flags."),
    ("Site registry", "Applications, their keys, allowed origins, mode, rules and registered agents."),
    ("Live stream", "A WebSocket that pushes each verdict to the dashboard; webhooks push to a customer's server with an HMAC signature."),
    ("Dashboard (Protection page)", "Live verdicts, agent watch, campaign integrity and the Add Application wizard."),
    ("NovaTrust Customer Demo", "A complete customer application with an AI assistant, used to demonstrate and test the loop."),
])
h2(doc, "2.2 Data Flow")
caption(doc, "Listing: Universal Engine Request Flow")
code(doc, """
 customer page (pk_, after consent)      customer backend / AI agent (sk_)
   Browser SDK                             Python SDK
      | POST /api/v1/sdk/events               | POST /api/v1/sdk/guard (or /events)
      +------------------+--------------------+
                         v
   [ SDK API: key check -> origin check (pk) -> normalize -> idempotency ]
                         |
                         v
   [ UniversalEngine.process ]
       features -> baseline z-scores -> scorer (spike, drift)
                         |
         +---------------+----------------+
         v               v                v
   [ humanity ]    [ bot farm ]     [ Agent Guard ]
         +---------------+----------------+
                         v
        verdict + risk + reasons (stored; flags and session stickiness)
                         |
       +-----------------+------------------+----------------+
       v                 v                  v                v
  response to SDK   WebSocket feed    webhooks (HMAC)   analyst override
  (pk: 5 fields)    /universal/ws     to the customer   (restore/confirm)""")
h2(doc, "2.3 Enabling the Engine and Storage")
para(doc, "The engine is off by default. With ENABLE_UNIVERSAL_ENGINE=false the Inference Service behaves exactly as in Volumes 1 to 3: no SDK routes "
          "and no extra storage. When enabled, state is kept in a key-value store. REDIS_URL selects Redis; without it the engine uses an in-process "
          "store with TTL support, which is correct for one process and for demos, and loses state on restart. Network identifiers are hashed with "
          "UNIVERSAL_HASH_SECRET before storage, so the engine never stores a raw IP address. Normalized events are also published to a Kafka topic (BEHAVIOR_EVENTS_TOPIC); the Kafka documentation is linked in section 13.6.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "3. Concepts & Data Model")
h2(doc, "3.1 Applications (Sites)")
para(doc, "Every website or agent platform that installs the SDK is an application (a 'site' in the code). An application belongs to one tenant.")
caption(doc, "Table: Application Record")
table(doc, ["Field", "Meaning"], [
    ["site_id, tenant_id, name", "Identity of the application and the tenant that owns it."],
    ["publishable_key (pk_...)", "Safe to place in a web page. Can send events and read the site's configuration; cannot read verdict detail."],
    ["secret_key (sk_...)", "Server side only. Stored only as a SHA-256 digest; shown once when the application is created."],
    ["allowed_origins", "Browser origins the publishable key may be used from. A request without an Origin header is checked against its Referer's origin."],
    ["mode", "observe (Monitor) or enforce (Protect). See 3.3."],
    ["app_type", "web, agent or both."],
    ["url", "Optional http(s) address of the application (at most 256 characters)."],
    ["preset, rules", "Rules that map clicks and form submits to actions for the browser SDK (for example the novatrust preset)."],
    ["agents", "The agent registry: up to 20 agents, each with its tools, sensitive actions and authorized resources (section 5)."],
    ["webhooks", "Destination URLs; each has a signing secret (whsec_...) used to sign deliveries with HMAC-SHA256."],
    ["demo", "True for an application connected to the NovaTrust demo."],
], [2600, 6760])

h2(doc, "3.2 Key Types and What They May Do")
caption(doc, "Table: Publishable vs. Secret Key")
table(doc, ["Capability", "Publishable key (pk_)", "Secret key (sk_)"], [
    ["Where it lives", "In the page; visible to visitors.", "On the customer's server or agent only."],
    ["Send events (POST /api/v1/sdk/events)", "Yes, from a registered origin.", "Yes."],
    ["Synchronous guard (POST /api/v1/sdk/guard)", "No.", "Yes."],
    ["Read a session verdict", "No.", "Yes."],
    ["Read site configuration (GET /api/v1/sdk/config)", "Yes, from a registered origin.", "Yes."],
    ["What a response contains", "verdict_id, session_id, event_id, action, enforced. Scores, reasons and linked accounts are withheld so a bot cannot learn what gave it away.", "The full verdict."],
], [2900, 3200, 3260])
callout(doc, "IMPORTANT", "Origin checks are not authentication",
        "The Origin and Referer checks stop another website from reusing a publishable key in a visitor's browser. They are headers the sender "
        "controls, so they are a browser-side control only. Anything that must be trusted uses the secret key.")

h2(doc, "3.3 Modes: Monitor and Protect")
para(doc, "Every verdict carries enforced=true when the application is in Protect mode. The engine scores identically in both modes; what changes is "
          "what the application is told to do with the result.")
caption(doc, "Table: Monitor vs. Protect")
table(doc, ["", "Monitor (observe)", "Protect (enforce)"], [
    ["Decision recorded and shown in the dashboard", "Yes", "Yes"],
    ["verdict.enforced", "false", "true"],
    ["guard_tool(block_only_when_enforced=True)", "The tool runs; the decision is recorded.", "The tool is blocked with ActionBlocked."],
    ["Shadowed sessions mirrored to the sandbox", "No", "Yes, once per session"],
    ["Purpose", "Learn what would be blocked before turning enforcement on.", "Stop the action."],
], [3400, 2980, 2980])

h2(doc, "3.4 The Event")
para(doc, "The SDK sends only what the page or agent knows. The server adds the tenant, the site, the schema version and the idempotency key, hashes network "
          "identifiers, and rejects unknown fields. A timestamp more than 300 seconds from server time is replaced with the server's time.")
caption(doc, "Table: Event Fields (SdkEvent)")
table(doc, ["Field", "Type and limits", "Notes"], [
    ["event_id", "UUID or any string; a non-UUID is mapped to a stable UUID per site.", "Makes retries idempotent: a repeated event returns the first verdict (cached for 1 hour)."],
    ["timestamp, session_id", "Unix seconds; string up to 256 characters.", "Sessions are the unit of stickiness (3.6)."],
    ["entity", "id (1 to 256 chars); type: human, agent, wallet or service.", "Who acted."],
    ["action", "One of the fixed taxonomy actions (3.5).", "What they did."],
    ["resource", "id; type (up to 64 chars); sensitivity: low, medium, high or critical.", "What it touched."],
    ["result", "success, failure or denied.", "Default success."],
    ["value", "amount (>= 0); asset (32); destination (256).", "For actions that move value."],
    ["context", "device_hash, user_agent_hash, wallet, funded_by, geo (8), page, page_origin.", "Used for novelty and for linking accounts."],
    ["telemetry", "session_vector (20 numbers) or events (up to 2000) plus event_count.", "Typing and movement timing; a keystroke is recorded only as a class (char, space, backspace), never the key."],
    ["agent", "tool (128), instruction_source: owner, system or external_content.", "Set by the agent harness, never by the language model."],
], [1700, 3900, 3760])

h2(doc, "3.5 Action Taxonomy")
caption(doc, "Table: Fixed Action Vocabulary (schemas/taxonomy.json)")
table(doc, ["Category", "Actions"], [
    ["navigation", "session.start, page.view, form.submit"],
    ["identity", "account.create, auth.login, auth.logout, wallet.connect, wallet.sign"],
    ["engagement", "campaign.join, task.complete, reward.claim, referral.create"],
    ["value", "token.buy, token.sell, token.transfer, liquidity.add, liquidity.remove"],
    ["agent", "agent.run, agent.tool_call, agent.config_change"],
    ["admin", "permission.change, api_key.create, api.call"],
], [2000, 7360])

h2(doc, "3.6 State, Stickiness and Retention")
bullets(doc, [
    ("Entity state", "Kept 30 days: recent events, devices, IPs and resources seen, hours of activity."),
    ("Account flag", "A suspected_bot, bot_farm or agent_anomaly verdict flags the account for 7 days. A later event that would otherwise be ok is raised back to the flagged verdict (risk at least 0.8) with the reason 'account was already flagged'."),
    ("Session stickiness", "A shadow or pause verdict sticks to its session for 24 hours. A review is a one-off step-up and does not stick."),
    ("Baselines learn only from good behavior", "The entity and its group baselines are updated only from ok and review verdicts, so an attacker cannot teach the engine that abuse is normal."),
    ("Verdicts", "Stored 7 days; the 500 most recent per tenant are listed for the dashboard."),
])

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "4. Detection & Decisions")
h2(doc, "4.1 The Pipeline")
para(doc, "For each event the engine (1) computes features from the entity's recent history, (2) converts the features that have a baseline into z-scores, "
          "(3) asks the scorer for a spike and a drift score, (4) runs three detectors, and (5) combines them into one verdict. The whole step runs under a lock "
          "per process so an entity's state is never updated by two events at once.")
h2(doc, "4.2 Features")
caption(doc, "Table: Per-Event Features")
table(doc, ["Group", "Features"], [
    ["Rate and rhythm", "event_rate_1m, event_rate_1h, burstiness, inter_event_cv, mean_gap_seconds, time_in_session, entity_age_hours"],
    ["Novelty", "new_device, new_ip, new_resource, new_action, new_destination"],
    ["Behavior shape", "failure_rate, action_entropy, sequence_surprise (how unusual the step from the previous action is, learned per entity group)"],
    ["Reach and privilege", "unique_resources_1h, fan_out_1h, privilege_delta (a more sensitive resource than ever before)"],
    ["Context change", "off_hours, geo_change, device_change, cold_start"],
    ["Value", "value_amount (only on events that carry a value)"],
], [2400, 6960])
h2(doc, "4.3 Baselines")
para(doc, "Seven features are scored against running baselines: event_rate_1m, inter_event_cv, failure_rate, sequence_surprise, unique_resources_1h, fan_out_1h "
          "and value_amount. Each keeps its own mean and variance (Welford's method) and its own count, so an amount is compared only with earlier amounts. "
          "A feature is scored once it has 5 observations, with a floor on its standard deviation so a perfectly regular history does not make the first small "
          "wobble look enormous. An entity uses its own baseline after 20 events; before that it is compared with its group (all entities of the same type).")
h2(doc, "4.4 The Scorer")
para(doc, "The scorer is the one place a learned model plugs in. It returns two numbers between 0 and 1: spike (a sudden burst) and drift (a gradual departure). "
          "The default ZScoreScorer derives both from the z-scores so the engine produces real scores from day one:")
code(doc, """
spike = clip((max(z[event_rate_1m], 0) - 2) / 4)
drift = clip((mean(|z| of the other baselined features) - 1) / 3)
drift = max(drift, clip((sequence_surprise - 0.8) / 0.2) * 0.5)
""")
para(doc, "Setting UNIVERSAL_SCORER=module:factory loads a trained SNN/LNN scorer instead. If it cannot be loaded the engine logs the error and falls back to the "
          "z-score scorer, so a broken model never takes the engine down.")
h2(doc, "4.5 The Three Detectors")
bullets(doc, [
    ("Humanity (is this session driven by a person?)", "Built from the 20-number session vector. Typing variation, mouse curvature and speed variation, time to finish and correction rate are combined as 0.30 typing + 0.30 mouse + 0.25 pace + 0.15 corrections. A score below 0.35 on an interactive action (form submit, task, claim, sign-up) gives suspected_bot. Reasons are plain, for example 'typing rhythm is machine-regular (variation 0.00, people ~0.3+)'. A form action with fewer than 3 input events scores 0.15."),
    ("Bot farm (are many accounts one operator?)", "Accounts on one resource are linked by a shared device hash or funding wallet (strong links), or by two weak links such as an IP block, and by near-identical input timing (within 2 percent). Five or more linked accounts is a bot_farm; every member is flagged."),
    ("Agent Guard (is this agent acting within its rules?)", "Described in section 5."),
])
h2(doc, "4.6 Verdicts and Responses")
caption(doc, "Table: Verdict, Recommended Response and Thresholds")
table(doc, ["Verdict", "Response", "Triggered when"], [
    ["ok", "allow", "No detector is above its threshold."],
    ["review", "step_up", "The largest of spike, drift, agent risk and 0.6 x (1 - humanity) is at least 0.6; or a non-agent entity trips the Agent Guard."],
    ["suspected_bot", "shadow", "Humanity below 0.35 on an interactive action."],
    ["bot_farm", "shadow", "Five or more linked accounts on one resource (risk 0.9)."],
    ["agent_anomaly", "pause_agent", "Agent Guard risk of at least 0.6 for an agent entity."],
], [2000, 1700, 5660])
para(doc, "Severity increases in the order shown. The most severe applicable verdict wins, and the order of checks is: agent, bot farm, humanity, then the general anomaly score.")
h2(doc, "4.7 Analyst Override")
para(doc, "An analyst can Restore or Confirm any flagged verdict (POST /api/v1/universal/verdicts/{id}/override). Restore clears the account flag, the agent's "
          "sensitive-action window and the session's stickiness; both outcomes are stored with the analyst's name and become training labels.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "5. The Agent Guard")
h2(doc, "5.1 Threat Model")
para(doc, "An AI agent that can move value can be manipulated by text it reads: an invoice, a web page or an email with a hidden instruction. The agent obeys, "
          "and the instruction never appears in the owner's request. The Agent Guard evaluates each action before the tool executes, in code outside the "
          "language model, so no prompt can argue past it. The harness (not the model) states where an instruction came from through instruction_source.")
h2(doc, "5.2 The Agent Registry")
para(doc, "An application registers the agents allowed to act for it. Each entry is validated when the application is created or updated.")
caption(doc, "Table: Agent Entry (AgentSpec)")
table(doc, ["Field", "Rules"], [
    ["agent_id", "Required. 2 to 63 characters: letters, digits, dot, dash, underscore, starting with a letter or digit. Unique within the application."],
    ["name", "Optional display name (up to 128 characters)."],
    ["tools", "Up to 50 tool names the agent may call."],
    ["sensitive_actions", "Up to 50. Each must be a taxonomy action; an unknown action is rejected with an error naming it."],
    ["authorized_resources", "Up to 50 resource identifiers the agent may act on."],
    ["max_sensitive_per_minute", "Optional integer 1 to 1000. Default 10."],
], [2600, 6760])
para(doc, "An application can register at most 20 agents. An application with no registered agents gets the anomaly checks in 5.4 only, exactly as before the registry existed.")
h2(doc, "5.3 Authorization Checks")
caption(doc, "Table: Policy Checks (each adds 0.70 risk; one is enough to pause)")
table(doc, ["Check", "Reason shown to the analyst"], [
    ["The agent is not in the registry", "agent <id> is not registered for this application"],
    ["The tool is not on the agent's tool list", "tool <name> is not permitted for agent <id>"],
    ["A value, tool-call, permission, API-key or config action targets a resource that is not authorized (or any of the agent's own sensitive actions does)", "agent <id> is not authorized to act on resource <resource>"],
    ["More sensitive actions in 60 seconds than the limit", "<n> sensitive actions in 60s; this agent is limited to <limit>"],
], [4800, 4560])
para(doc, "The sensitive-action window counts attempts, not successes, because a burst of blocked attempts is exactly what should keep tripping the guard. "
          "Value actions (token.buy, token.sell, token.transfer, liquidity.add, liquidity.remove) and the agent's own sensitive_actions count.")
h2(doc, "5.4 Anomaly Signals")
caption(doc, "Table: Behavioral Signals (added to the policy risk, capped at 1.0)")
table(doc, ["Signal", "Risk", "Reason shown"], [
    ["Value sent to a destination never used before", "+0.35", "sends value to a destination never used before (<destination>)"],
    ["Amount 3 or more standard deviations above the agent's usual", "+0.35", "amount <n> is <m> standard deviations above its usual (or 'far above' beyond 50)"],
    ["The instruction came from outside content", "+0.30", "the instruction came from outside content, not the agent's owner"],
    ["Tool calls much faster than the agent's pace (rate z-score at least 3)", "+0.15", "tool calls are much faster than this agent's normal pace"],
    ["First time this agent performs this action", "+0.10", "first time this agent has performed <action>"],
], [4300, 900, 4160])
para(doc, "Any total of 0.6 or more pauses the agent: the verdict is agent_anomaly and the recommended response is pause_agent.")
h2(doc, "5.5 Worked Examples")
caption(doc, "Table: Real Results from the Demo (section 9)")
table(doc, ["Scenario", "Result"], [
    ["An invoice hides 'pay $12,000 to attacker-9x7'; the agent obeys.", "0.35 (new destination) + 0.35 (amount far above usual) + 0.30 (outside instruction) = risk 1.00, pause_agent."],
    ["The agent calls token.transfer on treasury_cold_storage_vault.", "Risk 0.70 from the authorization check alone: pause_agent, reason 'agent novatrust-agent is not authorized to act on resource treasury_cold_storage_vault'."],
    ["The agent attempts 20 transfers in about 3 seconds.", "The first 10 are allowed; from the 11th the window exceeds the limit of 10 (risk 0.85, pause_agent)."],
    ["The same code runs as an agent id that was never registered.", "Blocked before the tool runs: 'agent rogue-agent is not registered for this application' (risk 0.70)."],
], [4200, 5160])
h2(doc, "5.6 Enforcement in the SDK")
code(doc, """
@soc.guard_tool(agent_id="novatrust-agent", action="token.transfer",
                resource="treasury", resource_type="account", sensitivity="high",
                block_only_when_enforced=True)
def create_transfer(to: str, amount: float, instruction_source: str = "owner"): ...

call -> guard request (secret key) -> verdict
   allow                -> the tool body runs
   pause_agent / shadow -> ActionBlocked raised; the body never runs
                           (Monitor + block_only_when_enforced: the body runs and
                            the decision is recorded)
   NeuroSOC unreachable -> ActionBlocked, verdict 'unavailable' (fails closed)""")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "6. The SDKs")
h2(doc, "6.1 Installation")
caption(doc, "Table: Distribution")
table(doc, ["SDK", "Install", "Notes"], [
    ["Python (neurosoc)", "pip install neurosoc", "Published on PyPI (release 0.1.2). Python 3.9+, standard library only, no dependencies."],
    ["Browser, script tag", "<script src=\".../neurosoc.min.js\" data-key=\"pk_...\" data-endpoint=\"https://your-neurosoc-host\" data-consent=\"wait\"></script>", "The bundle is served by the dashboard at /neurosoc.min.js, and built from sdk/js (under 5 KB gzipped)."],
    ["Browser, module", "Copy sdk/js/src, then NeuroSOC.init({ publishableKey, endpoint })", "The @neurosoc/sdk package is configured to publish from a git tag but is not on npm yet."],
], [1900, 4300, 3160])
h2(doc, "6.2 Browser SDK Reference")
caption(doc, "Table: NeuroSOC.init Options")
table(doc, ["Option", "Default", "Meaning"], [
    ["publishableKey", "required", "The pk_ key."],
    ["endpoint", "required", "The NeuroSOC API origin. Using the page's own origin avoids CORS when a proxy forwards /api."],
    ["waitForConsent", "false", "Start dormant: nothing is captured or sent until consent(true)."],
    ["captureBehavior", "true", "Capture typing and mouse timing (never content)."],
    ["autoCapture", "true", "Map clicks and submits to actions using the site's rules."],
    ["tagForms", "true", "Add a hidden neurosoc_session field to forms so the backend can check the verdict."],
    ["flushIntervalMs, maxBatch", "2000, 20", "Batching of events."],
    ["relay, debug", "false, false", "Send through the Lens extension; verbose logging."],
], [2300, 1500, 5560])
caption(doc, "Table: Browser SDK Methods")
table(doc, ["Method", "Purpose"], [
    ["NeuroSOC.init(options)", "Create the singleton client."],
    ["identify({ id, type })", "Say who the visitor is (for example after login)."],
    ["consent(granted)", "Start (true) or stop (false) capture."],
    ["track(input, urgent?)", "Record an action; resolves with the BrowserVerdict (action, enforced)."],
    ["guard(input)", "A track that is sent immediately."],
    ["onVerdict(listener)", "Subscribe to verdicts; returns an unsubscribe function."],
    ["getMode(), flush()", "Read observe or enforce; send the queue now."],
], [3000, 6360])
para(doc, "Events travel as a CORS 'simple request' (a text/plain body, the key in the query) so no preflight is needed and the same request works from "
          "navigator.sendBeacon when a page closes. With the script tag, data-consent=\"wait\" has the same effect as waitForConsent.")
h2(doc, "6.3 Python SDK Reference")
caption(doc, "Table: NeuroSOC (Python)")
table(doc, ["Member", "Purpose"], [
    ["NeuroSOC(endpoint, secret_key, *, timeout=5.0, transport=None)", "Create a client. Raises ValueError if the key is not an sk_ key."],
    ["session_verdict(session_id)", "The verdict for a browser session id, for example the neurosoc_session form field."],
    ["track(**fields) / guard(**fields)", "Record an action / ask for a decision. Fields are those of NeuroSOC.event(); a telemetry argument can carry how a user's input behaved."],
    ["guard_tool(...)", "Decorator that scores a tool before it runs (parameters below)."],
    ["Verdict", "verdict, action, risk, reasons, verdict_id, session_id, raw; allowed is true for 'allow'."],
    ["ActionBlocked", "Raised when a guarded call must not run; carries the Verdict."],
    ["NeuroSOCError", "The API could not be reached or refused the request. Every transport failure, including a connection dropped mid-reply, raises this."],
], [3500, 5860])
caption(doc, "Table: guard_tool Parameters")
table(doc, ["Parameter", "Default", "Meaning"], [
    ["agent_id", "required", "The registered agent id."],
    ["action, resource, resource_type, sensitivity", "agent.tool_call, agent-tools, tool, none", "What the tool does and what it touches."],
    ["owner_id, session_id", "none", "Who the agent acts for; a session id to group calls."],
    ["amount_arg, destination_arg", "amount, to", "Which tool arguments hold the amount and the destination."],
    ["instruction_source_arg", "instruction_source", "Which argument says who gave the instruction: owner, system or external_content."],
    ["block_on", "pause_agent, shadow", "Responses that block the call."],
    ["fail_open", "False", "When False, an unreachable NeuroSOC blocks the call (verdict 'unavailable'). Use True only for tools that cannot do harm."],
    ["block_only_when_enforced", "False", "Block only when the application is in Protect mode; in Monitor the call runs and is recorded."],
    ["on_verdict", "none", "Callback that receives every Verdict."],
], [3000, 2200, 4160])
h2(doc, "6.4 Releases")
para(doc, "The Python package version lives in sdk/python/pyproject.toml and sdk/python/neurosoc/__init__.py, which must match. A release is made by pushing a tag "
          "named sdk-py-v<version>; the publish workflow checks the tag against both files, runs the SDK tests, builds and uploads through PyPI trusted publishing, "
          "so no token is stored in the repository. A published version can never be reused.")
caption(doc, "Table: Python SDK Releases")
table(doc, ["Version", "Contents"], [
    ["0.1.0", "Session verdicts, track, guard and guard_tool."],
    ["0.1.2", "Adds guard_tool(block_only_when_enforced), a telemetry argument on events, and wraps dropped connections as NeuroSOCError so guarded tools fail closed instead of raising a raw network error."],
], [1500, 7860])
para(doc, "The dashboard serves the browser bundle from its own origin, and its Docker build context contains only the dashboard folder, so the SDK source and "
          "bundle are copied in by scripts/sync_dashboard_sdk.py. A test fails if the copy drifts from sdk/js.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "7. API Reference")
para(doc, "All routes are on the Inference Service. Authentication is a key in the X-NeuroSOC-Key header (the browser SDK may send a pk_ key as the key query "
          "parameter) for SDK routes, and the dashboard's bearer token for analyst routes. Requests are limited to API_RATE_LIMIT_PER_MINUTE (default 120) per client.")
h2(doc, "7.1 SDK Routes")
caption(doc, "Table: SDK Routes")
table(doc, ["Method and path", "Key", "Request", "Response"], [
    ["POST /api/v1/sdk/events", "pk or sk", "{ events: [SdkEvent, ...] }", "{ verdicts: [...], mode }. For pk, each verdict has 5 fields only."],
    ["POST /api/v1/sdk/guard", "sk only", "One SdkEvent", "The full verdict, synchronously."],
    ["GET /api/v1/sdk/sessions/{id}/verdict", "sk only", "None", "The session's current verdict, or not found."],
    ["GET /api/v1/sdk/config", "pk or sk", "key in header or query", "{ site_id, mode, rules }."],
], [2900, 1000, 2400, 3060])
para(doc, "Errors: 401 for a missing or unknown key, or a pk key on a secret-only route; 403 when the origin is not registered for a pk key; 422 for a body that fails "
          "validation. A repeated event_id returns the first verdict instead of scoring again.")
h2(doc, "7.2 Analyst and Application Routes")
caption(doc, "Table: Analyst Routes")
table(doc, ["Method and path", "Role", "Purpose"], [
    ["GET /api/v1/universal/verdicts/latest?limit=", "analyst", "Latest verdicts (up to 200), each with the application's current name."],
    ["GET /api/v1/universal/entities/{type}/{id}", "analyst", "An entity's profile: first seen, recent events, devices, flag, links."],
    ["GET /api/v1/universal/resources/{id}/integrity", "analyst", "For a campaign or resource: participants, flagged and human counts, claims paid and withheld."],
    ["POST /api/v1/universal/verdicts/{id}/override", "analyst", "{ decision: restore | confirm }. Returns the verdict with the override recorded."],
    ["GET /api/v1/universal/sites", "analyst", "The tenant's applications (never the secret key)."],
    ["POST /api/v1/universal/sites", "operator, admin, platform-admin", "Create an application. Returns the site, the secret key (once) and a note."],
    ["PUT /api/v1/universal/sites/{id}", "operator, admin, platform-admin", "Change mode, origins, rules, preset, app_type, url or agents."],
    ["POST /api/v1/universal/sites/{id}/webhooks", "operator, admin, platform-admin", "Add a webhook; returns its signing secret once."],
    ["WS /api/v1/universal/ws", "analyst", "Pushes { type: universal.snapshot } on connect, then { type: universal.verdict } per verdict."],
], [3300, 1800, 4260])
caption(doc, "Listing: Create an Application")
code(doc, """
POST /api/v1/universal/sites
{ "name": "NovaTrust", "mode": "enforce", "app_type": "both",
  "url": "http://localhost:5173/demo",
  "allowed_origins": ["http://localhost:5173"],
  "agents": [ {
      "agent_id": "novatrust-agent", "name": "Nova AI",
      "tools": ["get_balance", "get_transactions", "get_portfolio",
                "create_transfer", "cancel_transfer"],
      "sensitive_actions": ["token.transfer"],
      "authorized_resources": ["treasury"] } ] }

201 { "site": { "site_id": "...", "publishable_key": "pk_...", "mode": "enforce" },
      "secret_key": "sk_...", "note": "Store the secret key now." }""")
h2(doc, "7.3 Webhooks")
para(doc, "A webhook receives each verdict as JSON with the header X-NeuroSOC-Signature: sha256=<hex>, an HMAC-SHA256 of the request body keyed with the webhook's whsec_ secret. "
          "The receiver recomputes the HMAC and compares it before trusting the payload.")
h2(doc, "7.4 The Verdict Object")
caption(doc, "Table: Full Verdict (secret key and analyst routes)")
table(doc, ["Field", "Meaning"], [
    ["verdict_id, session_id, event_id", "Identifiers."],
    ["entity, event_action, resource, value", "What was judged."],
    ["site_id, site_name, agent_id, tool", "Which application and, for agents, which agent and tool."],
    ["verdict, action, enforced", "ok, review, suspected_bot, bot_farm or agent_anomaly; the recommended response; whether the application is in Protect mode."],
    ["risk", "0 to 1."],
    ["scores", "humanity (or null without telemetry), spike, drift, agent_risk, cluster_size."],
    ["reasons", "Plain-language reasons; 'matches this account's usual behavior' when nothing stands out."],
    ["linked_by", "For a bot farm, what the accounts share."],
    ["scorer, baseline", "The scorer used; whether the entity's own or its group's baseline was used."],
    ["override", "Present after an analyst decision: decision, actor, time."],
], [3000, 6360])

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "8. The Dashboard Workflow")
h2(doc, "8.1 Protection Page")
para(doc, "The Protection page (route /protection, shown when VITE_UNIVERSAL_ENABLED=true) has four tabs: Campaign integrity, Agent watch, Live verdicts and Sites.")
h2(doc, "8.2 Live Verdicts")
para(doc, "Every action seen by the SDK, newest first. The columns are Time, Application, Agent, Action, Resource, Decision, Risk and Reason (the first reason, "
          "expandable). A summary card shows the latest flagged event with its reasons, the table can be filtered to one application or to flagged events, and an analyst "
          "can Restore or Confirm a flagged row. The page reads the WebSocket at /api/v1/universal/ws; the dev server proxies it (ws: true on /api).")
h2(doc, "8.3 The Add Application Wizard")
caption(doc, "Table: Wizard Steps")
table(doc, ["Step", "What the user does", "What is sent or shown"], [
    ["1. Details", "Name, URL, type (Web app, AI agent, Both), mode (Monitor, Protect).", "app_type, mode, url; allowed origins default to the dashboard's own origin plus the URL's origin."],
    ["2. AI agent (agent or both)", "Agent id and name, tools, sensitive actions, authorized resources.", "An agents entry (section 5.2), validated on screen and by the API."],
    ["3. Keys", "Copy the public key; reveal and copy the secret key; confirm it was copied.", "Public key (safe in a page), secret key masked until revealed and shown once; the Done button stays disabled until confirmed."],
    ["3. Install the SDK", "Copy the install command.", "pip install neurosoc, shown in its own block for agent and both applications."],
    ["3. Integration snippets", "Choose Script tag, JavaScript module or Python agent.", "Runnable code using the application's own key and agent. The Python snippet reads the secret from the NEUROSOC_SECRET_KEY environment variable."],
    ["3. Launch NovaTrust", "Only when the API reports demo mode.", "Hands the secret to the demo backend's memory and opens /demo (section 9)."],
], [1900, 3500, 3960])
para(doc, "The secret is held in the wizard only while the dialog is open and is cleared on close. The dialog is an accessible modal: labelled, closable with Escape, "
          "with focus moved in, trapped and restored.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "9. The NovaTrust Customer Demo")
h2(doc, "9.1 Purpose")
para(doc, "NovaTrust is a fictional bank with an AI assistant, Nova AI. It is a customer of NeuroSOC: it uses the real browser SDK, the real Python SDK and the real "
          "engine, and the dashboard shows its events live. Only the bank is made up (balances, people, the ledger). The demo proves the whole loop: onboard, integrate, "
          "observe, analyze, decide, protect, visualize.")
h2(doc, "9.2 Architecture")
code(doc, """
 browser /demo
   |  JS SDK (pk_, only after Accept)
   |  ------------------------------> /api/v1/sdk/events ----+
   |                                                          |
   |  /api/v1/demo/*                                          v
   +--------------> Demo backend (DemoRuntime)         Universal Engine
                      - per-browser fake account              ^   |
                        (X-Demo-Session)                      |   v
                      - Nova AI tools -> guard_tool (sk_)     |  dashboard
                      - scripted planner, or Claude with      |  live feed
                        ANTHROPIC_API_KEY                     |
                      Python SDK over HTTP -------------------+
                      (NEUROSOC_SELF_URL)
""")
para(doc, "The demo backend calls NeuroSOC through the Python SDK over HTTP to NEUROSOC_SELF_URL (default http://127.0.0.1:PORT), not through a shortcut into the engine, so "
          "key checks, idempotency and rate limits all apply. Its handlers are synchronous so the loopback call cannot deadlock the event loop.")
h2(doc, "9.3 Nova AI")
caption(doc, "Table: Nova AI Tools")
table(doc, ["Tool", "Guarded", "Behavior"], [
    ["get_balance, get_transactions, get_portfolio", "No", "Read-only; keep working when NeuroSOC is unreachable. A best-effort telemetry event is sent."],
    ["create_transfer", "Yes (token.transfer on treasury, sensitivity high)", "Prepares a transfer and holds the funds until the owner confirms. Money never moves without confirmation."],
    ["cancel_transfer", "Yes (agent.tool_call on treasury, sensitivity medium)", "Cancels a pending transfer and releases the hold."],
], [3200, 2800, 3360])
para(doc, "The agent id, action and resource are fixed in code; nothing in a request and nothing a language model says can choose them. The scripted planner is the default and is deliberately "
          "naive: it follows a 'send X to Y' instruction found in an attached document, as the agents in real prompt-injection incidents did. When ANTHROPIC_API_KEY is set, Claude "
          "(claude-opus-5-5) chooses the tool calls instead, in a loop of at most 5 turns, with the same guarded tools. The harness sets instruction_source from where the text came from. "
          "When the guard blocks anything, the reply is the harness's own wording, so the assistant cannot claim that money moved.")
h2(doc, "9.4 Security Simulations")
caption(doc, "Table: Simulations (all run on the demo's own fake data, labelled simulated)")
table(doc, ["Simulation", "What happens", "Outcome"], [
    ["Prompt injection", "The agent is handed an invoice that hides an instruction to pay a stranger.", "Blocked, pause_agent, risk 1.00."],
    ["Unauthorized resource", "A transfer wired to a vault the agent is not registered for.", "Blocked: not authorized to act on that resource."],
    ["Excessive actions", "20 transfers, paced about 0.15 s apart.", "Allowed up to the limit of 10 per minute, then paused (attempt 11)."],
    ["Suspicious session", "A new visitor signs up with perfectly regular typing, a straight mouse path and a form finished in about a second.", "Flagged (shadow, risk 0.89)."],
], [2200, 4200, 2960])
para(doc, "Reset demo restores the account and un-pauses the agent. The simulations always use the scripted planner so they behave the same every time.")
h2(doc, "9.5 Safety Properties")
bullets(doc, [
    ("Demo-only", "The demo routes exist only when NEUROSOC_DEMO_MODE=true. The service refuses to start with it enabled when APP_ENV is staging or production. The dashboard shows the Security Testing panel only when VITE_DEMO_MODE=true and the API also reports demo mode."),
    ("Secrets", "The wizard hands the secret key to the backend through POST /api/v1/demo/connect, which accepts only loopback or private-network callers. The key is held in process memory, never returned and never stored in the browser."),
    ("Fail closed", "If NeuroSOC cannot be reached, guarded tools and the Transfer page report 'Security service temporarily unavailable' and move nothing. Reads keep working."),
    ("Consent", "The browser SDK starts dormant; with no consent no request is sent. Declining keeps it dormant across reloads."),
    ("Isolation", "Each browser tab has its own fake account keyed by X-Demo-Session (up to 200 accounts, expiring after 2 hours)."),
    ("No auth exemption", "Demo routes sit behind the same authentication as every other route; the local default OIDC_REQUIRED=false is what lets the demo run without sign-in."),
])
h2(doc, "9.6 Demo Routes")
caption(doc, "Table: /api/v1/demo/* (present only in demo mode)")
table(doc, ["Method and path", "Purpose"], [
    ["GET /config", "Demo mode, the connected application (never a secret), the planner in use, the agent's state."],
    ["POST /connect", "Hand the application's secret key to the backend (loopback or private caller only)."],
    ["GET /account, POST /account/reset", "This session's fake account; a fresh account and an un-paused agent."],
    ["POST /agent/chat", "One message to Nova AI; tool calls pass the guard. Optional attached content for the injection case."],
    ["POST /transfer", "A person's transfer from the Transfer page; guarded as a human action on the same resource."],
    ["POST /transfer/{id}/confirm, /cancel", "Confirm or cancel an agent-prepared transfer."],
    ["POST /simulate", "{ type: prompt_injection | unauthorized_resource | excessive_actions | suspicious_session }."],
], [3300, 6060])
h2(doc, "9.7 Running the Demo Locally")
code(doc, """
# API (from inference-service/); no Docker needed, memory store without REDIS_URL
ENABLE_UNIVERSAL_ENGINE=true NEUROSOC_DEMO_MODE=true REDIS_URL='' \\
DATABASE_URL='' KAFKA_BOOTSTRAP=127.0.0.1:1 \\
  python -m uvicorn main:app --port 8010

# Dashboard (from dashboard/)
VITE_DEMO_MODE=true VITE_UNIVERSAL_ENABLED=true VITE_API_URL=/ \\
VITE_PROXY_TARGET=http://127.0.0.1:8010 \\
  npx vite --port 5173

# Then open http://localhost:5173/protection?view=sites and add an application.""")
para(doc, "The WebSocket needs a WebSocket library in the API's environment; the Docker image has one (uvicorn[standard]).")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "10. Verification")
h2(doc, "10.1 Automated Tests")
caption(doc, "Table: Test Results for the Work in This Volume (pytest and Node, run on the final code)")
table(doc, ["Suite", "Result", "Covers"], [
    ["tests/test_universal_agents.py", "24 passed", "Registry validation, authorization and rate checks with their reasons, verdict context, Monitor vs Protect, key and origin handling including the Referer fallback."],
    ["tests/test_demo_backend.py", "24 passed", "Connect, tools behind the guard, simulations, session isolation, reset, outage behavior (guard down returns 'unavailable' and the ledger is unchanged)."],
    ["tests/test_demo_mode_gating.py", "4 passed", "Routes absent when demo mode is off, refusal to start in production, loopback-only connect."],
    ["tests/test_demo_claude_planner.py", "5 passed", "The Claude planner against a stubbed client: tool loop, harness-worded blocks, instruction source, turn bound, planner selection."],
    ["tests/test_dashboard_snippets.py", "4 passed, 1 skipped", "Wizard snippets parse (Python AST, node --check), the Python snippet runs and fails closed when NeuroSOC is unreachable; the skipped test installs the published package (run with NEUROSOC_TEST_PYPI=1)."],
    ["tests/test_dashboard_sdk_sync.py", "3 passed", "The dashboard's SDK copy matches sdk/js."],
    ["tests/test_requirements_compat.py, test_verdict_snapshot_response.py", "2 + 2 passed", "Pinned xgboost and scikit-learn compatibility; tenant id on verdict snapshots."],
    ["tests/02_integration/test_python_sdk.py", "5 passed", "The Python SDK, including a server that hangs up mid-reply raising NeuroSOCError and failing closed."],
    ["sdk/js (npm test)", "6 passed", "The browser SDK."],
], [3100, 1700, 4560])
para(doc, "Total for these suites: 73 passed and 1 skipped (pytest), 6 passed (Node). The dashboard builds with vite build.")
callout(doc, "NOTE", "Whole-repository run",
        "Running pytest over the entire tests/ folder gives 130 passed, 25 failed, 24 errors, 1 skipped. The failures and errors are in test files that were moved "
        "into tests/01_unit/ and tests/02_integration/ and still locate the repository root one folder too shallow, so they look for paths such as tests/schemas/... "
        "and tests/ingestion-service/.... The collection errors also occur on the untouched upstream branch tip, and none of the suites listed above is affected. "
        "Changing parents[1] to parents[2] in those files is the likely fix; it is not part of this work.")
h2(doc, "10.2 Browser End-to-End Run")
para(doc, "scripts/e2e_novatrust.mjs drives headless Chrome through the dashboard and NovaTrust against a real API and the Vite dev server, with no mocks and no Docker. "
          "It starts a proxy on the port the demo backend uses to reach NeuroSOC so it can cut that connection for the outage step. Result on the final code: 19 of 19 steps passed.")
caption(doc, "Table: End-to-End Steps and What They Prove")
table(doc, ["#", "Step", "Evidence"], [
    ["1", "Dashboard starts with no applications", "The Sites tab shows the empty state."],
    ["2", "Add Application: NovaTrust, Both, Protect, agent novatrust-agent", "5 tools checked, token.transfer sensitive, treasury authorized."],
    ["3-5", "Keys, snippets, secret handling", "Public key shown; secret masked until revealed and absent from browser storage; snippets contain the public key only; the SDK bundle is served."],
    ["6", "Launch NovaTrust", "The backend connects and /demo opens."],
    ["7-9", "Consent", "Zero SDK requests before Accept, and after 'Not now' including after a reload; Accept starts real events."],
    ["10-11", "Normal use", "A person's transfer is allowed; Nova AI answers a balance question and prepares a transfer that the owner confirms."],
    ["12-15", "Attacks", "Prompt injection and unauthorized resource blocked with reasons; excessive actions paused at attempt 11 of 20; suspicious session flagged."],
    ["16", "Live feed", "The 8 columns are present with NovaTrust and novatrust-agent rows (32 rows)."],
    ["17-18", "Outage and recovery", "With NeuroSOC unreachable the transfer fails closed, balance unchanged and the dashboard still readable; after recovery NeuroSOC answers with a real decision."],
    ["19", "No uncaught page errors", "None."],
], [800, 3500, 5060])
callout(doc, "NOTE", "Automated browsers can be flagged",
        "The humanity detector is real, so scripted mouse and keyboard input can be judged a bot. In earlier runs of this script a flag on the test account stuck and the recovery "
        "step ended with 'stopped: account was already flagged'; in the final run it did not. Step 18 therefore asserts that NeuroSOC answers with a real decision rather than "
        "that the transfer was sent, and a fresh API start is needed before each run because the flag is stored.")
h2(doc, "10.3 Known Limitations")
bullets(doc, [
    "State is in process memory unless REDIS_URL is set: the demo and tests are single-process and lose applications and flags on restart.",
    "Bot flags are sticky for 7 days by design; Reset demo clears the demo's agent state, not a flag raised by browser telemetry.",
    "The browser SDK is not published to npm yet; the script tag and the copied source are the supported routes.",
    "The live feed's WebSocket needs a WebSocket library on the server; without one the page stays on 'Connecting'.",
])

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "11. Configuration Reference")
caption(doc, "Table: Settings Used by the Universal Engine and the Demo")
table(doc, ["Setting", "Where", "Meaning"], [
    ["ENABLE_UNIVERSAL_ENGINE", "API", "Mounts the SDK, universal and (in demo mode) demo routes. Default false."],
    ["UNIVERSAL_HASH_SECRET", "API", "Keyed hash for IPs and IP blocks. Staging and production require 32 or more random characters."],
    ["UNIVERSAL_SITES_FILE", "API", "Seeds applications from a JSON file (for example sdk/sites.local.json, example keys, localhost only)."],
    ["UNIVERSAL_SCORER", "API", "module:factory for a trained scorer. Empty selects the z-score scorer."],
    ["BEHAVIOR_EVENTS_TOPIC", "API", "Kafka topic that normalized events are published to."],
    ["REDIS_URL", "API", "Selects Redis for the key-value store; empty uses process memory."],
    ["API_RATE_LIMIT_PER_MINUTE", "API", "Requests per client per minute. Default 120."],
    ["NEUROSOC_DEMO_MODE", "API", "Enables the demo routes. Refused in staging and production."],
    ["NEUROSOC_SELF_URL", "API", "Where the demo backend reaches NeuroSOC. Default http://127.0.0.1:PORT."],
    ["NOVATRUST_DEMO_SECRET_KEY", "API", "Optional: a secret key for headless demo runs."],
    ["ANTHROPIC_API_KEY", "API", "Optional: lets Nova AI use Claude instead of the scripted planner."],
    ["VITE_UNIVERSAL_ENABLED", "Dashboard", "Shows the Protection page."],
    ["VITE_DEMO_MODE", "Dashboard", "Shows the demo's Security Testing panel (also needs the API setting)."],
    ["VITE_API_URL, VITE_PROXY_TARGET", "Dashboard", "VITE_API_URL=/ makes the app call same-origin paths; the dev server proxies /api and /ws to VITE_PROXY_TARGET."],
], [3200, 1300, 4860])

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "12. Revisions to Volumes 1 to 3 (v1.2.0)")
para(doc, "Volumes 1 to 3 were revised to v1.2.0 in October 2026 to match the project as built. The table lists each change and the source it was checked against. "
          "The original files are unchanged and kept alongside the revised ones.")
caption(doc, "Table: Changes Made to Volumes 1 to 3")
table(doc, ["Volume and section", "Change", "Checked against"], [
    ["Volume 3, section 6 (API directory)", "Added the nine routes that were missing: GET /, GET /metrics, GET /api/v1/verdicts/current-session, POST /api/v1/alerts/{session_id}/decision, GET /api/v1/audit/events, GET /api/v1/models/candidates, POST .../candidates/{id}/promote and /reject, POST /api/v1/models/rollback, and WS /ws/alerts. Added a pointer to section 7 of this volume for the SDK, application and demo routes.", "inference-service/main.py, core/auth.py"],
    ["Volume 3, section 5.1 (RBAC)", "Four roles became five (platform-admin added). Corrected which role may do what: promoting, rejecting, rolling back and reloading models need platform-admin, not admin; alert decisions and the analysis and bank write routes need operator or admin; the audit log needs admin, auditor or platform-admin; the SDK application routes need operator, admin or platform-admin. Noted that SDK routes authenticate with application keys and that /, /health and /metrics are public.", "core/auth.py, api/routes/universal.py"],
    ["Volume 2, section 7.1 (candidate manifest)", "The listing now has the manifest's real field names (model_key, status, promoted_at, promoted_by) with the promoted XGBoost values, and states that candidates move from pending_approval to promoted or rejected. The security text now names platform-admin and the history snapshot, and describes the guard test accurately.", "models/candidates/*.manifest.json, main.py, tests/02_integration/test_model_promotion_guard.py"],
    ["Volume 2, section 4.1", "Added an implementation note: the promoted models use 76 features from CIC-IDS2017 and CIC-DDoS2019 in six classes with data, the Feature Service emits 80 differently named features, the two are not reconciled, and live-traffic accuracy is not established. Pointed to section 14 of this volume for measured accuracy.", "datasets/feature_columns.txt, core/engine.py, docker-compose.yml, section 14"],
    ["Volume 1, sections 2.1, 5.3, 6.1 and 6.2", "Added the Universal Engine and SDK API as an optional part of the Inference Service (no new container or port), the settings ENABLE_UNIVERSAL_ENGINE, UNIVERSAL_HASH_SECRET, UNIVERSAL_SITES_FILE, NEUROSOC_DEMO_MODE and the VITE_ flags, and the refusal to start with demo mode in staging or production. Added a note on the 76-feature list to the Feature Service entry.", "docker-compose.yml, .env.example, main.py"],
    ["Volumes 1 and 3 (NovaTrust)", "Noted that the NovaTrust Bank Simulation Portal and the NovaTrust Customer Demo are different applications.", "This volume, section 9"],
    ["All three, cover table", "Version / Release changed to v1.2.0-Production (revised October 2026).", "n/a"],
], [2500, 4800, 2060])
callout(doc, "NOTE", "Still open in Volumes 1 to 3",
        "These were not changed because nothing in the repository settles them. (1) Volume 1 states an inference time under 15 ms per event and a 99.8 percent reduction in human alert volume; "
        "neither has been measured here. (2) Volume 3's table lists POST /api/v1/behavioral as 'Public / Portal' while core/auth.py puts it among the routes that need operator or admin when OIDC is enforced. "
        "(3) The 80-versus-76 feature mismatch is documented as a known gap, not resolved. (4) The accuracy of the three models is reported only in section 14 of this volume.")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "13. Project Links & Resources")
para(doc, "Every address below was checked when this volume was written. Links marked 'when running' only work on a machine where the stack is started.")
H = ["Resource", "Link", "Notes"]
W3 = [2300, 4260, 2800]

h2(doc, "13.1 Source and Collaboration")
link_table(doc, H, [
    ("GitHub repository", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC", "All services, both SDKs, the dashboard, schemas and tests."),
    ("Issues", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/issues", "Bug reports and tracking."),
    ("Pull requests", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/pulls", "Open and merged changes."),
    ("PR #11: model promotion", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/pull/11", "Promotion of the trained SNN, LNN and XGBoost candidates (manifest 1.0.4)."),
    ("PR #13: NovaTrust demo", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/pull/13", "The agent registry and guard, the Add Application wizard, the customer demo and the end-to-end run."),
    ("Tags", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/tags", "SDK release tags sdk-py-v0.1.0, sdk-py-v0.1.1 (never published to PyPI) and sdk-py-v0.1.2."),
    ("SDK folder", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/tree/main/sdk", "Browser SDK, Python SDK, presets and their READMEs."),
    ("Action taxonomy", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/schemas/taxonomy.json", "The fixed action vocabulary (section 3.5)."),
    ("License (Apache-2.0)", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/LICENSE", "Terms of use; the text is at http://www.apache.org/licenses/LICENSE-2.0."),
], W3)

h2(doc, "13.2 Packages and Releases")
link_table(doc, H, [
    ("neurosoc on PyPI", "https://pypi.org/project/neurosoc/", "pip install neurosoc. Current release 0.1.2."),
    ("neurosoc 0.1.2", "https://pypi.org/project/neurosoc/0.1.2/", "Adds block_only_when_enforced, a telemetry argument and the dropped-connection fix."),
    ("neurosoc 0.1.2 tag on GitHub", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/releases/tag/sdk-py-v0.1.2", "The commit the release was built from."),
    ("PyPI project short link", "https://pypi.org/p/neurosoc", "The address the publish workflow reports as its environment."),
    ("@neurosoc/sdk on npm", "https://www.npmjs.com/package/@neurosoc/sdk", "Not published yet: the npm registry returned 'not found' when this volume was written. The page resolves after the first release."),
    ("CDN script (jsDelivr)", "https://cdn.jsdelivr.net/npm/@neurosoc/sdk/dist/neurosoc.min.js", "Works only after the npm release. Until then use the bundle the dashboard serves at /neurosoc.min.js."),
], W3)

h2(doc, "13.3 Documentation")
link_table(doc, H, [
    ("Detailed design document", "https://docs.google.com/document/d/1GcDYW006dY0nc87Vipmqk0Oph9lL2IFMOXp71v2yV8w/edit", "The original design document (Google Docs)."),
    ("Technical documentation archive", "https://drive.google.com/drive/folders/1kZnapQty0NLdxIYrU4Hc-vzrCqqcVp1g", "Google Drive folder: Volumes 1 to 3, the ASYNC 2026 presentation and, once uploaded, this volume."),
    ("Demo video", "https://youtu.be/eUf58W-rJoE", "The NeuroSOC demo video (YouTube)."),
    ("Project README", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/README.md", "Overview, quick start and the NovaTrust demo walkthrough."),
    ("SDK README", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/sdk/README.md", "Both SDKs, keys, rules, privacy and releasing."),
    ("Python SDK README", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/sdk/python/README.md", "The text published on the PyPI project page."),
    ("Browser SDK README", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/sdk/js/README.md", "Script tag and npm usage."),
    ("Testing guide", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/blob/main/TESTING.md", "How to run every suite, the end-to-end run and known issues."),
], W3)

h2(doc, "13.4 Build and Release Workflows")
link_table(doc, H, [
    ("All workflow runs", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/actions", "GitHub Actions for the repository."),
    ("Publish Python SDK", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/actions/workflows/publish-python-sdk.yml", "Runs on a tag named sdk-py-v<version>; publishes to PyPI by trusted publishing."),
    ("Publish JS SDK", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/actions/workflows/publish-js-sdk.yml", "Runs on a tag named sdk-js-v<version>; publishes to npm."),
    ("Product safety checks", "https://github.com/MUKUL-PRASAD-SIGH/Project_NeuroSOC/actions/workflows/product-safety.yml", "Production build guard and credential-pattern scan (Volume 1, section 6.2)."),
], W3)

h2(doc, "13.5 Local Endpoints (when running)")
link_table(doc, ["Service", "Address", "Notes"], [
    ("Analyst dashboard", "http://localhost:3000", "Docker stack. Protection page at /protection."),
    ("Inference Service API", "http://localhost:8000", "Docker stack."),
    ("Interactive API documentation", "http://localhost:8000/docs", "Swagger UI generated by the Inference Service (OpenAPI at /openapi.json)."),
    ("Honeypot sandbox", "http://localhost:8001", "Docker stack, sandbox network."),
    ("NovaTrust Bank Simulation Portal", "http://localhost:3001", "The older red-team portal (Volumes 1 and 3), not the customer demo."),
    ("Keycloak", "http://localhost:8081", "Local identity profile; bound to 127.0.0.1."),
    ("Prometheus", "http://localhost:9090", "Metrics."),
    ("Grafana", "http://localhost:3002", "Dashboards."),
    ("NovaTrust customer demo", "http://localhost:5173/demo", "Development setup in section 9.7."),
    ("Add Application wizard", "http://localhost:5173/protection?view=sites", "Development setup in section 9.7."),
    ("Development API", "http://localhost:8010", "The API in the development setup of section 9.7."),
], W3)

h2(doc, "13.6 Data and Technology References")
link_table(doc, H, [
    ("CIC-IDS2017 dataset", "https://www.unb.ca/cic/datasets/ids-2017.html", "Canadian Institute for Cybersecurity. One of the two datasets the promoted models were trained on."),
    ("CIC-DDoS2019 dataset", "https://www.unb.ca/cic/datasets/ddos-2019.html", "The second training dataset."),
    ("Norse", "https://github.com/norse/norse", "The spiking-network library used by the SNN (Volume 2)."),
    ("XGBoost documentation", "https://xgboost.readthedocs.io/", "The classifier library (version 3.2.0 is pinned)."),
    ("Apache Kafka documentation", "https://kafka.apache.org/documentation/", "The event streaming platform used by the network pipeline and for publishing behavior events (Volume 1, section 2)."),
], W3)

h2(doc, "13.7 Industry Context and Market References")
para(doc, "These are third-party publications on the problems NeuroSOC addresses. They are listed for context. Figures in them come from their publishers, "
          "several are vendor or market-research marketing material, and none of them measures NeuroSOC. In particular, the accuracy figure in the Rapid7 article "
          "describes Rapid7's own alert-triage product on its own data and must not be compared with the results in section 10.")
link_table(doc, H, [
    ("Alert fatigue (Vectra AI)", "https://www.vectra.ai/topics/alert-fatigue", "Explains alert fatigue, its causes and impact on SOCs, and how to reduce it. Background for the alert-volume problem in Volume 1, section 1."),
    ("AI alert triage (Rapid7)", "https://www.rapid7.com/blog/post/2025/04/29/insightidr-ai-alert-triage-automatically-classifies-alerts-with-99-93-accuracy/", "Rapid7 blog post, 29 April 2025, announcing AI alert triage in InsightIDR with a vendor-reported 99.93% classification accuracy. An example of AI triage in a commercial SIEM."),
    ("Cost of a Data Breach (IBM)", "https://www.ibm.com/reports/data-breach", "IBM's annual global report on the financial impact of data breaches (the page shows the 2026 edition)."),
    ("Account-takeover fraud (Expert Insights)", "https://expertinsights.com/news/262-million-lost-to-account-takeover-fraud-in-2025", "News report on account-takeover fraud in 2025 in which attackers impersonated financial-institution support teams. Background for the account-abuse scenarios that the humanity detector and Agent Guard address."),
    ("UEBA market report (Marketintelo)", "https://marketintelo.com/report/ueba-market", "Market research on user and entity behavior analytics (UEBA), the category the universal engine belongs to. Its summary states a market of USD 1.9 billion in 2025 growing at 18.2% a year to 2034; this is the publisher's estimate."),
    ("UEBA software market (GII, in Chinese)", "https://www.gii.tw/report/veri1737257-global-user-entity-behavior-analytics-ueba.html", "A second market-research listing for global UEBA software by type, industry vertical, deployment and region (page in Chinese; the full report is paid)."),
], W3)

# ─────────────────────────────────────────────────────────────────────────────────────────────────
h1(doc, "14. Detection Models & Measured Accuracy")
para(doc, "The network detection path (Volumes 1 to 3) fuses three models. This section states what each does and the accuracy measured for the models promoted in manifest 1.0.4. "
          "All figures are from evaluations run on 1 October 2026 on the project's public-dataset test data, and they reproduce the validation scores in the model manifests.")
h2(doc, "14.1 The Three Models")
bullets(doc, [
    ("Spiking Neural Network (SNN)", "Converts each flow's features into spikes and reacts to sudden bursts such as floods and scans (Volume 2, section 2)."),
    ("Liquid reservoir network (LNN)", "A reservoir of 500 recurrently coupled neurons that tracks how a session evolves over a window of 20 flows (Volume 2, section 3). It is an echo-state reservoir with a trained linear readout."),
    ("XGBoost", "A gradient-boosted tree classifier over the flow features, with deterministic safety overrides; it makes the final attack-class decision (Volume 2, section 4)."),
])
para(doc, "In one sentence: the SNN catches sudden bursts, the LNN follows how behavior evolves, and XGBoost makes the final call. Combining a spiking network, a recurrent temporal model "
          "and a tree ensemble is a design choice made for NeuroSOC; this volume does not claim it is novel or that published research validates the combination.")
h2(doc, "14.2 Training Data and Evaluation Setup")
bullets(doc, [
    "Datasets: CIC-IDS2017 and CIC-DDoS2019, unified into six classes with data (BENIGN, DDOS, BRUTE_FORCE, RECONNAISSANCE, WEB_ATTACK, BOT) on 76 flow features. A seventh class, OTHER, exists in the taxonomy but has no samples in the test data.",
    "XGBoost was scored on all 83,325 rows of the held-out test file. The SNN was scored on a random 20,000-row sample of the same file (natural class mix). The LNN was scored on its 12,667 validation sequences (windows of 20 flows).",
    "Active manifest: 1.0.4, with validation macro F1 of 0.729 (SNN), 0.749 (LNN) and 0.961 (XGBoost). The re-run SNN score on the 20,000-row sample is 0.739.",
])
h2(doc, "14.3 Overall Results")
caption(doc, "Table: Overall Accuracy of the Promoted Models")
table(doc, ["Metric", "SNN", "LNN", "XGBoost"], [
    ["Accuracy", "0.903", "0.920", "0.996"],
    ["Macro F1", "0.739", "0.749", "0.961"],
    ["Weighted F1", "0.906", "0.931", "0.996"],
    ["Rows scored", "20,000 (sample)", "12,667 (sequences)", "83,325 (all)"],
], [2400, 2300, 2300, 2360])
h2(doc, "14.4 Per-Class Results")
caption(doc, "Table: F1 (precision / recall) per Class")
table(doc, ["Class", "SNN", "LNN", "XGBoost"], [
    ["BENIGN", "0.891 (0.92 / 0.86)", "0.886 (0.98 / 0.81)", "0.998 (1.00 / 1.00)"],
    ["DDOS", "0.938 (0.93 / 0.95)", "0.992 (0.99 / 0.99)", "0.997 (1.00 / 1.00)"],
    ["BRUTE_FORCE", "0.635 (0.66 / 0.61)", "0.799 (0.68 / 0.97)", "1.000 (1.00 / 1.00)"],
    ["RECONNAISSANCE", "0.996 (1.00 / 0.99)", "0.991 (0.99 / 1.00)", "0.999 (1.00 / 1.00)"],
    ["WEB_ATTACK", "0.554 (0.44 / 0.76)", "0.396 (0.25 / 0.90)", "0.805 (0.71 / 0.93)"],
    ["BOT", "0.417 (0.27 / 0.96)", "0.430 (0.28 / 0.92)", "0.964 (0.94 / 1.00)"],
    ["Support (rows)", "BENIGN 7,939; DDOS 10,414; BRUTE_FORCE 664; RECON 747; WEB 127; BOT 109", "BENIGN 4,798; DDOS 6,466; BRUTE_FORCE 677; RECON 495; WEB 102; BOT 129", "BENIGN 33,323; DDOS 43,318; BRUTE_FORCE 2,767; RECON 3,000; WEB 524; BOT 393"],
], [1800, 2520, 2520, 2520])
h2(doc, "14.5 What the Results Show")
bullets(doc, [
    ("XGBoost is the strong model", "It scores above 0.99 F1 on four of six classes. Its weakest class is WEB_ATTACK (0.805): 191 DDOS flows were labelled WEB_ATTACK."),
    ("The SNN and LNN raise many false alarms on rare classes", "Recall on WEB_ATTACK and BOT is high (0.76 to 0.96) but precision is low (0.25 to 0.44). In the LNN, 301 BENIGN sequences were called BOT and 258 were called WEB_ATTACK. The SNN also confuses BENIGN with DDOS in both directions (575 and 511 flows)."),
    ("Use macro F1 as the headline for the SNN and LNN", "BENIGN and DDOS are about 90 percent of the data, which inflates accuracy. Macro F1 (about 0.74) weights every class equally."),
])
h2(doc, "14.6 Limits of These Figures")
bullets(doc, [
    "These are results on public datasets. Detection accuracy on live traffic has not been measured: the Feature Service computes some flow statistics (time units among them) differently from how the training data was built, and in earlier tests the models missed live packet attacks.",
    "The three models were not scored on the same rows, so the columns are not strictly comparable.",
    "The SNN and LNN checkpoints were chosen by their validation score, so those scores are slightly optimistic. The SNN's macro F1 varied between about 0.62 and 0.73 from epoch to epoch.",
    "The false-positive rate of the fused system and the SNN anomaly AUROC have not been measured.",
    "Human-in-the-loop retraining exists (analyst overrides and sandbox sessions become labelled samples, and a candidate is promoted only by an administrator), but the feedback data in manifest 1.0.4 is small: 137 training rows. It is not evidence of real-world continuous improvement.",
    "The file retraining-service/evaluation/evaluation_report.json describes version 1.0.1 on a small synthetic set and must not be quoted for the current models.",
])
h2(doc, "14.7 Relation to the Unpublished NeuroShield Manuscript")
para(doc, "An unpublished manuscript by the project team, 'NeuroShield: A Neuromorphic Multi-Model Cybersecurity Platform with Autonomous Deception, Behavioral Biometrics, and Continuous Learning', "
          "describes the same architecture. It reports performance targets, not measurements, and it differs from the system as built in the points below. It has no public link.")
caption(doc, "Table: Manuscript vs. System as Built")
table(doc, ["Topic", "Manuscript", "As built (this volume and Volume 2)"], [
    ["XGBoost input", "A 509-dimensional vector fused from SNN score, LNN state, behavioral delta and LNN probabilities.", "The 76 flow features. The three models are fused by a weighted formula (Volume 2, section 6)."],
    ["Training data", "Five datasets: CIC-IDS2017, CSE-CIC-IDS2018, CICIoT2023, CICIoMT2024, NSL-KDD.", "CIC-IDS2017 and CIC-DDoS2019."],
    ["SNN encoding and size", "10 receptive fields per feature (800 inputs); layers 256 and 64.", "5 per feature (400 inputs); layers 256 and 128."],
    ["XGBoost settings", "300 trees, learning rate 0.05.", "500 trees, learning rate 0.1."],
    ["Norse version", "0.0.7.", "1.1.0."],
    ["Retraining", "Only XGBoost is retrained automatically.", "All three models were trained and promoted through the candidate and approval flow."],
    ["Targets vs. results", "XGBoost macro F1 at least 0.92; LNN macro F1 at least 0.90; SNN AUROC at least 0.92.", "XGBoost 0.961 (met); LNN 0.749 (not met); SNN AUROC not measured (macro F1 0.739)."],
], [1900, 3700, 3760])
para(doc, "The manuscript's statement that this is the first application of liquid neural networks to cybersecurity is not supported by this documentation and is not repeated here. "
          "Its reference list has not been verified against the sources, and no research citations beyond those in section 13 are claimed in this volume.")

doc.add_paragraph()
para(doc, "End of Volume 4.")
OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(f"wrote {OUT}")
