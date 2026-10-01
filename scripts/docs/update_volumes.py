"""Applies the corrections to Volumes 1 to 3 of the NeuroSOC Technical Specification Series.

    python3 scripts/docs/update_volumes.py

Reads the original Word files from ~/Documents/NeuroSOC_Updated_Volumes/original/ (never modified) and writes the
revised files to ~/Documents/NeuroSOC_Updated_Volumes/. Every edit keeps the formatting of the paragraph or table
row it is based on. Each statement was checked against the code (inference-service/core/auth.py, main.py,
core/engine.py, docker-compose.yml, models/ manifests); the sources are named in the revision notes in each file.
Re-running always starts from the originals, so the result is the same each time.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import docx
from docx.table import Table, _Row
from docx.text.paragraph import Paragraph

BASE = Path.home() / "Documents" / "NeuroSOC_Updated_Volumes"
SRC = BASE / "original"
FILES = {
    1: "NeuroSOC_Documentation_Volume_1_System_Architecture_and_Operations.docx",
    2: "NeuroSOC_Documentation_Volume_2_Neuromorphic_AI_and_Detection_Engine.docx",
    3: "NeuroSOC_Documentation_Volume_3_Microservices_APIs_and_Security.docx",
}
REVISED = "v1.2.0-Production (revised October 2026)"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────
def set_text(paragraph: Paragraph, text: str) -> None:
    """Replace a paragraph's text, keeping the formatting of its first run."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for extra in runs[1:]:
        extra._r.getparent().remove(extra._r)


def find(doc, starts: str, after: int = 0) -> Paragraph:
    for index, paragraph in enumerate(doc.paragraphs):
        if index >= after and paragraph.text.startswith(starts):
            return paragraph
    raise LookupError(f"paragraph not found: {starts!r}")


def insert_after(anchor: Paragraph | Table, text: str, like: Paragraph) -> Paragraph:
    """Add a paragraph after ``anchor`` with the formatting of ``like``."""
    new = copy.deepcopy(like._p)
    element = anchor._p if isinstance(anchor, Paragraph) else anchor._tbl
    element.addnext(new)
    paragraph = Paragraph(new, like._parent)
    set_text(paragraph, text)
    return paragraph


def append_run_text(paragraph: Paragraph, extra: str) -> None:
    last = paragraph.runs[-1]
    last.text = last.text + extra


def set_cell(cell, text: str) -> None:
    set_text(cell.paragraphs[0], text)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def add_row(table: Table, values: list[str]) -> None:
    """Append a row cloned from an existing body row, alternating the two body templates to keep banding."""
    body = table.rows[1:]
    template = body[len(body) % 2 if len(body) > 1 else 0]
    clone = copy.deepcopy(template._tr)
    table._tbl.append(clone)
    row = _Row(clone, table)
    for cell, value in zip(row.cells, values):
        set_cell(cell, value)


def row_with(table: Table, first_cell: str) -> _Row:
    for row in table.rows:
        if row.cells[0].text.strip() == first_cell:
            return row
    raise LookupError(first_cell)


def set_listing(cell, lines: list[str]) -> None:
    """Replace the paragraphs of a one-cell code listing with ``lines``."""
    paragraphs = cell.paragraphs
    template = paragraphs[2] if len(paragraphs) > 2 else paragraphs[-1]
    first = paragraphs[0]
    for extra in paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    set_text(first, lines[0])
    previous = first
    for line in lines[1:]:
        new = copy.deepcopy(template._p)
        previous._p.addnext(new)
        previous = Paragraph(new, template._parent)
        set_text(previous, line if line else " ")


def stamp_version(doc, volume: int) -> None:
    table = doc.tables[0]
    row = row_with(table, "Version / Release")
    set_cell(row.cells[1], REVISED)


def add_note_after_heading(doc, heading_start: str, text: str, body_like: str) -> None:
    heading = find(doc, heading_start)
    body = find(doc, body_like)
    insert_after(heading, text, body)


# ── Volume 1 ─────────────────────────────────────────────────────────────────────────────────
def volume1(doc) -> None:
    stamp_version(doc, 1)
    body = find(doc, "The platform comprises nine core custom microservices")

    feature = find(doc, "2. Feature Service")
    append_run_text(feature, " (The promoted detection models were trained on a 76-column feature list that is named differently; see Volume 2, section 4.1.)")

    inference = find(doc, "3. Inference Service")
    extra = insert_after(inference,
        "3a. Universal Behavioral Engine and SDK API (inside the Inference Service, :8000) — Optional, enabled with ENABLE_UNIVERSAL_ENGINE=true (default false). "
        "Scores behavior events sent by the browser and Python SDKs on routes under /api/v1/sdk/ (authenticated with application keys, not Keycloak) and serves the "
        "analyst and application-management routes under /api/v1/universal/. It adds no container, port, Kafka topic or database. See Volume 4.", inference)
    del extra

    portal = find(doc, "8. NovaTrust Bank Portal")
    append_run_text(portal, " Not to be confused with the NovaTrust Customer Demo (served at /demo by the analyst dashboard), a separate application described in Volume 4 that exercises the SDK.")

    heading = find(doc, "5.3 Port Allocation & Service Mapping")
    table = doc.tables[8]
    insert_after(table, "Note: the Universal Behavioral Engine runs inside the neuroshield-inference container and uses port 8000; it adds no row to this table. "
                 "Outside Docker, the demonstration set-up in Volume 4 (section 9.7) uses ports 8010 for the API and 5173 for the Vite development server. "
                 "The ports above are as defined in docker-compose.yml (for example 8081 for Keycloak is published on 127.0.0.1 only).", body)
    del heading

    profiles = doc.tables[9]
    insert_after(profiles,
        "Settings added since v1.1.0 (passed to the inference container by docker-compose.yml): ENABLE_UNIVERSAL_ENGINE (default false) turns on the SDK and universal routes; "
        "UNIVERSAL_HASH_SECRET (32 or more random characters in staging and production) keys the hashing of IP addresses; UNIVERSAL_SITES_FILE seeds applications for local use; "
        "NEUROSOC_DEMO_MODE (default false) mounts the NovaTrust customer-demo routes. In the dashboard build, VITE_UNIVERSAL_ENABLED shows the Protection page and VITE_DEMO_MODE "
        "shows the demo's Security Testing panel. All are off unless set.", body)

    runtime = find(doc, "3. Runtime Production Verification")
    append_run_text(runtime, " The service also refuses to start when NEUROSOC_DEMO_MODE=true under either value, because the demo is for local use only.")


# ── Volume 2 ─────────────────────────────────────────────────────────────────────────────────
MANIFEST = [
    "Candidate Manifest Structure (models/candidates/<candidate_id>.manifest.json),",
    "shown with the values of the promoted XGBoost candidate:",
    "{",
    "  'candidate_id': 'xgb_candidate_20260930T101408_6abb8505',",
    "  'status': 'promoted',   # or 'pending_approval' / 'rejected'",
    "  'model_key': 'xgb',     # 'snn', 'lnn' or 'xgb'",
    "  'base_model_version': '1.0.1',",
    "  'proposed_version': '1.0.2',",
    "  'artifact_path': 'candidates/xgb_candidate_20260930T101408_6abb8505.json',",
    "  'validation_f1': 0.9606,",
    "  'metrics': {'cv_f1_macro_mean': 0.9645, 'test_accuracy': 0.9961,",
    "              'test_f1_macro': 0.9606},",
    "  'created_at': '2026-09-30T10:14:08+00:00',",
    "  'promoted_at': '2026-09-30T10:52:28+00:00',",
    "  'promoted_by': '<identity of the approver>'",
    "}",
    "",
    "Security Enforcement:",
    "  * test_model_promotion_guard.py verifies that writing a candidate never",
    "    changes model_version.json and leaves it in status 'pending_approval'.",
    "  * Listing, promoting and rejecting candidates, POST /api/v1/models/rollback",
    "    and POST /api/v1/models/reload require the 'platform-admin' role. The",
    "    'admin' role cannot promote models. Only a candidate in status",
    "    'pending_approval' can be promoted or rejected.",
    "  * Each promotion saves the previous model_version.json to models/history/",
    "    so that a rollback can restore it.",
]


def volume2(doc) -> None:
    stamp_version(doc, 2)
    body = find(doc, "The XGBoost classifier maps 80 flow features")
    taxonomy = doc.tables[6]
    insert_after(taxonomy,
        "Implementation note (October 2026). The promoted models (manifest 1.0.4) were trained on 76 flow features from CIC-IDS2017 and CIC-DDoS2019 (datasets/feature_columns.txt), "
        "in six classes that have data: BENIGN, DDOS, BRUTE_FORCE, RECONNAISSANCE, WEB_ATTACK and BOT. The class OTHER exists in the taxonomy but has no samples in the training or test data. "
        "The Feature Service, by contrast, emits the 80 CICFlowMeter-named features written to /data/feature_columns.txt, which the Inference Service loads. The two lists use different names "
        "and the live feature computation is not fully reconciled with the training data, so accuracy on live traffic has not been established. Measured accuracy on the public-dataset test data "
        "(accuracy 0.903, 0.920 and 0.996; macro F1 0.739, 0.749 and 0.961 for the SNN, LNN and XGBoost) is reported with per-class tables and limits in Volume 4, section 14.", body)

    caption = find(doc, "Listing / Diagram: NeuroSOC Candidate Model Manifest")
    del caption
    set_listing(doc.tables[10].rows[0].cells[0], MANIFEST)

    intro = find(doc, "NeuroSOC enforces a zero-trust model deployment policy")
    append_run_text(intro, " As of manifest 1.0.4 the SNN, LNN and XGBoost candidates have each been promoted through this flow (validation macro F1 0.729, 0.749 and 0.961).")


# ── Volume 3 ─────────────────────────────────────────────────────────────────────────────────
RBAC_ROWS = {
    "analyst": ("Read access to alerts, statistics, latest verdicts and user profiles. Every role listed below can also read (GET) the same data.",
                "GET /api/v1/alerts/*, GET /api/v1/stats, GET /api/v1/profiles/*, GET /api/v1/universal/*, WS /api/v1/ws/alerts"),
    "operator": ("Analyst permissions + response actions: alert decisions (block, restore), analysis and behavioral write routes, and managing SDK applications.",
                 "POST /api/v1/alerts/{session_id}/decision, POST /api/v1/analyze, POST /api/v1/behavioral*, POST /api/v1/bank/*, POST/PUT /api/v1/universal/sites*"),
    "admin": ("Operator permissions + the audit log. Cannot promote or reload models (that needs platform-admin).",
              "All operator routes + GET /api/v1/audit/events"),
    "auditor": ("Read access, including the immutable security audit log and compliance reports.",
                "GET /api/v1/audit/events, GET /api/v1/reports/*"),
}
ROLE_PLATFORM_ADMIN = ["platform-admin",
                       "Everything an admin can do, plus model lifecycle control: listing, promoting and rejecting candidates, rollback, reload, and /admin routes. "
                       "Model-admin routes are always authenticated, even when OIDC_REQUIRED is false.",
                       "GET /api/v1/models/candidates, POST /api/v1/models/candidates/{id}/promote and /reject, POST /api/v1/models/rollback, POST /api/v1/models/reload",
                       "Platform owners; the only role allowed to change the active models."]

API_ROWS = [
    ["GET /", "Public", "None", "Service banner: service name, phase, topic names (200 OK)"],
    ["GET /metrics", "Public", "None", "Prometheus metrics in text format (200 OK)"],
    ["GET /api/v1/verdicts/current-session", "Any NeuroSOC role", "None", "Verdict snapshot of the current portal session, or INCONCLUSIVE (200 OK)"],
    ["POST /api/v1/alerts/{session_id}/decision", "operator, admin", "{decision, ...} (AlertDecisionRequest)", "Records the analyst's block or restore decision (200 OK)"],
    ["GET /api/v1/audit/events", "admin, auditor, platform-admin", "Query: after_sequence, limit (up to 500)", "A page of tamper-evident audit events for the tenant (200 OK)"],
    ["GET /api/v1/models/candidates", "platform-admin", "None", "All candidate model manifests (200 OK)"],
    ["POST /api/v1/models/candidates/{candidate_id}/promote", "platform-admin", "None", "Promotes a candidate in status pending_approval and writes models/history (200 OK)"],
    ["POST /api/v1/models/candidates/{candidate_id}/reject", "platform-admin", "None", "Marks a pending candidate rejected (200 OK)"],
    ["POST /api/v1/models/rollback", "platform-admin", "None", "Restores the latest snapshot in models/history (200 OK; 404 if none)"],
    ["WS /ws/alerts", "Any NeuroSOC role", "WebSocket Upgrade", "The alert stream (the same feed as /api/v1/ws/alerts)"],
]


def volume3(doc) -> None:
    stamp_version(doc, 3)
    body = find(doc, "This third and final volume")

    portal = find(doc, "Operating on port 3001, the NovaTrust portal")
    insert_after(portal,
        "Note: this is the NovaTrust Bank Simulation Portal, a red-team testbed for the network detection path. It is a different application from the NovaTrust Customer Demo "
        "(served at /demo by the analyst dashboard), which is a customer of the SDK and is described in Volume 4.", body)

    lead = find(doc, "Authentication is delegated to Keycloak")
    set_text(lead, lead.text.replace("NeuroSOC defines four hierarchical roles:", "NeuroSOC defines five roles (analyst, operator, admin, auditor and platform-admin); the route-to-role mapping is in inference-service/core/auth.py:"))
    rbac = doc.tables[5]
    for role, (permissions, routes) in RBAC_ROWS.items():
        row = row_with(rbac, role)
        set_cell(row.cells[1], permissions)
        set_cell(row.cells[2], routes)
    add_row(rbac, ROLE_PLATFORM_ADMIN)
    insert_after(rbac,
        "Notes. Read (GET, HEAD, OPTIONS) routes are open to every role above. Writes to the analysis and bank routes and alert decisions need operator or admin. "
        "SDK routes under /api/v1/sdk/ do not use Keycloak or the service API key: they authenticate with an application's publishable or secret key (Volume 4, section 3.2). "
        "The /, /health and /metrics routes are public.", body)

    listing = find(doc, "The complete specification for all REST and WebSocket endpoints")
    set_text(listing, "The specification for the platform's REST and WebSocket endpoints exposed by the NeuroSOC Inference Service is documented below. "
                      "The SDK, application-management and demo routes (/api/v1/sdk/*, /api/v1/universal/*, /api/v1/demo/*) are specified in Volume 4, section 7.")
    api = doc.tables[6]
    for row in API_ROWS:
        add_row(api, row)


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}: put the three original .docx files there", file=sys.stderr)
        return 1
    for volume, name in FILES.items():
        doc = docx.Document(SRC / name)
        {1: volume1, 2: volume2, 3: volume3}[volume](doc)
        out = BASE / name
        doc.save(out)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
