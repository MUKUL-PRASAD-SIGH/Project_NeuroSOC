"""/api/v1/verdicts/current, /current-session and /{user_id} return 500 if a stored verdict carries tenant_id
but the strict response model does not declare it (tenant_id was added to verdicts without updating this model)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference-service"))

import main as inference_main  # noqa: E402


def _verdict(**extra):
    return {"tenant_id": "local", "session_id": "session-00000001", "user_id": "u1", "source_ip": "10.0.0.1",
            "snn_score": 0.2, "lnn_class": "BENIGN", "xgb_class": "BENIGN", "behavioral_delta": 0.0,
            "confidence": 0.1, "verdict": "LEGITIMATE", "timestamp": 1.0, "model_version": "1.0.4", **extra}


def test_snapshot_accepts_tenant_id_on_the_verdict_and_its_history():
    snapshot = inference_main.VerdictSnapshotResponse(**_verdict(history=[_verdict()]))
    assert snapshot.tenant_id == "local" and snapshot.history[0].tenant_id == "local"


def test_snapshot_still_rejects_unknown_fields():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        inference_main.VerdictSnapshotResponse(**_verdict(not_a_field=1))
