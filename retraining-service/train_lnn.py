from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from common import (
    ClassOrderEncoder,
    CLASS_NAMES,
    DATASET_TRAIN_PATH,
    MODEL_VERSION_PATH,
    add_inference_service_to_path,
    balanced_class_weights,
    candidate_artifact_path,
    generate_synthetic_dataset,
    load_tabular_dataset,
    make_sliding_windows,
    subsample_stratified,
    train_val_split,
    write_model_candidate,
)

add_inference_service_to_path()

from core.lnn.classifier import LNNClassifier
from core.lnn.reservoir import LiquidReservoir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the NeuroShield LNN readout.")
    parser.add_argument("--dataset", type=Path, default=DATASET_TRAIN_PATH)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("models/lnn_best.pt"),
        help="Filename hint for candidate output; artifacts are always written under the model candidates directory.",
    )
    parser.add_argument("--version-file", type=Path, default=MODEL_VERSION_PATH)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--window-size", type=int, default=20)
    parser.add_argument("--reservoir-size", type=int, default=500)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--sequence-dataset",
        type=Path,
        default=None,
        help="sequences.npz from datasets/build_sequences.py (real windows, block-level train/test split).",
    )
    parser.add_argument("--max-rows", type=int, default=0, help="Stratified row cap before windowing (0 = all).")
    parser.add_argument("--class-weight", action="store_true", help="Weight the loss by inverse class frequency.")
    return parser.parse_args()


def prepare_dataset(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if args.smoke_test or not args.dataset.exists():
        return generate_synthetic_dataset(n_samples_per_class=22)
    return load_tabular_dataset(args.dataset)


def evaluate(
    reservoir: LiquidReservoir,
    classifier: LNNClassifier,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, float]:
    classifier.eval()
    predictions: list[int] = []
    targets: list[int] = []
    with torch.no_grad():
        for batch_sequences, batch_labels in loader:
            sequence_tensor = batch_sequences.to(device).transpose(0, 1)
            states, _ = reservoir(sequence_tensor)
            logits = classifier(states)
            predictions.extend(torch.argmax(logits, dim=1).cpu().tolist())
            targets.extend(batch_labels.cpu().tolist())
    accuracy = accuracy_score(targets, predictions)
    f1 = f1_score(targets, predictions, average="macro")
    return accuracy, f1


def main() -> int:
    args = parse_args()
    device = torch.device(args.device)
    if args.sequence_dataset is not None and not args.smoke_test:
        with np.load(args.sequence_dataset, allow_pickle=False) as data:
            x_train, y_train = data["x_train"], data["y_train"]
            x_val, y_val = data["x_test"], data["y_test"]
            feature_names = [str(name) for name in data["feature_names"]]
            args.window_size = int(data["window_size"])
        if args.max_rows:
            x_train, y_train = subsample_stratified(x_train, y_train, args.max_rows)
        print(f"[INFO] Loaded sequences {args.sequence_dataset}: train {x_train.shape}, val {x_val.shape}")
    else:
        features, labels, feature_names = prepare_dataset(args)
        features, labels = subsample_stratified(features, labels, args.max_rows)
        windows, window_labels = make_sliding_windows(features, labels, window_size=args.window_size)
        x_train, x_val, y_train, y_val = train_val_split(windows, window_labels)

    label_encoder = ClassOrderEncoder()
    label_encoder.fit(CLASS_NAMES)
    y_train_encoded = label_encoder.transform(y_train)
    y_val_encoded = label_encoder.transform(y_val)

    train_loader = DataLoader(
        TensorDataset(torch.tensor(x_train, dtype=torch.float32), torch.tensor(y_train_encoded, dtype=torch.long)),
        batch_size=args.batch_size,
        shuffle=True,
    )
    val_loader = DataLoader(
        TensorDataset(torch.tensor(x_val, dtype=torch.float32), torch.tensor(y_val_encoded, dtype=torch.long)),
        batch_size=args.batch_size,
    )

    reservoir = LiquidReservoir(
        input_size=x_train.shape[2],
        reservoir_size=128 if args.smoke_test else args.reservoir_size,
    ).to(device)
    assert not any(parameter.requires_grad for parameter in reservoir.parameters())

    classifier = LNNClassifier(reservoir_size=reservoir.reservoir_size).to(device)
    optimizer = torch.optim.Adam(classifier.parameters(), lr=args.lr)
    class_weight = None
    if args.class_weight:
        class_weight = torch.tensor(balanced_class_weights(y_train_encoded, len(CLASS_NAMES)), device=device)
    criterion = nn.CrossEntropyLoss(weight=class_weight)

    best_f1 = -1.0
    best_payload: dict | None = None
    epochs = 2 if args.smoke_test else args.epochs

    for epoch in range(epochs):
        classifier.train()
        running_loss = 0.0
        for batch_sequences, batch_labels in train_loader:
            optimizer.zero_grad()
            sequence_tensor = batch_sequences.to(device).transpose(0, 1)
            states, _ = reservoir(sequence_tensor)
            logits = classifier(states)
            loss = criterion(logits, batch_labels.to(device))
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item())

        accuracy, f1 = evaluate(reservoir, classifier, val_loader, device)
        print(
            json.dumps(
                {
                    "epoch": epoch + 1,
                    "loss": round(running_loss / max(len(train_loader), 1), 4),
                    "val_accuracy": round(accuracy, 4),
                    "val_f1_macro": round(f1, 4),
                    "spectral_radius": round(reservoir.compute_spectral_radius(), 4),
                }
            )
        )
        if f1 > best_f1:
            best_f1 = f1
            best_payload = {
                "reservoir_config": {
                    "input_size": reservoir.input_size,
                    "reservoir_size": reservoir.reservoir_size,
                    "spectral_radius": reservoir.target_spectral_radius,
                    "leak_rate": reservoir.leak_rate,
                    "sparsity": reservoir.sparsity,
                    "seed": reservoir.seed,
                    "feature_names": feature_names,
                    "window_size": args.window_size,
                },
                "reservoir_state": reservoir.state_dict(),
                "classifier_config": {
                    "reservoir_size": classifier.reservoir_size,
                    "n_classes": classifier.n_classes,
                },
                "classifier_state": classifier.state_dict(),
            }

    if best_payload is None:
        raise RuntimeError("Training did not produce a valid LNN checkpoint.")

    candidate_path = candidate_artifact_path("lnn", args.model_path, args.version_file)
    torch.save(best_payload, candidate_path)
    candidate = write_model_candidate(
        "lnn",
        candidate_path,
        best_f1,
        args.version_file,
        metrics={"validation_f1": float(best_f1)},
    )
    print(f"[PASS] Saved LNN candidate checkpoint to {candidate_path}")
    print(f"[INFO] Candidate {candidate['candidate_id']} is inactive; active model remains {candidate['base_model_version']}.")
    print(f"[PASS] Best validation F1: {best_f1:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
