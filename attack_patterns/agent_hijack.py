"""Agent hijack scene: routine treasury moves, then a prompt-injected transfer that NeuroSOC blocks.

    python attack_patterns/agent_hijack.py --normal 20

Runs sdk/examples/agent/agent.py. Requires the stack with ENABLE_UNIVERSAL_ENGINE=true.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1] / "sdk" / "examples" / "agent" / "agent.py"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent hijack demo")
    parser.add_argument("--normal", type=int, default=20, help="routine moves before the poisoned message")
    parser.add_argument("--pause", type=float, default=0.4)
    args = parser.parse_args()
    raise SystemExit(subprocess.call([sys.executable, str(AGENT), "--normal", str(args.normal),
                                      "--pause", str(args.pause), "--inject"]))
