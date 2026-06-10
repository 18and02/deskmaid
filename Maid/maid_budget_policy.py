"""Budget-side policy helpers shared by guardrails, chat, and UI."""

from __future__ import annotations

from dataclasses import dataclass

from maid_preferences import normalize_budget_mode


TOOL_RISK_LEVEL_LIMITS: dict[str, int] = {
    "low": 6,
    "medium": 4,
    "high": 2,
    "critical": 1,
}

_TOOL_RISK_LEVEL_LABELS = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
    "critical": "极高风险",
}

_TOOL_RISK_LEVEL_DESCRIPTIONS = {
    "low": "只读概览或澄清类工具，允许多试几次。",
    "medium": "轻度桌面操作或敏感读取，先收一层。",
    "high": "会改数据或读取更敏感正文，单轮只给少量额度。",
    "critical": "发送、删除、模拟输入这类动作，单轮只放一脚。",
}

_TOOL_RISK_LEVEL_EXAMPLES = {
    "low": "AskUserQuestion / list_windows / list_calendar_events / list_reminders",
    "medium": "open_app / open_url / focus_window / read_mail_message",
    "high": "create_mail_draft / create_calendar_event / update_reminder",
    "critical": "send_mail_draft / delete_calendar_event / paste_text / press_keys",
}

_LOW_RISK_TOOLS = {
    "AskUserQuestion",
    "get_frontmost_app",
    "list_windows",
    "list_calendar_events",
    "list_reminders",
}

_MEDIUM_RISK_TOOLS = {
    "open_app",
    "open_url",
    "focus_window",
    "read_clipboard_text",
    "read_unread_mail_headers",
    "read_mail_message",
    "mark_mail_read",
}

_HIGH_RISK_TOOLS = {
    "set_clipboard_text",
    "create_mail_draft",
    "create_calendar_event",
    "update_calendar_event",
    "create_reminder",
    "update_reminder",
}

_CRITICAL_RISK_TOOLS = {
    "send_mail_draft",
    "delete_calendar_event",
    "delete_reminder",
    "paste_text",
    "press_keys",
}

_TOOL_RISK_LEVELS: dict[str, str] = {}
for _tool_name in _LOW_RISK_TOOLS:
    _TOOL_RISK_LEVELS[_tool_name] = "low"
for _tool_name in _MEDIUM_RISK_TOOLS:
    _TOOL_RISK_LEVELS[_tool_name] = "medium"
for _tool_name in _HIGH_RISK_TOOLS:
    _TOOL_RISK_LEVELS[_tool_name] = "high"
for _tool_name in _CRITICAL_RISK_TOOLS:
    _TOOL_RISK_LEVELS[_tool_name] = "critical"

del _tool_name

_RISK_LEVEL_ORDER = ("low", "medium", "high", "critical")
_MEMORY_TIER_ORDER = ("full", "compact", "minimal")
_MEMORY_TIER_INDEX = {name: index for index, name in enumerate(_MEMORY_TIER_ORDER)}


@dataclass(frozen=True)
class MemoryBudgetPolicy:
    tier: str
    label: str
    max_items: int
    clip_chars: int
    budget_factor: float
    reasons: tuple[str, ...] = ()


def leaf_tool_name(tool_name: str) -> str:
    text = str(tool_name or "").strip()
    if "__" in text:
        return text.rsplit("__", 1)[-1]
    return text


def tool_risk_level(tool_name: str) -> str:
    leaf_name = leaf_tool_name(tool_name)
    if not leaf_name:
        return "high"
    return _TOOL_RISK_LEVELS.get(leaf_name, "high")


def tool_risk_label(level: str) -> str:
    normalized = str(level or "").strip().lower()
    return _TOOL_RISK_LEVEL_LABELS.get(normalized, _TOOL_RISK_LEVEL_LABELS["high"])


def tool_risk_limit(level: str) -> int:
    normalized = str(level or "").strip().lower()
    return int(TOOL_RISK_LEVEL_LIMITS.get(normalized, TOOL_RISK_LEVEL_LIMITS["high"]))


def tool_risk_description(level: str) -> str:
    normalized = str(level or "").strip().lower()
    return _TOOL_RISK_LEVEL_DESCRIPTIONS.get(
        normalized,
        _TOOL_RISK_LEVEL_DESCRIPTIONS["high"],
    )


def tool_risk_examples(level: str) -> str:
    normalized = str(level or "").strip().lower()
    return _TOOL_RISK_LEVEL_EXAMPLES.get(normalized, _TOOL_RISK_LEVEL_EXAMPLES["high"])


def tool_risk_quota_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for level in _RISK_LEVEL_ORDER:
        rows.append(
            {
                "level": level,
                "label": tool_risk_label(level),
                "limit": tool_risk_limit(level),
                "description": tool_risk_description(level),
                "examples": tool_risk_examples(level),
            }
        )
    return rows


def _raise_memory_tier(current: str, target: str) -> str:
    current_index = _MEMORY_TIER_INDEX.get(current, _MEMORY_TIER_INDEX["full"])
    target_index = _MEMORY_TIER_INDEX.get(target, _MEMORY_TIER_INDEX["full"])
    if target_index > current_index:
        return target
    return current


def _memory_tier_profile(tier: str) -> tuple[str, int, int, float]:
    normalized = str(tier or "compact").strip().lower()
    if normalized == "full":
        return "标准", 6, 96, 1.0
    if normalized == "minimal":
        return "省预算", 2, 56, 0.75
    return "轻量", 4, 72, 0.90


def build_memory_budget_policy(
    *,
    budget_mode: str,
    budget_status,
    recalled_count: int = 0,
    preview: bool = False,
) -> MemoryBudgetPolicy:
    normalized_mode = normalize_budget_mode(budget_mode)
    tier = "compact"
    reasons: list[str] = []

    if normalized_mode == "open":
        tier = "full"
        reasons.append("当前是放开档，命中记忆时先走标准记忆窗。")
    elif normalized_mode == "cautious":
        tier = "minimal"
        reasons.append("当前是谨慎档，命中记忆时默认走省预算窗。")
    else:
        reasons.append("当前是标准档，命中记忆时默认先走轻量窗。")

    if budget_status is not None:
        daily_pressure = str(
            getattr(budget_status, "daily_pressure_level", "ok") or "ok"
        ).strip().lower()
        weekly_pressure = str(
            getattr(budget_status, "weekly_pressure_level", "ok") or "ok"
        ).strip().lower()
        idle_stage = str(
            getattr(budget_status, "idle_throttle_stage", "active") or "active"
        ).strip().lower()
        blocked = bool(getattr(budget_status, "blocked", False))
        if blocked or not bool(
            getattr(budget_status, "remaining_allows_full_base_run", True)
        ):
            tier = "minimal"
            reasons.append("日 / 周预算余量已经很紧，记忆只带最少几条事实。")
        elif "critical" in {daily_pressure, weekly_pressure}:
            tier = "minimal"
            reasons.append("日 / 周预算进入告急区，记忆继续压一档。")
        elif "warning" in {daily_pressure, weekly_pressure}:
            tier = _raise_memory_tier(tier, "compact")
            reasons.append("日 / 周预算开始偏紧，记忆维持轻量窗。")

        if idle_stage in {"away", "parked"}:
            tier = _raise_memory_tier(tier, "compact")
            reasons.append("当前处于长时闲置阶段，记忆上下文也收一层。")

    label, max_items, clip_chars, budget_factor = _memory_tier_profile(tier)

    actual_recalled = max(0, int(recalled_count or 0))
    if not preview and actual_recalled <= 1:
        budget_factor = 1.0
        reasons.append("这轮命中的长期记忆不多，不额外压缩单轮预算。")

    return MemoryBudgetPolicy(
        tier=tier,
        label=label,
        max_items=max_items,
        clip_chars=clip_chars,
        budget_factor=budget_factor,
        reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
    )
