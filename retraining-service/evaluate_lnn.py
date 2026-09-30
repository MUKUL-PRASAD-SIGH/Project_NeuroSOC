"""Per-class evaluation of an LNN candidate on the held-out windows in sequences.npz."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix

from common import CLASS_NAMES, ClassOrderEncoder, add_inference_service_to_path

add_inference_service_to_path()

from core.lnn.classifier import LNNClassifier
from core.lnn.reservoir import LiquidReservoir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--sequences", type=Path, default=Path("../datasets/processed/sequences.npz"))
    parser.add_argument("--batch-size", type=int, default=512)
    args = parser.parse_args()

    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = payload["reservoir_config"]
    reservoir = LiquidReservoir(**{key: config[key] for key in (
        "input_size", "reservoir_size", "spectral_radius", "leak_rate", "sparsity", "seed")})
    reservoir.load_state_dict(payload["reservoir_state"])
    classifier = LNNClassifier(**payload["classifier_config"])
    classifier.load_state_dict(payload["classifier_state"])
    reservoir.eval()
    classifier.eval()

    with np.load(args.sequences, allow_pickle=False) as data:
        x, y = data["x_test"], data["y_test"]
    # Same encoding as the training scripts (and as inference): index in CLASS_NAMES.
    encoder = ClassOrderEncoder().fit(CLASS_NAMES)
    preprocessor_path = args.checkpoint.with_suffix(args.checkpoint.suffix + ".preproc.pkl")
    if preprocessor_path.exists():  # windows in sequences.npz are MinMax-scaled; models trained with the quantile step need it
        import joblib

        quantile = joblib.load(preprocessor_path)["quantile"]
        if quantile is not None:
            x = quantile.transform(x.reshape(-1, x.shape[2])).reshape(x.shape).astype(np.float32)
    target = encoder.transform(y)
    predictions = []
    with torch.no_grad():
        for start in range(0, len(x), args.batch_size):
            batch = torch.tensor(x[start:start + args.batch_size]).transpose(0, 1)
            states, _ = reservoir(batch)
            predictions.extend(classifier(states).argmax(dim=1).tolist())
    predictions = np.array(predictions)

    present = sorted(set(target) | set(predictions))
    names = [str(encoder.classes_[index]) for index in present]
    print(classification_report(target, predictions, labels=present, target_names=names, digits=3, zero_division=0))
    print("confusion matrix (rows = true, cols = predicted):", names)
    print(confusion_matrix(target, predictions, labels=present))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
