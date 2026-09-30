#!/usr/bin/env bash
# Train the NeuroSOC candidate models on a Colab VM with the `colab` CLI.
#
#   scripts/colab_train.sh smoke   # synthetic data, tiny run: checks imports, paths and CUDA
#   scripts/colab_train.sh full    # trains on datasets/processed/unified_{train,test}.csv
#
# Env: SESSION (default neurosoc-train), GPU (default T4; empty string = CPU VM),
#      EXEC_TIMEOUT (seconds, default 21600), CONFIG_JSON (optional JSON merged over the defaults in scripts/colab_train.py).
# Candidates are downloaded into models/candidates/ and stay pending_approval.
set -euo pipefail

MODE="${1:-smoke}"
SESSION="${SESSION:-neurosoc-train}"
GPU="${GPU-T4}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'echo "[colab_train.sh] stopping session $SESSION"; colab stop -s "$SESSION" || true; rm -rf "$WORK"' EXIT

case "$MODE" in
  smoke) DEFAULT_CONFIG='{"smoke": true}' ;;
  full)  DEFAULT_CONFIG='{}' ;;
  *) echo "usage: $0 smoke|full" >&2; exit 2 ;;
esac
CONFIG="${CONFIG_JSON:-$DEFAULT_CONFIG}"

TRAIN="$REPO/datasets/processed/unified_train.csv"
TEST="$REPO/datasets/processed/unified_test.csv"
if [ "$MODE" = full ] && { [ ! -f "$TRAIN" ] || [ ! -f "$TEST" ]; }; then
  echo "missing $TRAIN or $TEST; run datasets/preprocess.py first" >&2
  exit 1
fi

# Code bundle: the training scripts, the model classes they import, and the active version file.
tar czf "$WORK/neurosoc_code.tgz" -C "$REPO" \
  --exclude='__pycache__' --exclude='results' \
  retraining-service inference-service/core models/model_version.json datasets/scaler.pkl
echo "$CONFIG" > "$WORK/colab_train_config.json"

# `colab run --keep` provisions the VM (it got a T4 where `colab new --gpu T4` was refused)
# and leaves it running, so the uploads below have somewhere to go.
colab run --keep -s "$SESSION" ${GPU:+--gpu "$GPU"} "$REPO/scripts/colab_probe.py"
colab upload "$WORK/neurosoc_code.tgz" /content/neurosoc_code.tgz -s "$SESSION"
colab upload "$WORK/colab_train_config.json" /content/colab_train_config.json -s "$SESSION"
if [ "$MODE" = full ]; then
  # Gzipped and uploaded to /content/ (colab_train.py unpacks them): the Jupyter upload API
  # rejected the raw 300 MB CSV dropped into a directory that did not exist yet.
  gzip -c "$TRAIN" > "$WORK/unified_train.csv.gz"
  gzip -c "$TEST" > "$WORK/unified_test.csv.gz"
  colab upload "$WORK/unified_train.csv.gz" /content/unified_train.csv.gz -s "$SESSION"
  colab upload "$WORK/unified_test.csv.gz" /content/unified_test.csv.gz -s "$SESSION"
  if [ -f "$REPO/datasets/processed/sequences.npz" ]; then
    colab upload "$REPO/datasets/processed/sequences.npz" /content/sequences.npz -s "$SESSION"
  fi
fi

colab exec -s "$SESSION" --timeout "${EXEC_TIMEOUT:-21600}" -f "$REPO/scripts/colab_train.py"

colab download /content/neurosoc_results.tgz "$WORK/neurosoc_results.tgz" -s "$SESSION"
mkdir -p "$REPO/models/candidates" "$REPO/retraining-service/results"
tar xzf "$WORK/neurosoc_results.tgz" -C "$REPO" --keep-old-files
echo "[colab_train.sh] candidates now in $REPO/models/candidates:"
ls "$REPO/models/candidates"
