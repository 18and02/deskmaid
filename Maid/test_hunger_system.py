"""Tests for the budget-driven hunger system (evaluation, announcer, widget wiring).

Usage:
    .venv/bin/python -u Maid/test_hunger_system.py
"""

from __future__ import annotations

import os
from pathlib import Path
import random
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lines import (
    HUNGER_FULL_LINES,
    HUNGER_HUNGRY_LINES,
    HUNGER_PECKISH_LINES,
    HUNGER_STARVING_LINES,
)
from maid_hunger import (
    HUNGER_STAGE_HUNGRY,
    HUNGER_STAGE_NORMAL,
    HUNGER_STAGE_PECKISH,
    HUNGER_STAGE_STARVING,
    HungerAnnouncer,
    HungerState,
    evaluate_hunger,
    pick_hunger_line,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _snapshot(
    *,
    daily_limit: float | None = None,
    daily_used: float = 0.0,
    weekly_limit: float | None = None,
    weekly_used: float = 0.0,
    blocked: bool = False,
    blocked_scope: str = "",
) -> dict[str, object]:
    return {
        "daily_limit_usd": daily_limit,
        "daily_used_usd": daily_used,
        "weekly_limit_usd": weekly_limit,
        "weekly_used_usd": weekly_used,
        "blocked": blocked,
        "blocked_scope": blocked_scope,
    }


def test_evaluate_hunger():
    no_limits = evaluate_hunger(_snapshot())
    _assert(no_limits.stage == HUNGER_STAGE_NORMAL, f"no limits should be normal: {no_limits!r}")
    _assert(no_limits.ratio is None, f"no limits should have no ratio: {no_limits!r}")

    half = evaluate_hunger(_snapshot(daily_limit=1.0, daily_used=0.5))
    _assert(half.stage == HUNGER_STAGE_NORMAL, f"50% should be normal: {half!r}")

    peckish = evaluate_hunger(_snapshot(daily_limit=1.0, daily_used=0.85))
    _assert(peckish.stage == HUNGER_STAGE_PECKISH, f"85% should be peckish: {peckish!r}")
    _assert(peckish.scope == "day", f"unexpected scope: {peckish!r}")

    hungry = evaluate_hunger(_snapshot(daily_limit=1.0, daily_used=0.96))
    _assert(hungry.stage == HUNGER_STAGE_HUNGRY, f"96% should be hungry: {hungry!r}")

    starving = evaluate_hunger(_snapshot(daily_limit=1.0, daily_used=1.0))
    _assert(starving.stage == HUNGER_STAGE_STARVING, f"100% should be starving: {starving!r}")

    blocked = evaluate_hunger(
        _snapshot(daily_limit=1.0, daily_used=0.4, blocked=True, blocked_scope="day")
    )
    _assert(
        blocked.stage == HUNGER_STAGE_STARVING,
        f"blocked should be starving regardless of ratio: {blocked!r}",
    )
    _assert(blocked.blocked, f"blocked flag should persist: {blocked!r}")

    week_worse = evaluate_hunger(
        _snapshot(daily_limit=1.0, daily_used=0.3, weekly_limit=5.0, weekly_used=4.9)
    )
    _assert(week_worse.stage == HUNGER_STAGE_HUNGRY, f"weekly 98% should win: {week_worse!r}")
    _assert(week_worse.scope == "week", f"unexpected scope: {week_worse!r}")


def test_pick_hunger_line():
    rng = random.Random(7)
    lines = ["a", "b", "c"]
    last = pick_hunger_line(lines, rng=rng)
    for _ in range(40):
        current = pick_hunger_line(lines, last_line=last, rng=rng)
        _assert(current != last, "should not repeat the previous line")
        last = current

    only = pick_hunger_line(["solo"], last_line="solo", rng=rng)
    _assert(only == "solo", "single-line pool may repeat")
    _assert(pick_hunger_line([], rng=rng) == "", "empty pool returns empty string")


def test_hunger_announcer():
    stage_lines = {
        HUNGER_STAGE_PECKISH: HUNGER_PECKISH_LINES,
        HUNGER_STAGE_HUNGRY: HUNGER_HUNGRY_LINES,
        HUNGER_STAGE_STARVING: HUNGER_STARVING_LINES,
    }
    announcer = HungerAnnouncer(stage_lines, HUNGER_FULL_LINES, rng=random.Random(3))

    _assert(
        announcer.observe(HungerState(stage=HUNGER_STAGE_NORMAL)) is None,
        "normal -> normal should not announce",
    )

    rise = announcer.observe(HungerState(stage=HUNGER_STAGE_PECKISH))
    _assert(rise is not None and rise.kind == "stage", f"expected peckish announcement: {rise!r}")
    _assert(rise.line in HUNGER_PECKISH_LINES, f"unexpected line: {rise!r}")

    _assert(
        announcer.observe(HungerState(stage=HUNGER_STAGE_PECKISH)) is None,
        "repeat stage should not announce again",
    )

    skip = announcer.observe(HungerState(stage=HUNGER_STAGE_STARVING))
    _assert(
        skip is not None and skip.line in HUNGER_STARVING_LINES,
        f"jump to starving should announce starving: {skip!r}",
    )

    partial_drop = announcer.observe(HungerState(stage=HUNGER_STAGE_HUNGRY))
    _assert(partial_drop is None, f"partial drop should stay quiet: {partial_drop!r}")

    full = announcer.observe(HungerState(stage=HUNGER_STAGE_NORMAL))
    _assert(full is not None and full.kind == "full", f"drop to normal should celebrate: {full!r}")
    _assert(full.line in HUNGER_FULL_LINES, f"unexpected full line: {full!r}")

    restarted = HungerAnnouncer(
        stage_lines,
        HUNGER_FULL_LINES,
        initial_stage=HUNGER_STAGE_STARVING,
        rng=random.Random(3),
    )
    _assert(
        restarted.observe(HungerState(stage=HUNGER_STAGE_STARVING)) is None,
        "restart at starving should not re-announce",
    )


def test_widget_hunger_wiring():
    from PySide6.QtWidgets import QApplication

    from bubble import SpeechBubble
    from maid_sprite_packs import resolve_sprite_pack
    import main as maid_main

    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="deskmaid-hunger-") as tmp_dir:
        os.environ["MAID_APP_STATE_PATH"] = str(Path(tmp_dir) / "app_state.json")
        os.environ["MAID_BUDGET_STATE_PATH"] = str(Path(tmp_dir) / "budget_state.json")
        os.environ["MAID_OUTING_STATE_PATH"] = str(Path(tmp_dir) / "outing_state.json")
        maid_main.HAVE_AUTO_DND_NATIVE_NOTIFICATIONS = False

        sprite_pack = resolve_sprite_pack(
            assets_dir=maid_main.ASSETS,
            sprite_set="petdex-maid-codex",
            sprite=None,
        )
        for state in ("hungry", "starving", "full"):
            _assert(state in sprite_pack.states, f"petdex pack should provide {state!r}")

        widget = maid_main.MaidWidget(sprite_pack, SpeechBubble(), demo_short=True)
        widget._enter_until = None
        widget._state = maid_main.MaidState.IDLE

        _assert(
            widget._hunger_state.stage == HUNGER_STAGE_NORMAL,
            f"fresh budget store should start normal: {widget._hunger_state!r}",
        )
        _assert(widget._current_state_key() == "idle", "normal stage should idle")

        snapshots = {"value": _snapshot(daily_limit=1.0, daily_used=0.96)}
        maid_main.get_budget_guard_snapshot = lambda: snapshots["value"]
        maid_main.consume_budget_reset_notice = lambda: ""

        widget._poll_budget_reset_notice()
        _assert(
            widget._hunger_state.stage == HUNGER_STAGE_HUNGRY,
            f"poll should pick up hungry stage: {widget._hunger_state!r}",
        )
        _assert(
            widget._state == maid_main.MaidState.ALERT,
            "threshold crossing should announce via bubble",
        )
        widget.end_alert()
        _assert(
            widget._current_state_key() == "hungry",
            f"hungry stage should swap idle sprite: {widget._current_state_key()!r}",
        )

        snapshots["value"] = _snapshot(daily_limit=1.0, daily_used=1.0)
        widget._poll_budget_reset_notice()
        widget.end_alert()
        _assert(
            widget._current_state_key() == "starving",
            f"starving stage should swap idle sprite: {widget._current_state_key()!r}",
        )
        _assert(
            widget._current_pixmap().size().width() > 0,
            "starving pixmap should resolve",
        )

        snapshots["value"] = _snapshot(daily_limit=1.0, daily_used=0.0)
        maid_main.consume_budget_reset_notice = lambda: "状态回执 · 预算窗口已重置"
        widget._poll_budget_reset_notice()
        _assert(
            widget._hunger_state.stage == HUNGER_STAGE_NORMAL,
            f"reset should return stage to normal: {widget._hunger_state!r}",
        )
        _assert(widget._emote_key == "full", f"reset should play full emote: {widget._emote_key!r}")
        _assert(widget._emote_until is not None, "full emote window should be active")
        widget.end_alert()
        _assert(
            widget._current_state_key() == "full",
            f"full emote should render jumping frames: {widget._current_state_key()!r}",
        )

        widget.end_alert()

        # 免打扰期间的播报应排队而不是丢弃，解除后由空闲兜底自动补发。
        widget._do_not_disturb = True
        snapshots["value"] = _snapshot(daily_limit=1.0, daily_used=0.96)
        widget._poll_budget_reset_notice()
        _assert(
            widget._hunger_state.stage == HUNGER_STAGE_HUNGRY,
            f"stage should still advance under DND: {widget._hunger_state!r}",
        )
        _assert(
            widget._state != maid_main.MaidState.ALERT,
            "DND should keep the bubble quiet",
        )
        _assert(
            bool(widget._deferred_alert_line),
            "DND should queue the hunger line instead of dropping it",
        )
        widget._do_not_disturb = False
        widget._maybe_flush_deferred_alert(time.monotonic())
        _assert(
            widget._state == maid_main.MaidState.ALERT,
            "queued hunger line should flush once DND ends",
        )
        _assert(
            widget._deferred_alert_line is None,
            "deferred queue should be empty after flush",
        )
        widget.end_alert()

        widget._timer.stop()
        widget._auto_dnd_timer.stop()
        widget._budget_notice_timer.stop()
        widget._auto_dnd_native_observer.stop()


def main():
    test_evaluate_hunger()
    test_pick_hunger_line()
    test_hunger_announcer()
    test_widget_hunger_wiring()
    print("ok")


if __name__ == "__main__":
    main()
