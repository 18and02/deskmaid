"""Calendar.app core helpers for the desktop maid."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, NotRequired, Required, TypedDict

from maid_tools_shared import (
    _local_now,
    _normalize_calendar_names,
    _normalize_optional_text,
    _normalize_required_text,
    _parse_time_range_value,
    _run_jxa_json,
)

class ListCalendarEventsArgs(TypedDict, total=False):
    start: NotRequired[
        Annotated[
            str,
            "Start of the time range to inspect. Accepts ISO 8601 datetime strings "
            "or YYYY-MM-DD dates. Defaults to now in the local timezone.",
        ]
    ]
    end: NotRequired[
        Annotated[
            str,
            "End of the time range to inspect. Accepts ISO 8601 datetime strings "
            "or YYYY-MM-DD dates. Defaults to 7 days after start.",
        ]
    ]
    calendars: NotRequired[
        Annotated[
            list[str],
            "Optional Calendar.app calendar names to search. Defaults to every calendar.",
        ]
    ]
    limit: NotRequired[
        Annotated[
            int,
            "Maximum number of matching events to return. Defaults to 20 and is capped at 100.",
        ]
    ]

class CreateCalendarEventArgs(TypedDict, total=False):
    summary: NotRequired[
        Annotated[
            str,
            "Event title. Alias: title.",
        ]
    ]
    title: NotRequired[
        Annotated[
            str,
            "Alias of summary: event title.",
        ]
    ]
    start: Required[Annotated[
        str,
        "Event start time. Accepts ISO 8601 datetime strings or YYYY-MM-DD dates.",
    ]]
    end: NotRequired[
        Annotated[
            str,
            "Optional event end time. Accepts ISO 8601 datetime strings or YYYY-MM-DD dates. "
            "Defaults to 1 hour after start, or to the end of that day for all-day events.",
        ]
    ]
    calendar: NotRequired[
        Annotated[
            str,
            "Optional Calendar.app calendar name. Defaults to the first available calendar.",
        ]
    ]
    all_day: NotRequired[
        Annotated[
            bool,
            "Whether the event is all day. Defaults to false.",
        ]
    ]
    location: NotRequired[
        Annotated[
            str,
            "Optional event location.",
        ]
    ]
    notes: NotRequired[
        Annotated[
            str,
            "Optional event notes or description. Alias: description.",
        ]
    ]
    description: NotRequired[
        Annotated[
            str,
            "Alias of notes: event notes or description.",
        ]
    ]
    url: NotRequired[
        Annotated[
            str,
            "Optional event URL.",
        ]
    ]


class UpdateCalendarEventArgs(TypedDict, total=False):
    id: Required[Annotated[
        str,
        "Calendar.app event id, such as the id returned by list_calendar_events.",
    ]]
    calendar: Required[Annotated[
        str,
        "Calendar.app calendar name that currently contains the event.",
    ]]
    summary: NotRequired[
        Annotated[
            str,
            "Optional new event title. Alias: title. Pass an empty string to clear only where supported.",
        ]
    ]
    title: NotRequired[
        Annotated[
            str,
            "Alias of summary: new event title.",
        ]
    ]
    start: NotRequired[
        Annotated[
            str,
            "Optional new event start time.",
        ]
    ]
    end: NotRequired[
        Annotated[
            str,
            "Optional new event end time.",
        ]
    ]
    all_day: NotRequired[
        Annotated[
            bool,
            "Optional new all-day state.",
        ]
    ]
    location: NotRequired[
        Annotated[
            str,
            "Optional new location. Pass an empty string to clear it.",
        ]
    ]
    notes: NotRequired[
        Annotated[
            str,
            "Optional new notes or description. Alias: description. Pass an empty string to clear it.",
        ]
    ]
    description: NotRequired[
        Annotated[
            str,
            "Alias of notes: new event notes or description.",
        ]
    ]
    url: NotRequired[
        Annotated[
            str,
            "Optional new event URL. Pass an empty string to clear it.",
        ]
    ]


class DeleteCalendarEventArgs(TypedDict, total=False):
    id: Required[Annotated[
        str,
        "Calendar.app event id, such as the id returned by list_calendar_events.",
    ]]
    calendar: Required[Annotated[
        str,
        "Calendar.app calendar name that currently contains the event.",
    ]]

DEFAULT_CALENDAR_LOOKAHEAD_DAYS = 7
DEFAULT_CALENDAR_EVENT_LIMIT = 20
MAX_CALENDAR_EVENT_LIMIT = 100
DEFAULT_CALENDAR_EVENT_DURATION_MINUTES = 60

_LIST_CALENDAR_EVENTS_JXA = r"""
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
  var config = JSON.parse(argv[0] || "{}");
  var start = new Date(config.start);
  var end = new Date(config.end);
  var limit = Number(config.limit || 20);

  if (isNaN(start.getTime()) || isNaN(end.getTime())) {
    throw new Error("invalid time range");
  }

  var app = Application("Calendar");
  var allCalendars = app.calendars();
  var availableNames = [];
  var calendarByName = {};
  for (var i = 0; i < allCalendars.length; i++) {
    var calendar = allCalendars[i];
    var name = calendar.name();
    availableNames.push(name);
    if (!Object.prototype.hasOwnProperty.call(calendarByName, name)) {
      calendarByName[name] = calendar;
    }
  }

  var requestedNames = Array.isArray(config.calendars) && config.calendars.length
    ? config.calendars
    : availableNames;
  var selectedNames = [];
  var missingNames = [];
  var selectedCalendars = [];
  for (var j = 0; j < requestedNames.length; j++) {
    var requested = String(requestedNames[j] || "").trim();
    if (!requested.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(calendarByName, requested)) {
      selectedNames.push(requested);
      selectedCalendars.push(calendarByName[requested]);
    } else {
      missingNames.push(requested);
    }
  }

  var events = [];
  for (var c = 0; c < selectedCalendars.length; c++) {
    var selected = selectedCalendars[c];
    var calendarName = selected.name();
    var matches = selected.events.whose({
      startDate: {"<": end},
      endDate: {">": start}
    })();

    for (var e = 0; e < matches.length; e++) {
      var event = matches[e];
      events.push({
        id: normalizeText(event.id()),
        calendar: calendarName,
        summary: normalizeText(event.summary()) || "",
        start: isoOrNull(event.startDate()),
        end: isoOrNull(event.endDate()),
        all_day: !!event.alldayEvent(),
        location: normalizeText(event.location()),
        notes: normalizeText(event.description()),
        url: normalizeText(event.url())
      });
    }
  }

  events.sort(function(a, b) {
    if ((a.start || "") < (b.start || "")) {
      return -1;
    }
    if ((a.start || "") > (b.start || "")) {
      return 1;
    }
    if ((a.calendar || "") < (b.calendar || "")) {
      return -1;
    }
    if ((a.calendar || "") > (b.calendar || "")) {
      return 1;
    }
    if ((a.summary || "") < (b.summary || "")) {
      return -1;
    }
    if ((a.summary || "") > (b.summary || "")) {
      return 1;
    }
    return 0;
  });

  var totalMatches = events.length;
  if (limit >= 0 && events.length > limit) {
    events = events.slice(0, limit);
  }

  return JSON.stringify({
    range_start: start.toISOString(),
    range_end: end.toISOString(),
    available_calendars: availableNames,
    selected_calendars: selectedNames,
    missing_calendars: missingNames,
    total_matches: totalMatches,
    returned_count: events.length,
    events: events
  });
}
"""

_LIST_CALENDAR_NAMES_JXA = r"""
function run(argv) {
  var app = Application("Calendar");
  var calendars = app.calendars();
  var names = [];
  for (var i = 0; i < calendars.length; i++) {
    names.push(String(calendars[i].name() || ""));
  }
  return JSON.stringify({available_calendars: names});
}
"""

_LOOKUP_CALENDAR_EVENT_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var requestedCalendar = normalizeText(config.calendar);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedCalendar) {
    throw new Error("calendar is required");
  }

  var app = Application("Calendar");
  var calendars = app.calendars();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var name = calendar.name();
    availableNames.push(name);
    if (name === requestedCalendar && selected === null) {
      selected = calendar;
    }
  }

  if (selected === null) {
    return JSON.stringify({
      found: false,
      calendar_found: false,
      requested_calendar: requestedCalendar,
      available_calendars: availableNames
    });
  }

  var events = selected.events();
  for (var e = 0; e < events.length; e++) {
    var event = events[e];
    if (normalizeText(event.id()) !== targetId) {
      continue;
    }
    return JSON.stringify({
      found: true,
      calendar_found: true,
      requested_calendar: requestedCalendar,
      available_calendars: availableNames,
      event: eventRecord(event, requestedCalendar)
    });
  }

  return JSON.stringify({
    found: false,
    calendar_found: true,
    requested_calendar: requestedCalendar,
    available_calendars: availableNames
  });
}
"""


_CREATE_CALENDAR_EVENT_JXA = r"""
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
  var summary = String(config.summary || "").trim();
  if (!summary.length) {
    throw new Error("summary is required");
  }

  var start = new Date(config.start);
  var end = new Date(config.end);
  if (isNaN(start.getTime()) || isNaN(end.getTime())) {
    throw new Error("invalid start or end");
  }

  var app = Application("Calendar");
  var calendars = app.calendars();
  if (!calendars.length) {
    throw new Error("no calendars found");
  }

  var availableNames = [];
  var selected = null;
  var requestedCalendar = normalizeText(config.calendar);
  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var name = calendar.name();
    availableNames.push(name);
    if (requestedCalendar && name === requestedCalendar && selected === null) {
      selected = calendar;
    }
  }

  var usedDefaultCalendar = false;
  if (selected === null) {
    if (requestedCalendar) {
      throw new Error("calendar not found: " + requestedCalendar);
    }
    selected = calendars[0];
    usedDefaultCalendar = true;
  }

  var props = {
    summary: summary,
    startDate: start,
    endDate: end,
    alldayEvent: !!config.all_day
  };
  if (Object.prototype.hasOwnProperty.call(config, "location")) {
    props.location = config.location === null ? "" : String(config.location);
  }
  if (Object.prototype.hasOwnProperty.call(config, "notes")) {
    props.description = config.notes === null ? "" : String(config.notes);
  }
  if (Object.prototype.hasOwnProperty.call(config, "url")) {
    props.url = config.url === null ? "" : String(config.url);
  }

  var event = app.Event(props);
  selected.events.push(event);
  delay(0.2);

  return JSON.stringify({
    selected_calendar: selected.name(),
    available_calendars: availableNames,
    used_default_calendar: usedDefaultCalendar,
    created: eventRecord(event, selected.name())
  });
}
"""


_UPDATE_CALENDAR_EVENT_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var requestedCalendar = normalizeText(config.calendar);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedCalendar) {
    throw new Error("calendar is required");
  }

  var app = Application("Calendar");
  var calendars = app.calendars();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var name = calendar.name();
    availableNames.push(name);
    if (name === requestedCalendar && selected === null) {
      selected = calendar;
    }
  }
  if (selected === null) {
    throw new Error("calendar not found: " + requestedCalendar);
  }

  var events = selected.events();
  var target = null;
  for (var e = 0; e < events.length; e++) {
    if (normalizeText(events[e].id()) === targetId) {
      target = events[e];
      break;
    }
  }
  if (target === null) {
    throw new Error("event not found");
  }

  var before = eventRecord(target, requestedCalendar);
  var currentStart = target.startDate();
  var currentEnd = target.endDate();
  var nextStart = null;
  var nextEnd = null;
  var hasStart = Object.prototype.hasOwnProperty.call(config, "start");
  var hasEnd = Object.prototype.hasOwnProperty.call(config, "end");

  if (hasStart) {
    nextStart = new Date(config.start);
    if (isNaN(nextStart.getTime())) {
      throw new Error("invalid start");
    }
  }
  if (hasEnd) {
    nextEnd = new Date(config.end);
    if (isNaN(nextEnd.getTime())) {
      throw new Error("invalid end");
    }
  }
  if (Object.prototype.hasOwnProperty.call(config, "summary")) {
    target.summary = String(config.summary || "");
  }

  if (hasStart && hasEnd) {
    if (nextStart.getTime() >= currentEnd.getTime()) {
      target.endDate = nextEnd;
      target.startDate = nextStart;
    } else if (nextEnd.getTime() <= currentStart.getTime()) {
      target.startDate = nextStart;
      target.endDate = nextEnd;
    } else {
      target.startDate = nextStart;
      target.endDate = nextEnd;
    }
  } else {
    if (hasStart) {
      target.startDate = nextStart;
    }
    if (hasEnd) {
      target.endDate = nextEnd;
    }
  }
  if (Object.prototype.hasOwnProperty.call(config, "all_day")) {
    target.alldayEvent = !!config.all_day;
  }
  if (Object.prototype.hasOwnProperty.call(config, "location")) {
    target.location = config.location === null ? "" : String(config.location);
  }
  if (Object.prototype.hasOwnProperty.call(config, "notes")) {
    target.description = config.notes === null ? "" : String(config.notes);
  }
  if (Object.prototype.hasOwnProperty.call(config, "url")) {
    target.url = config.url === null ? "" : String(config.url);
  }
  delay(0.2);

  return JSON.stringify({
    available_calendars: availableNames,
    selected_calendar: requestedCalendar,
    before: before,
    after: eventRecord(target, requestedCalendar)
  });
}
"""


_DELETE_CALENDAR_EVENT_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var requestedCalendar = normalizeText(config.calendar);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedCalendar) {
    throw new Error("calendar is required");
  }

  var app = Application("Calendar");
  var calendars = app.calendars();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < calendars.length; i++) {
    var calendar = calendars[i];
    var name = calendar.name();
    availableNames.push(name);
    if (name === requestedCalendar && selected === null) {
      selected = calendar;
    }
  }
  if (selected === null) {
    throw new Error("calendar not found: " + requestedCalendar);
  }

  var events = selected.events();
  var target = null;
  for (var e = 0; e < events.length; e++) {
    if (normalizeText(events[e].id()) === targetId) {
      target = events[e];
      break;
    }
  }
  if (target === null) {
    throw new Error("event not found");
  }

  var deleted = eventRecord(target, requestedCalendar);
  target.delete();
  delay(0.2);
  return JSON.stringify({
    available_calendars: availableNames,
    selected_calendar: requestedCalendar,
    deleted: deleted
  });
}
"""

def _list_calendar_names_sync() -> list[str]:
    result = _run_jxa_json(_LIST_CALENDAR_NAMES_JXA, {})
    return _normalize_calendar_names(result.get("available_calendars"))

def _resolve_calendar_target_sync(calendar: str | None = None) -> dict[str, object]:
    available = _list_calendar_names_sync()
    if not available:
        raise LookupError("no calendars found")
    requested = _normalize_optional_text(calendar)
    if requested:
        if requested not in available:
            raise LookupError(
                "calendar not found"
                + (f"; available calendars: {', '.join(available)}" if available else "")
            )
        return {
            "calendar": requested,
            "available_calendars": available,
            "used_default_calendar": False,
        }
    return {
        "calendar": available[0],
        "available_calendars": available,
        "used_default_calendar": True,
    }

def _list_calendar_events_sync(
    start: str | None = None,
    end: str | None = None,
    calendars: list[str] | None = None,
    limit: int = DEFAULT_CALENDAR_EVENT_LIMIT,
) -> dict[str, object]:
    start_dt = _parse_time_range_value(start, end_of_day=False) if start else _local_now()
    if end:
        end_dt = _parse_time_range_value(end, end_of_day=True)
    else:
        end_dt = start_dt + timedelta(days=DEFAULT_CALENDAR_LOOKAHEAD_DAYS)
    if end_dt <= start_dt:
        raise ValueError("end must be later than start")

    safe_limit = int(limit)
    if safe_limit < 1:
        safe_limit = 1
    if safe_limit > MAX_CALENDAR_EVENT_LIMIT:
        safe_limit = MAX_CALENDAR_EVENT_LIMIT

    calendar_names = _normalize_calendar_names(calendars)
    result = _run_jxa_json(
        _LIST_CALENDAR_EVENTS_JXA,
        {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "calendars": calendar_names,
            "limit": safe_limit,
        },
    )
    if calendar_names and not result.get("selected_calendars"):
        available = ", ".join(result.get("available_calendars") or [])
        raise LookupError(
            "none of the requested calendars were found"
            + (f"; available calendars: {available}" if available else "")
        )
    return result

def _lookup_calendar_event_sync(
    id: str,
    calendar: str,
) -> dict[str, object]:
    target_id = _normalize_required_text(id, "id")
    calendar_name = _normalize_required_text(calendar, "calendar")
    result = _run_jxa_json(
        _LOOKUP_CALENDAR_EVENT_JXA,
        {
            "id": target_id,
            "calendar": calendar_name,
        },
        timeout_s=30.0,
    )
    available = _normalize_calendar_names(result.get("available_calendars"))
    if not result.get("calendar_found"):
        raise LookupError(
            "calendar not found"
            + (f"; available calendars: {', '.join(available)}" if available else "")
        )
    if not result.get("found"):
        raise LookupError(
            f"no calendar event matched id {target_id!r} in calendar {calendar_name!r}"
        )
    event = dict(result.get("event") or {})
    event["available_calendars"] = available
    event["requested_calendar"] = calendar_name
    return event


def _create_calendar_event_sync(
    summary: str,
    start: str,
    end: str | None = None,
    calendar: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    notes: str | None = None,
    url: str | None = None,
) -> dict[str, object]:
    summary_text = _normalize_required_text(summary, "summary")
    resolved = _resolve_calendar_target_sync(calendar)

    start_dt = _parse_time_range_value(start, end_of_day=False)
    if all_day:
        start_dt = start_dt.astimezone().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    if end:
        end_dt = _parse_time_range_value(end, end_of_day=bool(all_day))
    else:
        end_dt = start_dt + (
            timedelta(days=1)
            if all_day
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )
    if end_dt <= start_dt:
        raise ValueError("end must be later than start")

    payload: dict[str, object] = {
        "summary": summary_text,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "calendar": resolved["calendar"],
        "all_day": bool(all_day),
    }
    if location is not None:
        payload["location"] = str(location)
    if notes is not None:
        payload["notes"] = str(notes)
    if url is not None:
        payload["url"] = str(url)

    result = _run_jxa_json(
        _CREATE_CALENDAR_EVENT_JXA,
        payload,
        timeout_s=30.0,
    )
    created = dict(result.get("created") or {})
    created["available_calendars"] = _normalize_calendar_names(
        result.get("available_calendars")
    )
    created["selected_calendar"] = str(result.get("selected_calendar") or "")
    created["used_default_calendar"] = bool(result.get("used_default_calendar"))
    return created


def _update_calendar_event_sync(
    id: str,
    calendar: str,
    *,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    all_day: bool | None = None,
    location: str | None = None,
    notes: str | None = None,
    url: str | None = None,
    has_summary: bool = False,
    has_start: bool = False,
    has_end: bool = False,
    has_all_day: bool = False,
    has_location: bool = False,
    has_notes: bool = False,
    has_url: bool = False,
) -> dict[str, object]:
    existing = _lookup_calendar_event_sync(id, calendar)
    existing_start_raw = str(existing.get("start") or "").strip()
    existing_end_raw = str(existing.get("end") or "").strip()
    if not existing_start_raw or not existing_end_raw:
        raise RuntimeError("target event is missing start or end time")
    existing_start_dt = _parse_time_range_value(existing_start_raw, end_of_day=False)
    existing_end_dt = _parse_time_range_value(existing_end_raw, end_of_day=False)
    existing_all_day = bool(existing.get("all_day"))
    current_duration = existing_end_dt - existing_start_dt
    if current_duration.total_seconds() <= 0:
        current_duration = (
            timedelta(days=1)
            if existing_all_day
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )

    final_all_day = bool(all_day) if has_all_day else existing_all_day
    start_dt = existing_start_dt
    end_dt = existing_end_dt

    if has_start:
        start_dt = _parse_time_range_value(str(start), end_of_day=False)
    if final_all_day:
        start_dt = start_dt.astimezone().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if has_end:
        end_dt = _parse_time_range_value(str(end), end_of_day=final_all_day)
    elif has_start:
        end_dt = start_dt + (
            timedelta(days=1)
            if final_all_day
            else current_duration
        )
    elif has_all_day and final_all_day != existing_all_day:
        end_dt = start_dt + (
            timedelta(days=1)
            if final_all_day
            else timedelta(minutes=DEFAULT_CALENDAR_EVENT_DURATION_MINUTES)
        )

    if end_dt <= start_dt:
        raise ValueError("end must be later than start")

    payload: dict[str, object] = {
        "id": _normalize_required_text(id, "id"),
        "calendar": _normalize_required_text(calendar, "calendar"),
    }
    if has_summary:
        payload["summary"] = _normalize_required_text(summary, "summary")
    if has_start or has_end or has_all_day:
        payload["start"] = start_dt.isoformat()
        payload["end"] = end_dt.isoformat()
    if has_all_day:
        payload["all_day"] = final_all_day
    if has_location:
        payload["location"] = "" if location is None else str(location)
    if has_notes:
        payload["notes"] = "" if notes is None else str(notes)
    if has_url:
        payload["url"] = "" if url is None else str(url)

    result = _run_jxa_json(
        _UPDATE_CALENDAR_EVENT_JXA,
        payload,
        timeout_s=30.0,
    )
    return {
        "available_calendars": _normalize_calendar_names(
            result.get("available_calendars")
        ),
        "selected_calendar": str(result.get("selected_calendar") or ""),
        "before": dict(result.get("before") or {}),
        "after": dict(result.get("after") or {}),
    }


def _delete_calendar_event_sync(
    id: str,
    calendar: str,
) -> dict[str, object]:
    payload = {
        "id": _normalize_required_text(id, "id"),
        "calendar": _normalize_required_text(calendar, "calendar"),
    }
    result = _run_jxa_json(
        _DELETE_CALENDAR_EVENT_JXA,
        payload,
        timeout_s=30.0,
    )
    return {
        "available_calendars": _normalize_calendar_names(
            result.get("available_calendars")
        ),
        "selected_calendar": str(result.get("selected_calendar") or ""),
        "deleted": dict(result.get("deleted") or {}),
    }

def _parse_create_calendar_event_args(args: dict[str, object]) -> dict[str, object]:
    raw_summary = args.get("summary") if "summary" in args else args.get("title")
    raw_notes = args.get("notes") if "notes" in args else args.get("description")
    return {
        "summary": raw_summary,
        "start": args.get("start"),
        "end": args.get("end"),
        "calendar": args.get("calendar") or args.get("calendar_name"),
        "all_day": bool(args.get("all_day") or args.get("allDay") or False),
        "location": args.get("location") if "location" in args else None,
        "notes": raw_notes if ("notes" in args or "description" in args) else None,
        "url": args.get("url") if "url" in args else None,
    }


def _parse_update_calendar_event_args(args: dict[str, object]) -> dict[str, object]:
    has_summary = "summary" in args or "title" in args
    has_notes = "notes" in args or "description" in args
    has_all_day = "all_day" in args or "allDay" in args
    return {
        "id": args.get("id"),
        "calendar": args.get("calendar"),
        "summary": args.get("summary") if "summary" in args else args.get("title"),
        "start": args.get("start"),
        "end": args.get("end"),
        "all_day": (args.get("all_day") if "all_day" in args else args.get("allDay")),
        "location": args.get("location") if "location" in args else None,
        "notes": args.get("notes") if "notes" in args else args.get("description"),
        "url": args.get("url") if "url" in args else None,
        "has_summary": has_summary,
        "has_start": "start" in args,
        "has_end": "end" in args,
        "has_all_day": has_all_day,
        "has_location": "location" in args,
        "has_notes": has_notes,
        "has_url": "url" in args,
    }


def _parse_delete_calendar_event_args(args: dict[str, object]) -> dict[str, object]:
    return {
        "id": args.get("id"),
        "calendar": args.get("calendar"),
    }
