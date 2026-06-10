"""Local tests for Deskmaid's day/week budget guardrails.

Usage:
    .venv/bin/python -u Maid/test_budget_guard_store.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_budget import BudgetUsageStore


_LOCAL_TZ = datetime.now().astimezone().tzinfo


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0, tzinfo=_LOCAL_TZ).timestamp()


def main():
    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)

        baseline = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 12),
        )
        _assert(not baseline.blocked, f"fresh budget should not block: {baseline!r}")
        _assert(
            abs(float(baseline.daily_limit_usd or 0.0) - 4.0) < 1e-6,
            f"unexpected daily limit: {baseline!r}",
        )
        _assert(
            abs(float(baseline.weekly_limit_usd or 0.0) - 20.0) < 1e-6,
            f"unexpected weekly limit: {baseline!r}",
        )
        _assert(
            abs(float(baseline.effective_max_budget_usd or 0.0) - 0.80) < 1e-6,
            f"unexpected per-run cap on fresh store: {baseline!r}",
        )
        _assert(
            baseline.remaining_allows_full_base_run,
            f"fresh budget should allow a full base run: {baseline!r}",
        )

        entry = store.record_usage(
            3.60,
            budget_mode="normal",
            session_id="sess-a",
            input_tokens=111,
            output_tokens=222,
            stop_reason="stop",
            recorded_at=_ts(2026, 5, 27, 9),
        )
        _assert(entry is not None, "expected budget entry to be recorded")

        tightened = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 18),
        )
        _assert(not tightened.blocked, f"store should still have room left: {tightened!r}")
        _assert(
            abs(tightened.daily_used_usd - 3.60) < 1e-6,
            f"unexpected daily usage after one run: {tightened!r}",
        )
        _assert(
            abs(float(tightened.daily_remaining_usd or 0.0) - 0.40) < 1e-6,
            f"unexpected daily remaining after one run: {tightened!r}",
        )
        _assert(
            abs(float(tightened.effective_max_budget_usd or 0.0) - 0.40) < 1e-6,
            f"expected effective per-run cap to tighten: {tightened!r}",
        )
        _assert(
            tightened.daily_pressure_level == "critical",
            f"expected critical daily pressure after a near-cap spend: {tightened!r}",
        )
        _assert(
            abs(float(tightened.daily_base_runs_left or 0.0) - 0.50) < 1e-6,
            f"unexpected daily base-runs-left value: {tightened!r}",
        )
        _assert(
            not tightened.remaining_allows_full_base_run,
            f"daily remaining below the base run should be flagged: {tightened!r}",
        )
        _assert(
            abs(float(tightened.remaining_shortfall_usd or 0.0) - 0.40) < 1e-6,
            f"unexpected shortfall against a full base run: {tightened!r}",
        )

        store.record_usage(
            0.50,
            budget_mode="normal",
            session_id="sess-b",
            recorded_at=_ts(2026, 5, 27, 19),
        )
        blocked_day = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 20),
        )
        _assert(blocked_day.blocked, f"daily cap should block after overspend: {blocked_day!r}")
        _assert(
            blocked_day.blocked_scope == "day",
            f"expected daily block scope, got {blocked_day!r}",
        )

        reloaded = BudgetUsageStore(path)
        reloaded_status = reloaded.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 28, 10),
        )
        _assert(
            not reloaded_status.blocked,
            f"next day should reset the daily budget window: {reloaded_status!r}",
        )
        _assert(
            abs(reloaded_status.daily_used_usd - 0.0) < 1e-6,
            f"next day daily usage should reset: {reloaded_status!r}",
        )
        _assert(
            abs(reloaded_status.weekly_used_usd - 4.10) < 1e-6,
            f"weekly usage should keep the same-week spend: {reloaded_status!r}",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-week-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.record_usage(
            19.40,
            budget_mode="normal",
            session_id="sess-week-a",
            recorded_at=_ts(2026, 5, 25, 9),
        )

        weekly_tightened = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 28, 12),
        )
        _assert(
            not weekly_tightened.blocked,
            f"weekly budget should still leave a little room: {weekly_tightened!r}",
        )
        _assert(
            abs(float(weekly_tightened.weekly_remaining_usd or 0.0) - 0.60) < 1e-6,
            f"unexpected weekly remaining: {weekly_tightened!r}",
        )
        _assert(
            abs(float(weekly_tightened.effective_max_budget_usd or 0.0) - 0.60) < 1e-6,
            f"weekly remaining should tighten the per-run cap: {weekly_tightened!r}",
        )

        store.record_usage(
            0.80,
            budget_mode="normal",
            session_id="sess-week-b",
            recorded_at=_ts(2026, 5, 28, 13),
        )
        blocked_week = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 29, 12),
        )
        _assert(blocked_week.blocked, f"weekly cap should block after overspend: {blocked_week!r}")
        _assert(
            blocked_week.blocked_scope == "week",
            f"expected weekly block scope, got {blocked_week!r}",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-warning-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.record_usage(
            3.10,
            budget_mode="normal",
            session_id="sess-warning",
            recorded_at=_ts(2026, 5, 27, 9),
        )

        warning_status = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 18),
        )
        _assert(
            not warning_status.blocked,
            f"soft-warning case should not block: {warning_status!r}",
        )
        _assert(
            warning_status.daily_pressure_level == "warning",
            f"expected soft warning pressure before hitting the cap: {warning_status!r}",
        )
        _assert(
            abs(float(warning_status.daily_base_runs_left or 0.0) - 1.125) < 1e-6,
            f"unexpected base-runs-left in soft warning case: {warning_status!r}",
        )
        _assert(
            warning_status.remaining_allows_full_base_run,
            f"soft warning case should still allow a full base run: {warning_status!r}",
        )
        _assert(
            abs(float(warning_status.effective_max_budget_usd or 0.0) - 0.80) < 1e-6,
            f"soft warning alone should not tighten the per-run cap: {warning_status!r}",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-runtime-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.mark_activity(recorded_at=_ts(2026, 5, 27, 8))

        active = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 8),
        )
        _assert(
            active.idle_throttle_stage == "active",
            f"fresh activity should stay in active stage: {active!r}",
        )
        _assert(
            abs(active.idle_throttle_factor - 1.0) < 1e-6,
            f"fresh activity should not throttle budget: {active!r}",
        )

        away = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 11),
        )
        _assert(
            away.idle_throttle_stage == "away",
            f"three hours of quiet should enter away stage: {away!r}",
        )
        _assert(
            abs(away.idle_throttle_factor - 0.60) < 1e-6,
            f"unexpected away-stage throttle factor: {away!r}",
        )
        _assert(
            abs(float(away.effective_max_budget_usd or 0.0) - 0.48) < 1e-6,
            f"away-stage throttle should tighten the per-run cap: {away!r}",
        )

        store.note_suspend(recorded_at=_ts(2026, 5, 27, 9))
        suspended_for = store.note_resume(recorded_at=_ts(2026, 5, 27, 20))
        _assert(
            abs(suspended_for - (11 * 60 * 60)) < 1e-6,
            f"unexpected suspended duration accounting: {suspended_for!r}",
        )

        folded = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 21),
        )
        _assert(
            abs(folded.raw_idle_seconds - (13 * 60 * 60)) < 1e-6,
            f"unexpected raw idle duration after long suspend: {folded!r}",
        )
        _assert(
            abs(folded.suspended_idle_seconds - (11 * 60 * 60)) < 1e-6,
            f"unexpected suspended idle duration after resume: {folded!r}",
        )
        _assert(
            folded.folded_idle_seconds < folded.raw_idle_seconds,
            f"sleep time should be discounted in folded idle accounting: {folded!r}",
        )
        _assert(
            folded.idle_throttle_stage == "away",
            f"long suspend should fold into away, not parked, throttle: {folded!r}",
        )

        store.mark_activity(recorded_at=_ts(2026, 5, 27, 21))
        recovered = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 21),
        )
        _assert(
            recovered.idle_throttle_stage == "active",
            f"new activity should clear idle throttling: {recovered!r}",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-reset-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.record_usage(
            1.25,
            budget_mode="normal",
            session_id="sess-reset-day",
            recorded_at=_ts(2026, 5, 27, 9),
        )
        baseline_message = store.consume_reset_message(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 10),
        )
        _assert(
            baseline_message == "",
            f"same-window consume should not emit reset notice: {baseline_message!r}",
        )

        day_reset_message = store.consume_reset_message(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 28, 9),
        )
        _assert(
            "今天的预算窗已经重置了" in day_reset_message,
            f"expected daily reset notice, got: {day_reset_message!r}",
        )
        duplicate_day_reset = store.consume_reset_message(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 28, 10),
        )
        _assert(
            duplicate_day_reset == "",
            f"daily reset notice should only emit once per window change: {duplicate_day_reset!r}",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-week-reset-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.record_usage(
            3.40,
            budget_mode="normal",
            session_id="sess-reset-week",
            recorded_at=_ts(2026, 5, 25, 9),
        )
        store.consume_reset_message(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 31, 10),
        )
        week_reset_message = store.consume_reset_message(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 6, 1, 9),
        )
        _assert(
            "本周的预算窗已经重置了" in week_reset_message,
            f"expected weekly reset notice, got: {week_reset_message!r}",
        )

    print("ok")


if __name__ == "__main__":
    main()
