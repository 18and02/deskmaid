"""Unified Calendar / Reminders / Mail regression entry for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_apple_apps_regression.py

This runner executes the Apple-app domain integration scripts in a stable order.
It runs cases when the local app store has the needed prerequisites, and skips
environment-sensitive cases when the local machine lacks the required data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPT_DIR))

from maid_tools import _run_jxa_json


REGRESSION_CASES: tuple[tuple[str, str, str], ...] = (
    ("list_calendar_events", "test_list_calendar_events_tool.py", "calendar_has_event"),
    ("calendar_write_tools", "test_calendar_write_tools.py", "calendar_has_calendar"),
    ("list_reminders", "test_list_reminders_tool.py", "reminders_has_list"),
    ("reminder_write_tools", "test_reminder_write_tools.py", "reminders_has_list"),
    ("read_unread_mail_headers", "test_read_unread_mail_headers_tool.py", "mail_has_unread"),
    ("read_mail_message", "test_read_mail_message_tool.py", "mail_has_unread"),
    ("mark_mail_read", "test_mark_mail_read_tool.py", "mail_has_unread"),
    ("create_mail_draft", "test_create_mail_draft_tool.py", "mail_has_drafts"),
    ("send_mail_draft", "test_send_mail_draft_tool.py", "mail_send_enabled"),
)


_CALENDAR_PREREQ_JXA = r"""
function run() {
  var app = Application("Calendar");
  var calendars = app.calendars();
  var names = [];
  var hasEvent = false;

  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    names.push(String(calendar.name() || ""));
    try {
      if (calendar.events().length > 0) {
        hasEvent = true;
      }
    } catch (error) {
    }
    if (hasEvent) {
      break;
    }
  }

  return JSON.stringify({
    has_calendar: calendars.length > 0,
    has_event: hasEvent,
    calendar_count: calendars.length,
    calendars: names.slice(0, 5)
  });
}
"""


_REMINDERS_PREREQ_JXA = r"""
function run() {
  var app = Application("Reminders");
  var lists = app.lists();
  var names = [];

  for (var i = 0; i < lists.length; i++) {
    names.push(String(lists[i].name() || ""));
  }

  return JSON.stringify({
    has_list: lists.length > 0,
    list_count: lists.length,
    lists: names.slice(0, 5)
  });
}
"""


_MAIL_PREREQ_JXA = r"""
function run() {
  var app = Application("Mail");
  var accounts = app.accounts();
  var names = [];
  var hasDraftsMailbox = false;
  var hasUnread = false;
  var hasAnyMessage = false;

  for (var i = 0; i < accounts.length; i++) {
    var account = accounts[i];
    names.push(String(account.name() || ""));

    try {
      if (account.mailboxes.byName("Drafts")()) {
        hasDraftsMailbox = true;
      }
    } catch (error) {
    }

    var mailboxes = [];
    try {
      mailboxes = account.mailboxes();
    } catch (error) {
      mailboxes = [];
    }

    for (var j = 0; j < mailboxes.length; j++) {
      var mailbox = mailboxes[j];
      try {
        if (mailbox.messages().length > 0) {
          hasAnyMessage = true;
        }
      } catch (error) {
      }
      try {
        if (mailbox.messages.whose({readStatus: false})().length > 0) {
          hasUnread = true;
        }
      } catch (error) {
      }
      if (hasDraftsMailbox && hasUnread && hasAnyMessage) {
        break;
      }
    }
  }

  return JSON.stringify({
    has_account: accounts.length > 0,
    has_drafts_mailbox: hasDraftsMailbox,
    has_unread: hasUnread,
    has_any_message: hasAnyMessage,
    account_count: accounts.length,
    accounts: names.slice(0, 5)
  });
}
"""


def _collect_prerequisites() -> dict[str, object]:
    send_to = str(os.environ.get("DESKMAID_SEND_MAIL_TEST_TO") or "").strip()
    return {
        "calendar": _run_jxa_json(_CALENDAR_PREREQ_JXA, {}),
        "reminders": _run_jxa_json(_REMINDERS_PREREQ_JXA, {}),
        "mail": _run_jxa_json(_MAIL_PREREQ_JXA, {}),
        "send_mail_opt_in": bool(send_to),
        "send_mail_target": send_to or None,
    }


def _print_prerequisites(snapshot: dict[str, object]):
    calendar = dict(snapshot.get("calendar") or {})
    reminders = dict(snapshot.get("reminders") or {})
    mail = dict(snapshot.get("mail") or {})
    send_target = snapshot.get("send_mail_target")

    print(
        "[precheck] calendar "
        f"count={int(calendar.get('calendar_count') or 0)} "
        f"has_event={bool(calendar.get('has_event'))}"
    )
    print(
        "[precheck] reminders "
        f"count={int(reminders.get('list_count') or 0)}"
    )
    print(
        "[precheck] mail "
        f"accounts={int(mail.get('account_count') or 0)} "
        f"has_drafts={bool(mail.get('has_drafts_mailbox'))} "
        f"has_unread={bool(mail.get('has_unread'))} "
        f"has_any_message={bool(mail.get('has_any_message'))}"
    )
    if send_target:
        print(f"[precheck] send_mail_draft enabled -> {send_target}")
    else:
        print("[precheck] send_mail_draft disabled (set DESKMAID_SEND_MAIL_TEST_TO to enable)")


def _skip_reason(prereq_key: str, snapshot: dict[str, object]) -> str | None:
    calendar = dict(snapshot.get("calendar") or {})
    reminders = dict(snapshot.get("reminders") or {})
    mail = dict(snapshot.get("mail") or {})
    send_mail_opt_in = bool(snapshot.get("send_mail_opt_in"))

    if prereq_key == "calendar_has_event":
        if not calendar.get("has_calendar"):
            return "no Calendar calendars found"
        if not calendar.get("has_event"):
            return "no Calendar events found"
        return None

    if prereq_key == "calendar_has_calendar":
        if not calendar.get("has_calendar"):
            return "no Calendar calendars found"
        return None

    if prereq_key == "reminders_has_list":
        if not reminders.get("has_list"):
            return "no Reminders lists found"
        return None

    if prereq_key == "mail_has_unread":
        if not mail.get("has_account"):
            return "no Mail accounts found"
        if not mail.get("has_unread"):
            return "no unread Mail messages found"
        return None

    if prereq_key == "mail_has_drafts":
        if not mail.get("has_account"):
            return "no Mail accounts found"
        if not mail.get("has_drafts_mailbox"):
            return "no Mail Drafts mailbox found"
        return None

    if prereq_key == "mail_send_enabled":
        if not mail.get("has_account"):
            return "no Mail accounts found"
        if not mail.get("has_drafts_mailbox"):
            return "no Mail Drafts mailbox found"
        if not send_mail_opt_in:
            return "send_mail_draft is opt-in; set DESKMAID_SEND_MAIL_TEST_TO to enable"
        return None

    return None


def _run_case(label: str, filename: str) -> tuple[int, float]:
    path = SCRIPT_DIR / filename
    if not path.is_file():
        print(f"[error] missing regression script for {label}: {path}", file=sys.stderr)
        return 1, 0.0

    cmd = [PYTHON, "-u", str(path)]
    print(f"\n=== {label} :: start ===")
    print(f"[cmd] {' '.join(cmd)}")
    started = time.monotonic()
    env = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix=f"deskmaid-{label}-") as tmp_dir:
        env["MAID_SESSION_STATE_PATH"] = str(Path(tmp_dir) / "session_state.json")
        env["MAID_APP_STATE_PATH"] = str(Path(tmp_dir) / "app_state.json")
        env["MAID_BUDGET_STATE_PATH"] = str(Path(tmp_dir) / "budget_state.json")
        completed = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR.parent),
            check=False,
            env=env,
        )
    duration_s = time.monotonic() - started
    print(
        f"=== {label} :: {'ok' if completed.returncode == 0 else 'failed'} "
        f"({duration_s:.2f}s) ==="
    )
    return completed.returncode, duration_s


def main():
    started = time.monotonic()
    failures: list[str] = []
    skipped: list[str] = []
    ran_count = 0

    try:
        prereq_snapshot = _collect_prerequisites()
    except Exception as exc:
        print(f"[error] failed to collect Apple-app prerequisites: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_prerequisites(prereq_snapshot)

    for label, filename, prereq_key in REGRESSION_CASES:
        reason = _skip_reason(prereq_key, prereq_snapshot)
        if reason:
            print(f"\n=== {label} :: skipped ===")
            print(f"[skip] {reason}")
            skipped.append(f"{label}: {reason}")
            continue

        ran_count += 1
        returncode, _ = _run_case(label, filename)
        if returncode != 0:
            failures.append(label)

    total_duration_s = time.monotonic() - started
    if failures:
        print(
            f"\n[error] Apple-app regression failed: {', '.join(failures)} "
            f"(ran {ran_count}, skipped {len(skipped)}, total {total_duration_s:.2f}s)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"\n[ok] Apple-app regression passed "
        f"(ran {ran_count}, skipped {len(skipped)}, total {total_duration_s:.2f}s)"
    )
    for item in skipped:
        print(f"[skip] {item}")


if __name__ == "__main__":
    main()
