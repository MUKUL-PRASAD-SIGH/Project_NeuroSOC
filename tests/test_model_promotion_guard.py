from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RETRAINING_DIR = REPO_ROOT / "retraining-service"
sys.path.insert(0, str(RETRAINING_DIR))
import common as retraining_common


def load_retraining_main():
    module_name = "neurosoc_retraining_main_for_tests"
    module_path = RETRAINING_DIR / "main.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_writer_never_changes_active_model_manifest(tmp_path):
    version_file = tmp_path / "model_version.json"
    active_manifest = {
        "version": "2.4.1",
        "snn": "snn_active.pt",
        "lnn": "lnn_active.pt",
        "xgb": "xgb_active.json",
        "validation_f1": {"xgb": 0.72},
    }
    version_file.write_text(json.dumps(active_manifest), encoding="utf-8")
    requested_artifact = tmp_path / "xgboost_best.json"
    candidate_artifact = retraining_common.candidate_artifact_path(
        "xgb",
        requested_artifact,
        version_file,
    )
    candidate_artifact.write_text("candidate model", encoding="utf-8")
    original_contents = version_file.read_text(encoding="utf-8")

    candidate = retraining_common.write_model_candidate(
        "xgb",
        candidate_artifact,
        0.91,
        version_file,
        metrics={"test_accuracy": 0.93},
    )

    assert version_file.read_text(encoding="utf-8") == original_contents
    assert candidate["status"] == "pending_approval"
    assert candidate["base_model_version"] == "2.4.1"
    assert candidate["proposed_version"] == "2.4.2"
    assert candidate["artifact_path"].startswith("candidates/")
    manifest_path = version_file.parent / "candidates" / f"{candidate['candidate_id']}.manifest.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == candidate


def test_feedback_retraining_creates_candidate_without_promoting_or_reloading(tmp_path, monkeypatch):
    retraining_main = load_retraining_main()
    version_file = tmp_path / "models" / "model_version.json"
    version_file.parent.mkdir(parents=True)
    active_manifest = {
        "version": "1.0.4",
        "snn": "snn_active.pt",
        "lnn": "lnn_active.pt",
        "xgb": "xgb_active.json",
        "validation_f1": {"xgb": 0.6},
    }
    version_file.write_text(json.dumps(active_manifest), encoding="utf-8")
    original_contents = version_file.read_text(encoding="utf-8")
    sample = retraining_main.FeedbackSample(
        id=7,
        session_id="feedback-session",
        features=[0.0] * 80,
        label="BENIGN",
    )

    class FakeRepository:
        def bootstrap(self):
            return None

        def fetch_feedback_samples(self, min_id_exclusive=0, max_id_inclusive=None):
            return [sample]

    class FakeModel:
        def save(self, path):
            Path(path).write_text("candidate artifact", encoding="utf-8")

    service = retraining_main.RetrainingService(
        FakeRepository(),
        model_version_file=version_file,
        state_file=tmp_path / "retraining_state.json",
        results_dir=tmp_path / "results",
        min_feedback_samples=1,
    )
    monkeypatch.setattr(
        service,
        "_load_training_corpus",
        lambda _samples: (
            np.zeros((2, 80), dtype=np.float32),
            np.asarray(["BENIGN", "BENIGN"], dtype=object),
            [f"feature_{index}" for index in range(80)],
        ),
    )
    monkeypatch.setattr(
        service,
        "_train_xgboost",
        lambda *_args: (
            FakeModel(),
            0.9,
            0.92,
            {"training_rows": 2, "validation_rows": 1},
        ),
    )

    result = service.run_once()

    assert result.status == "candidate-pending-approval"
    assert result.model_version == "1.0.4"
    assert result.candidate_id
    assert not hasattr(result, "reload_triggered")
    assert version_file.read_text(encoding="utf-8") == original_contents
    candidate_path = version_file.parent / result.model_path
    assert candidate_path.is_file()
    assert not hasattr(service, "_trigger_reload")
