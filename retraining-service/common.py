from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split


CLASS_NAMES = [
    "BENIGN",
    "DDOS",
    "BRUTE_FORCE",
    "RECONNAISSANCE",
    "WEB_ATTACK",
    "BOT",
    "OTHER",
]



class ClassOrderEncoder:
    """Encode class names as their index in CLASS_NAMES.

    Inference decodes predictions with CLASS_NAMES[index] (inference-service/core/engine.py,
    core/xgboost/model.py), so training must use the same order. sklearn's LabelEncoder sorts
    names alphabetically, which silently relabels most classes. Same interface as the subset of
    LabelEncoder the training code uses (`fit`, `transform`, `classes_`).
    """

    classes_ = np.asarray(CLASS_NAMES)

    def fit(self, _labels=None) -> "ClassOrderEncoder":
        return self

    def transform(self, labels) -> np.ndarray:
        index = {name: position for position, name in enumerate(CLASS_NAMES)}
        unknown = sorted({str(label) for label in labels} - set(index))
        if unknown:
            raise ValueError(f"Unknown class labels {unknown}; expected a subset of {CLASS_NAMES}.")
        return np.array([index[str(label)] for label in labels], dtype=np.int64)


REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_SERVICE_DIR = REPO_ROOT / "inference-service"
MODELS_DIR = REPO_ROOT / "models"
RESULTS_DIR = REPO_ROOT / "retraining-service" / "results"
DATASET_TRAIN_PATH = REPO_ROOT / "datasets" / "processed" / "unified_train.csv"
DATASET_TEST_PATH = REPO_ROOT / "datasets" / "processed" / "unified_test.csv"
MODEL_VERSION_PATH = MODELS_DIR / "model_version.json"


def add_inference_service_to_path() -> None:
    target = str(INFERENCE_SERVICE_DIR)
    if target not in sys.path:
        sys.path.insert(0, target)


def load_tabular_dataset(csv_path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    frame = pd.read_csv(csv_path)
    if "label" not in frame.columns:
        raise ValueError(f"{csv_path} is missing the 'label' column.")
    feature_names = [column for column in frame.columns if column != "label"]
    features = frame[feature_names].to_numpy(dtype=np.float32)
    labels = frame["label"].astype(str).to_numpy()
    return features, labels, feature_names


def generate_synthetic_dataset(
    n_samples_per_class: int = 24,
    n_features: int = 80,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    centers = np.linspace(0.05, 0.95, len(CLASS_NAMES))
    features: list[np.ndarray] = []
    labels: list[str] = []
    for class_index, class_name in enumerate(CLASS_NAMES):
        base = centers[class_index]
        class_features = rng.normal(loc=base, scale=0.03, size=(n_samples_per_class, n_features))
        class_features[:, class_index % n_features] += 0.12
        features.append(np.clip(class_features, 0.0, 1.0).astype(np.float32))
        labels.extend([class_name] * n_samples_per_class)
    feature_names = [f"feature_{index}" for index in range(n_features)]
    return np.vstack(features), np.asarray(labels), feature_names


def train_val_split(
    features: np.ndarray,
    labels: np.ndarray,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return train_test_split(
        features,
        labels,
        test_size=test_size,
        stratify=labels,
        random_state=random_state,
    )


def subsample_stratified(
    features: np.ndarray,
    labels: np.ndarray,
    max_rows: int,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Keep at most `max_rows` rows, preserving class proportions (0 = keep all)."""
    if max_rows <= 0 or len(features) <= max_rows:
        return features, labels
    keep, _ = train_test_split(
        np.arange(len(features)),
        train_size=max_rows,
        stratify=labels,
        random_state=random_state,
    )
    keep.sort()
    return features[keep], labels[keep]


def balanced_class_weights(encoded_labels: np.ndarray, n_classes: int) -> np.ndarray:
    """Inverse-frequency weights (mean 1 over classes present); absent classes get 1.0."""
    counts = np.bincount(encoded_labels, minlength=n_classes).astype(np.float64)
    present = counts > 0
    weights = np.ones(n_classes, dtype=np.float64)
    weights[present] = counts[present].sum() / (present.sum() * counts[present])
    return weights.astype(np.float32)


def pad_absent_classes(
    features: np.ndarray,
    encoded_labels: np.ndarray,
    sample_weight: np.ndarray | None,
    n_classes: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Append one zero-weight row per class missing from the labels.

    XGBoost's sklearn wrapper needs labels 0..n-1 to all occur, but the model keeps the
    full CLASS_NAMES output (including classes such as OTHER that the data never contains).
    """
    weights = np.ones(len(encoded_labels), dtype=np.float32) if sample_weight is None else sample_weight
    missing = np.setdiff1d(np.arange(n_classes), np.unique(encoded_labels))
    if len(missing) == 0:
        return features, encoded_labels, weights
    return (
        np.vstack([features, np.repeat(features[:1], len(missing), axis=0)]),
        np.concatenate([encoded_labels, missing]),
        np.concatenate([weights, np.zeros(len(missing), dtype=np.float32)]),
    )


def make_sliding_windows(
    features: np.ndarray,
    labels: np.ndarray,
    window_size: int = 20,
) -> tuple[np.ndarray, np.ndarray]:
    if len(features) < window_size:
        raise ValueError(f"Need at least {window_size} samples to build sliding windows.")
    windows = []
    window_labels = []
    for start in range(0, len(features) - window_size + 1):
        end = start + window_size
        windows.append(features[start:end])
        window_labels.append(labels[end - 1])
    return np.stack(windows).astype(np.float32), np.asarray(window_labels)


def _increment_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "0.0.1"
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def candidate_artifact_path(
    key: str,
    requested_path: Path,
    version_file: Path = MODEL_VERSION_PATH,
) -> Path:
    if key not in {"snn", "lnn", "xgb"}:
        raise ValueError(f"Unsupported model key: {key}")
    requested_path = Path(requested_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    candidate_dir = Path(version_file).parent / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    return candidate_dir / (
        f"{key}_candidate_{timestamp}_{uuid.uuid4().hex[:8]}{requested_path.suffix}"
    )


def write_model_candidate(
    key: str,
    artifact_path: Path,
    validation_f1: float,
    version_file: Path = MODEL_VERSION_PATH,
    metrics: dict | None = None,
) -> dict:
    if key not in {"snn", "lnn", "xgb"}:
        raise ValueError(f"Unsupported model key: {key}")
    version_file = Path(version_file)
    candidate_dir = (version_file.parent / "candidates").resolve()
    artifact_path = Path(artifact_path).resolve()
    if not artifact_path.is_relative_to(candidate_dir) or not artifact_path.is_file():
        raise ValueError("Candidate artifacts must be saved as files under the model candidates directory.")

    if version_file.exists():
        payload = json.loads(version_file.read_text(encoding="utf-8"))
    else:
        payload = {
            "version": "0.0.0",
            "snn": None,
            "lnn": None,
            "xgb": None,
            "validation_f1": {"snn": None, "lnn": None, "xgb": None},
        }

    active_version = str(payload.get("version", "0.0.0"))
    candidate_id = artifact_path.stem
    candidate = {
        "candidate_id": candidate_id,
        "status": "pending_approval",
        "model_key": key,
        "base_model_version": active_version,
        "proposed_version": _increment_version(active_version),
        "artifact_path": artifact_path.relative_to(version_file.parent.resolve()).as_posix(),
        "validation_f1": float(validation_f1),
        "metrics": metrics or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = candidate_dir / f"{candidate_id}.manifest.json"
    temporary_path = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
        temporary_path.replace(manifest_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return candidate
