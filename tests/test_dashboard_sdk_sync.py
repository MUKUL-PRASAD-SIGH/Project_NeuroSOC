"""The dashboard carries a copy of the JavaScript SDK (its Docker context cannot reach ../sdk); it must not drift."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_dashboard_sdk.py"


def test_dashboard_sdk_copy_matches_the_sdk_source():
    completed = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + "\nRun: python scripts/sync_dashboard_sdk.py"


def test_every_sdk_source_file_has_a_copy_and_there_are_no_strays():
    source = {p.name for p in (ROOT / "sdk" / "js" / "src").glob("*.ts")}
    copy = {p.name for p in (ROOT / "dashboard" / "src" / "sdk").glob("*.ts")}
    assert source and source == copy


def test_the_script_tag_build_the_wizard_loads_is_committed_and_current():
    served = ROOT / "dashboard" / "public" / "neurosoc.min.js"
    assert served.exists() and b"neurosoc" in served.read_bytes().lower()
    built = ROOT / "sdk" / "js" / "dist" / "neurosoc.min.js"
    if not built.exists():
        pytest.skip("sdk/js has not been built here (npm run build); only the committed copy was checked")
    assert served.read_bytes() == built.read_bytes(), "run: python scripts/sync_dashboard_sdk.py"
