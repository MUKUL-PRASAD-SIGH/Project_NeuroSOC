"""The 'best epoch' snapshot must be a copy: state_dict() returns live tensors that training keeps mutating."""
import copy

import torch
from torch import nn


def test_state_dict_is_live_so_snapshots_must_copy():
    model = nn.Linear(2, 2)
    live = model.state_dict()
    snapshot = copy.deepcopy(model.state_dict())
    with torch.no_grad():
        model.weight.add_(1.0)  # a later training step
    assert torch.equal(live["weight"], model.weight)  # the uncopied "snapshot" followed training
    assert not torch.equal(snapshot["weight"], model.weight)  # the deepcopy kept the best-epoch weights


def test_training_scripts_snapshot_with_deepcopy():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "retraining-service"
    for name in ("train_snn.py", "train_lnn.py"):
        source = (root / name).read_text()
        assert "copy.deepcopy(" in source and "import copy" in source, name
