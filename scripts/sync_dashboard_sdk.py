#!/usr/bin/env python3
"""Keep the dashboard's copy of the JavaScript SDK in step with sdk/js.

The dashboard image builds from ./dashboard only, so it cannot import ../sdk/js; it carries a copy instead:

  sdk/js/src/*.ts                -> dashboard/src/sdk/*.ts      (what `import ... from "@neurosoc/sdk"` resolves to)
  sdk/js/dist/neurosoc.min.js    -> dashboard/public/neurosoc.min.js   (the script-tag build the wizard snippets load)

Nobody edits the copies by hand. Change sdk/js/src, run `npm run build` in sdk/js, then run this script.
`--check` changes nothing and exits 1 when a copy has drifted (tests/test_dashboard_sdk_sync.py runs it).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sdk" / "js" / "src"
DEST = ROOT / "dashboard" / "src" / "sdk"
BUNDLE = ROOT / "sdk" / "js" / "dist" / "neurosoc.min.js"
BUNDLE_COPY = ROOT / "dashboard" / "public" / "neurosoc.min.js"


def pairs() -> list[tuple[Path, Path]]:
    found = [(source, DEST / source.name) for source in sorted(SRC.glob("*.ts"))]
    if BUNDLE.exists():
        found.append((BUNDLE, BUNDLE_COPY))
    return found


def drifted() -> list[str]:
    problems = []
    sources = {source.name for source in SRC.glob("*.ts")}
    for source, copy in pairs():
        if not copy.exists():
            problems.append(f"missing {copy.relative_to(ROOT)}")
        elif source.read_bytes() != copy.read_bytes():
            problems.append(f"{copy.relative_to(ROOT)} differs from {source.relative_to(ROOT)}")
    if DEST.exists():
        problems += [f"stray {extra.relative_to(ROOT)}" for extra in sorted(DEST.glob("*.ts")) if extra.name not in sources]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report drift and exit 1; change nothing")
    args = parser.parse_args()
    if args.check:
        problems = drifted()
        for problem in problems:
            print(f"DRIFT: {problem}")
        if problems:
            print("Run: python scripts/sync_dashboard_sdk.py")
        return 1 if problems else 0
    if not BUNDLE.exists():
        print("note: sdk/js/dist/neurosoc.min.js is missing; run `npm run build` in sdk/js to refresh the script-tag build")
    DEST.mkdir(parents=True, exist_ok=True)
    BUNDLE_COPY.parent.mkdir(parents=True, exist_ok=True)
    for stale in drifted():
        if stale.startswith("stray "):
            (ROOT / stale[len("stray "):]).unlink()
    for source, copy in pairs():
        shutil.copyfile(source, copy)
        print(f"copied {source.relative_to(ROOT)} -> {copy.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
