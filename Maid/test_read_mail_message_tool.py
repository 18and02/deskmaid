"""Standalone read_mail_message MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_read_mail_message_tool.py

The test discovers one real message from the local Mail.app store, asks Claude
to explicitly call read_mail_message for that account/mailbox/message id,
auto-allows the permission prompt, and verifies that the permission and trace
path are both exercised.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import (
    ChatConfigError,
    ChatTraceEvent,
    PermissionRequest,
    ask_maid,
    set_permission_handler,
    shutdown_maid_session,
)
from maid_tools import _run_jxa_json
from test_integration_helpers import (
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    print_chat_result,
)


READ_MAIL_MESSAGE_TOOL_NAMES = {
    "read_mail_message",
    "mcp__deskmaid_local__read_mail_message",
}


_DISCOVER_SAMPLE_MAIL_MESSAGE_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function run(argv) {
  var app = Application("Mail");
  var accounts = app.accounts();

  for (var i = 0; i < accounts.length; i++) {
    var account = accounts[i];
    var accountName = account.name();
    var mailboxes = account.mailboxes();
    for (var j = 0; j < mailboxes.length; j++) {
      var mailbox = mailboxes[j];
      var unread = mailbox.messages.whose({readStatus: false})();
      if (!unread.length) {
        continue;
      }

      var message = unread[0];
      return JSON.stringify({
        account: accountName,
        mailbox: mailbox.name(),
        id: String(message.id()),
        message_id: normalizeText(message.messageId()),
        subject: normalizeText(message.subject()) || "",
        sender: normalizeText(message.sender())
      });
    }
  }

  return JSON.stringify({});
}
"""


def _discover_sample_mail_message() -> dict[str, object]:
    sample = _run_jxa_json(_DISCOVER_SAMPLE_MAIL_MESSAGE_JXA, {})
    if not sample.get("account") or not sample.get("mailbox") or not sample.get("id"):
        raise RuntimeError("no readable mail message found in the local Mail.app store")
    return sample


def main():
    try:
        sample = _discover_sample_mail_message()
    except Exception as exc:
        print(f"[error] unable to discover a sample mail message: {exc}", file=sys.stderr)
        sys.exit(1)

    account_name = str(sample["account"])
    mailbox_name = str(sample["mailbox"])
    local_id = str(sample["id"])
    message_id = str(sample.get("message_id") or "")
    subject = str(sample.get("subject") or "")
    sender = str(sample.get("sender") or "")
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 read_mail_message 集成测试。"
            "你必须调用名为 read_mail_message 的工具。"
            f"参数 account={json.dumps(account_name, ensure_ascii=False)}，"
            f"mailbox={json.dumps(mailbox_name, ensure_ascii=False)}，"
            f"id={json.dumps(local_id, ensure_ascii=False)}，"
            f"message_id={json.dumps(message_id, ensure_ascii=False)}，"
            "max_body_chars=600。"
            "调用成功后，只回复 read。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        result = ask_maid(prompt, trace_handler=on_trace)
    except ChatConfigError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        set_permission_handler(None)
        shutdown_maid_session()

    print_chat_result(result)

    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=READ_MAIL_MESSAGE_TOOL_NAMES,
        label="read_mail_message",
        tool_result_markers=[
            account_name,
            mailbox_name,
            local_id,
            message_id,
            subject,
            sender,
        ],
        tool_result_description="the sample mail account, mailbox, ids, subject, or sender",
    )

    if result.text.strip() != "read":
        print(
            f"[error] expected final reply 'read', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
