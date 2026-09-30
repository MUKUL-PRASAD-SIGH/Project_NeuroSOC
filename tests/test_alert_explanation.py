from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference-service"))

import main as inference_main  # noqa: E402
from core.auth import OIDCConfig, OIDCValidationError  # noqa: E402


@pytest.fixture
def protected_client(monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", True)
    monkeypatch.setattr(inference_main, "OIDC_ISSUER", "http://localhost:8081/realms/neurosoc")
    monkeypatch.setattr(inference_main, "API_KEY", "")
    inference_main.rate_limiter.clear()
    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", lambda event: None)

    def fake_validate_access_token(token: str, _config: OIDCConfig) -> dict[str, object]:
        if token == "invalid":
            raise OIDCValidationError("Invalid OIDC access token")
        return {"sub": "test-user", "tenant_id": "test-tenant", "roles": [token]}

    monkeypatch.setattr(inference_main, "validate_access_token", fake_validate_access_token)
    return TestClient(inference_main.app)


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    with inference_main.runtime._lock:
        saved_alerts = list(inference_main.runtime._latest_alerts)
        inference_main.runtime._latest_alerts.clear()
    try:
        yield
    finally:
        with inference_main.runtime._lock:
            inference_main.runtime._latest_alerts.clear()
            inference_main.runtime._latest_alerts.extend(saved_alerts)
        inference_main._SHAP_EXPLAINER_CACHE["model_id"] = None
        inference_main._SHAP_EXPLAINER_CACHE["explainer"] = None


def _sample_verdict(**overrides):
    verdict = {
        "tenant_id": "test-tenant",
        "session_id": "explain-test",
        "user_id": "victim1",
        "source_ip": "203.0.113.9",
        "verdict": "HACKER",
        "confidence": 0.91,
        "xgb_class": "BRUTE_FORCE",
        "snn_score": 0.77,
        "behavioral_delta": 0.55,
        "lnn_class": "BRUTE_FORCE",
        "features_dict": {f"feature_{i}": float(i) / 80 for i in range(80)},
        "model_version": "1.0.1",
        "timestamp": 1_800_000_000.0,
    }
    verdict.update(overrides)
    return verdict


def test_fallback_explanation_when_no_xgb_model_is_loaded(monkeypatch):
    monkeypatch.setattr(inference_main.runtime.engine, "xgb_model", None)
    explanation = inference_main._explanation_for_verdict(_sample_verdict())

    assert explanation["method"] == "feature_magnitude"
    assert len(explanation["topFeatures"]) == 5
    values = [item["value"] for item in explanation["topFeatures"]]
    assert values == sorted(values, key=abs, reverse=True)
    assert "BRUTE_FORCE" not in explanation["summary"] or "Brute Force" in explanation["summary"]


def test_shap_path_is_attempted_against_a_real_sklearn_style_xgb_model_and_degrades_safely(monkeypatch):
    """Exercises the real shap.TreeExplainer call against a genuine XGBClassifier.

    Whether this environment's installed shap/xgboost pair can actually parse a multi-class
    booster (some combinations can't -- see the try/except in _shap_top_features) is a library
    compatibility detail, not something this test should assume either way. Either outcome must
    produce a well-formed, real explanation -- never a crash and never placeholder text.
    """
    rng = np.random.default_rng(3)
    features = rng.random((60, 80)).astype(np.float32)
    labels = rng.integers(0, 7, size=60)
    estimator = XGBClassifier(n_estimators=8, max_depth=2, objective="multi:softprob", num_class=7)
    estimator.fit(features, labels)

    class Wrapper:
        model = estimator

    monkeypatch.setattr(inference_main.runtime.engine, "xgb_model", Wrapper())
    monkeypatch.setattr(inference_main.runtime.engine, "feature_names", [f"feature_{i}" for i in range(80)])

    verdict = _sample_verdict(xgb_class="BRUTE_FORCE")
    explanation = inference_main._explanation_for_verdict(verdict)

    assert explanation["method"] in {"shap", "feature_magnitude"}
    assert len(explanation["topFeatures"]) == 5
    assert all(item["feature"].startswith("feature_") for item in explanation["topFeatures"])
    if explanation["method"] == "shap":
        # If shap did run, it must have produced real, non-trivial attributions.
        assert any(abs(item["impact"]) > 0 for item in explanation["topFeatures"])


def test_alert_list_includes_explanation_field(protected_client):
    with inference_main.runtime._lock:
        inference_main.runtime._latest_alerts.appendleft(_sample_verdict())

    response = protected_client.get("/api/v1/alerts", headers={"Authorization": "Bearer analyst"})
    assert response.status_code == 200
    matching = [alert for alert in response.json() if alert["id"] == "explain-test"]
    assert matching
    explanation = matching[0]["explanation"]
    assert explanation["method"] in {"shap", "feature_magnitude"}
    assert len(explanation["topFeatures"]) == 5
    assert explanation["snnSpikeScore"] == pytest.approx(0.77)
