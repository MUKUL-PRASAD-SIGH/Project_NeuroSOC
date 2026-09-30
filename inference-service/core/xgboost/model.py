from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from xgboost import XGBClassifier


CLASS_NAMES = [
    "BENIGN",
    "DDOS",
    "BRUTE_FORCE",
    "RECONNAISSANCE",
    "WEB_ATTACK",
    "BOT",
    "OTHER",
]


def _load_default_feature_names() -> list[str]:
    service_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        Path(os.getenv("FEATURE_COLUMNS_PATH")).expanduser() if os.getenv("FEATURE_COLUMNS_PATH") else None,
        Path("/data/feature_columns.txt"),
        repo_root / "data" / "feature_columns.txt",
        repo_root / "datasets" / "feature_columns.txt",
        service_root / "data" / "feature_columns.txt",
        Path.cwd() / "data" / "feature_columns.txt",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return [line.strip() for line in candidate.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [f"feature_{idx}" for idx in range(80)]


class XGBoostClassifier:
    """XGBoost wrapper for normalized flow vectors.

    A model trained on a subset of the live 80 features (for example the 76 that the CIC datasets
    provide) ships its own column list in `<model>.meta.json` and its own MinMax scaler in
    `<model>.scaler.pkl`. Such a model is fed the live *raw* vector through
    `predict_proba_from_raw`, which picks its columns by name and scales them itself.
    """

    CLASS_NAMES = CLASS_NAMES

    def __init__(self, model_path: str | None = None, feature_names: list[str] | None = None) -> None:
        self.model_path = model_path
        self.feature_names = feature_names or _load_default_feature_names()
        self.model: XGBClassifier | None = None
        self.scaler: Any | None = None
        if model_path and Path(model_path).exists():
            self.load(model_path)

    def _ensure_2d(self, features: np.ndarray) -> np.ndarray:
        array = np.asarray(features, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2:
            raise ValueError("features must be a 1D or 2D array.")
        return array

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("XGBoost model is not loaded.")
        array = self._ensure_2d(features)
        return self.model.predict_proba(array)

    def predict_proba_from_raw(self, raw_vector: np.ndarray, live_feature_names: list[str]) -> np.ndarray:
        """Score a raw (unscaled) live feature vector whose columns are `live_feature_names`."""
        if self.model is None:
            raise RuntimeError("XGBoost model is not loaded.")
        if self.scaler is None:
            raise RuntimeError("This XGBoost model has no scaler; it cannot score raw features.")
        raw = np.asarray(raw_vector, dtype=np.float64).reshape(-1)
        if raw.shape[0] != len(live_feature_names):
            raise RuntimeError(f"Expected {len(live_feature_names)} raw features, got {raw.shape[0]}.")
        position = {name: index for index, name in enumerate(live_feature_names)}
        missing = [name for name in self.feature_names if name not in position]
        if missing:
            raise RuntimeError(f"Live features are missing columns this model needs: {missing[:5]}")
        selected = raw[[position[name] for name in self.feature_names]].reshape(1, -1)
        scaled = np.clip(self.scaler.transform(selected), 0.0, 1.0).astype(np.float32)
        return self.model.predict_proba(scaled)

    def get_top_class(self, features: np.ndarray) -> tuple[str, float]:
        probabilities = self.predict_proba(features)[0]
        best_idx = int(np.argmax(probabilities))
        return self.CLASS_NAMES[best_idx], float(probabilities[best_idx])

    def feature_importance(self) -> dict[str, float]:
        if self.model is None:
            return {}
        booster = self.model.get_booster()
        raw_scores = booster.get_score(importance_type="gain")
        mapped: dict[str, float] = {}
        for raw_name, score in raw_scores.items():
            if raw_name.startswith("f") and raw_name[1:].isdigit():
                feature_idx = int(raw_name[1:])
                name = self.feature_names[feature_idx] if feature_idx < len(self.feature_names) else raw_name
            else:
                name = raw_name
            mapped[name] = float(score)
        return dict(sorted(mapped.items(), key=lambda item: item[1], reverse=True))

    def save(self, path: str | Path) -> None:
        if self.model is None:
            raise RuntimeError("No XGBoost model is available to save.")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(target))
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata_path.write_text(
            json.dumps({"feature_names": self.feature_names}, indent=2),
            encoding="utf-8",
        )

    def load(self, path: str | Path) -> "XGBoostClassifier":
        target = Path(path)
        model = XGBClassifier()
        model.load_model(str(target))
        self.model = model
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.feature_names = metadata.get("feature_names", self.feature_names)
        scaler_path = target.with_suffix(target.suffix + ".scaler.pkl")
        self.scaler = joblib.load(scaler_path) if scaler_path.exists() else None
        if self.scaler is not None and self.scaler.n_features_in_ != len(self.feature_names):
            raise ValueError(
                f"{scaler_path.name} expects {self.scaler.n_features_in_} features but the model lists "
                f"{len(self.feature_names)}."
            )
        return self


if __name__ == "__main__":
    classifier = XGBoostClassifier(model_path="models/xgboost_best.json")
    dummy = np.zeros((1, 80), dtype=np.float32)
    if classifier.model is None:
        print("No model loaded — run training first.")
    else:
        top_class, confidence = classifier.get_top_class(dummy)
        print(f"Top class: {top_class}, confidence: {confidence:.4f}")
