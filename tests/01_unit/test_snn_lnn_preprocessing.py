"""SNN/LNN candidates ship a preprocessor; the engine must use it on live raw vectors."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from sklearn.preprocessing import MinMaxScaler, QuantileTransformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "inference-service"))

from core.behavioral import BehavioralProfiler  # noqa: E402
from core.engine import DecisionEngine  # noqa: E402
from core.lnn.classifier import LNNClassifier  # noqa: E402
from core.lnn.reservoir import LiquidReservoir  # noqa: E402
from core.preprocessing import FeaturePreprocessor  # noqa: E402
from core.snn.network import SNNAnomalyDetector  # noqa: E402

LIVE = [line.strip() for line in (ROOT / "data" / "feature_columns.txt").read_text().splitlines() if line.strip()]
MODEL_COLUMNS = LIVE[:6] + LIVE[8:12]  # 10 columns; skips two live columns the model never sees
IGNORED = LIVE[6:8]


def _fit_preprocessor(rng) -> FeaturePreprocessor:
    raw = rng.uniform(0, 1000, size=(300, len(MODEL_COLUMNS))) ** 2  # heavy-tailed on purpose
    scaler = MinMaxScaler().fit(raw)
    quantile = QuantileTransformer(n_quantiles=50, output_distribution="uniform").fit(scaler.transform(raw))
    return FeaturePreprocessor(MODEL_COLUMNS, scaler, quantile)


def test_preprocessor_selects_by_name_and_ignores_other_columns():
    pre = _fit_preprocessor(np.random.default_rng(0))
    live = np.random.default_rng(1).uniform(0, 1e6, size=len(LIVE))
    out = pre.transform(live, LIVE)
    assert out.shape == (1, len(MODEL_COLUMNS)) and out.min() >= 0 and out.max() <= 1

    changed = live.copy()
    changed[[LIVE.index(name) for name in IGNORED]] += 99999.0
    assert np.allclose(pre.transform(changed, LIVE), out)


def test_preprocessor_reports_missing_columns():
    pre = _fit_preprocessor(np.random.default_rng(0))
    with pytest.raises(RuntimeError):
        pre.transform(np.zeros(3), ["a", "b", "c"])


@pytest.fixture()
def engine_with_candidates(tmp_path):
    rng = np.random.default_rng(3)
    pre = _fit_preprocessor(rng)

    snn = SNNAnomalyDetector(input_size=len(MODEL_COLUMNS) * 5, hidden_sizes=[16, 8], n_classes=7)
    snn_path = tmp_path / "snn.pt"
    torch.save(
        {"config": {"input_size": snn.input_size, "hidden_sizes": [16, 8], "n_classes": 7, "timesteps": 10,
                    "n_features": len(MODEL_COLUMNS), "feature_names": MODEL_COLUMNS},
         "state_dict": snn.state_dict()},
        snn_path,
    )
    pre.save(snn_path)

    reservoir = LiquidReservoir(input_size=len(MODEL_COLUMNS), reservoir_size=32)
    classifier = LNNClassifier(reservoir_size=32)
    lnn_path = tmp_path / "lnn.pt"
    torch.save(
        {"reservoir_config": {"input_size": len(MODEL_COLUMNS), "reservoir_size": 32, "spectral_radius": 0.9,
                              "leak_rate": 0.3, "sparsity": 0.1, "seed": 42, "feature_names": MODEL_COLUMNS,
                              "window_size": 20},
         "reservoir_state": reservoir.state_dict(),
         "classifier_config": {"reservoir_size": 32, "n_classes": 7},
         "classifier_state": classifier.state_dict()},
        lnn_path,
    )
    pre.save(lnn_path)

    version_path = tmp_path / "model_version.json"
    version_path.write_text(json.dumps({"version": "t", "snn": str(snn_path), "lnn": str(lnn_path),
                                        "xgb": None, "validation_f1": {}}))
    return DecisionEngine(model_version_path=version_path, behavioral_profiler=BehavioralProfiler(),
                          start_model_monitor=False)


def test_loading_a_subset_lnn_does_not_replace_the_live_feature_contract(engine_with_candidates):
    engine = engine_with_candidates
    assert engine.feature_names == LIVE  # used to be overwritten with the model's 10 names
    assert engine.snn_model.preprocessor is not None and engine.lnn_classifier.preprocessor is not None


def test_engine_scores_raw_live_vector_and_falls_back_without_it(engine_with_candidates):
    engine = engine_with_candidates
    raw = np.random.default_rng(5).uniform(0, 1e5, size=len(LIVE)).tolist()

    verdict = engine.analyze_session({"session_id": "s", "user_id": "u", "flow_features": [0.0] * len(LIVE),
                                      "raw_features": raw})
    assert verdict.lnn_class != "INCONCLUSIVE" and 0.0 <= verdict.snn_score <= 1.0

    fallback = engine.analyze_session({"session_id": "s2", "user_id": "u", "flow_features": [0.0] * len(LIVE)})
    assert fallback.lnn_class != "INCONCLUSIVE" and 0.0 <= fallback.snn_score <= 1.0


def test_norse_checkpoint_without_norse_falls_back_instead_of_crashing(tmp_path, monkeypatch):
    """Promoting a Norse-trained SNN must not stop an image without Norse from starting."""
    pytest.importorskip("norse")
    import core.engine as engine_module

    snn = SNNAnomalyDetector(input_size=len(MODEL_COLUMNS) * 5, hidden_sizes=[16, 8], n_classes=7)
    snn_path = tmp_path / "snn.pt"
    torch.save({"config": {"input_size": snn.input_size, "hidden_sizes": [16, 8], "n_classes": 7,
                           "timesteps": 10, "n_features": len(MODEL_COLUMNS)},
                "state_dict": snn.state_dict()}, snn_path)
    assert any(key.endswith("input_weights") for key in snn.state_dict())  # really a Norse checkpoint

    monkeypatch.setattr(engine_module, "LIFRecurrentCell", None)  # the docker image: Norse not installed
    version_path = tmp_path / "model_version.json"
    version_path.write_text(json.dumps({"version": "t", "snn": str(snn_path), "xgb": None, "validation_f1": {}}))
    engine = DecisionEngine(model_version_path=version_path, behavioral_profiler=BehavioralProfiler(),
                            start_model_monitor=False)
    assert engine.snn_model is None
    verdict = engine.analyze_session({"session_id": "s", "user_id": "u", "flow_features": [0.0] * len(LIVE)})
    assert 0.0 <= verdict.snn_score <= 1.0  # heuristic
