"""Mail draft-side tools for the desktop maid."""

from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

from maid_tools_mail_core import (
    CreateMailDraftArgs,
    format_create_mail_draft_preview,
    preview_create_mail_draft_request,
    _create_mail_draft_sync,
)
from maid_tools_shared import (
    _normalize_attachment_paths,
    _normalize_calendar_names,
    _tool_error_result,
    _tool_success_result,
)


@tool(
    name="create_mail_draft",
    description=(
        "Create a saved draft in macOS Mail without sending it. Supports both new drafts "
        "and reply drafts when a reply_to_id or reply_to_message_id is provided, and can "
        "optionally attach local files from attachments/attachment_paths."
    ),
    input_schema=CreateMailDraftArgs,
)
async def create_mail_draft(args: CreateMailDraftArgs) -> dict:
    raw_reply_accounts = (
        args.get("reply_accounts")
        or args.get("reply_account_names")
        or args.get("reply_account")
    )
    raw_reply_mailboxes = (
        args.get("reply_mailboxes")
        or args.get("reply_mailbox_names")
        or args.get("reply_mailbox")
    )
    raw_reply_message_id = (
        args.get("reply_to_message_id")
        or args.get("in_reply_to_message_id")
        or args.get("replyToMessageId")
    )
    raw_attachments = (
        args.get("attachments")
        or args.get("attachment_paths")
        or args.get("attachment")
    )

    try:
        result = await asyncio.to_thread(
            _create_mail_draft_sync,
            _normalize_calendar_names(args.get("to")),
            _normalize_calendar_names(args.get("cc")),
            _normalize_calendar_names(args.get("bcc")),
            args.get("subject"),
            args.get("body"),
            _normalize_attachment_paths(raw_attachments),
            args.get("reply_to_id") or args.get("in_reply_to_id"),
            raw_reply_message_id,
            _normalize_calendar_names(raw_reply_accounts),
            _normalize_calendar_names(raw_reply_mailboxes),
        )
    except Exception as exc:
        return _tool_error_result("create_mail_draft", exc)

    return _tool_success_result("create_mail_draft", result)
