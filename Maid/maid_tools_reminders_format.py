"""Reminders preview and receipt formatting for the desktop maid."""

from __future__ import annotations

from maid_tools_apple_common import (
    _format_boolean_label,
    _format_preview_datetime,
    _format_priority_label,
    _format_receipt_datetime,
    _format_receipt_priority,
    _trim_preview_block,
)
from maid_tools_reminders_core import (
    _lookup_reminder_sync,
    _normalize_reminder_priority,
    _parse_create_reminder_args,
    _parse_delete_reminder_args,
    _parse_update_reminder_args,
    _resolve_reminder_list_target_sync,
)
from maid_tools_shared import (
    _normalize_required_text,
    _parse_time_range_value,
)


def _reminder_preview_lines(reminder: dict[str, object], include_id: bool = True) -> list[str]:
    lines = [
        f"标题: {str(reminder.get('name') or '').strip() or '（无标题）'}",
        f"列表: {str(reminder.get('list') or reminder.get('selected_list') or '').strip() or '（未指定）'}",
        f"截止: {_format_preview_datetime(reminder.get('due_date'))}",
        f"已完成: {_format_boolean_label(reminder.get('completed'))}",
        f"优先级: {_format_priority_label(reminder.get('priority'))}",
        f"备注: {_trim_preview_block(str(reminder.get('body') or ''), limit=220)}",
    ]
    if include_id:
        lines.append(f"提醒 id: {str(reminder.get('id') or '').strip() or '（无）'}")
    return lines


def preview_create_reminder_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_create_reminder_args(args)
    resolved = _resolve_reminder_list_target_sync(parsed["list"])
    due_date = None
    if parsed["due_date"] is not None:
        due_date = _parse_time_range_value(
            _normalize_required_text(parsed["due_date"], "due_date"),
            end_of_day=True,
        ).isoformat()
    priority = (
        _normalize_reminder_priority(parsed["priority"])
        if parsed["priority"] is not None
        else 0
    )
    return {
        "action": "create",
        "name": _normalize_required_text(parsed["name"], "name"),
        "list": str(resolved["list"]),
        "selected_list": str(resolved["list"]),
        "due_date": due_date,
        "body": "" if parsed["body"] is None else str(parsed["body"]),
        "priority": priority,
        "completed": False,
        "available_lists": resolved["available_lists"],
        "used_default_list": bool(resolved["used_default_list"]),
    }


def format_create_reminder_preview(preview: dict[str, object]) -> str:
    lines = ["将要创建的提醒：", *_reminder_preview_lines(preview, include_id=False)]
    if preview.get("used_default_list"):
        lines.append("说明: 没指定列表，所以会写进第一个可用列表。")
    return "\n".join(lines)


def preview_update_reminder_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_update_reminder_args(args)
    if not any(
        [
            parsed["has_name"],
            parsed["has_due_date"],
            bool(parsed["clear_due_date"]),
            parsed["has_body"],
            parsed["has_priority"],
            parsed["has_completed"],
        ]
    ):
        raise ValueError("no fields to update were provided")
    if parsed["clear_due_date"]:
        raise ValueError(
            "clear_due_date is not supported by macOS Reminders scripting"
        )
    before = _lookup_reminder_sync(
        _normalize_required_text(parsed["id"], "id"),
        _normalize_required_text(parsed["list"], "list"),
    )
    after = dict(before)
    if parsed["clear_due_date"] and parsed["has_due_date"]:
        raise ValueError("due_date and clear_due_date cannot be used together")
    if parsed["has_name"]:
        after["name"] = _normalize_required_text(parsed["name"], "name")
    if parsed["has_due_date"]:
        after["due_date"] = _parse_time_range_value(
            _normalize_required_text(parsed["due_date"], "due_date"),
            end_of_day=True,
        ).isoformat()
    elif parsed["clear_due_date"]:
        after["due_date"] = None
    if parsed["has_body"]:
        after["body"] = "" if parsed["body"] is None else str(parsed["body"])
    if parsed["has_priority"]:
        after["priority"] = _normalize_reminder_priority(parsed["priority"])
    if parsed["has_completed"]:
        after["completed"] = bool(parsed["completed"])
    return {
        "action": "update",
        "before": before,
        "after": after,
    }


def format_update_reminder_preview(preview: dict[str, object]) -> str:
    before = dict(preview.get("before") or {})
    after = dict(preview.get("after") or {})
    return "\n".join(
        [
            "将要更新的提醒：",
            "",
            "当前：",
            *_reminder_preview_lines(before),
            "",
            "更新后：",
            *_reminder_preview_lines(after),
        ]
    )


def preview_delete_reminder_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_delete_reminder_args(args)
    reminder = _lookup_reminder_sync(
        _normalize_required_text(parsed["id"], "id"),
        _normalize_required_text(parsed["list"], "list"),
    )
    return {
        "action": "delete",
        "reminder": reminder,
    }


def format_delete_reminder_preview(preview: dict[str, object]) -> str:
    reminder = dict(preview.get("reminder") or {})
    return "\n".join(
        ["将要删除的提醒：", *_reminder_preview_lines(reminder)]
    )


def _format_reminder_receipt_lines(reminder: dict[str, object]) -> list[str]:
    lines = [
        f"事项: {str(reminder.get('name') or '').strip() or '（无标题）'}",
        f"列表: {str(reminder.get('list') or reminder.get('selected_list') or '').strip() or '（未指定）'}",
        f"截止: {_format_receipt_datetime(reminder.get('due_date'))}",
        f"状态: {'已完成' if bool(reminder.get('completed')) else '未完成'}",
    ]
    priority = _format_receipt_priority(reminder.get("priority"))
    if priority:
        lines.append(f"优先级: {priority}")
    return lines
