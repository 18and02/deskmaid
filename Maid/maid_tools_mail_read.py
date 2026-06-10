"""Mail read-side tools for the desktop maid."""

from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

from maid_tools_mail_core import (
    DEFAULT_MAIL_BODY_CHAR_LIMIT,
    DEFAULT_MAIL_HEADER_LIMIT,
    MarkMailReadArgs,
    ReadMailMessageArgs,
    ReadUnreadMailHeadersArgs,
    _mark_mail_read_sync,
    _read_mail_message_sync,
    _read_unread_mail_headers_sync,
)
from maid_tools_shared import _normalize_calendar_names, _tool_error_result, _tool_success_result


@tool(
    name="read_unread_mail_headers",
    description=(
        "Read unread mail headers from macOS Mail without fetching message bodies. "
        "Use this when the user asks about unread emails, inbox headers, or who sent new mail."
    ),
    input_schema=ReadUnreadMailHeadersArgs,
)
async def read_unread_mail_headers(args: ReadUnreadMailHeadersArgs) -> dict:
    raw_accounts = args.get("accounts") or args.get("account_names") or args.get("account")
    raw_mailboxes = args.get("mailboxes") or args.get("mailbox_names") or args.get("mailbox")

    try:
        result = await asyncio.to_thread(
            _read_unread_mail_headers_sync,
            _normalize_calendar_names(raw_accounts),
            _normalize_calendar_names(raw_mailboxes),
            int(args.get("limit", DEFAULT_MAIL_HEADER_LIMIT)),
            bool(args.get("newest_first", True)),
        )
    except Exception as exc:
        return _tool_error_result("read_unread_mail_headers", exc)

    return _tool_success_result("read_unread_mail_headers", result)


@tool(
    name="read_mail_message",
    description=(
        "Read a specific message from macOS Mail, including the message body text. "
        "Use this when the user asks to open or read a particular email after identifying it "
        "by id, message_id, account, or mailbox."
    ),
    input_schema=ReadMailMessageArgs,
)
async def read_mail_message(args: ReadMailMessageArgs) -> dict:
    raw_accounts = (
        args.get("accounts")
        or args.get("account_names")
        or args.get("account")
    )
    raw_mailboxes = (
        args.get("mailboxes")
        or args.get("mailbox_names")
        or args.get("mailbox")
    )
    raw_message_id = args.get("message_id") or args.get("messageId")

    try:
        result = await asyncio.to_thread(
            _read_mail_message_sync,
            args.get("id"),
            raw_message_id,
            _normalize_calendar_names(raw_accounts),
            _normalize_calendar_names(raw_mailboxes),
            int(args.get("max_body_chars", DEFAULT_MAIL_BODY_CHAR_LIMIT)),
        )
    except Exception as exc:
        return _tool_error_result("read_mail_message", exc)

    return _tool_success_result("read_mail_message", result)


@tool(
    name="mark_mail_read",
    description=(
        "Mark a specific macOS Mail message as read. Use this when the user asks to "
        "mark an email as read after identifying it by id, message_id, account, or mailbox."
    ),
    input_schema=MarkMailReadArgs,
)
async def mark_mail_read(args: MarkMailReadArgs) -> dict:
    raw_accounts = (
        args.get("accounts")
        or args.get("account_names")
        or args.get("account")
    )
    raw_mailboxes = (
        args.get("mailboxes")
        or args.get("mailbox_names")
        or args.get("mailbox")
    )
    raw_message_id = args.get("message_id") or args.get("messageId")

    try:
        result = await asyncio.to_thread(
            _mark_mail_read_sync,
            args.get("id"),
            raw_message_id,
            _normalize_calendar_names(raw_accounts),
            _normalize_calendar_names(raw_mailboxes),
        )
    except Exception as exc:
        return _tool_error_result("mark_mail_read", exc)

    return _tool_success_result("mark_mail_read", result)
