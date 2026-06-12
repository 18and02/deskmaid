"""Standalone Calendar write-chain MCP integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_calendar_write_tools.py

The test chooses one real Calendar.app calendar, then asks Claude to create,
update, and delete a unique event through the MCP tools. It verifies:
- the permission prompt path is exercised for each write tool
- the human preview text and confirm labels are present
- write tools cannot be remembered for the whole session
- the UI receipt text is produced via ChatResult.display_text
- the actual Calendar.app store reflects the create/update/delete lifecycle
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
from test_integration_helpers import final_reply_matches


CREATE_CALENDAR_EVENT_TOOL_NAMES = {
    "create_calendar_event",
    "mcp__deskmaid_local__create_calendar_event",
}
UPDATE_CALENDAR_EVENT_TOOL_NAMES = {
    "update_calendar_event",
    "mcp__deskmaid_local__update_calendar_event",
}
DELETE_CALENDAR_EVENT_TOOL_NAMES = {
    "delete_calendar_event",
    "mcp__deskmaid_local__delete_calendar_event",
}


_DISCOVER_CALENDAR_JXA = r"""
function run() {
  var app = Application("Calendar");
  var calendars = app.calendars();
  var names = [];
  for (var i = 0; i < calendars.length; i++) {
    names.push(String(calendars[i].name() || ""));
  }
  return JSON.stringify({
    found: names.length > 0,
    calendar: names.length ? names[0] : null,
    available_calendars: names
  });
}
"""


_LOOKUP_EVENT_JXA = r"""
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

function eventRecord(event, calendarName) {
  return {
    id: normalizeText(event.id()),
    calendar: calendarName,
    summary: normalizeText(event.summary()) || "",
    start: isoOrNull(event.startDate()),
    end: isoOrNull(event.endDate()),
    all_day: !!event.alldayEvent(),
    location: normalizeText(event.location()),
    notes: normalizeText(event.description()),
    url: normalizeText(event.url())
  };
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var requestedCalendar = String(config.calendar || "");
  var targetId = normalizeText(config.id);
  var targetSummary = normalizeText(config.summary);
  var app = Application("Calendar");
  var calendars = app.calendars();
  var availableNames = [];
  var selected = null;

  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var name = String(calendar.name() || "");
    availableNames.push(name);
    if (name === requestedCalendar) {
      selected = calendar;
    }
  }

  if (!selected) {
    return JSON.stringify({
      calendar_found: false,
      found: false,
      available_calendars: availableNames
    });
  }

  var events = selected.events();
  for (var j = 0; j < events.length; j++) {
    var event = events[j];
    if (targetId && normalizeText(event.id()) !== targetId) {
      continue;
    }
    if (targetSummary && (normalizeText(event.summary()) || "") !== targetSummary) {
      continue;
    }
    return JSON.stringify({
      calendar_found: true,
      found: true,
      event: eventRecord(event, requestedCalendar)
    });
  }

  return JSON.stringify({
    calendar_found: true,
    found: false,
    available_calendars: availableNames
  });
}
"""


_DELETE_EVENTS_BY_SUMMARY_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var requestedCalendar = String(config.calendar || "");
  var targetSummaries = Array.isArray(config.summaries) ? config.summaries : [];
  var lookup = {};
  for (var i = 0; i < targetSummaries.length; i++) {
    lookup[String(targetSummaries[i] || "")] = true;
  }

  var app = Application("Calendar");
  var calendars = app.calendars();
  var selected = null;
  for (var j = 0; j < calendars.length; j++) {
    var calendar = calendars[j];
    if (String(calendar.name() || "") === requestedCalendar) {
      selected = calendar;
      break;
    }
  }
  if (!selected) {
    return JSON.stringify({deleted: 0});
  }

  var deleted = 0;
  var events = selected.events();
  for (var k = events.length - 1; k >= 0; k--) {
    var event = events[k];
    var summary = String(event.summary() || "");
    if (!lookup[summary]) {
      continue;
    }
    event.delete();
    deleted += 1;
  }
  return JSON.stringify({deleted: deleted});
}
"""


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()


def _discover_calendar_name() -> str:
    result = _run_jxa_json(_DISCOVER_CALENDAR_JXA, {})
    calendar_name = str(result.get("calendar") or "").strip()
    if not calendar_name:
        raise RuntimeError("no calendars found in the local Calendar.app store")
    return calendar_name


def _lookup_event(
    calendar_name: str,
    *,
    event_id: str | None = None,
    summary: str | None = None,
) -> dict[str, object]:
    return _run_jxa_json(
        _LOOKUP_EVENT_JXA,
        {
            "calendar": calendar_name,
            "id": event_id,
            "summary": summary,
        },
    )


def _wait_for_event(
    calendar_name: str,
    *,
    event_id: str | None = None,
    summary: str | None = None,
    timeout_s: float = 12.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last_state: dict[str, object] | None = None
    while time.time() < deadline:
        state = _lookup_event(
            calendar_name,
            event_id=event_id,
            summary=summary,
        )
        last_state = state
        if state.get("found"):
            return dict(state.get("event") or {})
        time.sleep(0.4)
    raise RuntimeError(
        f"calendar event did not appear in {calendar_name!r}; last state was {last_state!r}"
    )


def _wait_for_event_absent(
    calendar_name: str,
    *,
    event_id: str,
    timeout_s: float = 12.0,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = _lookup_event(calendar_name, event_id=event_id)
        if not state.get("found"):
            return True
        time.sleep(0.4)
    return False


def _cleanup_events(calendar_name: str, summaries: list[str]):
    if not calendar_name or not summaries:
        return
    result = _run_jxa_json(
        _DELETE_EVENTS_BY_SUMMARY_JXA,
        {
            "calendar": calendar_name,
            "summaries": summaries,
        },
    )
    print(
        f"[cleanup] deleted={int(result.get('deleted') or 0)} "
        f"calendar={calendar_name!r} summaries={summaries!r}"
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
    if not final_reply_matches(result.text, expected_reply):
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
    calendar_name = ""
    create_summary = f"deskmaid-calendar-create-{uuid4().hex[:10]}"
    update_summary = f"deskmaid-calendar-update-{uuid4().hex[:10]}"
    create_location = "Deskmaid Test Room A"
    update_location = "Deskmaid Test Room B"
    create_notes = f"deskmaid create notes {uuid4().hex[:8]}"
    update_notes = f"deskmaid update notes {uuid4().hex[:8]}"
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None

    try:
        calendar_name = _discover_calendar_name()
        create_start = (
            datetime.now().astimezone() + timedelta(days=2, hours=1)
        ).replace(second=0, microsecond=0)
        create_end = create_start + timedelta(hours=1)
        update_start = create_start + timedelta(hours=3)
        update_end = update_start + timedelta(hours=1, minutes=30)

        create_prompt = (
            "这是一次 Calendar 写入链路集成测试（创建阶段）。"
            "你必须调用名为 create_calendar_event 的工具。"
            f"参数 summary={json.dumps(create_summary, ensure_ascii=False)}，"
            f"calendar={json.dumps(calendar_name, ensure_ascii=False)}，"
            f"start={json.dumps(create_start.isoformat(), ensure_ascii=False)}，"
            f"end={json.dumps(create_end.isoformat(), ensure_ascii=False)}，"
            f"location={json.dumps(create_location, ensure_ascii=False)}，"
            f"notes={json.dumps(create_notes, ensure_ascii=False)}。"
            "调用成功后，只回复 created。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        create_result, create_requests, create_events, create_remembered = _run_agent_prompt(
            create_prompt
        )
        _print_result("Calendar create", create_result)
        _assert_step(
            label="create_calendar_event",
            result=create_result,
            expected_reply="created",
            expected_receipt_markers=["日程已创建", create_summary, calendar_name, create_location],
            seen_requests=create_requests,
            tool_names=CREATE_CALENDAR_EVENT_TOOL_NAMES,
            expected_confirm_label="确认创建",
            preview_markers=[create_summary, calendar_name, create_location, create_notes],
            remembered_after=create_remembered,
            events=create_events,
        )

        created_event = _wait_for_event(calendar_name, summary=create_summary)
        event_id = str(created_event.get("id") or "").strip()
        if not event_id:
            raise RuntimeError(f"create_calendar_event: missing event id {created_event!r}")
        if str(created_event.get("summary") or "") != create_summary:
            raise RuntimeError(f"create_calendar_event: unexpected summary {created_event!r}")
        if str(created_event.get("calendar") or "") != calendar_name:
            raise RuntimeError(f"create_calendar_event: unexpected calendar {created_event!r}")
        if str(created_event.get("location") or "") != create_location:
            raise RuntimeError(f"create_calendar_event: unexpected location {created_event!r}")
        if str(created_event.get("notes") or "") != create_notes:
            raise RuntimeError(f"create_calendar_event: unexpected notes {created_event!r}")
        _assert_datetimes_close(str(created_event.get("start") or ""), create_start, "create start")
        _assert_datetimes_close(str(created_event.get("end") or ""), create_end, "create end")

        update_prompt = (
            "这是一次 Calendar 写入链路集成测试（更新阶段）。"
            "你必须调用名为 update_calendar_event 的工具。"
            f"参数 id={json.dumps(event_id, ensure_ascii=False)}，"
            f"calendar={json.dumps(calendar_name, ensure_ascii=False)}，"
            f"summary={json.dumps(update_summary, ensure_ascii=False)}，"
            f"start={json.dumps(update_start.isoformat(), ensure_ascii=False)}，"
            f"end={json.dumps(update_end.isoformat(), ensure_ascii=False)}，"
            f"location={json.dumps(update_location, ensure_ascii=False)}，"
            f"notes={json.dumps(update_notes, ensure_ascii=False)}。"
            "调用成功后，只回复 updated。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        update_result, update_requests, update_events, update_remembered = _run_agent_prompt(
            update_prompt
        )
        _print_result("Calendar update", update_result)
        _assert_step(
            label="update_calendar_event",
            result=update_result,
            expected_reply="updated",
            expected_receipt_markers=["日程已更新", update_summary, calendar_name, update_location],
            seen_requests=update_requests,
            tool_names=UPDATE_CALENDAR_EVENT_TOOL_NAMES,
            expected_confirm_label="确认更新",
            preview_markers=[create_summary, update_summary, update_location, "当前：", "更新后："],
            remembered_after=update_remembered,
            events=update_events,
        )

        updated_event = _wait_for_event(calendar_name, event_id=event_id)
        if str(updated_event.get("summary") or "") != update_summary:
            raise RuntimeError(f"update_calendar_event: unexpected summary {updated_event!r}")
        if str(updated_event.get("location") or "") != update_location:
            raise RuntimeError(f"update_calendar_event: unexpected location {updated_event!r}")
        if str(updated_event.get("notes") or "") != update_notes:
            raise RuntimeError(f"update_calendar_event: unexpected notes {updated_event!r}")
        _assert_datetimes_close(str(updated_event.get("start") or ""), update_start, "update start")
        _assert_datetimes_close(str(updated_event.get("end") or ""), update_end, "update end")

        delete_prompt = (
            "这是一次 Calendar 写入链路集成测试（删除阶段）。"
            "你必须调用名为 delete_calendar_event 的工具。"
            f"参数 id={json.dumps(event_id, ensure_ascii=False)}，"
            f"calendar={json.dumps(calendar_name, ensure_ascii=False)}。"
            "调用成功后，只回复 deleted。"
            "不要调用别的工具，也不要改用 Bash。"
        )
        delete_result, delete_requests, delete_events, delete_remembered = _run_agent_prompt(
            delete_prompt
        )
        _print_result("Calendar delete", delete_result)
        _assert_step(
            label="delete_calendar_event",
            result=delete_result,
            expected_reply="deleted",
            expected_receipt_markers=["日程已删除", update_summary, calendar_name],
            seen_requests=delete_requests,
            tool_names=DELETE_CALENDAR_EVENT_TOOL_NAMES,
            expected_confirm_label="确认删除",
            preview_markers=[update_summary, calendar_name],
            remembered_after=delete_remembered,
            events=delete_events,
        )

        if not _wait_for_event_absent(calendar_name, event_id=event_id):
            raise RuntimeError(
                f"delete_calendar_event: event {event_id!r} is still present in {calendar_name!r}"
            )

    except ChatConfigError as exc:
        run_error = (f"[error] {exc}", 2)
    except Exception as exc:
        run_error = (f"[error] {exc}", 1)
    finally:
        try:
            _cleanup_events(calendar_name, [create_summary, update_summary])
        except Exception as exc:
            cleanup_error = str(exc)

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] failed to clean up temporary calendar events: {cleanup_error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
