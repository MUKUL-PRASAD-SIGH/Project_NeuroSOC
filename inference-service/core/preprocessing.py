"""Input preprocessing shipped alongside a trained SNN/LNN candidate.

Flow features are heavy-tailed, so MinMax scaling alone squeezes most values into the first few
percent of [0, 1] and the spike encoder cannot tell them apart. Models trained on quantile-transformed
inputs score far better, so the same transform has to run at inference.

A `FeaturePreprocessor` turns the live *raw* vector (columns named by `live_feature_names`) into the
model's input: pick the model's columns by name, MinMax-scale, clip to [0, 1], then apply the quantile
transform. It is saved next to the checkpoint as `<checkpoint>.preproc.pkl`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

PREPROCESSOR_SUFFIX = ".preproc.pkl"


class FeaturePreprocessor:
    def __init__(self, feature_names: list[str], scaler: Any, quantile: Any | None = None) -> None:
        if scaler.n_features_in_ != len(feature_names):
            raise ValueError(
                f"Scaler expects {scaler.n_features_in_} features but {len(feature_names)} names were given."
            )
        self.feature_names = list(feature_names)
        self.scaler = scaler
        self.quantile = quantile

    @staticmethod
    def path_for(checkpoint_path: str | Path) -> Path:
        target = Path(checkpoint_path)
        return target.with_suffix(target.suffix + PREPROCESSOR_SUFFIX)

    def save(self, checkpoint_path: str | Path) -> Path:
        path = self.path_for(checkpoint_path)
        joblib.dump(
            {"feature_names": self.feature_names, "scaler": self.scaler, "quantile": self.quantile},
            path,
        )
        return path

    @classmethod
    def load_for(cls, checkpoint_path: str | Path) -> "FeaturePreprocessor | None":
        path = cls.path_for(checkpoint_path)
        if not path.exists():
            return None
        payload = joblib.load(path)
        return cls(payload["feature_names"], payload["scaler"], payload.get("quantile"))

    def transform(self, raw: np.ndarray, live_feature_names: list[str]) -> np.ndarray:
        """raw: [n_features] or [rows, n_features] in `live_feature_names` order -> [rows, len(self.feature_names)]."""
        matrix = np.atleast_2d(np.asarray(raw, dtype=np.float64))
        if matrix.shape[1] != len(live_feature_names):
            raise RuntimeError(f"Expected {len(live_feature_names)} raw features, got {matrix.shape[1]}.")
        position = {name: index for index, name in enumerate(live_feature_names)}
        missing = [name for name in self.feature_names if name not in position]
        if missing:
            raise RuntimeError(f"Live features are missing columns this model needs: {missing[:5]}")
        selected = matrix[:, [position[name] for name in self.feature_names]]
        scaled = np.clip(self.scaler.transform(selected), 0.0, 1.0)
        if self.quantile is not None:
            scaled = self.quantile.transform(scaled)
        return np.clip(scaled, 0.0, 1.0).astype(np.float32)
