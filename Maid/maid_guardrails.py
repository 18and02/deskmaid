"""Runaway guardrails for a single maid agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field

from maid_budget_policy import (
    TOOL_RISK_LEVEL_LIMITS,
    leaf_tool_name as _policy_leaf_tool_name,
    tool_risk_label,
    tool_risk_level,
    tool_risk_limit,
)


DEFAULT_MAX_AGENT_TURNS = 4
DEFAULT_MAX_AGENT_RUNTIME_S = 90.0
DEFAULT_MAX_TOOL_USES_PER_RUN = 8
DEFAULT_MAX_SAME_TOOL_USES_PER_RUN = 3
DEFAULT_MAX_SIDE_EFFECT_TOOL_USES_PER_RUN = 5

_SIDE_EFFECT_TOOL_NAMES = {
    "create_calendar_event",
    "create_mail_draft",
    "create_reminder",
    "delete_calendar_event",
    "delete_reminder",
    "focus_window",
    "mark_mail_read",
    "open_app",
    "open_url",
    "paste_text",
    "press_keys",
    "send_mail_draft",
    "set_clipboard_text",
    "update_calendar_event",
    "update_reminder",
}


def leaf_tool_name(tool_name: str) -> str:
    return _policy_leaf_tool_name(tool_name)


def is_side_effect_tool(tool_name: str) -> bool:
    return leaf_tool_name(tool_name) in _SIDE_EFFECT_TOOL_NAMES


@dataclass
class ToolUseGuardrail:
    max_total_uses: int = DEFAULT_MAX_TOOL_USES_PER_RUN
    max_same_tool_uses: int = DEFAULT_MAX_SAME_TOOL_USES_PER_RUN
    max_side_effect_uses: int = DEFAULT_MAX_SIDE_EFFECT_TOOL_USES_PER_RUN
    max_risk_level_uses: dict[str, int] = field(
        default_factory=lambda: dict(TOOL_RISK_LEVEL_LIMITS)
    )
    total_uses: int = 0
    side_effect_uses: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    risk_counts: dict[str, int] = field(default_factory=dict)

    def quota_snapshot(self, tool_name: str) -> dict[str, int | str]:
        leaf_name = leaf_tool_name(tool_name)
        risk_level = tool_risk_level(leaf_name)
        risk_limit = int(self.max_risk_level_uses.get(risk_level, tool_risk_limit(risk_level)))
        risk_used = int(self.risk_counts.get(risk_level, 0))
        total_limit = int(self.max_total_uses)
        total_used = int(self.total_uses)
        return {
            "tool_name": leaf_name,
            "risk_level": risk_level,
            "risk_label": tool_risk_label(risk_level),
            "risk_limit": risk_limit,
            "risk_used": risk_used,
            "risk_remaining": max(0, risk_limit - risk_used),
            "total_limit": total_limit,
            "total_used": total_used,
            "total_remaining": max(0, total_limit - total_used),
        }

    def observe(self, tool_name: str) -> str | None:
        leaf_name = leaf_tool_name(tool_name)
        if not leaf_name:
            return "这轮工具调用名字是空的，我先拦下来了。"

        if self.total_uses >= self.max_total_uses:
            return (
                f"这轮已经试了 {self.total_uses} 次工具。"
                "先停一下，把任务拆小一点再继续。"
            )

        current_count = int(self.counts.get(leaf_name, 0))
        if current_count >= self.max_same_tool_uses:
            return (
                f"这轮已经反复想调用 {leaf_name} {current_count} 次了。"
                "我先停住，免得在同一个动作里打转。"
            )

        risk_level = tool_risk_level(leaf_name)
        risk_limit = int(self.max_risk_level_uses.get(risk_level, tool_risk_limit(risk_level)))
        current_risk_count = int(self.risk_counts.get(risk_level, 0))
        if current_risk_count >= risk_limit:
            return (
                f"这轮已经用了 {current_risk_count} 次{tool_risk_label(risk_level)}工具"
                f"（上限 {risk_limit} 次）。"
                "先停一下，别把高影响动作在一轮里堆太满。"
            )

        side_effect = is_side_effect_tool(leaf_name)
        if side_effect and self.side_effect_uses >= self.max_side_effect_uses:
            return (
                f"这轮已经做了 {self.side_effect_uses} 次会改动桌面或数据的动作。"
                "先停一下，避免越做越偏。"
            )

        self.total_uses += 1
        self.counts[leaf_name] = current_count + 1
        self.risk_counts[risk_level] = current_risk_count + 1
        if side_effect:
            self.side_effect_uses += 1
        return None
