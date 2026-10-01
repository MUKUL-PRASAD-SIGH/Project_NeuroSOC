"""Training must encode classes in the same order inference decodes them."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "retraining-service"))
sys.path.insert(0, str(ROOT / "inference-service"))

from common import CLASS_NAMES, ClassOrderEncoder  # noqa: E402


def test_training_class_order_matches_inference_modules():
    pytest.importorskip("torch")
    pytest.importorskip("xgboost")
    from core.lnn.classifier import CLASS_NAMES as lnn_names
    from core.snn.network import CLASS_NAMES as snn_names
    from core.xgboost.model import CLASS_NAMES as xgb_names

    assert CLASS_NAMES == lnn_names == snn_names == xgb_names


def test_encoder_uses_class_names_order_not_alphabetical():
    encoder = ClassOrderEncoder().fit(CLASS_NAMES)
    labels = ["DDOS", "BENIGN", "BOT", "WEB_ATTACK"]
    assert encoder.transform(labels).tolist() == [CLASS_NAMES.index(label) for label in labels]
    assert list(encoder.classes_) == CLASS_NAMES
    assert encoder.transform(np.array(["DDOS"]))[0] == 1  # alphabetical order would give 3


def test_encoder_rejects_unknown_labels():
    with pytest.raises(ValueError):
        ClassOrderEncoder().transform(["NOT_A_CLASS"])
