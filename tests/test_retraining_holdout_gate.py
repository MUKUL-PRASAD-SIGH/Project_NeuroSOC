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
import common as retraining_common  # noqa: E402


def load_retraining_main():
    module_name = "neurosoc_retraining_holdout_gate_main_for_tests"
    module_path = RETRAINING_DIR / "main.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_shared_retraining_database_requires_verified_tls(monkeypatch):
    retraining_main = load_retraining_main()
    monkeypatch.setattr(retraining_main, "APP_ENV", "production")
    repository = retraining_main.PostgresFeedbackRepository(
        "postgresql://retrainer:secret@db.example.com:5432/neurosoc"
    )

    with pytest.raises(RuntimeError, match="sslmode=verify-full"):
        repository.connect()


def test_holdout_set_is_created_once_and_is_deterministic(tmp_path):
    retraining_main = load_retraining_main()
    holdout_path = tmp_path / "holdout_eval.json"

    features_a, labels_a = retraining_main.load_or_create_holdout_set(path=holdout_path)
    assert holdout_path.exists()
    features_b, labels_b = retraining_main.load_or_create_holdout_set(path=holdout_path)

    np.testing.assert_array_equal(features_a, features_b)
    np.testing.assert_array_equal(labels_a, labels_b)


def test_holdout_set_rejects_tampered_content(tmp_path):
    retraining_main = load_retraining_main()
    holdout_path = tmp_path / "holdout_eval.json"
    retraining_main.load_or_create_holdout_set(path=holdout_path)

    payload = json.loads(holdout_path.read_text(encoding="utf-8"))
    payload["labels"][0] = "TAMPERED"
    holdout_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        retraining_main.load_or_create_holdout_set(path=holdout_path)
        assert False, "expected a content-hash mismatch to raise"
    except ValueError as exc:
        assert "content-hash" in str(exc)


def test_first_candidate_passes_even_when_stale_manifest_f1_is_1_0(tmp_path, monkeypatch):
    """Reproduces the historical bug: model_version.json says xgb F1 == 1.0 (an overfit
    number from a 137-row run), and an honest new candidate must still be able to pass
    because there is no previous held-out baseline to compare against yet."""
    retraining_main = load_retraining_main()
    version_file = tmp_path / "models" / "model_version.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(
        json.dumps({"version": "1.0.1", "xgb": "xgb_active.json", "validation_f1": {"xgb": 1.0}}),
        encoding="utf-8",
    )

    sample = retraining_main.FeedbackSample(id=1, session_id="s1", features=[0.0] * 80, label="BENIGN")

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
        lambda *_args: (FakeModel(), 0.55, 0.6, {"training_rows": 2, "validation_rows": 1}),
    )
    # A real, honestly-evaluated candidate scores well below the stale manifest's 1.0.
    monkeypatch.setattr(service, "_evaluate_on_holdout", lambda _wrapper: 0.7)

    result = service.run_once()

    assert result.status == "candidate-pending-approval"
    state = retraining_main.RetrainingState.load(service.state_file)
    assert state.last_holdout_f1 == 0.7


def test_second_worse_candidate_is_rejected_against_the_recorded_holdout_baseline(tmp_path, monkeypatch):
    retraining_main = load_retraining_main()
    version_file = tmp_path / "models" / "model_version.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(
        json.dumps({"version": "1.0.1", "xgb": "xgb_active.json", "validation_f1": {"xgb": 1.0}}),
        encoding="utf-8",
    )
    state_file = tmp_path / "retraining_state.json"
    retraining_main.RetrainingState(last_holdout_f1=0.8, last_seen_feedback_id=1).save(state_file)

    sample = retraining_main.FeedbackSample(id=2, session_id="s2", features=[0.0] * 80, label="BENIGN")

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
        state_file=state_file,
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
        lambda *_args: (FakeModel(), 0.5, 0.6, {"training_rows": 2, "validation_rows": 1}),
    )
    monkeypatch.setattr(service, "_evaluate_on_holdout", lambda _wrapper: 0.6)

    result = service.run_once()

    assert result.status == "skipped"
    state_after = retraining_main.RetrainingState.load(state_file)
    # The baseline is untouched by a rejected candidate.
    assert state_after.last_holdout_f1 == 0.8
