"""Bot farm against the example rewards campaign (a page we control, never a live platform).

    python attack_patterns/bot_farm.py --count 50                 # scripted clients, no browser needed
    python attack_patterns/bot_farm.py --count 20 --browser       # real headless browsers (pip install playwright; --channel chrome uses your installed Chrome)

Every bot has its own wallet and session, but they all run from one machine (one device
fingerprint) with the same scripted rhythm. Watch the dashboard: the group is linked and shadowed,
and the campaign's backend withholds their rewards while each bot is told "pending review".
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor

import neurosoc_sim as sim

FARM_DEVICE = sim.fingerprint("farm-rig-01")


def api_bot(index: int, args) -> str:
    rng = random.Random(9000 + index)
    wallet = sim.wallet_address(rng)
    context = {"device_hash": FARM_DEVICE, "user_agent_hash": sim.fingerprint("headless-chrome")}
    return sim.campaign_run(wallet, sim.new_session(), context, sim.bot_telemetry, args.endpoint, args.campaign)


def browser_farm(args) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Browser mode needs Playwright: pip install playwright && playwright install chromium")
    statuses = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, channel=args.channel or None)
        for index in range(args.count):
            context = browser.new_context()  # fresh storage = a "new user" each time
            page = context.new_page()
            page.goto(args.campaign)
            page.wait_for_function("window.neurosoc !== undefined")
            page.click("#connect-wallet")
            page.fill("input[name=handle]", f"user{index:04d}")
            page.fill("textarea[name=why]", "airdrop")
            page.click("#profile-form button")
            for task in ("follow", "discord", "try"):
                page.click(f"[data-task={task}]")
            page.click("#claim")
            page.wait_for_selector("#result.paid, #result.pending")
            statuses.append("paid" if page.is_visible("#result.paid") else "pending_review")
            print(f"browser bot {index + 1:>3}  {statuses[-1]}")
            context.close()
            time.sleep(1.0 / max(args.speed, 0.1))
        browser.close()
    return statuses


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot farm against the example campaign")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--speed", type=float, default=10.0, help="higher = faster")
    parser.add_argument("--browser", action="store_true", help="use headless Chromium via Playwright")
    parser.add_argument("--headed", action="store_true", help="show the browsers (with --browser)")
    parser.add_argument("--channel", default="", help="use an installed browser: chrome or msedge (with --browser)")
    parser.add_argument("--endpoint", default=sim.ENDPOINT)
    parser.add_argument("--campaign", default=sim.CAMPAIGN_URL)
    args = parser.parse_args()

    if args.browser:
        statuses = browser_farm(args)
    else:
        statuses = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for index, status in enumerate(pool.map(lambda i: api_bot(i, args), range(args.count))):
                statuses.append(status)
                print(f"bot {index + 1:>3}  {status}")
                time.sleep(0.5 / max(args.speed, 0.1))
    paid = statuses.count("paid")
    print(f"\nFarm of {len(statuses)}: paid {paid}, withheld {len(statuses) - paid} "
          f"({(len(statuses) - paid) * 25} AUR not paid out)")


if __name__ == "__main__":
    main()
