"""Seed a fake DeskMaid budget ledger for hunger-state testing.

Usage:
    .venv/bin/python tools/seed_fake_budget.py [ledger_path] [used_usd]

Then launch the app against the fake ledger (the real one is untouched):
    MAID_BUDGET_STATE_PATH=<ledger_path> .venv/bin/python Maid/main.py

Stage cheat sheet for used=3.85 (daily limits: open $10 / normal $4 / cautious $1.50):
    open     -> 38%  normal
    normal   -> 96%  hungry
    cautious -> blocked  starving
Switch the budget mode in Setup (or edit the app state file) and wait for the
60s poll to see threshold announcements and the reset celebration live.
"""

from __future__ import annotations

import json
import sys
import time


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/maid_fake_budget.json"
    used = float(sys.argv[2]) if len(sys.argv) > 2 else 3.85
    payload = {
        "version": 2,
        "entries": [
            {
                "recorded_at": time.time(),
                "cost_usd": used,
                "mode": "normal",
                "session_id": "hunger-test",
                "input_tokens": 0,
                "output_tokens": 0,
                "stop_reason": "end_turn",
            }
        ],
        "runtime": {},
    }
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"seeded {target}: today used ${used:.2f}")


if __name__ == "__main__":
    main()
