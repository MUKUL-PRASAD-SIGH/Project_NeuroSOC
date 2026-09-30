"""Runs on the Colab VM (via `colab exec -f`): trains the NeuroSOC candidate models.

Expects, uploaded by scripts/colab_train.sh:
  /content/neurosoc_code.tgz         retraining-service/, inference-service/core/, models/model_version.json
  /content/unified_{train,test}.csv.gz   gzipped processed CSVs (not needed for smoke runs)
  /content/sequences.npz             optional windowed sequences for the LNN (datasets/build_sequences.py)
  /content/colab_train_config.json   optional overrides for CONFIG below

Writes /content/neurosoc_results.tgz with models/candidates/ and retraining-service/results/.
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path("/content/NeuroSOC")
SERVICE = ROOT / "retraining-service"

CONFIG = {
    "smoke": False,
    "models": ["xgboost", "lnn", "snn"],
    "class_weight": True,
    "device": "cuda",
    "xgb_cv_folds": 3,
    "lnn_max_rows": 200_000,
    "lnn_epochs": 30,
    "snn_max_rows": 60_000,
    "snn_epochs": 20,
    "batch_size": 128,
}

config_path = Path("/content/colab_train_config.json")
if config_path.exists():
    CONFIG.update(json.loads(config_path.read_text()))
print("[colab_train] config:", json.dumps(CONFIG))

ROOT.mkdir(parents=True, exist_ok=True)
with tarfile.open("/content/neurosoc_code.tgz") as archive:
    archive.extractall(ROOT)

PROCESSED = ROOT / "datasets" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)
for name in ("unified_train.csv", "unified_test.csv"):
    archive_path = Path("/content") / f"{name}.gz"
    if archive_path.exists():
        with gzip.open(archive_path, "rb") as source, open(PROCESSED / name, "wb") as target:
            shutil.copyfileobj(source, target)
        print(f"[colab_train] unpacked {name}")

SEQUENCES = PROCESSED / "sequences.npz"
if Path("/content/sequences.npz").exists():
    shutil.move("/content/sequences.npz", SEQUENCES)

if shutil.which("nvidia-smi"):
    subprocess.run(["nvidia-smi", "-L"], check=False)
try:
    import torch

    if CONFIG["device"] == "cuda" and not torch.cuda.is_available():
        print("[colab_train] WARNING: no CUDA device; falling back to cpu")
        CONFIG["device"] = "cpu"
except ImportError:
    sys.exit("torch is not installed on this VM")

# --no-deps keeps the VM's own torch build; the SNN falls back to a plain network if norse is missing.
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "norse"], check=False)
subprocess.run([sys.executable, "-c", "import norse; print('[colab_train] norse', norse.__version__)"], check=False)

flags = ["--smoke-test"] if CONFIG["smoke"] else []
weight = ["--class-weight"] if CONFIG["class_weight"] else []
device = ["--device", CONFIG["device"]]
batch = ["--batch-size", str(CONFIG["batch_size"])]

commands = {
    "xgboost": ["train_xgboost.py", *device, *weight, "--cv-folds", str(CONFIG["xgb_cv_folds"])],
    "lnn": [
        "train_lnn.py", *device, *weight, *batch,
        "--max-rows", str(CONFIG["lnn_max_rows"]), "--epochs", str(CONFIG["lnn_epochs"]),
        *(["--sequence-dataset", str(SEQUENCES)] if SEQUENCES.exists() else []),
    ],
    "snn": [
        "train_snn.py", *device, *weight, *batch,
        "--max-rows", str(CONFIG["snn_max_rows"]), "--epochs", str(CONFIG["snn_epochs"]),
    ],
}

LOG_DIR = ROOT / "retraining-service" / "results"
LOG_DIR.mkdir(parents=True, exist_ok=True)
failures = []
for name in CONFIG["models"]:
    cmd = [sys.executable, "-u", *commands[name], *flags]
    print(f"\n[colab_train] ===== {name}: {' '.join(cmd[2:])}", flush=True)
    # The notebook kernel does not see a child process's own stdout, so relay it line by line
    # (and keep a copy in the results archive).
    log_path = LOG_DIR / f"{name}.log"
    with subprocess.Popen(
        cmd, cwd=SERVICE, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    ) as process, open(log_path, "w") as log_file:
        for line in process.stdout:
            print(f"[{name}] {line}", end="", flush=True)
            log_file.write(line)
    if process.returncode != 0:
        failures.append(name)
        print(f"[colab_train] {name} FAILED (exit {process.returncode})", flush=True)

with tarfile.open("/content/neurosoc_results.tgz", "w:gz") as archive:
    for relative in ("models/candidates", "retraining-service/results"):
        target = ROOT / relative
        if target.exists():
            archive.add(target, arcname=relative)
print("\n[colab_train] wrote /content/neurosoc_results.tgz")
candidates = sorted((ROOT / "models" / "candidates").glob("*.manifest.json"))
for manifest in candidates:
    data = json.loads(manifest.read_text())
    print(f"[colab_train] candidate {data['model_key']}: validation_f1={data['validation_f1']:.4f} {data['artifact_path']}")

if failures:
    sys.exit(f"training failed for: {', '.join(failures)}")
