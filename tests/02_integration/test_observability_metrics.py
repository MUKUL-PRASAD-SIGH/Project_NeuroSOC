from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference-service"))

import main as inference_main  # noqa: E402

client = TestClient(inference_main.app)


def test_metrics_endpoint_is_reachable_without_auth():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_exposes_the_new_neurosoc_series():
    body = client.get("/metrics").text
    for series in (
        "neurosoc_events_processed_total",
        "neurosoc_inference_latency_seconds",
        "neurosoc_verdicts_total",
        "neurosoc_sandbox_active_sessions",
    ):
        assert series in body


def test_handle_verdict_increments_the_verdict_counter(monkeypatch):
    monkeypatch.setattr(inference_main.runtime, "_persist_verdict", lambda verdict: None)
    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", lambda event: None)

    before = inference_main.VERDICTS_TOTAL.labels(verdict="LEGITIMATE")._value.get()
    verdict = inference_main.ThreatVerdict(
        session_id="metrics-test", user_id="u1", source_ip="1.2.3.4", snn_score=0.1, lnn_class="BENIGN",
        xgb_class="BENIGN", behavioral_delta=0.05, confidence=0.05, verdict="LEGITIMATE",
        timestamp=1_800_000_000.0, model_version="1.0.1", features_dict={},
    )
    inference_main.runtime._handle_verdict(verdict)
    after = inference_main.VERDICTS_TOTAL.labels(verdict="LEGITIMATE")._value.get()

    assert after == before + 1


def test_sandbox_active_gauge_reflects_diverted_portal_sessions():
    state = inference_main.PortalState()
    plain = state.bind_aliases("plain-user", None, ["plain-user"])
    diverted = state.bind_aliases("diverted-user", None, ["diverted-user"])
    state.attach_sandbox(diverted.session_id, "sbx-token", "live")

    assert state.count_active_sandbox_sessions() == 1
    _ = plain  # not diverted; must not be counted
