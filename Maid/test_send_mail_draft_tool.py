"""Standalone send_mail_draft MCP tool integration test for the maid backend.

Usage:
    DESKMAID_SEND_MAIL_TEST_TO=someone@example.com .venv/bin/python -u Maid/test_send_mail_draft_tool.py

The test creates a unique Mail draft directly, asks Claude to explicitly call
send_mail_draft for it, verifies that the permission request includes a human
preview and cannot be remembered for the whole session, then confirms that the
draft leaves Drafts after send.
"""

from __future__ import annotations

import json
import os
import sys
from tempfile import NamedTemporaryFile
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import (
    ChatConfigError,
    ChatTraceEvent,
    PermissionRequest,
    ask_maid,
    clear_remembered_tool_permissions,
    get_remembered_tool_permissions,
    set_permission_handler,
    shutdown_maid_session,
)
from maid_tools import _create_mail_draft_sync, _run_jxa_json
from test_integration_helpers import (
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    print_chat_result,
)


SEND_MAIL_DRAFT_TOOL_NAMES = {
    "send_mail_draft",
    "mcp__deskmaid_local__send_mail_draft",
}


_LOOKUP_MAIL_STATE_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var subject = String(config.subject || "");
  var app = Application("Mail");
  var drafts = [];
  var mailboxMatches = [];
  var outgoing = [];

  var liveDrafts = app.outgoingMessages();
  for (var i = 0; i < liveDrafts.length; i++) {
    var draft = liveDrafts[i];
    if (String(draft.subject() || "") !== subject) {
      continue;
    }
    outgoing.push({
      outgoing_id: normalizeText(draft.id()),
      subject: normalizeText(draft.subject()) || ""
    });
  }

  var accounts = app.accounts();
  for (var a = 0; a < accounts.length; a++) {
    var account = accounts[a];
    var accountName = account.name();
    var mailboxes = account.mailboxes();
    for (var m = 0; m < mailboxes.length; m++) {
      var mailbox = mailboxes[m];
      var mailboxName = mailbox.name();
      var messages = mailbox.messages();
      for (var j = 0; j < messages.length; j++) {
        var message = messages[j];
        if (String(message.subject() || "") !== subject) {
          continue;
        }
        var row = {
          account: accountName,
          mailbox: mailboxName,
          id: normalizeText(message.id()),
          message_id: normalizeText(message.messageId()),
          subject: normalizeText(message.subject()) || ""
        };
        mailboxMatches.push(row);
        if (mailboxName === "Drafts") {
          drafts.push(row);
        }
      }
    }
  }

  return JSON.stringify({
    drafts: drafts,
    mailbox_matches: mailboxMatches,
    outgoing: outgoing
  });
}
"""


_DELETE_MESSAGES_BY_SUBJECT_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var subject = String(config.subject || "");
  var app = Application("Mail");
  var deletedOutgoing = 0;
  var deletedMessages = 0;

  var liveDrafts = app.outgoingMessages();
  for (var i = liveDrafts.length - 1; i >= 0; i--) {
    var draft = liveDrafts[i];
    if (String(draft.subject() || "") !== subject) {
      continue;
    }
    try {
      draft.delete();
      deletedOutgoing += 1;
    } catch (error) {
    }
  }

  var accounts = app.accounts();
  for (var a = 0; a < accounts.length; a++) {
    var account = accounts[a];
    var mailboxes = account.mailboxes();
    for (var m = 0; m < mailboxes.length; m++) {
      var mailbox = mailboxes[m];
      var messages = mailbox.messages();
      for (var j = messages.length - 1; j >= 0; j--) {
        var message = messages[j];
        if (String(message.subject() || "") !== subject) {
          continue;
        }
        try {
          message.delete();
          deletedMessages += 1;
        } catch (error) {
        }
      }
    }
  }

  return JSON.stringify({
    deleted_outgoing: deletedOutgoing,
    deleted_messages: deletedMessages
  });
}
"""


def _lookup_mail_state(subject: str) -> dict[str, object]:
    return _run_jxa_json(_LOOKUP_MAIL_STATE_JXA, {"subject": subject})


def _wait_for_mail_state(subject: str, *, drafts: int | None = None, outgoing: int | None = None) -> dict[str, object]:
    deadline = time.time() + 15.0
    last_state: dict[str, object] | None = None
    while time.time() < deadline:
        state = _lookup_mail_state(subject)
        last_state = state
        drafts_ok = drafts is None or len(state.get("drafts") or []) == drafts
        outgoing_ok = outgoing is None or len(state.get("outgoing") or []) == outgoing
        if drafts_ok and outgoing_ok:
            return state
        time.sleep(0.4)
    raise RuntimeError(
        f"mail state for {subject!r} did not reach the expected counts; last state was {last_state!r}"
    )


def _delete_messages_by_subject(subject: str):
    if not subject:
        return
    _run_jxa_json(_DELETE_MESSAGES_BY_SUBJECT_JXA, {"subject": subject})


def main():
    clear_remembered_tool_permissions()
    to_address = os.environ.get(
        "DESKMAID_SEND_MAIL_TEST_TO",
        "deskmaid.send.test@example.com",
    ).strip() or "deskmaid.send.test@example.com"
    subject = f"deskmaid-test-send-{uuid4().hex[:10]}"
    body = f"这是 Deskmaid send_mail_draft 集成测试邮件，可忽略。token={uuid4().hex[:10]}"
    attachment_file = NamedTemporaryFile(
        prefix="deskmaid-send-draft-attachment-",
        suffix=".txt",
        delete=False,
    )
    attachment_file.write(f"deskmaid send attachment {uuid4().hex[:10]}\n".encode("utf-8"))
    attachment_file.close()
    attachment_path = str(Path(attachment_file.name).resolve())
    attachment_name = Path(attachment_path).name
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None
    state_after_send: dict[str, object] | None = None
    remembered_after_send: list[str] = []

    draft = _create_mail_draft_sync(
        to=[to_address],
        subject=subject,
        body=body,
        attachments=[attachment_path],
    )
    _wait_for_mail_state(subject, drafts=1, outgoing=1)

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(
        seen_requests,
        events,
        remember_tool=True,
        print_preview=True,
    )

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 send_mail_draft 集成测试。"
            "你必须调用名为 send_mail_draft 的工具。"
            f"参数 id={json.dumps(str(draft.get('id') or ''), ensure_ascii=False)}，"
            f"message_id={json.dumps(str(draft.get('message_id') or ''), ensure_ascii=False)}，"
            f"outgoing_id={json.dumps(str(draft.get('outgoing_id') or ''), ensure_ascii=False)}，"
            f"account={json.dumps(str(draft.get('account') or ''), ensure_ascii=False)}，"
            f"mailbox={json.dumps(str(draft.get('mailbox') or ''), ensure_ascii=False)}。"
            "调用成功后，只回复 sent。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        result = ask_maid(prompt, trace_handler=on_trace)
        state_after_send = _wait_for_mail_state(subject, drafts=0)
        remembered_after_send = get_remembered_tool_permissions()
    except ChatConfigError as exc:
        run_error = (f"[error] {exc}", 2)
    except Exception as exc:
        run_error = (f"[error] {exc}", 1)
    finally:
        set_permission_handler(None)
        shutdown_maid_session()
        try:
            _delete_messages_by_subject(subject)
        except Exception as exc:
            cleanup_error = str(exc)
        try:
            Path(attachment_path).unlink(missing_ok=True)
        except Exception:
            pass

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] failed to delete local test messages: {cleanup_error}", file=sys.stderr)
        sys.exit(1)

    print_chat_result(result)

    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=SEND_MAIL_DRAFT_TOOL_NAMES,
        label="send_mail_draft",
    )

    send_requests = [
        request for request in seen_requests if request.tool_name in SEND_MAIL_DRAFT_TOOL_NAMES
    ]
    if not send_requests:
        print(
            "[error] expected permission request for send_mail_draft MCP tool, "
            f"got {seen_requests!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    first_request = send_requests[0]
    if first_request.allow_remember:
        print("[error] send_mail_draft should not allow session-wide remember", file=sys.stderr)
        sys.exit(1)
    if first_request.confirm_label != "确认发送":
        print(
            f"[error] expected confirm label '确认发送', got {first_request.confirm_label!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    for marker in (subject, to_address, body, attachment_name):
        if marker not in first_request.preview_text:
            print(
                f"[error] expected preview text to include {marker!r}, got {first_request.preview_text!r}",
                file=sys.stderr,
            )
            sys.exit(1)

    if remembered_after_send:
        print(
            "[error] expected send_mail_draft to remain unremembered, "
            f"got {remembered_after_send}",
            file=sys.stderr,
        )
        sys.exit(1)

    permission_events = [event for event in events if event.kind == "permission_request"]
    if permission_events and not any(
        subject in event.detail and to_address in event.detail
        for event in permission_events
    ):
        print(
            "[error] expected permission_request trace to include the previewed draft subject and recipient, "
            f"got {permission_events!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if state_after_send is None:
        print("[error] missing post-send state lookup", file=sys.stderr)
        sys.exit(1)
    if state_after_send.get("drafts"):
        print(
            f"[error] expected the test draft to leave Drafts, got {state_after_send!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if result.text.strip() != "sent":
        print(
            f"[error] expected final reply 'sent', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
