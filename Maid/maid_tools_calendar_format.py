"""Calendar preview and receipt formatting for the desktop maid."""

from __future__ import annotations

from datetime import timedelta

from maid_tools_apple_common import (
    _format_boolean_label,
    _format_calendar_receipt_window,
    _format_calendar_time_window,
    _trim_preview_block,
)
from maid_tools_calendar_core import (
    DEFAULT_CALENDAR_EVENT_DURATION_MINUTES,
    _lookup_calendar_event_sync,
    _parse_create_calendar_event_args,
    _parse_delete_calendar_event_args,
    _parse_update_calendar_event_args,
    _resolve_calendar_target_sync,
)
from maid_tools_shared import (
    _normalize_optional_text,
    _normalize_required_text,
    _parse_time_range_value,
)


def _calendar_event_preview_lines(event: dict[str, object], include_id: bool = True) -> list[str]:
    lines = [
        f"标题: {str(event.get('summary') or '').strip() or '（无标题）'}",
        f"日历: {str(event.get('calendar') or event.get('selected_calendar') or '').strip() or '（未指定）'}",
        f"时间: {_format_calendar_time_window(event.get('start'), event.get('end'), all_day=bool(event.get('all_day')))}",
        f"全天: {_format_boolean_label(event.get('all_day'))}",
        f"地点: {str(event.get('location') or '').strip() or '（无）'}",
        f"备注: {_trim_preview_block(str(event.get('notes') or ''), limit=220)}",
        f"URL: {str(event.get('url') or '').strip() or '（无）'}",
    ]
    if include_id:
        lines.append(f"事件 id: {str(event.get('id') or '').strip() or '（无）'}")
    return lines


def preview_create_calendar_event_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_create_calendar_event_args(args)
    resolved = _resolve_calendar_target_sync(parsed["calendar"])
    start_dt = _parse_time_range_value(
        _normalize_required_text(parsed["start"], "start"),
        end_of_day=False,
    )
    if parsed["all_day"]:
        start_dt = start_dt.astimezone().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    raw_end = _normalize_optional_text(parsed["end"])
    if raw_end:
        end_dt = _parse_time_range_value(raw_end, end_of_day=bool(parsed["all_day"]))
    else:
        end_dt = start_dt + (
            timedelta(days=1)
            if parsed["all_day"]
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )
    if end_dt <= start_dt:
        raise ValueError("end must be later than start")
    return {
        "action": "create",
        "summary": _normalize_required_text(parsed["summary"], "summary"),
        "calendar": str(resolved["calendar"]),
        "selected_calendar": str(resolved["calendar"]),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "all_day": bool(parsed["all_day"]),
        "location": "" if parsed["location"] is None else str(parsed["location"]),
        "notes": "" if parsed["notes"] is None else str(parsed["notes"]),
        "url": "" if parsed["url"] is None else str(parsed["url"]),
        "available_calendars": resolved["available_calendars"],
        "used_default_calendar": bool(resolved["used_default_calendar"]),
    }


def format_create_calendar_event_preview(preview: dict[str, object]) -> str:
    lines = ["将要创建的日历事件：", *_calendar_event_preview_lines(preview, include_id=False)]
    if preview.get("used_default_calendar"):
        lines.append("说明: 没指定日历，所以会写进第一个可用日历。")
    return "\n".join(lines)


def preview_update_calendar_event_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_update_calendar_event_args(args)
    if not any(
        [
            parsed["has_summary"],
            parsed["has_start"],
            parsed["has_end"],
            parsed["has_all_day"],
            parsed["has_location"],
            parsed["has_notes"],
            parsed["has_url"],
        ]
    ):
        raise ValueError("no fields to update were provided")
    existing = _lookup_calendar_event_sync(
        _normalize_required_text(parsed["id"], "id"),
        _normalize_required_text(parsed["calendar"], "calendar"),
    )
    existing_start_dt = _parse_time_range_value(
        _normalize_required_text(existing.get("start"), "start"),
        end_of_day=False,
    )
    existing_end_dt = _parse_time_range_value(
        _normalize_required_text(existing.get("end"), "end"),
        end_of_day=False,
    )
    current_duration = existing_end_dt - existing_start_dt
    if current_duration.total_seconds() <= 0:
        current_duration = (
            timedelta(days=1)
            if bool(existing.get("all_day"))
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )

    after = dict(existing)
    final_all_day = bool(parsed["all_day"]) if parsed["has_all_day"] else bool(existing.get("all_day"))
    start_dt = existing_start_dt
    end_dt = existing_end_dt
    if parsed["has_start"]:
        start_dt = _parse_time_range_value(
            _normalize_required_text(parsed["start"], "start"),
            end_of_day=False,
        )
    if final_all_day:
        start_dt = start_dt.astimezone().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    if parsed["has_end"]:
        end_dt = _parse_time_range_value(
            _normalize_required_text(parsed["end"], "end"),
            end_of_day=final_all_day,
        )
    elif parsed["has_start"]:
        end_dt = start_dt + (
            timedelta(days=1) if final_all_day else current_duration
        )
    elif parsed["has_all_day"] and final_all_day != bool(existing.get("all_day")):
        end_dt = start_dt + (
            timedelta(days=1)
            if final_all_day
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )
    if end_dt <= start_dt:
        raise ValueError("end must be later than start")

    if parsed["has_summary"]:
        after["summary"] = _normalize_required_text(parsed["summary"], "summary")
    if parsed["has_start"] or parsed["has_end"] or parsed["has_all_day"]:
        after["start"] = start_dt.isoformat()
        after["end"] = end_dt.isoformat()
    if parsed["has_all_day"]:
        after["all_day"] = final_all_day
    if parsed["has_location"]:
        after["location"] = "" if parsed["location"] is None else str(parsed["location"])
    if parsed["has_notes"]:
        after["notes"] = "" if parsed["notes"] is None else str(parsed["notes"])
    if parsed["has_url"]:
        after["url"] = "" if parsed["url"] is None else str(parsed["url"])
    return {
        "action": "update",
        "before": existing,
        "after": after,
    }


def format_update_calendar_event_preview(preview: dict[str, object]) -> str:
    before = dict(preview.get("before") or {})
    after = dict(preview.get("after") or {})
    lines = [
        "将要更新的日历事件：",
        "",
        "当前：",
        *_calendar_event_preview_lines(before),
        "",
        "更新后：",
        *_calendar_event_preview_lines(after),
    ]
    return "\n".join(lines)


def preview_delete_calendar_event_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_delete_calendar_event_args(args)
    event = _lookup_calendar_event_sync(
        _normalize_required_text(parsed["id"], "id"),
        _normalize_required_text(parsed["calendar"], "calendar"),
    )
    return {
        "action": "delete",
        "event": event,
    }


def format_delete_calendar_event_preview(preview: dict[str, object]) -> str:
    event = dict(preview.get("event") or {})
    return "\n".join(
        ["将要删除的日历事件：", *_calendar_event_preview_lines(event)]
    )


def _format_calendar_event_receipt_lines(event: dict[str, object]) -> list[str]:
    lines = [
        f"事项: {str(event.get('summary') or '').strip() or '（无标题）'}",
        (
            "时间: "
            + _format_calendar_receipt_window(
                event.get("start"),
                event.get("end"),
                all_day=bool(event.get("all_day")),
            )
        ),
        f"日历: {str(event.get('calendar') or event.get('selected_calendar') or '').strip() or '（未指定）'}",
    ]
    location = str(event.get("location") or "").strip()
    if location:
        lines.append(f"地点: {location}")
    return lines
