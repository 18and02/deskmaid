"""Smoke test for the budget-status explainability view."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_budget import BudgetUsageStore, format_budget_usage_summary
from maid_budget_policy import build_memory_budget_policy, tool_risk_quota_rows
import main as maid_main


_LOCAL_TZ = datetime.now().astimezone().tzinfo


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0, tzinfo=_LOCAL_TZ).timestamp()


def _find_card(cards: list[dict[str, object]], title: str) -> dict[str, object]:
    for card in cards:
        if str(card.get("title") or "") == title:
            return card
    raise AssertionError(f"missing card {title!r}")


def _snapshot_from_status(status) -> dict[str, object]:
    memory_policy = build_memory_budget_policy(
        budget_mode=status.mode,
        budget_status=status,
        recalled_count=4,
        preview=True,
    )
    return {
        "mode": status.mode,
        "per_run_limit_usd": status.per_run_limit_usd,
        "effective_max_budget_usd": status.effective_max_budget_usd,
        "daily_limit_usd": status.daily_limit_usd,
        "daily_used_usd": status.daily_used_usd,
        "daily_remaining_usd": status.daily_remaining_usd,
        "weekly_limit_usd": status.weekly_limit_usd,
        "weekly_used_usd": status.weekly_used_usd,
        "weekly_remaining_usd": status.weekly_remaining_usd,
        "raw_idle_seconds": status.raw_idle_seconds,
        "suspended_idle_seconds": status.suspended_idle_seconds,
        "folded_idle_seconds": status.folded_idle_seconds,
        "idle_throttle_factor": status.idle_throttle_factor,
        "idle_throttle_stage": status.idle_throttle_stage,
        "idle_throttle_reason": status.idle_throttle_reason,
        "daily_pressure_level": status.daily_pressure_level,
        "weekly_pressure_level": status.weekly_pressure_level,
        "daily_base_runs_left": status.daily_base_runs_left,
        "weekly_base_runs_left": status.weekly_base_runs_left,
        "remaining_allows_full_base_run": status.remaining_allows_full_base_run,
        "remaining_shortfall_usd": status.remaining_shortfall_usd,
        "next_daily_reset_at": status.next_daily_reset_at,
        "next_weekly_reset_at": status.next_weekly_reset_at,
        "blocked": status.blocked,
        "blocked_scope": status.blocked_scope,
        "summary": format_budget_usage_summary(status),
        "tool_risk_quotas": tool_risk_quota_rows(),
        "memory_budget_tier": memory_policy.tier,
        "memory_budget_label": memory_policy.label,
        "memory_budget_max_items": memory_policy.max_items,
        "memory_budget_clip_chars": memory_policy.clip_chars,
        "memory_budget_factor": memory_policy.budget_factor,
        "memory_budget_reasons": list(memory_policy.reasons),
    }


def main():
    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-view-warning-") as tmp_dir:
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
        warning_view = maid_main._build_budget_status_view(
            _snapshot_from_status(warning_status)
        )
        warning_view_en = maid_main._build_budget_status_view(
            _snapshot_from_status(warning_status),
            language="en-US",
        )

        _assert(
            "余量已经开始变紧" in str(warning_view.get("status_text") or ""),
            f"unexpected warning status text: {warning_view!r}",
        )
        warning_cards = [
            dict(item)
            for item in (warning_view.get("cards") or [])
            if isinstance(item, dict)
        ]
        warning_window_card = _find_card(warning_cards, "预算窗")
        _assert(
            str(warning_window_card.get("badge") or "") == "偏紧",
            f"expected warning budget badge: {warning_window_card!r}",
        )
        _assert(
            "按基础档还够 1.1轮" in str(warning_window_card.get("summary") or ""),
            f"warning card should show remaining base runs: {warning_window_card!r}",
        )
        risk_card = _find_card(warning_cards, "工具风险配额")
        _assert(
            "低风险 6 次" in str(risk_card.get("summary") or ""),
            f"risk quota card should show the low-risk quota: {risk_card!r}",
        )
        memory_card = _find_card(warning_cards, "记忆省预算档")
        _assert(
            str(memory_card.get("badge") or "") == "轻量",
            f"expected compact memory budget badge in warning view: {memory_card!r}",
        )
        warning_cards_en = [
            dict(item)
            for item in (warning_view_en.get("cards") or [])
            if isinstance(item, dict)
        ]
        _assert(
            "inside budget" in str(warning_view_en.get("status_text") or ""),
            f"unexpected english warning status text: {warning_view_en!r}",
        )
        _assert(
            _find_card(warning_cards_en, "Current Tier"),
            "expected english budget card title",
        )

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-view-tight-") as tmp_dir:
        path = Path(tmp_dir) / "budget.json"
        store = BudgetUsageStore(path)
        store.record_usage(
            3.60,
            budget_mode="normal",
            session_id="sess-tight",
            recorded_at=_ts(2026, 5, 27, 9),
        )
        tight_status = store.guard_status(
            budget_mode="normal",
            per_run_limit_usd=0.80,
            now=_ts(2026, 5, 27, 18),
        )
        tight_view = maid_main._build_budget_status_view(
            _snapshot_from_status(tight_status)
        )

        _assert(
            "不足一整轮基础档" in str(tight_view.get("status_text") or ""),
            f"tightened view should explain the shortfall: {tight_view!r}",
        )
        tight_cards = [
            dict(item)
            for item in (tight_view.get("cards") or [])
            if isinstance(item, dict)
        ]
        tight_window_card = _find_card(tight_cards, "预算窗")
        _assert(
            str(tight_window_card.get("badge") or "") == "不足一轮",
            f"expected shortfall badge in budget window card: {tight_window_card!r}",
        )
        _assert(
            "还差 $0.40" in str(tight_window_card.get("hint") or ""),
            f"budget window hint should expose the shortfall: {tight_window_card!r}",
        )
        recovery_card = _find_card(tight_cards, "恢复节点")
        _assert(
            "05-28 00:00" in str(recovery_card.get("summary") or ""),
            f"recovery card should show the next reset time: {recovery_card!r}",
        )
        memory_card = _find_card(tight_cards, "记忆省预算档")
        _assert(
            str(memory_card.get("badge") or "") == "省预算",
            f"expected minimal memory budget badge in tight view: {memory_card!r}",
        )
        _assert(
            "最多带 2 条事实" in str(memory_card.get("summary") or ""),
            f"tight memory card should show the reduced memory window: {memory_card!r}",
        )

    print("ok")


if __name__ == "__main__":
    main()
