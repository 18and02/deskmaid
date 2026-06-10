"""Standalone Reminders write-chain MCP integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_reminder_write_tools.py

The test chooses one real Reminders.app list, then asks Claude to create,
update, and delete a unique reminder through the MCP tools. It verifies:
- the permission prompt path is exercised for each write tool
- the human preview text and confirm labels are present
- write tools cannot be remembered for the whole session
- the UI receipt text is produced via ChatResult.display_text
- the actual Reminders.app store reflects the create/update/delete lifecycle
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
    ChatResult,
    ChatTraceEvent,
    PermissionDecision,
    PermissionRequest,
    ask_maid,
    clear_remembered_tool_permissions,
    get_remembered_tool_permissions,
    set_permission_handler,
    shutdown_maid_session,
)
from maid_tools import _run_jxa_json


CREATE_REMINDER_TOOL_NAMES = {
    "create_reminder",
    "mcp__deskmaid_local__create_reminder",
}
UPDATE_REMINDER_TOOL_NAMES = {
    "update_reminder",
    "mcp__deskmaid_local__update_reminder",
}
DELETE_REMINDER_TOOL_NAMES = {
    "delete_reminder",
    "mcp__deskmaid_local__delete_reminder",
}


_DISCOVER_LIST_JXA = r"""
function run() {
  var app = Application("Reminders");
  var lists = app.lists();
  var names = [];
  for (var i = 0; i < lists.length; i++) {
    names.push(String(lists[i].name() || ""));
  }
  return JSON.stringify({
    found: names.length > 0,
    list: names.length ? names[0] : null,
    available_lists: names
  });
}
"""


_LOOKUP_REMINDER_JXA = r"""
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

function reminderRecord(reminder, listName) {
  return {
    id: normalizeText(reminder.id()),
    list: listName,
    name: normalizeText(reminder.name()) || "",
    body: normalizeText(reminder.body()),
    due_date: isoOrNull(reminder.dueDate()),
    completed: !!reminder.completed(),
    completion_date: isoOrNull(reminder.completionDate()),
    creation_date: isoOrNull(reminder.creationDate()),
    modification_date: isoOrNull(reminder.modificationDate()),
    priority: Number(reminder.priority())
  };
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var requestedList = String(config.list || "");
  var targetId = normalizeText(config.id);
  var targetName = normalizeText(config.name);
  var app = Application("Reminders");
  var lists = app.lists();
  var availableNames = [];
  var selected = null;

  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var name = String(list.name() || "");
    availableNames.push(name);
    if (name === requestedList) {
      selected = list;
    }
  }

  if (!selected) {
    return JSON.stringify({
      list_found: false,
      found: false,
      available_lists: availableNames
    });
  }

  var reminders = selected.reminders();
  for (var j = 0; j < reminders.length; j++) {
    var reminder = reminders[j];
    if (targetId && normalizeText(reminder.id()) !== targetId) {
      continue;
    }
    if (targetName && (normalizeText(reminder.name()) || "") !== targetName) {
      continue;
    }
    return JSON.stringify({
      list_found: true,
      found: true,
      reminder: reminderRecord(reminder, requestedList)
    });
  }

  return JSON.stringify({
    list_found: true,
    found: false,
    available_lists: availableNames
  });
}
"""


_DELETE_REMINDERS_BY_NAME_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var requestedList = String(config.list || "");
  var targetNames = Array.isArray(config.names) ? config.names : [];
  var lookup = {};
  for (var i = 0; i < targetNames.length; i++) {
    lookup[String(targetNames[i] || "")] = true;
  }

  var app = Application("Reminders");
  var lists = app.lists();
  var selected = null;
  for (var j = 0; j < lists.length; j++) {
    var list = lists[j];
    if (String(list.name() || "") === requestedList) {
      selected = list;
      break;
    }
  }
  if (!selected) {
    return JSON.stringify({deleted: 0});
  }

  var deleted = 0;
  var reminders = selected.reminders();
  for (var k = reminders.length - 1; k >= 0; k--) {
    var reminder = reminders[k];
    var name = String(reminder.name() || "");
    if (!lookup[name]) {
      continue;
    }
    reminder.delete();
    deleted += 1;
  }

  return JSON.stringify({deleted: deleted});
}
"""


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()


def _discover_list_name() -> str:
    result = _run_jxa_json(_DISCOVER_LIST_JXA, {})
    list_name = str(result.get("list") or "").strip()
    if not list_name:
        raise RuntimeError("no reminder lists found in the local Reminders.app store")
    return list_name


def _lookup_reminder(
    list_name: str,
    *,
    reminder_id: str | None = None,
    name: str | None = None,
) -> dict[str, object]:
    return _run_jxa_json(
        _LOOKUP_REMINDER_JXA,
        {
            "list": list_name,
            "id": reminder_id,
            "name": name,
        },
    )


def _wait_for_reminder(
    list_name: str,
    *,
    reminder_id: str | None = None,
    name: str | None = None,
    timeout_s: float = 12.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last_state: dict[str, object] | None = None
    while time.time() < deadline:
        state = _lookup_reminder(
            list_name,
            reminder_id=reminder_id,
            name=name,
        )
        last_state = state
        if state.get("found"):
            return dict(state.get("reminder") or {})
        time.sleep(0.4)
    raise RuntimeError(
        f"reminder did not appear in list {list_name!r}; last state was {last_state!r}"
    )


def _wait_for_reminder_absent(
    list_name: str,
    *,
    reminder_id: str,
    timeout_s: float = 12.0,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = _lookup_reminder(list_name, reminder_id=reminder_id)
        if not state.get("found"):
            return True
        time.sleep(0.4)
    return False


def _cleanup_reminders(list_name: str, names: list[str]):
    if not list_name or not names:
        return
    result = _run_jxa_json(
        _DELETE_REMINDERS_BY_NAME_JXA,
        {
            "list": list_name,
            "names": names,
        },
    )
    print(
        f"[cleanup] deleted={int(result.get('deleted') or 0)} "
        f"list={list_name!r} names={names!r}"
    )


def _run_agent_prompt(
    prompt: str,
) -> tuple[ChatResult, list[PermissionRequest], list[ChatTraceEvent], list[str]]:
    clear_remembered_tool_permissions()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []

    def auto_allow(request: PermissionRequest) -> PermissionDecision:
        seen_requests.append(request)
        print(
            f"[perm] tool={request.tool_name} allow_remember={request.allow_remember} "
            f"confirm_label={request.confirm_label!r}"
        )
        print(f"[perm] preview=\n{request.preview_text}")
        return PermissionDecision(allow=True, remember_tool=True)

    def on_trace(event: ChatTraceEvent):
        events.append(event)
        print(f"[trace] {event.kind}: {event.title} :: {event.detail}")

    set_permission_handler(auto_allow)
    try:
        result = ask_maid(prompt, trace_handler=on_trace)
        remembered_after = get_remembered_tool_permissions()
    finally:
        set_permission_handler(None)
        shutdown_maid_session()

    return result, seen_requests, events, remembered_after


def _print_result(label: str, result: ChatResult):
    print(f"<<< {label}: {result.text}")
    print(
        f"    (session={result.session_id} in={result.input_tokens} "
        f"out={result.output_tokens} stop={result.stop_reason} "
        f"dur={result.duration_ms}ms cost={result.total_cost_usd})"
    )
    if result.display_text and result.display_text != result.text:
        print(f"    display=\n{result.display_text}")


def _assert_trace_coverage(
    *,
    events: list[ChatTraceEvent],
    tool_names: set[str],
    label: str,
):
    kinds = [event.kind for event in events]
    for required in (
        "run_started",
        "permission_request",
        "permission_decision",
        "tool_use",
        "result",
    ):
        if required not in kinds:
            raise RuntimeError(f"{label}: missing trace event kind {required!r}")

    if not any(
        event.kind == "tool_use" and event.tool_name in tool_names
        for event in events
    ):
        raise RuntimeError(f"{label}: missing tool_use trace for {tool_names}")


def _assert_step(
    *,
    label: str,
    result: ChatResult,
    expected_reply: str,
    expected_receipt_markers: list[str],
    seen_requests: list[PermissionRequest],
    tool_names: set[str],
    expected_confirm_label: str,
    preview_markers: list[str],
    remembered_after: list[str],
    events: list[ChatTraceEvent],
):
    if result.text.strip() != expected_reply:
        raise RuntimeError(
            f"{label}: expected final reply {expected_reply!r}, got {result.text!r}"
        )

    display_text = str(result.display_text or "").strip()
    if not display_text:
        raise RuntimeError(f"{label}: expected non-empty display_text receipt")
    for marker in expected_receipt_markers:
        if marker not in display_text:
            raise RuntimeError(
                f"{label}: expected display_text to include {marker!r}, got {display_text!r}"
            )

    matching_requests = [
        request for request in seen_requests if request.tool_name in tool_names
    ]
    if not matching_requests:
        raise RuntimeError(
            f"{label}: expected permission request for {tool_names}, got {seen_requests!r}"
        )

    request = matching_requests[0]
    if request.allow_remember:
        raise RuntimeError(f"{label}: write tool should not allow remember")
    if request.confirm_label != expected_confirm_label:
        raise RuntimeError(
            f"{label}: expected confirm label {expected_confirm_label!r}, got {request.confirm_label!r}"
        )
    preview_text = str(request.preview_text or "").strip()
    if not preview_text:
        raise RuntimeError(f"{label}: expected non-empty preview text")
    for marker in preview_markers:
        if marker not in preview_text:
            raise RuntimeError(
                f"{label}: expected preview text to include {marker!r}, got {preview_text!r}"
            )

    if remembered_after:
        raise RuntimeError(
            f"{label}: expected no remembered tools after run, got {remembered_after!r}"
        )

    _assert_trace_coverage(events=events, tool_names=tool_names, label=label)


def _assert_datetimes_close(actual_raw: str, expected: datetime, label: str):
    actual = _parse_iso_datetime(actual_raw)
    delta_s = abs((actual - expected.astimezone(actual.tzinfo)).total_seconds())
    if delta_s > 61:
        raise RuntimeError(
            f"{label}: expected {expected.isoformat()}, got {actual.isoformat()}"
        )


def main():
    list_name = ""
    create_name = f"deskmaid-reminder-create-{uuid4().hex[:10]}"
    update_name = f"deskmaid-reminder-update-{uuid4().hex[:10]}"
    create_body = f"deskmaid reminder create body {uuid4().hex[:8]}"
    update_body = f"deskmaid reminder update body {uuid4().hex[:8]}"
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None

    try:
        list_name = _discover_list_name()
        create_due = (
            datetime.now().astimezone() + timedelta(days=2, hours=2)
        ).replace(second=0, microsecond=0)
        update_due = create_due + timedelta(days=1, hours=1)

        create_prompt = (
            "这是一次 Reminders 写入链路集成测试（创建阶段）。"
            "你必须调用名为 create_reminder 的工具。"
            f"参数 name={json.dumps(create_name, ensure_ascii=False)}，"
            f"list={json.dumps(list_name, ensure_ascii=False)}，"
            f"due_date={json.dumps(create_due.isoformat(), ensure_ascii=False)}，"
            f"body={json.dumps(create_body, ensure_ascii=False)}，"
            "priority=1。"
            "调用成功后，只回复 created。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        create_result, create_requests, create_events, create_remembered = _run_agent_prompt(
            create_prompt
        )
        _print_result("Reminder create", create_result)
        _assert_step(
            label="create_reminder",
            result=create_result,
            expected_reply="created",
            expected_receipt_markers=["提醒已创建", create_name, list_name],
            seen_requests=create_requests,
            tool_names=CREATE_REMINDER_TOOL_NAMES,
            expected_confirm_label="确认创建",
            preview_markers=[create_name, list_name, create_body],
            remembered_after=create_remembered,
            events=create_events,
        )

        created_reminder = _wait_for_reminder(list_name, name=create_name)
        reminder_id = str(created_reminder.get("id") or "").strip()
        if not reminder_id:
            raise RuntimeError(f"create_reminder: missing reminder id {created_reminder!r}")
        if str(created_reminder.get("name") or "") != create_name:
            raise RuntimeError(f"create_reminder: unexpected name {created_reminder!r}")
        if str(created_reminder.get("list") or "") != list_name:
            raise RuntimeError(f"create_reminder: unexpected list {created_reminder!r}")
        if str(created_reminder.get("body") or "") != create_body:
            raise RuntimeError(f"create_reminder: unexpected body {created_reminder!r}")
        if int(created_reminder.get("priority") or 0) != 1:
            raise RuntimeError(f"create_reminder: unexpected priority {created_reminder!r}")
        _assert_datetimes_close(str(created_reminder.get("due_date") or ""), create_due, "create due")

        update_prompt = (
            "这是一次 Reminders 写入链路集成测试（更新阶段）。"
            "你必须调用名为 update_reminder 的工具。"
            f"参数 id={json.dumps(reminder_id, ensure_ascii=False)}，"
            f"list={json.dumps(list_name, ensure_ascii=False)}，"
            f"name={json.dumps(update_name, ensure_ascii=False)}，"
            f"due_date={json.dumps(update_due.isoformat(), ensure_ascii=False)}，"
            f"body={json.dumps(update_body, ensure_ascii=False)}，"
            "priority=6，completed=true。"
            "调用成功后，只回复 updated。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        update_result, update_requests, update_events, update_remembered = _run_agent_prompt(
            update_prompt
        )
        _print_result("Reminder update", update_result)
        _assert_step(
            label="update_reminder",
            result=update_result,
            expected_reply="updated",
            expected_receipt_markers=["提醒已更新", update_name, list_name, "已完成"],
            seen_requests=update_requests,
            tool_names=UPDATE_REMINDER_TOOL_NAMES,
            expected_confirm_label="确认更新",
            preview_markers=[create_name, update_name, update_body, "当前：", "更新后：", "已完成: 是"],
            remembered_after=update_remembered,
            events=update_events,
        )

        updated_reminder = _wait_for_reminder(list_name, reminder_id=reminder_id)
        if str(updated_reminder.get("name") or "") != update_name:
            raise RuntimeError(f"update_reminder: unexpected name {updated_reminder!r}")
        if str(updated_reminder.get("body") or "") != update_body:
            raise RuntimeError(f"update_reminder: unexpected body {updated_reminder!r}")
        if int(updated_reminder.get("priority") or 0) != 6:
            raise RuntimeError(f"update_reminder: unexpected priority {updated_reminder!r}")
        if not bool(updated_reminder.get("completed")):
            raise RuntimeError(f"update_reminder: expected completed reminder {updated_reminder!r}")
        _assert_datetimes_close(str(updated_reminder.get("due_date") or ""), update_due, "update due")

        delete_prompt = (
            "这是一次 Reminders 写入链路集成测试（删除阶段）。"
            "你必须调用名为 delete_reminder 的工具。"
            f"参数 id={json.dumps(reminder_id, ensure_ascii=False)}，"
            f"list={json.dumps(list_name, ensure_ascii=False)}。"
            "调用成功后，只回复 deleted。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        delete_result, delete_requests, delete_events, delete_remembered = _run_agent_prompt(
            delete_prompt
        )
        _print_result("Reminder delete", delete_result)
        _assert_step(
            label="delete_reminder",
            result=delete_result,
            expected_reply="deleted",
            expected_receipt_markers=["提醒已删除", update_name, list_name],
            seen_requests=delete_requests,
            tool_names=DELETE_REMINDER_TOOL_NAMES,
            expected_confirm_label="确认删除",
            preview_markers=[update_name, list_name],
            remembered_after=delete_remembered,
            events=delete_events,
        )

        if not _wait_for_reminder_absent(list_name, reminder_id=reminder_id):
            raise RuntimeError(
                f"delete_reminder: reminder {reminder_id!r} is still present in {list_name!r}"
            )

    except ChatConfigError as exc:
        run_error = (f"[error] {exc}", 2)
    except Exception as exc:
        run_error = (f"[error] {exc}", 1)
    finally:
        try:
            _cleanup_reminders(list_name, [create_name, update_name])
        except Exception as exc:
            cleanup_error = str(exc)

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] failed to clean up temporary reminders: {cleanup_error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
