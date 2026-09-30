from __future__ import annotations

import argparse
import sys
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

try:
    from imblearn.over_sampling import SMOTE
except ImportError:
    SMOTE = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "datasets"
DEFAULT_RAW_DIR = DATASETS_DIR / "raw"
DEFAULT_PROCESSED_DIR = DATASETS_DIR / "processed"
DEFAULT_SCALER_PATH = DATASETS_DIR / "scaler.pkl"
DEFAULT_FEATURE_COLUMNS_PATH = DATASETS_DIR / "feature_columns.txt"
DEFAULT_RUNTIME_DATA_DIR = REPO_ROOT / "data"
DEFAULT_CONTRACT_CANDIDATES = [
    DEFAULT_RUNTIME_DATA_DIR / "feature_columns.txt",
    DEFAULT_FEATURE_COLUMNS_PATH,
]

CHUNK_SIZE = 100_000
DEFAULT_MAX_ROWS = 500_000
DEFAULT_RANDOM_STATE = 42

LABEL_CANDIDATES = (
    "label",
    "attack",
    "attack_type",
    "class",
    "classification",
    "category",
)

COLUMN_ALIASES = {
    "flow_byts_s": "flow_bytes_per_s",
    "flow_bytes_s": "flow_bytes_per_s",
    "flow_packets_s": "flow_packets_per_s",
    "flow_pkts_s": "flow_packets_per_s",
    "tot_fwd_pkts": "fwd_packets_total",
    "total_fwd_packets": "fwd_packets_total",
    "total_forward_packets": "fwd_packets_total",
    "tot_bwd_pkts": "bwd_packets_total",
    "total_backward_packets": "bwd_packets_total",
    "total_bwd_packets": "bwd_packets_total",
    "totlen_fwd_pkts": "fwd_bytes_total",
    "total_length_of_fwd_packets": "fwd_bytes_total",
    "totlen_bwd_pkts": "bwd_bytes_total",
    "total_length_of_bwd_packets": "bwd_bytes_total",
    "fwd_iat_tot": "fwd_iat_total",
    "bwd_iat_tot": "bwd_iat_total",
    "fwd_header_len": "fwd_header_length",
    "bwd_header_len": "bwd_header_length",
    "fwd_header_length_1": "fwd_header_length_again",
    "pkt_len_var": "pkt_len_variance",
    "packet_length_variance": "pkt_len_variance",
    "packet_size_variance": "pkt_len_variance",
    "average_packet_size": "avg_packet_size",
    "pkt_size_avg": "avg_packet_size",
    "fwd_seg_size_avg": "avg_fwd_segment_size",
    "avg_fwd_segment_size": "avg_fwd_segment_size",
    "bwd_seg_size_avg": "avg_bwd_segment_size",
    "avg_bwd_segment_size": "avg_bwd_segment_size",
    "subflow_fwd_pkts": "subflow_fwd_packets",
    "subflow_fwd_byts": "subflow_fwd_bytes",
    "subflow_bwd_pkts": "subflow_bwd_packets",
    "subflow_bwd_byts": "subflow_bwd_bytes",
    "init_fwd_win_byts": "init_win_bytes_fwd",
    "init_bwd_win_byts": "init_win_bytes_bwd",
    "fwd_act_data_pkts": "act_data_pkt_fwd",
    "fwd_seg_size_min": "min_seg_size_fwd",
    "cwr_flag_count": "cwe_flag_count",
    "flow_bytes_ss": "flow_bytes_per_s",
    "flow_packets_ss": "flow_packets_per_s",
    "fwd_packets_ss": "fwd_packets_per_s",
    "bwd_packets_ss": "bwd_packets_per_s",
    "down_sup_ratio": "down_up_ratio",
    "fwd_packet_length_max": "fwd_pkt_len_max",
    "fwd_packet_length_min": "fwd_pkt_len_min",
    "fwd_packet_length_mean": "fwd_pkt_len_mean",
    "fwd_packet_length_std": "fwd_pkt_len_std",
    "bwd_packet_length_max": "bwd_pkt_len_max",
    "bwd_packet_length_min": "bwd_pkt_len_min",
    "bwd_packet_length_mean": "bwd_pkt_len_mean",
    "bwd_packet_length_std": "bwd_pkt_len_std",
    "min_packet_length": "pkt_len_min",
    "max_packet_length": "pkt_len_max",
    "packet_length_mean": "pkt_len_mean",
    "packet_length_std": "pkt_len_std",
    "init_win_bytes_forward": "init_win_bytes_fwd",
    "init_win_bytes_backward": "init_win_bytes_bwd",
    "min_seg_size_forward": "min_seg_size_fwd",
}

# Classes with too few rows to learn from; dropped instead of folded into OTHER.
DROPPED_LABELS = {"infiltration", "heartbleed"}

# Raw rows kept per (source file, raw label) while streaming, so large files
# (CICDDoS2019 is ~21 GB) never have to fit in memory.
DEFAULT_MAX_PER_FILE_LABEL = 15_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unify raw intrusion datasets into NeuroShield train/test CSVs."
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--scaler-path", type=Path, default=DEFAULT_SCALER_PATH)
    parser.add_argument("--feature-columns-path", type=Path, default=DEFAULT_FEATURE_COLUMNS_PATH)
    parser.add_argument("--runtime-data-dir", type=Path, default=DEFAULT_RUNTIME_DATA_DIR)
    parser.add_argument("--contract-file", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument(
        "--max-per-file-label",
        type=int,
        default=DEFAULT_MAX_PER_FILE_LABEL,
        help="Rows kept per (file, raw label) while streaming. 0 disables the cap.",
    )
    parser.add_argument(
        "--write-runtime-copies",
        action="store_true",
        help="Also overwrite data/scaler.pkl and data/feature_columns.txt used by the live services.",
    )
    parser.add_argument("--min-samples-per-class", type=int, default=1000)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=DEFAULT_RANDOM_STATE)
    return parser.parse_args()


def snake_case(name: object) -> str:
    text = str(name).strip().lower()
    text = text.replace("%", "percent")
    text = text.replace("/", "_s")
    text = re.sub(r"[\s\-\.]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return COLUMN_ALIASES.get(text, text or "unnamed")


def load_contract_features(contract_file: Path | None) -> list[str]:
    candidates = [contract_file] if contract_file else DEFAULT_CONTRACT_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.exists():
            with candidate.open("r", encoding="utf-8") as handle:
                features = [line.strip() for line in handle if line.strip()]
            if features:
                print(f"[INFO] Loaded feature contract from {candidate}")
                return features
    print("[WARN] No feature contract file found. Falling back to discovered numeric columns.")
    return []


def find_input_files(raw_dir: Path) -> list[Path]:
    patterns = ("*.csv", "*.txt")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(raw_dir.rglob(pattern)))
    empty = [path for path in files if path.stat().st_size == 0]
    for path in empty:
        print(f"[WARN] Skipping empty file {path}")
    return [path for path in files if path not in empty]


def iter_file_chunks(path: Path):
    read_kwargs = {
        "chunksize": CHUNK_SIZE,
        "low_memory": False,
    }
    if path.suffix.lower() == ".txt":
        read_kwargs["header"] = None

    # latin-1 never fails to decode. Trying utf-8 first could raise mid-file
    # (CIC label columns contain invalid bytes) and re-yield already-read chunks.
    yield from pd.read_csv(path, encoding="latin-1", **read_kwargs)


def assign_default_headers(frame: pd.DataFrame) -> pd.DataFrame:
    if not all(isinstance(col, int) for col in frame.columns):
        return frame

    renamed = frame.copy()
    renamed.columns = [f"column_{idx}" for idx in range(len(renamed.columns))]
    if len(renamed.columns) >= 2:
        renamed = renamed.rename(
            columns={
                renamed.columns[-2]: "label",
                renamed.columns[-1]: "difficulty",
            }
        )
    return renamed


def collapse_duplicate_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if not frame.columns.duplicated().any():
        return frame

    collapsed: dict[str, pd.Series] = {}
    for column in dict.fromkeys(frame.columns):
        duplicate_frame = frame.loc[:, frame.columns == column]
        if duplicate_frame.shape[1] == 1:
            collapsed[column] = duplicate_frame.iloc[:, 0]
        else:
            collapsed[column] = duplicate_frame.bfill(axis=1).iloc[:, 0]
    return pd.DataFrame(collapsed, index=frame.index)


def locate_label_column(columns: list[str]) -> str | None:
    for candidate in LABEL_CANDIDATES:
        if candidate in columns:
            return candidate
    for column in columns:
        if "label" in column:
            return column
    return None


def map_label(value: object) -> str | None:
    """Fold a raw dataset label into a NeuroSOC class; None means drop the row."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    if not text:
        return "OTHER"
    if text in {"benign", "normal"}:
        return "BENIGN"
    if text in DROPPED_LABELS:
        return None
    # CICDDoS2019 reflection attacks ("DrDoS_MSSQL", "DrDoS_SNMP", ...) are named
    # after the abused service, so they must be caught before the keyword checks
    # below ("sql" would otherwise make DrDoS_MSSQL a web attack).
    if text.startswith("drdos"):
        return "DDOS"
    # Web checks come before brute force so "Web Attack - Brute Force" is a web
    # attack, and before DoS so CICDDoS2019's "WebDDoS" is not a network flood.
    if "web" in text or "xss" in text or "sql" in text or "injection" in text:
        return "WEB_ATTACK"
    if "brute" in text or "patator" in text:
        return "BRUTE_FORCE"
    if "scan" in text or "probe" in text or "recon" in text:
        return "RECONNAISSANCE"
    if "bot" in text:
        return "BOT"
    if "dos" in text or text in {"syn", "tftp", "udp lag", "udplag"}:
        return "DDOS"
    return "OTHER"


def add_derived_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill contract features CIC does not ship but that follow from columns it does.

    Formulas mirror feature-service/main.py.
    """
    def col(name: str) -> pd.Series | None:
        return frame[name] if name in frame.columns else None

    def numeric(name: str) -> pd.Series | None:
        series = col(name)
        return pd.to_numeric(series, errors="coerce") if series is not None else None

    fwd, bwd = numeric("fwd_packets_total"), numeric("bwd_packets_total")
    n_pkts = (fwd + bwd).replace(0, np.nan) if fwd is not None and bwd is not None else None

    if "flow_iat_total" not in frame.columns and "flow_duration" in frame.columns:
        frame["flow_iat_total"] = frame["flow_duration"]
    if n_pkts is not None:
        for source, target in (("syn_flag_count", "syn_ratio"), ("ack_flag_count", "ack_ratio")):
            flags = numeric(source)
            if target not in frame.columns and flags is not None:
                frame[target] = flags / n_pkts
        fwd_bytes, bwd_bytes = numeric("fwd_bytes_total"), numeric("bwd_bytes_total")
        if "bytes_per_packet" not in frame.columns and fwd_bytes is not None and bwd_bytes is not None:
            frame["bytes_per_packet"] = (fwd_bytes + bwd_bytes) / n_pkts
    if "packet_size_variance" not in frame.columns and "pkt_len_variance" in frame.columns:
        frame["packet_size_variance"] = frame["pkt_len_variance"]
    return frame


def preprocess_chunk(chunk: pd.DataFrame, source: Path) -> pd.DataFrame | None:
    frame = assign_default_headers(chunk)
    frame = frame.copy()
    frame.columns = [snake_case(column) for column in frame.columns]
    frame = collapse_duplicate_columns(frame)

    label_column = locate_label_column(list(frame.columns))
    if label_column is None:
        print(f"[WARN] Skipping {source.name}: no label column found after normalization.")
        return None

    frame = add_derived_features(frame)
    raw_labels = frame[label_column].astype(str).str.strip()
    mapped = raw_labels.map(map_label)
    keep = mapped.notna()
    if not keep.any():
        return None
    frame = frame.loc[keep].drop(columns=[label_column], errors="ignore")
    frame = frame.drop(columns=["difficulty"], errors="ignore")
    labels = mapped.loc[keep].astype(str)
    raw_labels = raw_labels.loc[keep]

    numeric_frame = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        numeric_series = pd.to_numeric(frame[column], errors="coerce")
        if numeric_series.notna().any():
            numeric_frame[column] = numeric_series

    if numeric_frame.empty:
        print(f"[WARN] Skipping {source.name}: no numeric features found.")
        return None

    numeric_frame["label"] = labels
    numeric_frame["_raw_label"] = raw_labels
    return numeric_frame


def cap_per_raw_label(kept: dict[str, pd.DataFrame], processed: pd.DataFrame, cap: int, seed: int) -> None:
    """Merge a chunk into `kept`, holding at most `cap` rows per raw label."""
    for raw_label, group in processed.groupby("_raw_label", sort=False):
        previous = kept.get(raw_label)
        merged = group if previous is None else pd.concat([previous, group], ignore_index=True)
        if cap > 0 and len(merged) > cap:
            merged = merged.sample(n=cap, random_state=seed)
        kept[raw_label] = merged


def load_raw_frames(raw_dir: Path, max_per_file_label: int = 0, seed: int = DEFAULT_RANDOM_STATE) -> pd.DataFrame:
    input_files = find_input_files(raw_dir)
    if not input_files:
        raise FileNotFoundError(
            f"No dataset files found under {raw_dir}. "
            "Download the raw datasets into datasets/raw/ first."
        )

    file_frames: list[pd.DataFrame] = []
    for path in input_files:
        print(f"[INFO] Reading {path}")
        kept: dict[str, pd.DataFrame] = {}
        for chunk in iter_file_chunks(path):
            processed = preprocess_chunk(chunk, path)
            if processed is not None and not processed.empty:
                cap_per_raw_label(kept, processed, max_per_file_label, seed)
        if not kept:
            print(f"[WARN] No usable rows were loaded from {path.name}")
            continue
        frame = pd.concat(kept.values(), ignore_index=True)
        frame["_source"] = path.parent.name
        file_frames.append(frame)
        print(f"[INFO]   kept {len(frame)} rows: {frame['_raw_label'].value_counts().to_dict()}")

    if not file_frames:
        raise ValueError("No usable labeled numeric data was found in datasets/raw/.")

    return pd.concat(file_frames, ignore_index=True)


def print_distribution(title: str, labels: pd.Series) -> None:
    print(title)
    counts = labels.value_counts().sort_index()
    for label, count in counts.items():
        print(f"  - {label}: {count}")


def stratified_cap_rows(frame: pd.DataFrame, max_rows: int, random_state: int) -> pd.DataFrame:
    if max_rows <= 0 or len(frame) <= max_rows:
        return frame

    fraction = max_rows / float(len(frame))
    capped_parts: list[pd.DataFrame] = []
    for _, group in frame.groupby("label", sort=True):
        minimum = 2 if len(group) >= 2 else 1
        sample_size = min(len(group), max(minimum, int(round(len(group) * fraction))))
        capped_parts.append(group.sample(n=sample_size, random_state=random_state))

    capped = pd.concat(capped_parts, ignore_index=True)
    if len(capped) > max_rows:
        capped = capped.sample(n=max_rows, random_state=random_state)
    return capped.reset_index(drop=True)


def clean_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.drop(columns=["label"]).replace([np.inf, -np.inf], np.nan)
    sparse_columns = [
        column for column in numeric.columns
        if numeric[column].isna().mean() > 0.5
    ]
    if sparse_columns:
        print(f"[INFO] Dropping {len(sparse_columns)} sparse columns (>50% null/inf).")
        numeric = numeric.drop(columns=sparse_columns)

    medians = numeric.median(numeric_only=True)
    numeric = numeric.fillna(medians).fillna(0.0)
    labels = frame["label"].astype(str).reset_index(drop=True)
    numeric = numeric.reset_index(drop=True)
    numeric["label"] = labels
    return numeric


def align_to_contract(frame: pd.DataFrame, contract_features: list[str]) -> tuple[pd.DataFrame, list[str]]:
    labels = frame["label"].astype(str).reset_index(drop=True)
    numeric = frame.drop(columns=["label"]).reset_index(drop=True)

    if not contract_features:
        discovered = sorted(numeric.columns.tolist())
        aligned = numeric.reindex(columns=discovered, fill_value=0.0)
        aligned["label"] = labels
        return aligned, discovered

    matched = [feature for feature in contract_features if feature in numeric.columns]
    unmatched = [feature for feature in contract_features if feature not in numeric.columns]
    print(f"[INFO] Contract feature coverage: {len(matched)}/{len(contract_features)} columns matched from raw data.")
    if unmatched:
        print(f"[INFO] Dropping {len(unmatched)} contract features with no source in the datasets: {unmatched}")

    aligned = numeric.reindex(columns=matched)
    aligned = aligned.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    aligned["label"] = labels
    return aligned, matched


def oversample_with_replacement(
    features: pd.DataFrame,
    labels: pd.Series,
    targets: dict[str, int],
    random_state: int,
) -> tuple[pd.DataFrame, pd.Series]:
    merged = features.copy()
    merged["label"] = labels.values
    pieces = [merged]
    for label, target_size in targets.items():
        current = merged[merged["label"] == label]
        needed = target_size - len(current)
        if needed > 0:
            pieces.append(current.sample(n=needed, replace=True, random_state=random_state))
    resampled = pd.concat(pieces, ignore_index=True)
    resampled = resampled.sample(frac=1.0, random_state=random_state).reset_index(drop=True)
    return resampled.drop(columns=["label"]), resampled["label"]


def balance_classes(
    features: pd.DataFrame,
    labels: pd.Series,
    min_samples_per_class: int,
    random_state: int,
) -> tuple[pd.DataFrame, pd.Series]:
    counts = labels.value_counts().sort_index()
    targets = {
        label: min_samples_per_class
        for label, count in counts.items()
        if count < min_samples_per_class
    }

    if not targets:
        print("[INFO] Class balancing skipped: all classes already meet the minimum target.")
        return features, labels

    if SMOTE is not None:
        smallest_class = min(counts[label] for label in targets)
        if smallest_class > 1:
            neighbors = min(5, smallest_class - 1)
            try:
                sampler = SMOTE(
                    sampling_strategy=targets,
                    random_state=random_state,
                    k_neighbors=neighbors,
                )
                resampled_features, resampled_labels = sampler.fit_resample(features, labels)
                print(f"[INFO] Applied SMOTE with k_neighbors={neighbors}.")
                return (
                    pd.DataFrame(resampled_features, columns=features.columns),
                    pd.Series(resampled_labels, name="label"),
                )
            except Exception as exc:
                print(f"[WARN] SMOTE failed ({exc}). Falling back to replacement oversampling.")

    print("[INFO] Using replacement oversampling fallback.")
    return oversample_with_replacement(features, labels, targets, random_state)


def save_feature_contract(feature_names: list[str], feature_columns_path: Path, runtime_data_dir: Path | None) -> None:
    feature_columns_path.parent.mkdir(parents=True, exist_ok=True)
    feature_columns_path.write_text("\n".join(feature_names) + "\n", encoding="utf-8")
    print(f"[INFO] Saved training feature contract to {feature_columns_path}")
    if runtime_data_dir is None:
        return

    runtime_data_dir.mkdir(parents=True, exist_ok=True)
    runtime_feature_columns_path = runtime_data_dir / "feature_columns.txt"
    runtime_feature_columns_path.write_text("\n".join(feature_names) + "\n", encoding="utf-8")

    print(f"[INFO] Saved runtime feature contract to {runtime_feature_columns_path}")


def save_scaler(scaler: MinMaxScaler, scaler_path: Path, runtime_data_dir: Path | None) -> None:
    scaler_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(scaler, scaler_path)
    print(f"[INFO] Saved training scaler to {scaler_path}")
    if runtime_data_dir is None:
        return

    runtime_data_dir.mkdir(parents=True, exist_ok=True)
    runtime_scaler_path = runtime_data_dir / "scaler.pkl"
    joblib.dump(scaler, runtime_scaler_path)

    print(f"[INFO] Saved runtime scaler to {runtime_scaler_path}")


def ensure_split_is_feasible(labels: pd.Series, test_size: float) -> None:
    class_count = labels.nunique()
    minimum_test_rows = int(np.ceil(len(labels) * test_size))
    if minimum_test_rows < class_count:
        raise ValueError(
            f"Stratified split is not possible: test split would contain {minimum_test_rows} rows "
            f"for {class_count} classes. Increase the dataset size or lower the class count."
        )


def main() -> int:
    args = parse_args()

    try:
        contract_features = load_contract_features(args.contract_file)
        raw_frame = load_raw_frames(args.raw_dir, args.max_per_file_label, args.random_state)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] Failed while loading raw datasets: {exc}")
        return 1

    print("[INFO] Rows per source and class:")
    print(pd.crosstab(raw_frame["_source"], raw_frame["label"]).to_string())
    raw_frame = raw_frame.drop(columns=["_source", "_raw_label"])

    raw_frame = stratified_cap_rows(raw_frame, args.max_rows, args.random_state)
    print(f"[INFO] Combined usable rows: {len(raw_frame)}")
    print_distribution("[INFO] Class distribution before balancing:", raw_frame["label"])

    cleaned = clean_numeric_frame(raw_frame)
    aligned, feature_names = align_to_contract(cleaned, contract_features)

    features = aligned.drop(columns=["label"])
    labels = aligned["label"].astype(str)

    # Split first so neither the scaler nor the oversampler ever sees test rows.
    try:
        ensure_split_is_feasible(labels, args.test_size)
        x_train_raw, x_test_raw, y_train, y_test = train_test_split(
            features,
            labels,
            test_size=args.test_size,
            stratify=labels,
            random_state=args.random_state,
        )
    except Exception as exc:
        print(f"[ERROR] Failed during train/test split: {exc}")
        return 1

    scaler = MinMaxScaler()
    x_train = pd.DataFrame(scaler.fit_transform(x_train_raw), columns=feature_names)
    x_test = pd.DataFrame(
        np.clip(scaler.transform(x_test_raw), 0.0, 1.0), columns=feature_names
    )
    y_train = y_train.reset_index(drop=True)
    y_test = y_test.reset_index(drop=True)

    x_train, y_train = balance_classes(
        x_train,
        y_train,
        args.min_samples_per_class,
        args.random_state,
    )
    y_train = pd.Series(y_train).reset_index(drop=True)

    args.processed_dir.mkdir(parents=True, exist_ok=True)
    train_frame = x_train.copy()
    train_frame["label"] = y_train.values
    test_frame = x_test.copy()
    test_frame["label"] = y_test.values

    train_path = args.processed_dir / "unified_train.csv"
    test_path = args.processed_dir / "unified_test.csv"
    train_frame.to_csv(train_path, index=False)
    test_frame.to_csv(test_path, index=False)

    runtime_data_dir = args.runtime_data_dir if args.write_runtime_copies else None
    save_scaler(scaler, args.scaler_path, runtime_data_dir)
    save_feature_contract(feature_names, args.feature_columns_path, runtime_data_dir)

    print_distribution("[INFO] Train split distribution:", y_train)
    print_distribution("[INFO] Test split distribution:", y_test)
    print(f"[PASS] Saved train split to {train_path}")
    print(f"[PASS] Saved test split to {test_path}")
    print(f"[PASS] Train shape: {train_frame.shape}")
    print(f"[PASS] Test shape: {test_frame.shape}")
    print(f"[PASS] Feature count (excluding label): {len(feature_names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
