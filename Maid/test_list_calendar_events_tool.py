"""Standalone list_calendar_events MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_list_calendar_events_tool.py

The test discovers one real calendar event from the local Calendar.app store,
asks Claude to explicitly call list_calendar_events for that calendar and time
window, auto-allows the permission prompt, and verifies that the permission and
trace path are both exercised.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    final_reply_matches,
    print_chat_result,
)


LIST_CALENDAR_EVENTS_TOOL_NAMES = {
    "list_calendar_events",
    "mcp__deskmaid_local__list_calendar_events",
}


_DISCOVER_SAMPLE_EVENT_JXA = r"""
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
  var config = JSON.parse(argv[0] || "{}");
  var start = new Date(config.start);
  var end = new Date(config.end);
  var app = Application("Calendar");
  var calendars = app.calendars();

  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var matches = calendar.events.whose({
      startDate: {"<": end},
      endDate: {">": start}
    })();
    if (!matches.length) {
      continue;
    }

    var event = matches[0];
    return JSON.stringify({
      calendar: calendar.name(),
      summary: String(event.summary() || ""),
      start: isoOrNull(event.startDate()),
      end: isoOrNull(event.endDate())
    });
  }

  return JSON.stringify({});
}
"""


def _parse_event_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _discover_sample_event() -> tuple[dict[str, object], str, str]:
    now = datetime.now().astimezone()
    event = _run_jxa_json(
        _DISCOVER_SAMPLE_EVENT_JXA,
        {
            "start": (now - timedelta(days=30)).isoformat(),
            "end": (now + timedelta(days=365)).isoformat(),
        },
    )
    if not event.get("calendar") or not event.get("start"):
        raise RuntimeError("no calendar events found in the local Calendar.app store")

    start_dt = _parse_event_datetime(str(event["start"]))
    end_dt_raw = str(event.get("end") or event["start"])
    end_dt = _parse_event_datetime(end_dt_raw)
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(hours=1)

    query_start = (start_dt - timedelta(days=1)).astimezone().isoformat()
    query_end = (end_dt + timedelta(days=1)).astimezone().isoformat()
    return event, query_start, query_end


def main():
    try:
        sample_event, query_start, query_end = _discover_sample_event()
    except Exception as exc:
        print(f"[error] unable to discover a sample calendar event: {exc}", file=sys.stderr)
        sys.exit(1)

    calendar_name = str(sample_event["calendar"])
    summary = str(sample_event["summary"])
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    set_permission_handler(auto_allow)
    try:
        prompt = (
            "这是一次 list_calendar_events 集成测试。"
            "你必须调用名为 list_calendar_events 的工具。"
            f"参数 calendars=[{json.dumps(calendar_name, ensure_ascii=False)}]，"
            f"start={json.dumps(query_start, ensure_ascii=False)}，"
            f"end={json.dumps(query_end, ensure_ascii=False)}，limit=5。"
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
        tool_names=LIST_CALENDAR_EVENTS_TOOL_NAMES,
        label="list_calendar_events",
        tool_result_markers=[calendar_name, summary],
        tool_result_description="the sample calendar or summary",
    )

    if not final_reply_matches(result.text, "listed"):
        print(
            f"[error] expected final reply 'listed', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
