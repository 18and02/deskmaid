"""Mail send-side tools for the desktop maid."""

from __future__ import annotations

import asyncio

from claude_agent_sdk import tool

from maid_tools_mail_core import (
    SendMailDraftArgs,
    format_send_mail_draft_preview,
    preview_send_mail_draft_request,
    _parse_send_mail_draft_args,
    _send_mail_draft_sync,
)
from maid_tools_shared import _tool_error_result, _tool_success_result


@tool(
    name="send_mail_draft",
    description=(
        "Send a previously saved macOS Mail draft immediately. Use this only after the "
        "user has previewed and confirmed the exact draft to send."
    ),
    input_schema=SendMailDraftArgs,
)
async def send_mail_draft(args: SendMailDraftArgs) -> dict:
    parsed = _parse_send_mail_draft_args(args)

    try:
        result = await asyncio.to_thread(
            _send_mail_draft_sync,
            parsed["id"],
            parsed["message_id"],
            parsed["accounts"],
            parsed["mailboxes"],
            parsed["outgoing_id"],
        )
    except Exception as exc:
        return _tool_error_result("send_mail_draft", exc)

    return _tool_success_result("send_mail_draft", result)
