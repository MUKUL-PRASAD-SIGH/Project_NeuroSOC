"""Pinned library pairs that are known to break when combined."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pin(path: Path, name: str) -> tuple[int, ...] | None:
    match = re.search(rf"^{re.escape(name)}==([\d.]+)\s*$", path.read_text(), re.M)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def test_xgboost_pin_works_with_the_pinned_scikit_learn():
    """xgboost < 2.1.4 cannot use scikit-learn >= 1.6: XGBClassifier.load_model raises
    "'super' object has no attribute '__sklearn_tags__'", so the inference service could not load any model."""
    for service in ("inference-service", "retraining-service"):
        path = ROOT / service / "requirements.txt"
        xgboost, sklearn = _pin(path, "xgboost"), _pin(path, "scikit-learn")
        assert xgboost and sklearn, f"{service}: pin both xgboost and scikit-learn"
        if sklearn >= (1, 6):
            assert xgboost >= (2, 1, 4), f"{service}: xgboost {xgboost} is incompatible with scikit-learn {sklearn}"


def test_services_that_share_a_model_format_pin_the_same_xgboost():
    assert _pin(ROOT / "inference-service" / "requirements.txt", "xgboost") == \
        _pin(ROOT / "retraining-service" / "requirements.txt", "xgboost")
