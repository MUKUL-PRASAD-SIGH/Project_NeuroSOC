"""Build windowed flow sequences for the LNN from the raw CIC files.

preprocess.py shuffles and subsamples flows, which destroys any ordering. Here each file is read
in order and cut into non-overlapping windows of consecutive flows, so the LNN sees flows as a
stream. Caveats worth knowing:

* CICIDS2017 CSVs have no timestamps or IPs, so "order" is file order. Labels are interleaved
  (average run of 20-57 flows), i.e. a window is a slice of the traffic stream, not one entity.
* Windows are labelled with the label of their last flow (same as make_sliding_windows).
  They overlap (stride < window) so rare attack classes keep enough windows.
* Train and test are split by *blocks* of consecutive rows; a window that would straddle
  two blocks is dropped, so no row is ever in both train and test.

Uses the contract and scaler written by preprocess.py (datasets/feature_columns.txt, scaler.pkl).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import preprocess as pre

DEFAULT_OUTPUT = pre.DEFAULT_PROCESSED_DIR / "sequences.npz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build windowed flow sequences for the LNN.")
    parser.add_argument("--raw-dir", type=Path, default=pre.DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scaler-path", type=Path, default=pre.DEFAULT_SCALER_PATH)
    parser.add_argument("--feature-columns-path", type=Path, default=pre.DEFAULT_FEATURE_COLUMNS_PATH)
    parser.add_argument("--window-size", type=int, default=20)
    parser.add_argument("--stride", type=int, default=4, help="Rows between window starts.")
    parser.add_argument("--block-rows", type=int, default=1000, help="Rows per train/test block.")
    parser.add_argument("--max-windows-per-file-label", type=int, default=2500)
    parser.add_argument(
        "--limit-2019-rows",
        type=int,
        default=250_000,
        help="Only read this many leading rows of files under a '2019' directory (0 = all).",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=pre.DEFAULT_RANDOM_STATE)
    return parser.parse_args()


def read_file_in_order(path: Path, feature_names: list[str], row_limit: int) -> tuple[pd.DataFrame, np.ndarray]:
    """Return (features in contract order, labels) for one file, in file order."""
    parts: list[pd.DataFrame] = []
    rows = 0
    for chunk in pre.iter_file_chunks(path):
        processed = pre.preprocess_chunk(chunk, path)
        if processed is None or processed.empty:
            continue
        parts.append(processed)
        rows += len(processed)
        if row_limit and rows >= row_limit:
            break
    if not parts:
        return pd.DataFrame(columns=feature_names), np.array([], dtype=str)
    frame = pd.concat(parts, ignore_index=True)
    if row_limit:
        frame = frame.iloc[:row_limit]
    labels = frame["label"].astype(str).to_numpy()
    features = frame.reindex(columns=feature_names).replace([np.inf, -np.inf], np.nan)
    return features, labels


def main() -> int:
    args = parse_args()
    feature_names = [line.strip() for line in args.feature_columns_path.read_text().splitlines() if line.strip()]
    scaler = joblib.load(args.scaler_path)
    if scaler.n_features_in_ != len(feature_names):
        print(f"[ERROR] scaler expects {scaler.n_features_in_} features but the contract has {len(feature_names)}.")
        return 1
    rng = np.random.default_rng(args.random_state)
    window = args.window_size

    train_x: list[np.ndarray] = []
    train_y: list[np.ndarray] = []
    test_x: list[np.ndarray] = []
    test_y: list[np.ndarray] = []

    for path in pre.find_input_files(args.raw_dir):
        limit = args.limit_2019_rows if "2019" in str(path) else 0
        print(f"[INFO] Reading {path.name}")
        features, labels = read_file_in_order(path, feature_names, limit)
        n_rows = len(labels)
        starts = np.arange(0, n_rows - window + 1, args.stride)
        if len(starts) == 0:
            print(f"[WARN] {path.name}: too few rows for a window, skipping")
            continue
        ends = starts + window - 1
        y = labels[ends]  # label of the last flow
        block_ids = ends // args.block_rows
        keep = starts // args.block_rows == block_ids  # drop windows straddling two blocks

        # Cap windows per label (selected before any window is materialised).
        for label in np.unique(y):
            indices = np.flatnonzero((y == label) & keep)
            if len(indices) > args.max_windows_per_file_label:
                drop = rng.choice(indices, len(indices) - args.max_windows_per_file_label, replace=False)
                keep[drop] = False
        blocks = np.unique(block_ids[keep])
        if len(blocks) == 0:
            continue
        test_blocks = rng.choice(blocks, max(1, int(round(len(blocks) * args.test_size))), replace=False)
        is_test = np.isin(block_ids, test_blocks)

        # NaN -> the scaler's training minimum, which scales to 0.
        values = features.to_numpy(dtype=np.float64)
        values = np.where(np.isnan(values), scaler.data_min_, values)
        scaled = np.clip(scaler.transform(pd.DataFrame(values, columns=feature_names)), 0.0, 1.0).astype(np.float32)
        for mask, xs, ys in ((keep & ~is_test, train_x, train_y), (keep & is_test, test_x, test_y)):
            chosen = starts[mask]
            xs.append(scaled[chosen[:, None] + np.arange(window)])
            ys.append(y[mask])
        n_windows = len(starts)
        counts = {label: int((keep & (y == label)).sum()) for label in np.unique(y[keep])}
        print(f"[INFO]   {n_windows} windows, kept {counts}")

    if not train_x:
        print("[ERROR] No sequences were built.")
        return 1
    x_train, y_train = np.concatenate(train_x), np.concatenate(train_y)
    x_test, y_test = np.concatenate(test_x), np.concatenate(test_y)
    order = rng.permutation(len(x_train))
    x_train, y_train = x_train[order], y_train[order]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        x_train=x_train, y_train=y_train.astype("U16"), x_test=x_test, y_test=y_test.astype("U16"),
        feature_names=np.array(feature_names), window_size=np.array(window),
    )
    for title, labels in (("train", y_train), ("test", y_test)):
        print(f"[INFO] {title} windows per class: {pd.Series(labels).value_counts().sort_index().to_dict()}")
    print(f"[PASS] Saved {args.output}: train {x_train.shape}, test {x_test.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
