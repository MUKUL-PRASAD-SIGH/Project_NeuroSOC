"""Provisioning probe: `colab run --keep` executes this on a fresh VM and leaves the VM running."""
import shutil
import subprocess

import torch

print("torch", torch.__version__, "| cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device:", torch.cuda.get_device_name(0))
if shutil.which("nvidia-smi"):
    subprocess.run(["nvidia-smi", "-L"], check=False)
