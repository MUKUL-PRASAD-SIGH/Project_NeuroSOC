"""Per-class evaluation of an SNN candidate on a random sample of datasets/processed/unified_test.csv."""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import classification_report, confusion_matrix

from common import DATASET_TEST_PATH, ClassOrderEncoder, add_inference_service_to_path

add_inference_service_to_path()

from core.snn.encoder import SpikeEncoder
from core.snn.network import SNNAnomalyDetector


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--test-csv", type=Path, default=DATASET_TEST_PATH)
    parser.add_argument("--rows", type=int, default=8000, help="Random sample (keeps the natural class mix).")
    parser.add_argument("--sampled-spikes", action="store_true", help="Encode with random spikes instead of deterministic ones.")
    args = parser.parse_args()

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = checkpoint["config"]
    model = SNNAnomalyDetector(input_size=config["input_size"], hidden_sizes=list(config["hidden_sizes"]), n_classes=config["n_classes"])
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    encoder = SpikeEncoder(n_features=config["n_features"], n_neurons_per_feature=config["input_size"] // config["n_features"], T=config["timesteps"])
    encode = encoder.encode if args.sampled_spikes else encoder.encode_deterministic

    frame = pd.read_csv(args.test_csv).sample(n=args.rows, random_state=0)
    x = frame.drop(columns="label").to_numpy(np.float32)
    preprocessor_path = args.checkpoint.with_suffix(args.checkpoint.suffix + ".preproc.pkl")
    if preprocessor_path.exists():
        quantile = joblib.load(preprocessor_path)["quantile"]
        if quantile is not None:
            x = quantile.transform(x).astype(np.float32)
    target = ClassOrderEncoder().transform(frame["label"].to_numpy())

    predictions: list[int] = []
    with torch.no_grad():
        for start in range(0, len(x), 256):
            predictions.extend(model(encode(x[start:start + 256]))[0].argmax(dim=1).tolist())
    predictions = np.array(predictions)
    encoder_labels = ClassOrderEncoder()
    present = sorted(set(target) | set(predictions))
    names = [str(encoder_labels.classes_[index]) for index in present]
    print(classification_report(target, predictions, labels=present, target_names=names, digits=3, zero_division=0))
    print("confusion matrix (rows = true, cols = predicted):", names)
    print(confusion_matrix(target, predictions, labels=present))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
