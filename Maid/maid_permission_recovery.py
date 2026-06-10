"""Shared TCC / permission recovery helpers for Deskmaid."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import NotRequired, TypedDict


_SYSTEM_EVENTS_TOOLS = frozenset(
    {
        "focus_window",
        "paste_text",
        "press_keys",
    }
)

_CALENDAR_TOOLS = frozenset(
    {
        "list_calendar_events",
        "create_calendar_event",
        "preview_calendar_event_update",
        "update_calendar_event",
        "delete_calendar_event",
    }
)

_REMINDERS_TOOLS = frozenset(
    {
        "list_reminders",
        "create_reminder",
        "preview_reminder_update",
        "update_reminder",
        "delete_reminder",
    }
)

_MAIL_TOOLS = frozenset(
    {
        "read_unread_mail_headers",
        "read_mail_message",
        "mark_mail_read",
        "create_mail_draft",
        "send_mail_draft",
    }
)

_SETTINGS_BUNDLE_ID = "com.apple.systempreferences"
_ACCESSIBILITY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
_AUTOMATION_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
)


class PermissionRecoveryAction(TypedDict):
    id: str
    label: str
    kind: str
    target: str
    detail: NotRequired[str]


def _make_action(
    action_id: str,
    label: str,
    kind: str,
    target: str,
    *,
    detail: str = "",
) -> PermissionRecoveryAction:
    action: PermissionRecoveryAction = {
        "id": action_id,
        "label": label,
        "kind": kind,
        "target": target,
    }
    clean_detail_text = clean_permission_detail(detail)
    if clean_detail_text:
        action["detail"] = clean_detail_text
    return action


def _refresh_action() -> PermissionRecoveryAction:
    return _make_action(
        "refresh_permission_health",
        "刷新",
        "refresh",
        "",
        detail="改完系统设置后，回来重跑一次权限自检。",
    )


def _open_accessibility_action() -> PermissionRecoveryAction:
    return _make_action(
        "open_accessibility_settings",
        "打开辅助功能",
        "open_url",
        _ACCESSIBILITY_SETTINGS_URL,
        detail=accessibility_permission_hint(),
    )


def _open_automation_action() -> PermissionRecoveryAction:
    return _make_action(
        "open_automation_settings",
        "打开自动化",
        "open_url",
        _AUTOMATION_SETTINGS_URL,
        detail="在自动化页里确认 Deskmaid / osascript 对目标应用仍是允许状态。",
    )


def _open_app_action(app_name: str) -> PermissionRecoveryAction:
    normalized = str(app_name or "").strip() or "目标应用"
    return _make_action(
        f"open_app::{normalized.lower()}",
        f"打开 {normalized}",
        "open_app",
        normalized,
        detail=f"先打开 {normalized} 看看它能否正常启动，准备好后再回来刷新。",
    )


def _dedupe_actions(
    actions: list[PermissionRecoveryAction],
) -> list[PermissionRecoveryAction]:
    seen: set[str] = set()
    indexed_rows: list[tuple[int, PermissionRecoveryAction]] = []
    for index, action in enumerate(actions):
        action_id = str(action.get("id") or "").strip()
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        indexed_rows.append((index, dict(action)))

    def _priority(row: PermissionRecoveryAction) -> tuple[int, int, str]:
        action_id = str(row.get("id") or "").strip()
        if action_id == "open_accessibility_settings":
            return (10, 0, action_id)
        if action_id == "open_automation_settings":
            return (20, 0, action_id)
        if action_id.startswith("open_app::"):
            return (30, 0, action_id)
        if action_id == "refresh_permission_health":
            return (90, 0, action_id)
        return (50, 0, action_id)

    indexed_rows.sort(key=lambda item: (_priority(item[1]), item[0]))
    return [row for _, row in indexed_rows]


def _tools_for_key(key: str) -> list[str]:
    if key == "current_process_accessibility":
        return sorted(_SYSTEM_EVENTS_TOOLS)
    if key == "system_events_ui":
        return sorted(_SYSTEM_EVENTS_TOOLS)
    if key == "calendar_automation":
        return sorted(_CALENDAR_TOOLS)
    if key == "reminders_automation":
        return sorted(_REMINDERS_TOOLS)
    if key == "mail_automation":
        return sorted(_MAIL_TOOLS)
    return []


def clean_permission_detail(detail: str) -> str:
    return " ".join(str(detail or "").strip().split())


def looks_like_automation_denied(detail: str) -> bool:
    lowered = str(detail or "").lower()
    return (
        "not authorized to send apple events" in lowered
        or "not authorised to send apple events" in lowered
        or ("apple events" in lowered and "not authorized" in lowered)
        or "不允许将 apple 事件发送给" in str(detail or "")
        or ("apple 事件" in str(detail or "") and "不允许" in str(detail or ""))
        or "自动化" in str(detail or "")
        or "(-1743)" in lowered
    )


def looks_like_accessibility_denied(detail: str) -> bool:
    lowered = str(detail or "").lower()
    return (
        "assistive access" in lowered
        or "accessibility" in lowered
        or "辅助访问" in str(detail or "")
        or "辅助功能" in str(detail or "")
        or "不允许辅助访问" in str(detail or "")
        or "(-1719)" in lowered
    )


def looks_like_timeout(detail: str) -> bool:
    lowered = str(detail or "").lower()
    return "timed out" in lowered or "timeout" in lowered


def _find_bundle_root(executable: Path) -> Path | None:
    for candidate in [executable, *executable.parents]:
        if candidate.suffix == ".app":
            return candidate
    return None


def permission_sender_hint() -> str:
    executable = Path(sys.executable).resolve()
    bundle_root = _find_bundle_root(executable)
    if bundle_root is not None:
        bundle_name = bundle_root.stem.strip() or executable.name or "Deskmaid"
        return (
            f"`{bundle_name}`（如果系统设置里显示成 `osascript`，也一并确认它没被关掉）"
        )

    executable_name = executable.name.strip() or "python"
    if executable_name.lower().startswith("python"):
        return "`osascript`（开发态下也可能挂在当前 Python 进程名下）"
    if executable_name == "osascript":
        return "`osascript`"
    return f"`{executable_name}`（如果系统设置里显示成 `osascript`，也一并确认）"


def accessibility_permission_hint() -> str:
    return (
        "去 系统设置 -> 隐私与安全性 -> 辅助功能，确认 "
        f"{permission_sender_hint()} 仍被允许。"
    )


def automation_permission_hint(app_name: str) -> str:
    target = str(app_name or "").strip() or "目标应用"
    return (
        "去 系统设置 -> 隐私与安全性 -> 自动化，确认 "
        f"{permission_sender_hint()} 仍被允许控制 `{target}`。"
    )


def permission_refresh_hint() -> str:
    return "回到应用里打开 Permission health 刷新一次，再重试。"


def timeout_recovery_hint() -> str:
    return (
        "先确认系统里没有挂着的授权提示；如果你刚撤回或重置过权限，"
        f"{permission_refresh_hint()}"
    )


def _tool_target_app(tool_name: str) -> str | None:
    if tool_name in _SYSTEM_EVENTS_TOOLS:
        return "System Events"
    if tool_name in _CALENDAR_TOOLS:
        return "Calendar"
    if tool_name in _REMINDERS_TOOLS:
        return "Reminders"
    if tool_name in _MAIL_TOOLS:
        return "Mail"
    return None


def tool_permission_recovery_message(tool_name: str, detail: str) -> str | None:
    normalized_tool = str(tool_name or "").strip()
    clean_detail = clean_permission_detail(detail)
    if not normalized_tool or not clean_detail:
        return None

    if normalized_tool in _SYSTEM_EVENTS_TOOLS:
        if looks_like_accessibility_denied(clean_detail):
            return (
                f"`{normalized_tool}` 需要辅助功能授权。"
                f"{accessibility_permission_hint()} "
                f"{permission_refresh_hint()}"
            )
        if looks_like_automation_denied(clean_detail):
            return (
                f"`{normalized_tool}` 需要 `System Events` 自动化授权。"
                f"{automation_permission_hint('System Events')} "
                f"{permission_refresh_hint()}"
            )

    target_app = _tool_target_app(normalized_tool)
    if target_app is not None and looks_like_automation_denied(clean_detail):
        return (
            f"`{normalized_tool}` 需要 `{target_app}` 自动化授权。"
            f"{automation_permission_hint(target_app)} "
            f"{permission_refresh_hint()}"
        )

    if target_app is not None and looks_like_timeout(clean_detail):
        return f"`{normalized_tool}` 这次超时了。{timeout_recovery_hint()}"

    return None


def permission_health_recovery_actions(
    check: dict[str, object],
) -> list[PermissionRecoveryAction]:
    key = str(check.get("key") or "").strip()
    status = str(check.get("status") or "").strip()
    summary = str(check.get("summary") or "").strip()
    detail = clean_permission_detail(str(check.get("detail") or ""))
    if not key or status == "ok":
        return []

    actions: list[PermissionRecoveryAction] = []

    if key == "current_process_accessibility":
        actions.append(_open_accessibility_action())
    elif key == "system_events_ui":
        if (
            looks_like_accessibility_denied(detail)
            or "辅助功能" in summary
            or "辅助功能" in detail
        ):
            actions.append(_open_accessibility_action())
        if (
            looks_like_automation_denied(detail)
            or "自动化" in summary
            or "自动化" in detail
        ):
            actions.append(_open_automation_action())
        if looks_like_timeout(detail):
            actions.append(_open_accessibility_action())
            actions.append(_open_automation_action())
    elif key == "calendar_automation":
        if "还没有任何日历" in summary:
            actions.append(_open_app_action("Calendar"))
        else:
            actions.append(_open_automation_action())
            actions.append(_open_app_action("Calendar"))
    elif key == "reminders_automation":
        if "还没有任何提醒列表" in summary:
            actions.append(_open_app_action("Reminders"))
        else:
            actions.append(_open_automation_action())
            actions.append(_open_app_action("Reminders"))
    elif key == "mail_automation":
        if "还没有任何邮箱账号" in summary:
            actions.append(_open_app_action("Mail"))
        else:
            actions.append(_open_automation_action())
            actions.append(_open_app_action("Mail"))

    if actions:
        actions.append(_refresh_action())
    return _dedupe_actions(actions)


def enrich_permission_health_check(check: dict[str, object]) -> dict[str, object]:
    row = dict(check or {})
    key = str(row.get("key") or "").strip()
    if key and not row.get("tools"):
        tools = _tools_for_key(key)
        if tools:
            row["tools"] = tools

    actions = permission_health_recovery_actions(row)
    if actions:
        row["actions"] = actions
    return row


def _join_labels(labels: list[str]) -> str:
    rows = [str(label).strip() for label in labels if str(label).strip()]
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0]
    if len(rows) == 2:
        return f"{rows[0]} 和 {rows[1]}"
    return "、".join(rows[:-1]) + f" 和 {rows[-1]}"


def build_permission_recovery_guide(
    checks: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> dict[str, object] | None:
    rows = [dict(check) for check in checks if isinstance(check, dict)]
    if not rows:
        return None

    guide_actions: list[PermissionRecoveryAction] = []
    status = "warning"
    needs_accessibility = False
    automation_targets: list[str] = []

    for row in rows:
        actions = [
            dict(action)
            for action in (row.get("actions") or [])
            if isinstance(action, dict)
        ]
        if not actions:
            continue

        action_ids = {
            str(action.get("id") or "").strip()
            for action in actions
            if str(action.get("id") or "").strip()
        }
        has_settings_action = any(
            action_id in {"open_accessibility_settings", "open_automation_settings"}
            for action_id in action_ids
        )
        if not has_settings_action:
            continue

        if str(row.get("status") or "").strip() == "error":
            status = "error"

        guide_actions.extend(actions)
        if "open_accessibility_settings" in action_ids:
            needs_accessibility = True

        key = str(row.get("key") or "").strip()
        if "open_automation_settings" in action_ids:
            if key == "system_events_ui":
                automation_targets.append("System Events")
            elif key == "calendar_automation":
                automation_targets.append("Calendar")
            elif key == "reminders_automation":
                automation_targets.append("Reminders")
            elif key == "mail_automation":
                automation_targets.append("Mail")

    guide_actions = _dedupe_actions(guide_actions)
    if not guide_actions:
        return None

    automation_targets = sorted(set(automation_targets))
    summary_parts: list[str] = []
    if needs_accessibility:
        summary_parts.append("辅助功能")
    if automation_targets:
        summary_parts.append("自动化")

    status_label = "先修权限"
    summary = "先按下面的顺序补权限，再回来点刷新。"
    if summary_parts:
        summary = f"先把{_join_labels(summary_parts)}补齐，再回来点刷新。"

    detail_lines: list[str] = []
    if needs_accessibility:
        detail_lines.append(accessibility_permission_hint())
    if automation_targets:
        target_text = "、".join(f"`{item}`" for item in automation_targets)
        detail_lines.append(
            "去 系统设置 -> 隐私与安全性 -> 自动化，确认 "
            f"{permission_sender_hint()} 仍被允许控制 {target_text}。"
        )

    return {
        "key": "permission_recovery_guide",
        "title": "恢复向导",
        "status": status,
        "status_label": status_label,
        "summary": summary,
        "detail": "\n".join(detail_lines),
        "hint": "可以直接点下面的按钮打开对应设置页；改完后回这里点一次“刷新”。",
        "tools": [],
        "actions": guide_actions,
    }


def _run_open_command(args: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except Exception as exc:
        return False, clean_permission_detail(str(exc))

    if proc.returncode == 0:
        return True, ""

    detail = clean_permission_detail(
        proc.stderr or proc.stdout or f"open exited with code {proc.returncode}"
    )
    return False, detail


def perform_permission_recovery_action(
    action: dict[str, object],
) -> tuple[bool, str]:
    kind = str(action.get("kind") or "").strip()
    label = str(action.get("label") or "").strip() or "恢复入口"
    target = str(action.get("target") or "").strip()

    if kind == "refresh":
        return True, "正在重新检查权限和运行环境..."

    if kind == "open_url":
        ok, detail = _run_open_command(["open", target])
        if not ok:
            fallback_ok, fallback_detail = _run_open_command(
                ["open", "-b", _SETTINGS_BUNDLE_ID]
            )
            if not fallback_ok:
                failure_detail = detail or fallback_detail or "打开系统设置失败"
                return False, f"没能打开 {label}。{failure_detail}"
            return (
                True,
                f"已打开系统设置。请切到“{label.replace('打开', '')}”对应分区处理，改完后回来点“刷新”。",
            )
        return True, f"已打开{label}。改完后回来点“刷新”。"

    if kind == "open_app":
        ok, detail = _run_open_command(["open", "-a", target])
        if not ok:
            return False, f"没能打开 {target}。{detail or '请手动检查应用是否存在。'}"
        return True, f"已尝试打开 {target}。准备好后回来点“刷新”。"

    return False, f"暂不认识这个恢复动作：{kind or 'unknown'}"
