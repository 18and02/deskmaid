"""Standalone read_unread_mail_headers MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_read_unread_mail_headers_tool.py

The test discovers one real unread message header from the local Mail.app
store, asks Claude to explicitly call read_unread_mail_headers for that
account/mailbox, auto-allows the permission prompt, and verifies that the
permission and trace path are both exercised.
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


READ_UNREAD_MAIL_HEADERS_TOOL_NAMES = {
    "read_unread_mail_headers",
    "mcp__deskmaid_local__read_unread_mail_headers",
}


_DISCOVER_SAMPLE_UNREAD_MAIL_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function isoOrNull(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var date = new Date(value);
  if (isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
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
        unread_count: unread.length,
        subject: normalizeText(message.subject()) || "",
        sender: normalizeText(message.sender()),
        date_received: isoOrNull(message.dateReceived())
      });
    }
  }

  return JSON.stringify({});
}
"""


def _discover_sample_unread_mail() -> dict[str, object]:
    sample = _run_jxa_json(_DISCOVER_SAMPLE_UNREAD_MAIL_JXA, {})
    if not sample.get("account") or not sample.get("mailbox"):
        raise RuntimeError("no unread mail found in the local Mail.app store")
    return sample


def main():
    try:
        sample = _discover_sample_unread_mail()
    except Exception as exc:
        print(f"[error] unable to discover a sample unread mail header: {exc}", file=sys.stderr)
        sys.exit(1)

    account_name = str(sample["account"])
    mailbox_name = str(sample["mailbox"])
    subject = str(sample.get("subject") or "")
    sender = str(sample.get("sender") or "")
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 read_unread_mail_headers 集成测试。"
            "你必须调用名为 read_unread_mail_headers 的工具。"
            f"参数 accounts=[{json.dumps(account_name, ensure_ascii=False)}]，"
            f"mailboxes=[{json.dumps(mailbox_name, ensure_ascii=False)}]，"
            "limit=5，newest_first=true。"
            "调用成功后，只回复 listed。"
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
        tool_names=READ_UNREAD_MAIL_HEADERS_TOOL_NAMES,
        label="read_unread_mail_headers",
        tool_result_markers=[account_name, mailbox_name, subject, sender],
        tool_result_description="the sample mail account, mailbox, subject, or sender",
    )

    if result.text.strip() != "listed":
        print(
            f"[error] expected final reply 'listed', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
