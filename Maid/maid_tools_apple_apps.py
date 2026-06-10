"""Calendar, Reminders, and Mail tool facade for the desktop maid."""

from __future__ import annotations

import maid_tools_calendar as _calendar_tools
import maid_tools_mail as _mail_tools
import maid_tools_reminders as _reminder_tools


_DOMAIN_MODULES = (
    _calendar_tools,
    _reminder_tools,
    _mail_tools,
)

for _module in _DOMAIN_MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__"):
            continue
        if _name in {
            "asyncio",
            "json",
            "time",
            "Annotated",
            "NotRequired",
            "Required",
            "TypedDict",
            "tool",
        }:
            continue
        if _name in globals():
            continue
        globals()[_name] = _value

del _module, _name, _value, _DOMAIN_MODULES, _calendar_tools, _reminder_tools, _mail_tools


def format_write_tool_receipt(tool_name: str, payload: dict[str, object]) -> str | None:
    if not tool_name or not isinstance(payload, dict):
        return None

    if tool_name == "create_calendar_event" or tool_name.endswith("__create_calendar_event"):
        event = dict(payload)
        return "\n".join(["日程已创建", *_format_calendar_event_receipt_lines(event)])

    if tool_name == "update_calendar_event" or tool_name.endswith("__update_calendar_event"):
        event = dict(payload.get("after") or {})
        if not event:
            return None
        return "\n".join(["日程已更新", *_format_calendar_event_receipt_lines(event)])

    if tool_name == "delete_calendar_event" or tool_name.endswith("__delete_calendar_event"):
        event = dict(payload.get("deleted") or payload.get("event") or {})
        if not event:
            return None
        return "\n".join(["日程已删除", *_format_calendar_event_receipt_lines(event)])

    if tool_name == "create_reminder" or tool_name.endswith("__create_reminder"):
        reminder = dict(payload)
        return "\n".join(["提醒已创建", *_format_reminder_receipt_lines(reminder)])

    if tool_name == "update_reminder" or tool_name.endswith("__update_reminder"):
        reminder = dict(payload.get("after") or {})
        if not reminder:
            return None
        return "\n".join(["提醒已更新", *_format_reminder_receipt_lines(reminder)])

    if tool_name == "delete_reminder" or tool_name.endswith("__delete_reminder"):
        reminder = dict(payload.get("deleted") or payload.get("reminder") or {})
        if not reminder:
            return None
        return "\n".join(["提醒已删除", *_format_reminder_receipt_lines(reminder)])

    if tool_name == "create_mail_draft" or tool_name.endswith("__create_mail_draft"):
        message = dict(payload)
        return "\n".join(["邮件草稿已保存", *_format_mail_receipt_lines(message)])

    if tool_name == "send_mail_draft" or tool_name.endswith("__send_mail_draft"):
        message = dict(payload)
        return "\n".join(
            [
                "邮件已发送",
                *_format_mail_receipt_lines(
                    message,
                    include_sender=True,
                    include_mailbox=True,
                ),
            ]
        )

    return None
