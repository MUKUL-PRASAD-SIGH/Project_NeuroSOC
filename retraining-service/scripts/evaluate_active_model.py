"""Per-class evaluation report for the currently active XGBoost model.

IMPORTANT — read before citing this report anywhere:
This evaluates the active model against a fixed, seeded SYNTHETIC held-out set (the exact
same generator retraining's regression gate uses, see retraining-service/main.py
load_or_create_holdout_set()). There is no public IDS dataset (e.g. CIC-IDS2017) bundled in
this repo. This is development evidence only, consistent with PRODUCTION_BUILD_PLAN.md's
"report only existing evidence" rule — it is NOT evidence of real-world detection
performance. A production release needs an approved, versioned, real dataset with full
provenance (see PRODUCTION_BUILD_PLAN.md T032-T037).

Run: python retraining-service/scripts/evaluate_active_model.py
Writes: retraining-service/results/evaluation_report.json
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix

RETRAINING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RETRAINING_DIR))
from common import CLASS_NAMES, RESULTS_DIR, add_inference_service_to_path  # noqa: E402

add_inference_service_to_path()
from core.engine import DecisionEngine  # noqa: E402


def _load_retraining_main():
    # Every service in this repo names its entrypoint main.py; a bare `from main import ...`
    # would silently resolve to whatever service's main.py another already-imported module
    # cached under sys.modules["main"] (this script is also exercised from the shared pytest
    # session via tests/test_evaluation_report.py). Load it under a private name instead.
    module_name = "neurosoc_retraining_main_for_evaluate_script"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, RETRAINING_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


load_or_create_holdout_set = _load_retraining_main().load_or_create_holdout_set


def evaluate() -> dict:
    # Reuses DecisionEngine._run_xgb -- the exact function production inference calls --
    # instead of re-implementing legacy-vs-current model dispatch here, so this report can't
    # silently drift from what the running service actually does.
    engine = DecisionEngine(start_model_monitor=False)
    features, labels = load_or_create_holdout_set()

    predictions = []
    for row in features:
        predicted_label, _confidence = engine._run_xgb(np.asarray(row, dtype=np.float32), None, {})
        predictions.append(predicted_label if predicted_label in CLASS_NAMES else "OTHER")

    labels_list = list(labels)
    report = classification_report(
        labels_list, predictions, labels=list(CLASS_NAMES), output_dict=True, zero_division=0
    )
    matrix = confusion_matrix(labels_list, predictions, labels=list(CLASS_NAMES)).tolist()

    predictions_arr = np.asarray(predictions)
    labels_arr = np.asarray(labels_list)
    fp_rates: dict[str, float] = {}
    for class_name in CLASS_NAMES:
        predicted_positive = predictions_arr == class_name
        actual_negative = labels_arr != class_name
        false_positives = int(np.sum(predicted_positive & actual_negative))
        total_negative = int(np.sum(actual_negative))
        fp_rates[class_name] = false_positives / total_negative if total_negative else 0.0

    holdout_path = RESULTS_DIR / "holdout_eval.json"
    dataset_hash = None
    if holdout_path.exists():
        dataset_hash = json.loads(holdout_path.read_text(encoding="utf-8")).get("content_hash")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_type": "synthetic_development_only",
        "note": (
            "Evaluated against a fixed, seeded synthetic held-out set "
            "(retraining-service/results/holdout_eval.json), not a public IDS dataset. "
            "Not evidence of real-world detection performance. The active model's own "
            "training data predates this benchmark and is not known to share its "
            "distribution, so a low score here reflects an out-of-distribution transfer "
            "gap, not necessarily the model's real-world behavior -- see "
            "PRODUCTION_BUILD_PLAN.md T032-T037 for what a trustworthy evaluation needs."
        ),
        "model_version": str(engine.current_model_version),
        "dataset_hash": dataset_hash,
        "holdout_size": len(labels_list),
        "class_report": report,
        "confusion_matrix": {"labels": list(CLASS_NAMES), "matrix": matrix},
        "false_positive_rate_by_class": fp_rates,
    }


def main() -> None:
    report = evaluate()
    # retraining-service/results/ is gitignored (operational, regenerated-per-deployment
    # artifacts); this report is committed evidence, so it lives in its own tracked folder.
    output_path = RETRAINING_DIR / "evaluation" / "evaluation_report.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")
    print(json.dumps(report["class_report"]["macro avg"], indent=2))


if __name__ == "__main__":
    main()
