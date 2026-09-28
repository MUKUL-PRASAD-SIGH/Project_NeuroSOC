from __future__ import annotations

import re
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (REPOSITORY_ROOT / "dashboard" / "src", REPOSITORY_ROOT / "inference-service")
SIMULATION_FIXTURE = (REPOSITORY_ROOT / "inference-service" / "core" / "simulation_accounts.py").resolve()
FORBIDDEN_PATTERNS = re.compile(
    r"(?i)(?:password123|secure456|admin@2024!|change-me-local-only|ns_pass|neuroshield_admin)"
)
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".py"}


def main() -> int:
    findings: list[str] = []
    for scan_root in SCAN_ROOTS:
        for source_path in scan_root.rglob("*"):
            if not source_path.is_file() or source_path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if source_path.resolve() == SIMULATION_FIXTURE:
                continue
            try:
                source = source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(source.splitlines(), start=1):
                if "DATABASE_URL" in line and " in DATABASE_URL" in line:
                    # These literals are used only to reject local DB defaults at production startup.
                    continue
                if FORBIDDEN_PATTERNS.search(line):
                    findings.append(f"{source_path.relative_to(REPOSITORY_ROOT)}:{line_number}")

    if findings:
        print("Demo credential patterns found in production code paths:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1

    print("No known demo credential patterns found in production code paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
