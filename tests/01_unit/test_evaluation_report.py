from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_evaluate_script():
    module_name = "neurosoc_evaluate_active_model_for_tests"
    spec = importlib.util.spec_from_file_location(
        module_name, REPO_ROOT / "retraining-service" / "scripts" / "evaluate_active_model.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_produces_a_well_formed_report():
    evaluate_script = _load_evaluate_script()
    report = evaluate_script.evaluate()

    assert report["evidence_type"] == "synthetic_development_only"
    assert "not a public IDS dataset" in report["note"]
    assert report["holdout_size"] > 0

    labels = report["confusion_matrix"]["labels"]
    matrix = report["confusion_matrix"]["matrix"]
    assert len(matrix) == len(labels)
    assert all(len(row) == len(labels) for row in matrix)
    assert sum(sum(row) for row in matrix) == report["holdout_size"]

    for class_name in labels:
        assert class_name in report["class_report"]
        assert 0.0 <= report["false_positive_rate_by_class"][class_name] <= 1.0

    assert "macro avg" in report["class_report"]
