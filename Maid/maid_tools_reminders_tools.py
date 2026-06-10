"""Reminders tool wrappers for the desktop maid."""

from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

from maid_tools_reminders_core import (
    CreateReminderArgs,
    DEFAULT_REMINDER_LIMIT,
    DeleteReminderArgs,
    ListRemindersArgs,
    UpdateReminderArgs,
    _create_reminder_sync,
    _delete_reminder_sync,
    _list_reminders_sync,
    _normalize_reminder_priority,
    _parse_create_reminder_args,
    _parse_delete_reminder_args,
    _parse_update_reminder_args,
    _update_reminder_sync,
)
from maid_tools_shared import (
    _normalize_calendar_names,
    _normalize_optional_text,
    _tool_error_result,
    _tool_success_result,
)


@tool(
    name="list_reminders",
    description=(
        "List reminders from macOS Reminders.app. Use this when the user asks about "
        "to-do items, reminder lists, or reminders due soon."
    ),
    input_schema=ListRemindersArgs,
)
async def list_reminders(args: ListRemindersArgs) -> dict:
    raw_lists = args.get("lists") or args.get("list_names") or args.get("list")

    try:
        result = await asyncio.to_thread(
            _list_reminders_sync,
            args.get("due_after"),
            args.get("due_before"),
            _normalize_calendar_names(raw_lists),
            bool(args.get("include_completed", False)),
            int(args.get("limit", DEFAULT_REMINDER_LIMIT)),
        )
    except Exception as exc:
        return _tool_error_result("list_reminders", exc)

    return _tool_success_result("list_reminders", result)


@tool(
    name="create_reminder",
    description=(
        "Create a new reminder in macOS Reminders.app. Use this when the user asks "
        "to add a to-do item, reminder, or task."
    ),
    input_schema=CreateReminderArgs,
)
async def create_reminder(args: CreateReminderArgs) -> dict:
    parsed = _parse_create_reminder_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _create_reminder_sync,
            parsed["name"],
            _normalize_optional_text(parsed["list"]),
            _normalize_optional_text(parsed["due_date"]),
            None if parsed["body"] is None else str(parsed["body"]),
            (
                _normalize_reminder_priority(parsed["priority"])
                if parsed["priority"] is not None
                else None
            ),
        )
    except Exception as exc:
        return _tool_error_result("create_reminder", exc)

    return _tool_success_result("create_reminder", result)


@tool(
    name="update_reminder",
    description=(
        "Update an existing reminder in macOS Reminders.app by id and list name. "
        "Use this to rename, reprioritize, change the due date, or mark a reminder "
        "completed or incomplete."
    ),
    input_schema=UpdateReminderArgs,
)
async def update_reminder(args: UpdateReminderArgs) -> dict:
    parsed = _parse_update_reminder_args(dict(args))
    has_any_update = any(
        [
            parsed["has_name"],
            parsed["has_due_date"],
            bool(parsed["clear_due_date"]),
            parsed["has_body"],
            parsed["has_priority"],
            parsed["has_completed"],
        ]
    )
    if not has_any_update:
        return _tool_error_result(
            "update_reminder",
            ValueError("no fields to update were provided"),
        )
    try:
        result = await asyncio.to_thread(
            _update_reminder_sync,
            parsed["id"],
            parsed["list"],
            name=None if parsed["name"] is None else str(parsed["name"]),
            due_date=None if parsed["due_date"] is None else str(parsed["due_date"]),
            body=None if parsed["body"] is None else str(parsed["body"]),
            priority=(
                _normalize_reminder_priority(parsed["priority"])
                if parsed["has_priority"]
                else None
            ),
            completed=(bool(parsed["completed"]) if parsed["has_completed"] else None),
            clear_due_date=bool(parsed["clear_due_date"]),
            has_name=bool(parsed["has_name"]),
            has_due_date=bool(parsed["has_due_date"]),
            has_body=bool(parsed["has_body"]),
            has_priority=bool(parsed["has_priority"]),
            has_completed=bool(parsed["has_completed"]),
        )
    except Exception as exc:
        return _tool_error_result("update_reminder", exc)

    return _tool_success_result("update_reminder", result)


@tool(
    name="delete_reminder",
    description=(
        "Delete an existing reminder from macOS Reminders.app by id and list name. "
        "Use this when the user asks to remove a known reminder."
    ),
    input_schema=DeleteReminderArgs,
)
async def delete_reminder(args: DeleteReminderArgs) -> dict:
    parsed = _parse_delete_reminder_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _delete_reminder_sync,
            parsed["id"],
            parsed["list"],
        )
    except Exception as exc:
        return _tool_error_result("delete_reminder", exc)

    return _tool_success_result("delete_reminder", result)
