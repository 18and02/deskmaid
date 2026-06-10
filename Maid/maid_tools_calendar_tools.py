"""Calendar tool wrappers for the desktop maid."""

from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

from maid_tools_calendar_core import (
    CreateCalendarEventArgs,
    DEFAULT_CALENDAR_EVENT_LIMIT,
    DeleteCalendarEventArgs,
    ListCalendarEventsArgs,
    UpdateCalendarEventArgs,
    _create_calendar_event_sync,
    _delete_calendar_event_sync,
    _list_calendar_events_sync,
    _parse_create_calendar_event_args,
    _parse_delete_calendar_event_args,
    _parse_update_calendar_event_args,
    _update_calendar_event_sync,
)
from maid_tools_shared import (
    _normalize_calendar_names,
    _normalize_optional_text,
    _tool_error_result,
    _tool_success_result,
)


@tool(
    name="list_calendar_events",
    description=(
        "List events from macOS Calendar.app within a time range. Use this when the user "
        "asks about today's schedule, upcoming meetings, or events on a named calendar."
    ),
    input_schema=ListCalendarEventsArgs,
)
async def list_calendar_events(args: ListCalendarEventsArgs) -> dict:
    raw_calendars = (
        args.get("calendars")
        or args.get("calendar_names")
        or args.get("calendar")
    )

    try:
        result = await asyncio.to_thread(
            _list_calendar_events_sync,
            args.get("start"),
            args.get("end"),
            _normalize_calendar_names(raw_calendars),
            int(args.get("limit", DEFAULT_CALENDAR_EVENT_LIMIT)),
        )
    except Exception as exc:
        return _tool_error_result("list_calendar_events", exc)

    return _tool_success_result("list_calendar_events", result)


@tool(
    name="create_calendar_event",
    description=(
        "Create a new event in macOS Calendar.app. Use this when the user asks to "
        "schedule a meeting, add a calendar event, or block time on a calendar."
    ),
    input_schema=CreateCalendarEventArgs,
)
async def create_calendar_event(args: CreateCalendarEventArgs) -> dict:
    parsed = _parse_create_calendar_event_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _create_calendar_event_sync,
            parsed["summary"],
            parsed["start"],
            _normalize_optional_text(parsed["end"]),
            _normalize_optional_text(parsed["calendar"]),
            bool(parsed["all_day"]),
            None if parsed["location"] is None else str(parsed["location"]),
            None if parsed["notes"] is None else str(parsed["notes"]),
            None if parsed["url"] is None else str(parsed["url"]),
        )
    except Exception as exc:
        return _tool_error_result("create_calendar_event", exc)

    return _tool_success_result("create_calendar_event", result)


@tool(
    name="update_calendar_event",
    description=(
        "Update an existing event in macOS Calendar.app by id and calendar name. "
        "Use this to reschedule, rename, or otherwise edit a known event."
    ),
    input_schema=UpdateCalendarEventArgs,
)
async def update_calendar_event(args: UpdateCalendarEventArgs) -> dict:
    parsed = _parse_update_calendar_event_args(dict(args))
    has_any_update = any(
        [
            parsed["has_summary"],
            parsed["has_start"],
            parsed["has_end"],
            parsed["has_all_day"],
            parsed["has_location"],
            parsed["has_notes"],
            parsed["has_url"],
        ]
    )
    if not has_any_update:
        return _tool_error_result(
            "update_calendar_event",
            ValueError("no fields to update were provided"),
        )

    try:
        result = await asyncio.to_thread(
            _update_calendar_event_sync,
            parsed["id"],
            parsed["calendar"],
            summary=None if parsed["summary"] is None else str(parsed["summary"]),
            start=None if parsed["start"] is None else str(parsed["start"]),
            end=None if parsed["end"] is None else str(parsed["end"]),
            all_day=(bool(parsed["all_day"]) if parsed["has_all_day"] else None),
            location=None if parsed["location"] is None else str(parsed["location"]),
            notes=None if parsed["notes"] is None else str(parsed["notes"]),
            url=None if parsed["url"] is None else str(parsed["url"]),
            has_summary=bool(parsed["has_summary"]),
            has_start=bool(parsed["has_start"]),
            has_end=bool(parsed["has_end"]),
            has_all_day=bool(parsed["has_all_day"]),
            has_location=bool(parsed["has_location"]),
            has_notes=bool(parsed["has_notes"]),
            has_url=bool(parsed["has_url"]),
        )
    except Exception as exc:
        return _tool_error_result("update_calendar_event", exc)

    return _tool_success_result("update_calendar_event", result)


@tool(
    name="delete_calendar_event",
    description=(
        "Delete an existing event from macOS Calendar.app by id and calendar name. "
        "Use this when the user asks to cancel or remove a known event."
    ),
    input_schema=DeleteCalendarEventArgs,
)
async def delete_calendar_event(args: DeleteCalendarEventArgs) -> dict:
    parsed = _parse_delete_calendar_event_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _delete_calendar_event_sync,
            parsed["id"],
            parsed["calendar"],
        )
    except Exception as exc:
        return _tool_error_result("delete_calendar_event", exc)

    return _tool_success_result("delete_calendar_event", result)
