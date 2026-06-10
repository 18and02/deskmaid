"""Unit-style smoke test for single-run agent guardrails.

Usage:
    .venv/bin/python -u Maid/test_agent_guardrails.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_budget_policy import tool_risk_level, tool_risk_quota_rows
from maid_guardrails import ToolUseGuardrail, is_side_effect_tool, leaf_tool_name


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    _assert(leaf_tool_name("mcp__deskmaid_local__open_app") == "open_app", "leaf tool parsing failed")
    _assert(is_side_effect_tool("open_app"), "open_app should count as side effect")
    _assert(not is_side_effect_tool("read_mail_message"), "read_mail_message should stay read-only")
    _assert(tool_risk_level("list_windows") == "low", "list_windows risk level mismatch")
    _assert(tool_risk_level("read_mail_message") == "medium", "read_mail_message risk level mismatch")
    _assert(tool_risk_level("create_mail_draft") == "high", "create_mail_draft risk level mismatch")
    _assert(tool_risk_level("send_mail_draft") == "critical", "send_mail_draft risk level mismatch")
    quota_rows = tool_risk_quota_rows()
    _assert(len(quota_rows) == 4, f"expected 4 risk quota rows, got {quota_rows!r}")

    same_tool_guard = ToolUseGuardrail(
        max_total_uses=10,
        max_same_tool_uses=2,
        max_side_effect_uses=10,
    )
    _assert(same_tool_guard.observe("list_windows") is None, "first list_windows should pass")
    _assert(same_tool_guard.observe("list_windows") is None, "second list_windows should pass")
    denied = same_tool_guard.observe("list_windows")
    _assert(denied is not None and "list_windows" in denied, "same tool guardrail did not trigger")

    side_effect_guard = ToolUseGuardrail(
        max_total_uses=10,
        max_same_tool_uses=10,
        max_side_effect_uses=2,
    )
    _assert(side_effect_guard.observe("open_app") is None, "first side effect should pass")
    _assert(side_effect_guard.observe("focus_window") is None, "second side effect should pass")
    denied = side_effect_guard.observe("paste_text")
    _assert(denied is not None and "改动桌面或数据" in denied, "side-effect guardrail did not trigger")

    total_guard = ToolUseGuardrail(
        max_total_uses=2,
        max_same_tool_uses=10,
        max_side_effect_uses=10,
    )
    _assert(total_guard.observe("list_windows") is None, "first total use should pass")
    _assert(total_guard.observe("read_mail_message") is None, "second total use should pass")
    denied = total_guard.observe("AskUserQuestion")
    _assert(denied is not None and "试了 2 次工具" in denied, "total use guardrail did not trigger")

    risk_guard = ToolUseGuardrail(
        max_total_uses=20,
        max_same_tool_uses=20,
        max_side_effect_uses=20,
    )
    for tool_name in (
        "list_windows",
        "list_calendar_events",
        "list_reminders",
        "get_frontmost_app",
        "AskUserQuestion",
        "list_windows",
    ):
        _assert(
            risk_guard.observe(tool_name) is None,
            f"risk guard should allow low-risk tool {tool_name}",
        )
    denied = risk_guard.observe("list_reminders")
    _assert(
        denied is not None and "低风险工具" in denied,
        f"low-risk quota guardrail did not trigger: {denied!r}",
    )

    critical_guard = ToolUseGuardrail(
        max_total_uses=20,
        max_same_tool_uses=20,
        max_side_effect_uses=20,
    )
    _assert(
        critical_guard.observe("paste_text") is None,
        "first critical-risk tool should pass",
    )
    denied = critical_guard.observe("send_mail_draft")
    _assert(
        denied is not None and "极高风险工具" in denied,
        f"critical-risk quota guardrail did not trigger: {denied!r}",
    )

    snapshot = critical_guard.quota_snapshot("send_mail_draft")
    _assert(snapshot.get("risk_label") == "极高风险", f"unexpected risk snapshot: {snapshot!r}")
    _assert(snapshot.get("risk_remaining") == 0, f"unexpected risk remaining: {snapshot!r}")
    _assert(snapshot.get("total_remaining") == 19, f"unexpected total remaining: {snapshot!r}")

    print("ok")


if __name__ == "__main__":
    main()
