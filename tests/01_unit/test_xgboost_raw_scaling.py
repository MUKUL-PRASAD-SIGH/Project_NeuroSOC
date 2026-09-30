"""An XGBoost model trained on a column subset must score the live 80-wide raw vector."""
import sys
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.preprocessing import MinMaxScaler

pytest.importorskip("xgboost")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inference-service"))

from core.xgboost.model import CLASS_NAMES, XGBoostClassifier  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

LIVE = [f"f{i}" for i in range(10)]
DROPPED = ["f3", "f7"]
MODEL_COLUMNS = [name for name in LIVE if name not in DROPPED]


@pytest.fixture()
def saved_model(tmp_path):
    rng = np.random.default_rng(0)
    raw = rng.uniform(0, 1000, size=(400, len(MODEL_COLUMNS)))
    labels = np.arange(400) % len(CLASS_NAMES)
    scaler = MinMaxScaler().fit(raw)
    estimator = XGBClassifier(n_estimators=5, objective="multi:softprob", num_class=len(CLASS_NAMES))
    estimator.fit(scaler.transform(raw), labels)
    wrapper = XGBoostClassifier(feature_names=MODEL_COLUMNS)
    wrapper.model = estimator
    path = tmp_path / "xgb.json"
    wrapper.save(path)
    joblib.dump(scaler, path.with_suffix(path.suffix + ".scaler.pkl"))
    return path


def test_scores_live_vector_and_ignores_dropped_columns(saved_model):
    model = XGBoostClassifier().load(saved_model)
    live = np.random.default_rng(1).uniform(0, 1000, size=len(LIVE))
    probabilities = model.predict_proba_from_raw(live, LIVE)
    assert probabilities.shape == (1, len(CLASS_NAMES))

    changed = live.copy()
    changed[[LIVE.index(name) for name in DROPPED]] += 12345.0
    assert np.allclose(model.predict_proba_from_raw(changed, LIVE), probabilities)


def test_missing_live_column_is_reported(saved_model):
    model = XGBoostClassifier().load(saved_model)
    with pytest.raises(RuntimeError):
        model.predict_proba_from_raw(np.zeros(9), LIVE[:9] + ["other"])


def test_model_without_scaler_refuses_raw_input(saved_model):
    saved_model.with_suffix(saved_model.suffix + ".scaler.pkl").unlink()
    model = XGBoostClassifier().load(saved_model)
    with pytest.raises(RuntimeError):
        model.predict_proba_from_raw(np.zeros(len(LIVE)), LIVE)
