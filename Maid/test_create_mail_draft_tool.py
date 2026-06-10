"""Standalone create_mail_draft MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_create_mail_draft_tool.py

The test asks Claude to explicitly call create_mail_draft for a unique draft,
auto-allows the permission prompt, verifies that the draft appears in Mail.app,
and then deletes the temporary draft.
"""

from __future__ import annotations

import json
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
    set_permission_handler,
    shutdown_maid_session,
)
from maid_tools import _run_jxa_json
from test_integration_helpers import (
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    print_chat_result,
)


CREATE_MAIL_DRAFT_TOOL_NAMES = {
    "create_mail_draft",
    "mcp__deskmaid_local__create_mail_draft",
}


_LOOKUP_DRAFT_JXA = r"""
function normalizeText(value) {
  if (value === null || value === undefined) {
    return null;
  }
  var text = String(value);
  return text.length ? text : null;
}

function normalizeBody(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value)
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

function recipientAddresses(recipients) {
  var addresses = [];
  var items = recipients();
  for (var i = 0; i < items.length; i++) {
    var recipient = items[i];
    try {
      var address = normalizeText(recipient.address());
      if (address) {
        addresses.push(address);
      }
    } catch (error) {
    }
  }
  return addresses;
}

function attachmentDetails(message) {
  var details = [];
  var items = [];
  try {
    items = message.mailAttachments();
  } catch (error) {
    return details;
  }
  for (var i = 0; i < items.length; i++) {
    var attachment = items[i];
    var sizeBytes = null;
    try {
      sizeBytes = Number(attachment.fileSize());
      if (isNaN(sizeBytes)) {
        sizeBytes = null;
      }
    } catch (error) {
      sizeBytes = null;
    }
    details.push({
      name: normalizeText(attachment.name()) || "",
      size_bytes: sizeBytes
    });
  }
  return details;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var subject = String(config.subject || "");
  var app = Application("Mail");
  var accounts = app.accounts();

  for (var i = 0; i < accounts.length; i++) {
    var account = accounts[i];
    var draftsMailbox = null;
    try {
      draftsMailbox = account.mailboxes.byName("Drafts")();
    } catch (error) {
      draftsMailbox = null;
    }
    if (!draftsMailbox) {
      continue;
    }

    var drafts = draftsMailbox.messages();
    for (var j = 0; j < drafts.length; j++) {
      var draft = drafts[j];
      if (String(draft.subject() || "") !== subject) {
        continue;
      }

      return JSON.stringify({
        found: true,
        account: account.name(),
        mailbox: draftsMailbox.name(),
        id: normalizeText(draft.id()),
        message_id: normalizeText(draft.messageId()),
        subject: normalizeText(draft.subject()) || "",
        sender: normalizeText(draft.sender()),
        to: recipientAddresses(draft.toRecipients),
        cc: recipientAddresses(draft.ccRecipients),
        bcc: recipientAddresses(draft.bccRecipients),
        body: normalizeBody(draft.content()),
        attachments: attachmentDetails(draft)
      });
    }
  }

  return JSON.stringify({found: false});
}
"""


_DELETE_DRAFT_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var targetSubject = String(config.subject || "");
  var app = Application("Mail");
  var deleted = 0;

  var accounts = app.accounts();
  for (var i = 0; i < accounts.length; i++) {
    var account = accounts[i];
    var draftsMailbox = null;
    try {
      draftsMailbox = account.mailboxes.byName("Drafts")();
    } catch (error) {
      draftsMailbox = null;
    }
    if (!draftsMailbox) {
      continue;
    }

    var drafts = draftsMailbox.messages();
    for (var j = drafts.length - 1; j >= 0; j--) {
      var draft = drafts[j];
      if (String(draft.subject() || "") !== targetSubject) {
        continue;
      }
      draft.delete();
      deleted += 1;
    }
  }

  return JSON.stringify({deleted: deleted});
}
"""


def _lookup_draft(subject: str) -> dict[str, object]:
    return _run_jxa_json(_LOOKUP_DRAFT_JXA, {"subject": subject})


def _wait_for_draft(subject: str) -> dict[str, object]:
    deadline = time.time() + 5.0
    last_status: dict[str, object] | None = None
    while time.time() < deadline:
        status = _lookup_draft(subject)
        last_status = status
        if status.get("found"):
            return status
        time.sleep(0.25)
    raise RuntimeError(f"draft {subject!r} did not appear; last status was {last_status!r}")


def _delete_draft(subject: str):
    if not subject:
        return
    result = _run_jxa_json(_DELETE_DRAFT_JXA, {"subject": subject})
    if int(result.get("deleted") or 0) < 1:
        raise RuntimeError(f"no draft deleted for subject {subject!r}")


def main():
    subject = f"deskmaid-test-draft-{uuid4().hex[:10]}"
    body = f"deskmaid integration draft body {uuid4().hex[:10]}"
    to_address = "deskmaid.to@example.com"
    cc_address = "deskmaid.cc@example.com"
    bcc_address = "deskmaid.bcc@example.com"
    attachment_file = NamedTemporaryFile(
        prefix="deskmaid-create-draft-attachment-",
        suffix=".txt",
        delete=False,
    )
    attachment_file.write(f"deskmaid attachment {uuid4().hex[:10]}\n".encode("utf-8"))
    attachment_file.close()
    attachment_path = str(Path(attachment_file.name).resolve())
    attachment_name = Path(attachment_path).name
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    draft_info: dict[str, object] | None = None
    result = None
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 create_mail_draft 集成测试。"
            "你必须调用名为 create_mail_draft 的工具。"
            f"参数 to=[{json.dumps(to_address, ensure_ascii=False)}]，"
            f"cc=[{json.dumps(cc_address, ensure_ascii=False)}]，"
            f"bcc=[{json.dumps(bcc_address, ensure_ascii=False)}]，"
            f"subject={json.dumps(subject, ensure_ascii=False)}，"
            f"body={json.dumps(body, ensure_ascii=False)}，"
            f"attachments=[{json.dumps(attachment_path, ensure_ascii=False)}]。"
            "调用成功后，只回复 drafted。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        result = ask_maid(prompt, trace_handler=on_trace)
        draft_info = _wait_for_draft(subject)
    except ChatConfigError as exc:
        run_error = (f"[error] {exc}", 2)
    except Exception as exc:
        run_error = (f"[error] {exc}", 1)
    finally:
        set_permission_handler(None)
        shutdown_maid_session()
        try:
            _delete_draft(subject)
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
        print(f"[error] failed to delete temporary draft: {cleanup_error}", file=sys.stderr)
        sys.exit(1)

    print_chat_result(result)

    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=CREATE_MAIL_DRAFT_TOOL_NAMES,
        label="create_mail_draft",
        tool_result_markers=[
            subject,
            to_address,
            cc_address,
            bcc_address,
            body,
            attachment_name,
        ],
        tool_result_description="the sample draft subject, recipients, or body",
    )

    if not draft_info or not draft_info.get("found"):
        print(f"[error] expected draft lookup to succeed, got {draft_info!r}", file=sys.stderr)
        sys.exit(1)
    if subject != str(draft_info.get("subject") or ""):
        print(
            f"[error] expected draft subject {subject!r}, got {draft_info.get('subject')!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if to_address not in (draft_info.get("to") or []):
        print(f"[error] expected to recipient {to_address!r}, got {draft_info!r}", file=sys.stderr)
        sys.exit(1)
    if cc_address not in (draft_info.get("cc") or []):
        print(f"[error] expected cc recipient {cc_address!r}, got {draft_info!r}", file=sys.stderr)
        sys.exit(1)
    if bcc_address not in (draft_info.get("bcc") or []):
        print(f"[error] expected bcc recipient {bcc_address!r}, got {draft_info!r}", file=sys.stderr)
        sys.exit(1)
    if body not in str(draft_info.get("body") or ""):
        print(f"[error] expected draft body to mention {body!r}, got {draft_info!r}", file=sys.stderr)
        sys.exit(1)
    attachment_names = [
        str(item.get("name") or "")
        for item in (draft_info.get("attachments") or [])
    ]
    if attachment_name not in attachment_names:
        print(
            f"[error] expected attachment {attachment_name!r}, got {draft_info!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if result.text.strip() != "drafted":
        print(
            f"[error] expected final reply 'drafted', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
