"""Standalone list_reminders MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_list_reminders_tool.py

The test creates a temporary reminder in the local Reminders.app store, asks
Claude to explicitly call list_reminders for that list and due window,
auto-allows the permission prompt, and verifies that the permission and trace
path are both exercised. The temporary reminder is deleted at the end.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import sys
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
from maid_tools import _list_reminders_sync, _run_jxa_json
from test_integration_helpers import (
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    print_chat_result,
)


LIST_REMINDERS_TOOL_NAMES = {
    "list_reminders",
    "mcp__deskmaid_local__list_reminders",
}


_CREATE_SAMPLE_REMINDER_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var app = Application("Reminders");
  var lists = app.lists();
  if (!lists.length) {
    throw new Error("no reminder lists found");
  }

  var selected = config.list_name
    ? app.lists.byName(String(config.list_name))()
    : lists[0];
  var dueDate = new Date(config.due_date);
  if (isNaN(dueDate.getTime())) {
    throw new Error("invalid due_date");
  }

  var reminder = app.Reminder({
    name: String(config.name || ""),
    body: String(config.body || ""),
    dueDate: dueDate,
    priority: Number(config.priority || 0)
  });
  selected.reminders.push(reminder);

  return JSON.stringify({
    list: selected.name(),
    name: String(config.name || ""),
    due_date: dueDate.toISOString()
  });
}
"""


_DELETE_SAMPLE_REMINDER_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var targetName = String(config.name || "");
  if (!targetName.length) {
    return JSON.stringify({deleted: 0});
  }

  var app = Application("Reminders");
  var lists = app.lists();
  var deleted = 0;
  for (var i = 0; i < lists.length; i++) {
    var reminders = lists[i].reminders();
    for (var j = reminders.length - 1; j >= 0; j--) {
      var reminder = reminders[j];
      if (String(reminder.name()) !== targetName) {
        continue;
      }
      reminder.delete();
      deleted += 1;
    }
  }

  return JSON.stringify({deleted: deleted});
}
"""


def _create_sample_reminder() -> tuple[dict[str, object], str, str]:
    due_dt = datetime.now().astimezone() + timedelta(days=1)
    name = f"deskmaid-test-reminder-{uuid4().hex[:10]}"
    body = "temporary reminder for deskmaid integration test"
    sample = _run_jxa_json(
        _CREATE_SAMPLE_REMINDER_JXA,
        {
            "name": name,
            "body": body,
            "due_date": due_dt.isoformat(),
            "priority": 1,
        },
    )
    due_after = (due_dt - timedelta(hours=12)).isoformat()
    due_before = (due_dt + timedelta(hours=12)).isoformat()
    return sample, due_after, due_before


def _cleanup_sample_reminder(name: str):
    if not name:
        return
    try:
        _run_jxa_json(_DELETE_SAMPLE_REMINDER_JXA, {"name": name})
    except Exception as exc:
        print(f"[warn] failed to clean up temporary reminder {name!r}: {exc}", file=sys.stderr)


def _wait_until_visible(name: str, list_name: str, due_after: str, due_before: str):
    for _ in range(6):
        result = _list_reminders_sync(
            due_after=due_after,
            due_before=due_before,
            lists=[list_name],
            include_completed=False,
            limit=20,
        )
        if any(str(item.get("name") or "") == name for item in result.get("reminders") or []):
            return
        time.sleep(0.5)
    raise RuntimeError(f"temporary reminder {name!r} did not appear in list {list_name!r}")


def main():
    sample_name = ""
    try:
        sample, due_after, due_before = _create_sample_reminder()
        sample_name = str(sample["name"])
        list_name = str(sample["list"])
        _wait_until_visible(sample_name, list_name, due_after, due_before)
    except Exception as exc:
        print(f"[error] unable to prepare a sample reminder: {exc}", file=sys.stderr)
        sys.exit(1)

    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 list_reminders 集成测试。"
            "你必须调用名为 list_reminders 的工具。"
            f"参数 lists=[{json.dumps(list_name, ensure_ascii=False)}]，"
            f"due_after={json.dumps(due_after, ensure_ascii=False)}，"
            f"due_before={json.dumps(due_before, ensure_ascii=False)}，"
            "include_completed=false，limit=5。"
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
        _cleanup_sample_reminder(sample_name)

    print_chat_result(result)

    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=LIST_REMINDERS_TOOL_NAMES,
        label="list_reminders",
        tool_result_markers=[sample_name, list_name],
        tool_result_description="the sample reminder or list",
    )

    if not final_reply_matches(result.text, "listed"):
        print(
            f"[error] expected final reply 'listed', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
