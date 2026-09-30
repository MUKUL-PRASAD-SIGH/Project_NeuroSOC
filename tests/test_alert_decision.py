from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference-service"))

import main as inference_main  # noqa: E402
from core.auth import OIDCConfig, OIDCValidationError  # noqa: E402


@pytest.fixture
def protected_client(monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", True)
    monkeypatch.setattr(inference_main, "OIDC_ISSUER", "http://localhost:8081/realms/neurosoc")
    monkeypatch.setattr(inference_main, "API_KEY", "")
    inference_main.rate_limiter.clear()
    audit_events: list[dict] = []
    monkeypatch.setattr(
        inference_main.runtime.repository,
        "record_audit_event",
        lambda event: audit_events.append(event),
    )

    def fake_validate_access_token(token: str, _config: OIDCConfig) -> dict[str, object]:
        if token == "invalid":
            raise OIDCValidationError("Invalid OIDC access token")
        role, separator, tenant_id = token.partition("@")
        return {
            "sub": "test-user",
            "username": f"{role}-user",
            "tenant_id": tenant_id if separator else "test-tenant",
            "roles": [role],
        }

    monkeypatch.setattr(inference_main, "validate_access_token", fake_validate_access_token)
    client = TestClient(inference_main.app)
    client.audit_events = audit_events
    return client


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    with inference_main.runtime._lock:
        saved_verdicts = list(inference_main.runtime._latest_verdicts)
        saved_alerts = list(inference_main.runtime._latest_alerts)
        saved_decisions = dict(inference_main.runtime._alert_decisions)
        inference_main.runtime._latest_verdicts.clear()
        inference_main.runtime._latest_alerts.clear()
        inference_main.runtime._alert_decisions.clear()
    try:
        yield
    finally:
        with inference_main.runtime._lock:
            inference_main.runtime._latest_verdicts.clear()
            inference_main.runtime._latest_verdicts.extend(saved_verdicts)
            inference_main.runtime._latest_alerts.clear()
            inference_main.runtime._latest_alerts.extend(saved_alerts)
            inference_main.runtime._alert_decisions.clear()
            inference_main.runtime._alert_decisions.update(saved_decisions)


@pytest.fixture
def decision_capture(monkeypatch, protected_client):
    calls = {"training_rows": [], "decisions": []}

    def fake_record_analyst_decision(
        tenant_id,
        session_id,
        decision,
        status,
        decided_by,
        decided_by_roles,
        notes,
        training_row,
        audit_event,
    ):
        if training_row is not None:
            calls["training_rows"].append(
                {
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    **training_row,
                }
            )
        calls["decisions"].append(
            {"tenant_id": tenant_id, "session_id": session_id, "decision": decision, "status": status, "decided_by": decided_by}
        )
        protected_client.audit_events.append(audit_event)
        return {
            "session_id": session_id,
            "decision": decision,
            "status": status,
            "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc),
            "training_label_written": training_row["label"] if training_row else None,
        }

    monkeypatch.setattr(inference_main.runtime.repository, "record_analyst_decision", fake_record_analyst_decision)
    return calls


def _seed_verdict(session_id: str, xgb_class: str = "BRUTE_FORCE", tenant_id: str = "test-tenant") -> None:
    with inference_main.runtime._lock:
        inference_main.runtime._latest_verdicts.appendleft(
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": "victim1",
                "source_ip": "203.0.113.5",
                "verdict": "HACKER",
                "confidence": 0.93,
                "xgb_class": xgb_class,
                "features_dict": {f"feature_{i}": 0.1 for i in range(80)},
                "model_version": "1.0.1",
                "timestamp": 1_800_000_000.0,
            }
        )


def test_decision_requires_operator_or_admin_role(protected_client, decision_capture):
    _seed_verdict("decision-role-test")
    response = protected_client.post(
        "/api/v1/alerts/decision-role-test/decision",
        json={"decision": "confirm_threat"},
        headers={"Authorization": "Bearer analyst"},
    )
    assert response.status_code == 403
    assert decision_capture["decisions"] == []


def test_unknown_session_returns_404(protected_client, decision_capture):
    response = protected_client.post(
        "/api/v1/alerts/does-not-exist/decision",
        json={"decision": "confirm_threat"},
        headers={"Authorization": "Bearer operator"},
    )
    assert response.status_code == 404


def test_decision_cannot_target_another_tenants_alert(protected_client, decision_capture):
    _seed_verdict("other-tenant-alert", tenant_id="tenant-b")
    response = protected_client.post(
        "/api/v1/alerts/other-tenant-alert/decision",
        json={"decision": "confirm_threat"},
        headers={"Authorization": "Bearer operator"},
    )
    assert response.status_code == 404
    assert decision_capture["decisions"] == []


def test_confirm_threat_writes_the_verdicts_own_class_as_the_training_label(protected_client, decision_capture):
    _seed_verdict("decision-confirm-test", xgb_class="BRUTE_FORCE")
    response = protected_client.post(
        "/api/v1/alerts/decision-confirm-test/decision",
        json={"decision": "confirm_threat", "notes": "Confirmed via IP reputation."},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "closed"
    assert body["trainingLabelWritten"] == "BRUTE_FORCE"
    assert decision_capture["training_rows"][0]["label"] == "BRUTE_FORCE"
    assert decision_capture["decisions"][0]["decision"] == "confirm_threat"
    assert any(event["event_type"] == "security.alert_decision" for event in protected_client.audit_events)


def test_false_positive_always_writes_benign(protected_client, decision_capture):
    _seed_verdict("decision-fp-test", xgb_class="BRUTE_FORCE")
    response = protected_client.post(
        "/api/v1/alerts/decision-fp-test/decision",
        json={"decision": "false_positive"},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert decision_capture["training_rows"][0]["label"] == "BENIGN"


@pytest.mark.parametrize("decision", ["restore_access", "escalate"])
def test_non_terminal_decisions_do_not_write_a_training_label(protected_client, decision_capture, decision):
    _seed_verdict(f"decision-{decision}-test")
    response = protected_client.post(
        f"/api/v1/alerts/decision-{decision}-test/decision",
        json={"decision": decision},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "triaged"
    assert response.json()["trainingLabelWritten"] is None
    assert decision_capture["training_rows"] == []


def test_invalid_decision_value_is_rejected(protected_client, decision_capture):
    _seed_verdict("decision-invalid-test")
    response = protected_client.post(
        "/api/v1/alerts/decision-invalid-test/decision",
        json={"decision": "not_a_real_decision"},
        headers={"Authorization": "Bearer operator"},
    )
    assert response.status_code == 422


def test_alert_list_reflects_the_recorded_decision_status(protected_client, decision_capture):
    _seed_verdict("decision-list-test", xgb_class="BOT")
    with inference_main.runtime._lock:
        inference_main.runtime._latest_alerts.appendleft(
            {
                "session_id": "decision-list-test",
                "tenant_id": "test-tenant",
                "user_id": "victim1",
                "source_ip": "203.0.113.5",
                "confidence": 0.93,
                "verdict": "HACKER",
                "timestamp": 1_800_000_000.0,
                "model_version": "1.0.1",
                "xgb_class": "BOT",
            }
        )
    protected_client.post(
        "/api/v1/alerts/decision-list-test/decision",
        json={"decision": "confirm_threat"},
        headers={"Authorization": "Bearer operator"},
    )

    alerts_response = protected_client.get("/api/v1/alerts", headers={"Authorization": "Bearer analyst"})
    assert alerts_response.status_code == 200
    matching = [alert for alert in alerts_response.json() if alert["id"] == "decision-list-test"]
    assert matching and matching[0]["status"] == "closed"
    assert matching[0]["decision"] == "confirm_threat"


def test_decision_is_not_cached_when_atomic_persistence_fails(protected_client, decision_capture, monkeypatch):
    session_id = "decision-audit-failure-test"
    _seed_verdict(session_id)

    def fail_atomic_write(*_args, **_kwargs):
        raise RuntimeError("database transaction failed")

    monkeypatch.setattr(inference_main.runtime.repository, "record_analyst_decision", fail_atomic_write)
    response = protected_client.post(
        f"/api/v1/alerts/{session_id}/decision",
        json={"decision": "confirm_threat"},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 503
    assert ("test-tenant", session_id) not in inference_main.runtime._alert_decisions
