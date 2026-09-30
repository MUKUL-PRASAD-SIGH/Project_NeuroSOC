"""Promote a model candidate offline, with the same bookkeeping as the inference service's
POST /api/v1/models/candidates/{id}/promote endpoint (inference-service/main.py):

  1. snapshot the current models/model_version.json into models/history/ (used by rollback)
  2. point the candidate's model key at its artifact, bump the version, record validation F1
  3. mark the candidate manifest `promoted` with who/when

It first checks that a DecisionEngine can load the resulting manifest, and writes nothing if not.
A running inference service hot-swaps to the new manifest on its next model-monitor poll.

    python scripts/promote_candidate.py <candidate_id> --by "<who approved this>"
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "inference-service"))

from core.engine import DecisionEngine  # noqa: E402


def next_version(proposed: str, current: str) -> str:
    """Use the candidate's proposed version unless it is not newer than the active one.

    Candidates trained from the same base both propose the same version (for example 1.0.3), so promoting
    a second one would otherwise leave the version unchanged.
    """
    def parse(text: str) -> tuple[int, ...]:
        return tuple(int(part) for part in text.split(".") if part.isdigit())

    if parse(proposed) > parse(current):
        return proposed
    parts = list(parse(current)) or [0, 0, 0]
    parts[-1] += 1
    return ".".join(str(part) for part in parts)


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        temp = Path(handle.name)
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("candidate_id")
    parser.add_argument("--by", required=True, help="Who approved the promotion (recorded in the manifest).")
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models")
    args = parser.parse_args()

    version_path = args.models_dir / "model_version.json"
    manifest_path = args.models_dir / "candidates" / f"{args.candidate_id}.manifest.json"
    candidate = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if candidate.get("status") != "pending_approval":
        print(f"[ERROR] {args.candidate_id} is already {candidate.get('status')}.")
        return 1

    current = json.loads(version_path.read_text(encoding="utf-8-sig")) if version_path.exists() else {}
    new_payload = dict(current)
    new_payload["version"] = next_version(candidate["proposed_version"], str(current.get("version", "0.0.0")))
    new_payload[candidate["model_key"]] = candidate["artifact_path"]
    validation_f1 = dict(new_payload.get("validation_f1") or {})
    validation_f1[candidate["model_key"]] = candidate["validation_f1"]
    new_payload["validation_f1"] = validation_f1
    new_payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Dry run against a scratch copy next to the real file, so relative artifact paths resolve.
    scratch = args.models_dir / f".promote_check_{args.candidate_id}.json"
    scratch.write_text(json.dumps(new_payload), encoding="utf-8")
    try:
        engine = DecisionEngine(model_version_path=scratch, start_model_monitor=False)
        loaded = {"snn": engine.snn_model, "lnn": engine.lnn_classifier, "xgb": engine.xgb_model}[candidate["model_key"]]
    finally:
        scratch.unlink(missing_ok=True)
    if loaded is None:
        print("[ERROR] The engine could not load the candidate artifact; nothing was changed.")
        return 1

    history_dir = args.models_dir / "history"
    snapshot = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}_{current.get('version', '0.0.0')}.json"
    atomic_write_json(history_dir / snapshot, current)
    atomic_write_json(version_path, new_payload)
    candidate["status"] = "promoted"
    candidate["promoted_at"] = datetime.now(timezone.utc).isoformat()
    candidate["promoted_by"] = args.by
    atomic_write_json(manifest_path, candidate)

    print(f"[PASS] Promoted {args.candidate_id}: {candidate['model_key']} -> {candidate['artifact_path']}")
    print(f"[INFO] Active version {current.get('version')} -> {new_payload['version']}; previous manifest saved as history/{snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
