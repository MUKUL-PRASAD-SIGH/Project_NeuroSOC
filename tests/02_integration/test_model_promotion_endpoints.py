from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402
from core.auth import OIDCConfig, OIDCValidationError  # noqa: E402


@pytest.fixture
def promotion_env(tmp_path, monkeypatch):
    version_path = tmp_path / "model_version.json"
    candidates_dir = tmp_path / "candidates"
    history_dir = tmp_path / "history"
    candidates_dir.mkdir()

    active_manifest = {
        "version": "1.0.1",
        "snn": "snn_active.pt",
        "lnn": "lnn_active.pt",
        "xgb": "xgb_active.json",
        "validation_f1": {"snn": None, "lnn": None, "xgb": 1.0},
        "timestamp": "2026-04-25T01:13:07+00:00",
    }
    version_path.write_text(json.dumps(active_manifest), encoding="utf-8")

    candidate = {
        "candidate_id": "xgb_candidate_test",
        "status": "pending_approval",
        "model_key": "xgb",
        "base_model_version": "1.0.1",
        "proposed_version": "1.0.2",
        "artifact_path": "candidates/xgb_candidate_test.json",
        "validation_f1": 0.87,
        "metrics": {"holdout_f1": 0.87},
        "created_at": "2026-09-29T00:00:00+00:00",
    }
    (candidates_dir / "xgb_candidate_test.manifest.json").write_text(json.dumps(candidate), encoding="utf-8")

    monkeypatch.setattr(inference_main, "MODEL_VERSION_PATH", version_path)
    monkeypatch.setattr(inference_main, "MODEL_CANDIDATES_DIR", candidates_dir)
    monkeypatch.setattr(inference_main, "MODEL_HISTORY_DIR", history_dir)
    monkeypatch.setattr(inference_main.runtime.engine, "model_version_path", version_path)

    force_activate_calls = []

    def fake_force_activate_manifest(payload):
        force_activate_calls.append(payload)
        inference_main.runtime.engine.current_model_version = str(payload.get("version", "0.0.0"))
        return True

    monkeypatch.setattr(inference_main.runtime.engine, "force_activate_manifest", fake_force_activate_manifest)
    monkeypatch.setattr(inference_main.runtime.engine, "current_model_version", "1.0.1")

    return {"version_path": version_path, "candidates_dir": candidates_dir, "history_dir": history_dir, "force_activate_calls": force_activate_calls}


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
        return {"sub": "test-user", "username": f"{token}-user", "tenant_id": "test-tenant", "roles": [token]}

    monkeypatch.setattr(inference_main, "validate_access_token", fake_validate_access_token)
    client = TestClient(inference_main.app)
    client.audit_events = audit_events
    return client


def test_list_candidates_returns_pending_candidate(protected_client, promotion_env):
    response = protected_client.get("/api/v1/models/candidates", headers={"Authorization": "Bearer platform-admin"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["candidateId"] == "xgb_candidate_test"
    assert body[0]["status"] == "pending_approval"


def test_tenant_admin_cannot_read_shared_model_candidates(protected_client, promotion_env):
    response = protected_client.get("/api/v1/models/candidates", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 403


def test_non_admin_cannot_promote(protected_client, promotion_env):
    response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer operator"},
    )
    assert response.status_code == 403


def test_promote_updates_manifest_and_activates_model(protected_client, promotion_env):
    response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "promoted"
    assert body["activeModelVersion"] == "1.0.2"
    assert body["reloaded"] is True

    new_manifest = json.loads(promotion_env["version_path"].read_text(encoding="utf-8"))
    assert new_manifest["version"] == "1.0.2"
    assert new_manifest["xgb"] == "candidates/xgb_candidate_test.json"
    assert new_manifest["validation_f1"]["xgb"] == 0.87
    # snn/lnn pointers are untouched by an xgb-only promotion.
    assert new_manifest["snn"] == "snn_active.pt"

    candidate_manifest = json.loads(
        (promotion_env["candidates_dir"] / "xgb_candidate_test.manifest.json").read_text(encoding="utf-8")
    )
    assert candidate_manifest["status"] == "promoted"
    assert candidate_manifest["promoted_by"] == "platform-admin-user"

    history_files = list(promotion_env["history_dir"].glob("*.json"))
    assert len(history_files) == 1
    old_snapshot = json.loads(history_files[0].read_text(encoding="utf-8"))
    assert old_snapshot["version"] == "1.0.1"

    assert promotion_env["force_activate_calls"][0]["version"] == "1.0.2"
    assert any(event["event_type"] == "security.model_promotion" for event in protected_client.audit_events)


def test_promote_restores_previous_model_when_success_audit_fails(protected_client, promotion_env, monkeypatch):
    original_record_audit = inference_main.runtime.repository.record_audit_event

    def fail_promotion_success(event):
        if event.get("event_type") == "security.model_promotion" and event.get("outcome") == "succeeded":
            raise RuntimeError("audit store unavailable")
        original_record_audit(event)

    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", fail_promotion_success)
    response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 503
    assert json.loads(promotion_env["version_path"].read_text(encoding="utf-8"))["version"] == "1.0.1"
    candidate = json.loads(
        (promotion_env["candidates_dir"] / "xgb_candidate_test.manifest.json").read_text(encoding="utf-8")
    )
    assert candidate["status"] == "pending_approval"
    assert list(promotion_env["history_dir"].glob("*.json")) == []
    assert inference_main.runtime.engine.current_model_version == "1.0.1"
    assert [call["version"] for call in promotion_env["force_activate_calls"]] == ["1.0.2", "1.0.1"]


def test_promote_unknown_candidate_returns_404(protected_client, promotion_env):
    response = protected_client.post(
        "/api/v1/models/candidates/does-not-exist/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )
    assert response.status_code == 404


def test_promote_already_decided_candidate_returns_409(protected_client, promotion_env):
    first = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )
    assert first.status_code == 200

    second = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )
    assert second.status_code == 409


def test_reject_marks_candidate_without_touching_active_manifest(protected_client, promotion_env):
    original_contents = promotion_env["version_path"].read_text(encoding="utf-8")

    response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/reject",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert promotion_env["version_path"].read_text(encoding="utf-8") == original_contents
    assert promotion_env["force_activate_calls"] == []


def test_reject_restores_candidate_when_success_audit_fails(protected_client, promotion_env, monkeypatch):
    original_record_audit = inference_main.runtime.repository.record_audit_event

    def fail_rejection_success(event):
        if event.get("event_type") == "security.model_rejection" and event.get("outcome") == "succeeded":
            raise RuntimeError("audit store unavailable")
        original_record_audit(event)

    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", fail_rejection_success)
    response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/reject",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 503
    candidate = json.loads(
        (promotion_env["candidates_dir"] / "xgb_candidate_test.manifest.json").read_text(encoding="utf-8")
    )
    assert candidate["status"] == "pending_approval"


def test_rollback_restores_previous_manifest(protected_client, promotion_env):
    promote_response = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )
    assert promote_response.status_code == 200
    assert len(list(promotion_env["history_dir"].glob("*.json"))) == 1

    rollback_response = protected_client.post(
        "/api/v1/models/rollback",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert rollback_response.status_code == 200
    body = rollback_response.json()
    assert body["restoredVersion"] == "1.0.1"
    assert body["activeModelVersion"] == "1.0.1"

    restored_manifest = json.loads(promotion_env["version_path"].read_text(encoding="utf-8"))
    assert restored_manifest["version"] == "1.0.1"
    assert restored_manifest["xgb"] == "xgb_active.json"
    # The snapshot is consumed on rollback.
    assert list(promotion_env["history_dir"].glob("*.json")) == []
    assert promotion_env["force_activate_calls"][-1]["version"] == "1.0.1"


def test_rollback_restores_active_manifest_and_snapshot_when_success_audit_fails(
    protected_client, promotion_env, monkeypatch
):
    promoted = protected_client.post(
        "/api/v1/models/candidates/xgb_candidate_test/promote",
        headers={"Authorization": "Bearer platform-admin"},
    )
    assert promoted.status_code == 200

    original_record_audit = inference_main.runtime.repository.record_audit_event

    def fail_rollback_success(event):
        if event.get("event_type") == "security.model_rollback" and event.get("outcome") == "succeeded":
            raise RuntimeError("audit store unavailable")
        original_record_audit(event)

    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", fail_rollback_success)
    response = protected_client.post(
        "/api/v1/models/rollback",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 503
    assert json.loads(promotion_env["version_path"].read_text(encoding="utf-8"))["version"] == "1.0.2"
    assert inference_main.runtime.engine.current_model_version == "1.0.2"
    snapshots = list(promotion_env["history_dir"].glob("*.json"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text(encoding="utf-8"))["version"] == "1.0.1"


def test_rollback_with_no_history_returns_404(protected_client, promotion_env):
    response = protected_client.post("/api/v1/models/rollback", headers={"Authorization": "Bearer platform-admin"})
    assert response.status_code == 404
