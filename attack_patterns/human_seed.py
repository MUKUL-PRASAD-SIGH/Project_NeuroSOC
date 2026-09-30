"""Seed believable human sessions on the example campaign so baselines exist before a demo.

    python attack_patterns/human_seed.py --count 30

Each person has their own device, wallet and typing speed. Requires the stack with
ENABLE_UNIVERSAL_ENGINE=true and the example campaign server (sdk/examples/rewards-campaign).
"""

from __future__ import annotations

import argparse
import random
import time

import neurosoc_sim as sim


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed human sessions")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--speed", type=float, default=10.0, help="higher = faster (0.2s pause at 10)")
    parser.add_argument("--endpoint", default=sim.ENDPOINT)
    parser.add_argument("--campaign", default=sim.CAMPAIGN_URL)
    args = parser.parse_args()

    results = {"paid": 0, "pending_review": 0}
    for index in range(args.count):
        rng = random.Random(1000 + index)
        wallet = sim.wallet_address(rng)
        context = {"device_hash": sim.fingerprint(f"person-{index}-device"),
                   "user_agent_hash": sim.fingerprint(rng.choice(["chrome-win", "safari-mac", "firefox-linux", "chrome-android"]))}
        status = sim.campaign_run(wallet, sim.new_session(), context, lambda r=rng: sim.human_telemetry(r),
                                  args.endpoint, args.campaign)
        results[status] = results.get(status, 0) + 1
        print(f"person {index + 1:>3}  {wallet[:6]}…  {status}")
        time.sleep(2.0 / max(args.speed, 0.1))
    print(f"\nPaid: {results.get('paid', 0)}   Pending review: {results.get('pending_review', 0)}")


if __name__ == "__main__":
    main()
