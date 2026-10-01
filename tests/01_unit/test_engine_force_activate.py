from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

from core.engine import DecisionEngine  # noqa: E402
from core.xgboost.model import XGBoostClassifier  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402


def _build_and_save_tiny_xgb_artifact(path: Path) -> None:
    rng = np.random.default_rng(7)
    features = rng.random((40, 80)).astype(np.float32)
    labels = rng.integers(0, 7, size=40)
    estimator = XGBClassifier(n_estimators=5, max_depth=2, objective="multi:softprob", num_class=7)
    estimator.fit(features, labels)
    wrapper = XGBoostClassifier(feature_names=[f"feature_{i}" for i in range(80)])
    wrapper.model = estimator
    wrapper.save(path)


def _build_engine(tmp_path: Path) -> tuple[DecisionEngine, Path]:
    version_path = tmp_path / "model_version.json"
    version_path.write_text(
        json.dumps({"version": "1.0.0", "xgb": None, "validation_f1": {"xgb": 0.95}}),
        encoding="utf-8",
    )
    engine = DecisionEngine(
        model_version_path=version_path,
        snn_model=object(),
        snn_encoder=object(),
        lnn_reservoir=object(),
        lnn_classifier=object(),
        start_model_monitor=False,
    )
    return engine, version_path


def test_force_activate_manifest_bypasses_the_f1_regression_guard(tmp_path):
    engine, version_path = _build_engine(tmp_path)
    assert engine.current_validation_f1.get("xgb") == 0.95

    artifact_path = tmp_path / "xgb_rollback_target.json"
    _build_and_save_tiny_xgb_artifact(artifact_path)

    # check_model_version() would refuse this: 0.40 < the current 0.95. force_activate_manifest
    # must not -- that guard exists for the periodic auto-monitor, not an explicit admin rollback.
    rollback_payload = {
        "version": "0.9.0",
        "xgb": str(artifact_path),
        "validation_f1": {"xgb": 0.40},
    }

    result = engine.force_activate_manifest(rollback_payload)

    assert result is True
    assert engine.current_model_version == "0.9.0"
    assert engine.current_validation_f1["xgb"] == 0.40
    assert engine.xgb_model is not None


def test_force_activate_manifest_reports_failure_for_a_broken_artifact(tmp_path):
    engine, _version_path = _build_engine(tmp_path)

    broken_path = tmp_path / "not_a_real_model.json"
    broken_path.write_text("{not valid xgboost json", encoding="utf-8")

    result = engine.force_activate_manifest({"version": "0.0.9", "xgb": str(broken_path), "validation_f1": {}})

    assert result is False
    # Version must not be bumped when activation fails partway through.
    assert engine.current_model_version == "1.0.0"
