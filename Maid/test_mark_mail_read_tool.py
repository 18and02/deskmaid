"""Standalone mark_mail_read MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_mark_mail_read_tool.py

The test discovers one real unread message from the local Mail.app store, asks
Claude to explicitly call mark_mail_read for that account/mailbox/message id,
auto-allows the permission prompt, verifies that the message becomes read, and
then restores the message back to unread.
"""

from __future__ import annotations

import json
import sys
import time
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
    final_reply_matches,
    print_chat_result,
)


MARK_MAIL_READ_TOOL_NAMES = {
    "mark_mail_read",
    "mcp__deskmaid_local__mark_mail_read",
}


_DISCOVER_SAMPLE_UNREAD_MAIL_JXA = r"""
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


_LOOKUP_MAIL_STATUS_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function findMessage(mailbox, targetId, targetMessageId) {
  var candidates;
  if (targetId) {
    var numericId = Number(targetId);
    if (isNaN(numericId)) {
      candidates = mailbox.messages();
    } else {
      candidates = mailbox.messages.whose({id: numericId})();
    }
  } else {
    candidates = mailbox.messages.whose({messageId: targetMessageId})();
  }

  for (var i = 0; i < candidates.length; i++) {
    var message = candidates[i];
    var candidateId = normalizeText(message.id());
    var candidateMessageId = normalizeText(message.messageId());
    if (targetId && candidateId !== targetId) {
      continue;
    }
    if (targetMessageId && candidateMessageId !== targetMessageId) {
      continue;
    }
    return message;
  }

  return null;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var app = Application("Mail");
  var account = app.accounts.byName(String(config.account || ""))();
  if (!account) {
    return JSON.stringify({found: false, reason: "account_not_found"});
  }
  var mailbox = account.mailboxes.byName(String(config.mailbox || ""))();
  if (!mailbox) {
    return JSON.stringify({found: false, reason: "mailbox_not_found"});
  }

  var message = findMessage(
    mailbox,
    normalizeText(config.id),
    normalizeText(config.message_id)
  );
  if (!message) {
    return JSON.stringify({found: false, reason: "message_not_found"});
  }

  return JSON.stringify({
    found: true,
    read_status: !!message.readStatus(),
    subject: normalizeText(message.subject()) || "",
    sender: normalizeText(message.sender())
  });
}
"""


_SET_MAIL_STATUS_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function findMessage(mailbox, targetId, targetMessageId) {
  var candidates;
  if (targetId) {
    var numericId = Number(targetId);
    if (isNaN(numericId)) {
      candidates = mailbox.messages();
    } else {
      candidates = mailbox.messages.whose({id: numericId})();
    }
  } else {
    candidates = mailbox.messages.whose({messageId: targetMessageId})();
  }

  for (var i = 0; i < candidates.length; i++) {
    var message = candidates[i];
    var candidateId = normalizeText(message.id());
    var candidateMessageId = normalizeText(message.messageId());
    if (targetId && candidateId !== targetId) {
      continue;
    }
    if (targetMessageId && candidateMessageId !== targetMessageId) {
      continue;
    }
    return message;
  }

  return null;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var app = Application("Mail");
  var account = app.accounts.byName(String(config.account || ""))();
  if (!account) {
    return JSON.stringify({updated: false, reason: "account_not_found"});
  }
  var mailbox = account.mailboxes.byName(String(config.mailbox || ""))();
  if (!mailbox) {
    return JSON.stringify({updated: false, reason: "mailbox_not_found"});
  }

  var message = findMessage(
    mailbox,
    normalizeText(config.id),
    normalizeText(config.message_id)
  );
  if (!message) {
    return JSON.stringify({updated: false, reason: "message_not_found"});
  }

  message.readStatus = !!config.read_status;
  delay(0.1);
  return JSON.stringify({
    updated: true,
    read_status: !!message.readStatus()
  });
}
"""


def _discover_sample_unread_mail() -> dict[str, object]:
    sample = _run_jxa_json(_DISCOVER_SAMPLE_UNREAD_MAIL_JXA, {})
    if not sample.get("account") or not sample.get("mailbox") or not sample.get("id"):
        raise RuntimeError("no unread mail found in the local Mail.app store")
    return sample


def _lookup_mail_status(sample: dict[str, object]) -> dict[str, object]:
    return _run_jxa_json(
        _LOOKUP_MAIL_STATUS_JXA,
        {
            "account": sample["account"],
            "mailbox": sample["mailbox"],
            "id": sample["id"],
            "message_id": sample.get("message_id"),
        },
    )


def _set_mail_status(sample: dict[str, object], read_status: bool):
    result = _run_jxa_json(
        _SET_MAIL_STATUS_JXA,
        {
            "account": sample["account"],
            "mailbox": sample["mailbox"],
            "id": sample["id"],
            "message_id": sample.get("message_id"),
            "read_status": bool(read_status),
        },
    )
    if not result.get("updated"):
        raise RuntimeError(f"failed to update mail read status: {result}")


def _wait_for_read_status(sample: dict[str, object], expected: bool) -> dict[str, object]:
    deadline = time.time() + 5.0
    last_status: dict[str, object] | None = None
    while time.time() < deadline:
        status = _lookup_mail_status(sample)
        last_status = status
        if status.get("found") and bool(status.get("read_status")) is expected:
            return status
        time.sleep(0.25)
    raise RuntimeError(
        f"mail read status did not become {expected}; last status was {last_status!r}"
    )


def main():
    try:
        sample = _discover_sample_unread_mail()
        _wait_for_read_status(sample, False)
    except Exception as exc:
        print(f"[error] unable to prepare a sample unread mail: {exc}", file=sys.stderr)
        sys.exit(1)

    account_name = str(sample["account"])
    mailbox_name = str(sample["mailbox"])
    local_id = str(sample["id"])
    message_id = str(sample.get("message_id") or "")
    subject = str(sample.get("subject") or "")
    sender = str(sample.get("sender") or "")
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None
    status_after_tool: dict[str, object] | None = None

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 mark_mail_read 集成测试。"
            "你必须调用名为 mark_mail_read 的工具。"
            f"参数 account={json.dumps(account_name, ensure_ascii=False)}，"
            f"mailbox={json.dumps(mailbox_name, ensure_ascii=False)}，"
            f"id={json.dumps(local_id, ensure_ascii=False)}，"
            f"message_id={json.dumps(message_id, ensure_ascii=False)}。"
            "调用成功后，只回复 marked。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        result = ask_maid(prompt, trace_handler=on_trace)
        status_after_tool = _wait_for_read_status(sample, True)
    except ChatConfigError as exc:
        run_error = (f"[error] {exc}", 2)
    except Exception as exc:
        run_error = (f"[error] {exc}", 1)
    finally:
        set_permission_handler(None)
        shutdown_maid_session()
        try:
            _set_mail_status(sample, False)
            _wait_for_read_status(sample, False)
        except Exception as exc:
            cleanup_error = str(exc)

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] failed to restore sample mail to unread: {cleanup_error}", file=sys.stderr)
        sys.exit(1)

    print_chat_result(result)

    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=MARK_MAIL_READ_TOOL_NAMES,
        label="mark_mail_read",
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

    if not status_after_tool or not bool(status_after_tool.get("read_status")):
        print(
            f"[error] expected the sample mail to become read, got {status_after_tool!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not final_reply_matches(result.text, "marked"):
        print(
            f"[error] expected final reply 'marked', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
