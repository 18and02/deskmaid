"""Reminders.app core helpers for the desktop maid."""

from __future__ import annotations

from typing import Annotated, NotRequired, Required, TypedDict

from maid_tools_shared import (
    _normalize_calendar_names,
    _normalize_optional_text,
    _normalize_required_text,
    _parse_time_range_value,
    _run_jxa_json,
)

class ListRemindersArgs(TypedDict, total=False):
    due_after: NotRequired[
        Annotated[
            str,
            "Optional lower bound for due dates. Accepts ISO 8601 datetime strings or "
            "YYYY-MM-DD dates. When omitted, reminders without due dates are still included.",
        ]
    ]
    due_before: NotRequired[
        Annotated[
            str,
            "Optional upper bound for due dates. Accepts ISO 8601 datetime strings or "
            "YYYY-MM-DD dates. When omitted, there is no upper due-date bound.",
        ]
    ]
    lists: NotRequired[
        Annotated[
            list[str],
            "Optional Reminders.app list names to search. Defaults to every list.",
        ]
    ]
    include_completed: NotRequired[
        Annotated[
            bool,
            "Whether completed reminders should be included. Defaults to false.",
        ]
    ]
    limit: NotRequired[
        Annotated[
            int,
            "Maximum number of matching reminders to return. Defaults to 20 and is capped at 100.",
        ]
    ]

class CreateReminderArgs(TypedDict, total=False):
    name: NotRequired[
        Annotated[
            str,
            "Reminder title. Alias: title.",
        ]
    ]
    title: NotRequired[
        Annotated[
            str,
            "Alias of name: reminder title.",
        ]
    ]
    list: NotRequired[
        Annotated[
            str,
            "Optional Reminders.app list name. Alias: list_name. Defaults to the first available list.",
        ]
    ]
    list_name: NotRequired[
        Annotated[
            str,
            "Alias of list: reminder list name.",
        ]
    ]
    due_date: NotRequired[
        Annotated[
            str,
            "Optional reminder due date or datetime.",
        ]
    ]
    body: NotRequired[
        Annotated[
            str,
            "Optional reminder notes. Alias: notes.",
        ]
    ]
    notes: NotRequired[
        Annotated[
            str,
            "Alias of body: reminder notes.",
        ]
    ]
    priority: NotRequired[
        Annotated[
            int,
            "Optional priority from 0 to 9. 0 means none, 1 is highest priority, 9 is lowest.",
        ]
    ]


class UpdateReminderArgs(TypedDict, total=False):
    id: Required[Annotated[
        str,
        "Reminders.app reminder id, such as the id returned by list_reminders.",
    ]]
    list: Required[Annotated[
        str,
        "Reminders.app list name that currently contains the reminder. Alias: list_name.",
    ]]
    list_name: NotRequired[
        Annotated[
            str,
            "Alias of list: reminder list name.",
        ]
    ]
    name: NotRequired[
        Annotated[
            str,
            "Optional new reminder title. Alias: title.",
        ]
    ]
    title: NotRequired[
        Annotated[
            str,
            "Alias of name: new reminder title.",
        ]
    ]
    due_date: NotRequired[
        Annotated[
            str,
            "Optional new due date or datetime. Set clear_due_date=true to remove the due date.",
        ]
    ]
    clear_due_date: NotRequired[
        Annotated[
            bool,
            "Whether to clear the current due date.",
        ]
    ]
    body: NotRequired[
        Annotated[
            str,
            "Optional new reminder notes. Alias: notes. Pass an empty string to clear it.",
        ]
    ]
    notes: NotRequired[
        Annotated[
            str,
            "Alias of body: new reminder notes.",
        ]
    ]
    priority: NotRequired[
        Annotated[
            int,
            "Optional new priority from 0 to 9.",
        ]
    ]
    completed: NotRequired[
        Annotated[
            bool,
            "Optional completion state. Use true to mark completed and false to mark incomplete again.",
        ]
    ]


class DeleteReminderArgs(TypedDict, total=False):
    id: Required[Annotated[
        str,
        "Reminders.app reminder id, such as the id returned by list_reminders.",
    ]]
    list: Required[Annotated[
        str,
        "Reminders.app list name that currently contains the reminder. Alias: list_name.",
    ]]
    list_name: NotRequired[
        Annotated[
            str,
            "Alias of list: reminder list name.",
        ]
    ]

DEFAULT_REMINDER_LIMIT = 20
MAX_REMINDER_LIMIT = 100

_LIST_REMINDERS_JXA = r"""
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

function sortKey(value, fallback) {
  return value === null || value === undefined ? fallback : value;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var includeCompleted = !!config.include_completed;
  var dueAfter = config.due_after ? new Date(config.due_after) : null;
  var dueBefore = config.due_before ? new Date(config.due_before) : null;
  var limit = Number(config.limit || 20);

  if (dueAfter && isNaN(dueAfter.getTime())) {
    throw new Error("invalid due_after");
  }
  if (dueBefore && isNaN(dueBefore.getTime())) {
    throw new Error("invalid due_before");
  }

  var app = Application("Reminders");
  var allLists = app.lists();
  var availableNames = [];
  var listByName = {};
  for (var i = 0; i < allLists.length; i++) {
    var list = allLists[i];
    var name = list.name();
    availableNames.push(name);
    if (!Object.prototype.hasOwnProperty.call(listByName, name)) {
      listByName[name] = list;
    }
  }

  var requestedNames = Array.isArray(config.lists) && config.lists.length
    ? config.lists
    : availableNames;
  var selectedNames = [];
  var missingNames = [];
  var selectedLists = [];
  for (var j = 0; j < requestedNames.length; j++) {
    var requested = String(requestedNames[j] || "").trim();
    if (!requested.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(listByName, requested)) {
      selectedNames.push(requested);
      selectedLists.push(listByName[requested]);
    } else {
      missingNames.push(requested);
    }
  }

  var reminders = [];
  for (var l = 0; l < selectedLists.length; l++) {
    var selected = selectedLists[l];
    var listName = selected.name();
    var matches = selected.reminders();
    for (var r = 0; r < matches.length; r++) {
      var reminder = matches[r];
      var completed = !!reminder.completed();
      if (!includeCompleted && completed) {
        continue;
      }

      var dueValue = reminder.dueDate();
      var dueDate = dueValue ? new Date(dueValue) : null;
      if (dueAfter && (!dueDate || dueDate < dueAfter)) {
        continue;
      }
      if (dueBefore && (!dueDate || dueDate > dueBefore)) {
        continue;
      }

      reminders.push({
        id: normalizeText(reminder.id()),
        list: listName,
        name: normalizeText(reminder.name()) || "",
        body: normalizeText(reminder.body()),
        completed: completed,
        due_date: isoOrNull(dueValue),
        completion_date: isoOrNull(reminder.completionDate()),
        creation_date: isoOrNull(reminder.creationDate()),
        modification_date: isoOrNull(reminder.modificationDate()),
        flagged: !!reminder.flagged(),
        priority: Number(reminder.priority())
      });
    }
  }

  reminders.sort(function(a, b) {
    if (a.completed !== b.completed) {
      return a.completed ? 1 : -1;
    }
    var aDue = sortKey(a.due_date, "9999-12-31T23:59:59.999Z");
    var bDue = sortKey(b.due_date, "9999-12-31T23:59:59.999Z");
    if (aDue < bDue) {
      return -1;
    }
    if (aDue > bDue) {
      return 1;
    }
    var aCreated = sortKey(a.creation_date, "9999-12-31T23:59:59.999Z");
    var bCreated = sortKey(b.creation_date, "9999-12-31T23:59:59.999Z");
    if (aCreated < bCreated) {
      return -1;
    }
    if (aCreated > bCreated) {
      return 1;
    }
    if ((a.list || "") < (b.list || "")) {
      return -1;
    }
    if ((a.list || "") > (b.list || "")) {
      return 1;
    }
    if ((a.name || "") < (b.name || "")) {
      return -1;
    }
    if ((a.name || "") > (b.name || "")) {
      return 1;
    }
    return 0;
  });

  var totalMatches = reminders.length;
  if (limit >= 0 && reminders.length > limit) {
    reminders = reminders.slice(0, limit);
  }

  return JSON.stringify({
    available_lists: availableNames,
    selected_lists: selectedNames,
    missing_lists: missingNames,
    include_completed: includeCompleted,
    due_after: dueAfter ? dueAfter.toISOString() : null,
    due_before: dueBefore ? dueBefore.toISOString() : null,
    total_matches: totalMatches,
    returned_count: reminders.length,
    reminders: reminders
  });
}
"""

_LIST_REMINDER_LIST_NAMES_JXA = r"""
function run(argv) {
  var app = Application("Reminders");
  var lists = app.lists();
  var names = [];
  for (var i = 0; i < lists.length; i++) {
    names.push(String(lists[i].name() || ""));
  }
  return JSON.stringify({available_lists: names});
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
  var targetId = normalizeText(config.id);
  var requestedList = normalizeText(config.list);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedList) {
    throw new Error("list is required");
  }

  var app = Application("Reminders");
  var lists = app.lists();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var name = list.name();
    availableNames.push(name);
    if (name === requestedList && selected === null) {
      selected = list;
    }
  }
  if (selected === null) {
    return JSON.stringify({
      found: false,
      list_found: false,
      requested_list: requestedList,
      available_lists: availableNames
    });
  }

  var reminders = selected.reminders();
  for (var r = 0; r < reminders.length; r++) {
    var reminder = reminders[r];
    if (normalizeText(reminder.id()) !== targetId) {
      continue;
    }
    return JSON.stringify({
      found: true,
      list_found: true,
      requested_list: requestedList,
      available_lists: availableNames,
      reminder: reminderRecord(reminder, requestedList)
    });
  }

  return JSON.stringify({
    found: false,
    list_found: true,
    requested_list: requestedList,
    available_lists: availableNames
  });
}
"""


_CREATE_REMINDER_JXA = r"""
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
  var name = String(config.name || "").trim();
  if (!name.length) {
    throw new Error("name is required");
  }

  var app = Application("Reminders");
  var lists = app.lists();
  if (!lists.length) {
    throw new Error("no reminder lists found");
  }

  var availableNames = [];
  var selected = null;
  var requestedList = normalizeText(config.list);
  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var listName = list.name();
    availableNames.push(listName);
    if (requestedList && listName === requestedList && selected === null) {
      selected = list;
    }
  }

  var usedDefaultList = false;
  if (selected === null) {
    if (requestedList) {
      throw new Error("reminder list not found: " + requestedList);
    }
    selected = lists[0];
    usedDefaultList = true;
  }

  var props = {
    name: name
  };
  if (Object.prototype.hasOwnProperty.call(config, "body")) {
    props.body = config.body === null ? "" : String(config.body);
  }
  if (Object.prototype.hasOwnProperty.call(config, "due_date")) {
    var dueDate = new Date(config.due_date);
    if (isNaN(dueDate.getTime())) {
      throw new Error("invalid due_date");
    }
    props.dueDate = dueDate;
  }
  if (Object.prototype.hasOwnProperty.call(config, "priority")) {
    props.priority = Number(config.priority);
  }

  var reminder = app.Reminder(props);
  selected.reminders.push(reminder);
  delay(0.2);

  return JSON.stringify({
    selected_list: selected.name(),
    available_lists: availableNames,
    used_default_list: usedDefaultList,
    created: reminderRecord(reminder, selected.name())
  });
}
"""


_UPDATE_REMINDER_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var requestedList = normalizeText(config.list);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedList) {
    throw new Error("list is required");
  }

  var app = Application("Reminders");
  var lists = app.lists();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var name = list.name();
    availableNames.push(name);
    if (name === requestedList && selected === null) {
      selected = list;
    }
  }
  if (selected === null) {
    throw new Error("reminder list not found: " + requestedList);
  }

  var reminders = selected.reminders();
  var target = null;
  for (var r = 0; r < reminders.length; r++) {
    if (normalizeText(reminders[r].id()) === targetId) {
      target = reminders[r];
      break;
    }
  }
  if (target === null) {
    throw new Error("reminder not found");
  }

  var before = reminderRecord(target, requestedList);
  if (Object.prototype.hasOwnProperty.call(config, "name")) {
    target.name = String(config.name || "");
  }
  if (Object.prototype.hasOwnProperty.call(config, "body")) {
    target.body = config.body === null ? "" : String(config.body);
  }
  if (Object.prototype.hasOwnProperty.call(config, "clear_due_date") && config.clear_due_date) {
    target.dueDate = null;
  } else if (Object.prototype.hasOwnProperty.call(config, "due_date")) {
    var dueDate = new Date(config.due_date);
    if (isNaN(dueDate.getTime())) {
      throw new Error("invalid due_date");
    }
    target.dueDate = dueDate;
  }
  if (Object.prototype.hasOwnProperty.call(config, "priority")) {
    target.priority = Number(config.priority);
  }
  if (Object.prototype.hasOwnProperty.call(config, "completed")) {
    target.completed = !!config.completed;
  }
  delay(0.2);

  return JSON.stringify({
    available_lists: availableNames,
    selected_list: requestedList,
    before: before,
    after: reminderRecord(target, requestedList)
  });
}
"""


_DELETE_REMINDER_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var requestedList = normalizeText(config.list);
  if (!targetId) {
    throw new Error("id is required");
  }
  if (!requestedList) {
    throw new Error("list is required");
  }

  var app = Application("Reminders");
  var lists = app.lists();
  var availableNames = [];
  var selected = null;
  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var name = list.name();
    availableNames.push(name);
    if (name === requestedList && selected === null) {
      selected = list;
    }
  }
  if (selected === null) {
    throw new Error("reminder list not found: " + requestedList);
  }

  var reminders = selected.reminders();
  var target = null;
  for (var r = 0; r < reminders.length; r++) {
    if (normalizeText(reminders[r].id()) === targetId) {
      target = reminders[r];
      break;
    }
  }
  if (target === null) {
    throw new Error("reminder not found");
  }

  var deleted = reminderRecord(target, requestedList);
  target.delete();
  delay(0.2);
  return JSON.stringify({
    available_lists: availableNames,
    selected_list: requestedList,
    deleted: deleted
  });
}
"""
def _normalize_reminder_priority(value) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("priority must be an integer") from exc
    if priority < 0:
        return 0
    if priority > 9:
        return 9
    return priority

def _list_reminder_list_names_sync() -> list[str]:
    result = _run_jxa_json(_LIST_REMINDER_LIST_NAMES_JXA, {})
    return _normalize_calendar_names(result.get("available_lists"))

def _resolve_reminder_list_target_sync(list_name: str | None = None) -> dict[str, object]:
    available = _list_reminder_list_names_sync()
    if not available:
        raise LookupError("no reminder lists found")
    requested = _normalize_optional_text(list_name)
    if requested:
        if requested not in available:
            raise LookupError(
                "reminder list not found"
                + (f"; available lists: {', '.join(available)}" if available else "")
            )
        return {
            "list": requested,
            "available_lists": available,
            "used_default_list": False,
        }
    return {
        "list": available[0],
        "available_lists": available,
        "used_default_list": True,
    }

def _list_reminders_sync(
    due_after: str | None = None,
    due_before: str | None = None,
    lists: list[str] | None = None,
    include_completed: bool = False,
    limit: int = DEFAULT_REMINDER_LIMIT,
) -> dict[str, object]:
    due_after_dt = (
        _parse_time_range_value(due_after, end_of_day=False)
        if due_after
        else None
    )
    due_before_dt = (
        _parse_time_range_value(due_before, end_of_day=True)
        if due_before
        else None
    )
    if (
        due_after_dt is not None
        and due_before_dt is not None
        and due_before_dt < due_after_dt
    ):
        raise ValueError("due_before must be later than or equal to due_after")

    safe_limit = int(limit)
    if safe_limit < 1:
        safe_limit = 1
    if safe_limit > MAX_REMINDER_LIMIT:
        safe_limit = MAX_REMINDER_LIMIT

    list_names = _normalize_calendar_names(lists)
    result = _run_jxa_json(
        _LIST_REMINDERS_JXA,
        {
            "due_after": due_after_dt.isoformat() if due_after_dt else None,
            "due_before": due_before_dt.isoformat() if due_before_dt else None,
            "lists": list_names,
            "include_completed": bool(include_completed),
            "limit": safe_limit,
        },
    )
    if list_names and not result.get("selected_lists"):
        available = ", ".join(result.get("available_lists") or [])
        raise LookupError(
            "none of the requested reminder lists were found"
            + (f"; available lists: {available}" if available else "")
        )
    return result

def _lookup_reminder_sync(
    id: str,
    list_name: str,
) -> dict[str, object]:
    target_id = _normalize_required_text(id, "id")
    normalized_list = _normalize_required_text(list_name, "list")
    result = _run_jxa_json(
        _LOOKUP_REMINDER_JXA,
        {
            "id": target_id,
            "list": normalized_list,
        },
        timeout_s=30.0,
    )
    available = _normalize_calendar_names(result.get("available_lists"))
    if not result.get("list_found"):
        raise LookupError(
            "reminder list not found"
            + (f"; available lists: {', '.join(available)}" if available else "")
        )
    if not result.get("found"):
        raise LookupError(
            f"no reminder matched id {target_id!r} in list {normalized_list!r}"
        )
    reminder = dict(result.get("reminder") or {})
    reminder["available_lists"] = available
    reminder["requested_list"] = normalized_list
    return reminder


def _create_reminder_sync(
    name: str,
    list_name: str | None = None,
    due_date: str | None = None,
    body: str | None = None,
    priority: int | None = None,
) -> dict[str, object]:
    name_text = _normalize_required_text(name, "name")
    resolved = _resolve_reminder_list_target_sync(list_name)

    payload: dict[str, object] = {
        "name": name_text,
        "list": resolved["list"],
    }
    if due_date is not None:
        payload["due_date"] = _parse_time_range_value(
            due_date,
            end_of_day=True,
        ).isoformat()
    if body is not None:
        payload["body"] = str(body)
    if priority is not None:
        payload["priority"] = _normalize_reminder_priority(priority)

    result = _run_jxa_json(
        _CREATE_REMINDER_JXA,
        payload,
        timeout_s=30.0,
    )
    created = dict(result.get("created") or {})
    created["available_lists"] = _normalize_calendar_names(
        result.get("available_lists")
    )
    created["selected_list"] = str(result.get("selected_list") or "")
    created["used_default_list"] = bool(result.get("used_default_list"))
    return created


def _update_reminder_sync(
    id: str,
    list_name: str,
    *,
    name: str | None = None,
    due_date: str | None = None,
    body: str | None = None,
    priority: int | None = None,
    completed: bool | None = None,
    clear_due_date: bool = False,
    has_name: bool = False,
    has_due_date: bool = False,
    has_body: bool = False,
    has_priority: bool = False,
    has_completed: bool = False,
) -> dict[str, object]:
    if clear_due_date:
        raise ValueError(
            "clear_due_date is not supported by macOS Reminders scripting"
        )
    if clear_due_date and has_due_date:
        raise ValueError("due_date and clear_due_date cannot be used together")

    payload: dict[str, object] = {
        "id": _normalize_required_text(id, "id"),
        "list": _normalize_required_text(list_name, "list"),
    }
    if has_name:
        payload["name"] = _normalize_required_text(name, "name")
    if has_due_date:
        payload["due_date"] = _parse_time_range_value(
            str(due_date),
            end_of_day=True,
        ).isoformat()
    if clear_due_date:
        payload["clear_due_date"] = True
    if has_body:
        payload["body"] = "" if body is None else str(body)
    if has_priority:
        payload["priority"] = _normalize_reminder_priority(priority)
    if has_completed:
        payload["completed"] = bool(completed)

    result = _run_jxa_json(
        _UPDATE_REMINDER_JXA,
        payload,
        timeout_s=30.0,
    )
    return {
        "available_lists": _normalize_calendar_names(result.get("available_lists")),
        "selected_list": str(result.get("selected_list") or ""),
        "before": dict(result.get("before") or {}),
        "after": dict(result.get("after") or {}),
    }


def _delete_reminder_sync(
    id: str,
    list_name: str,
) -> dict[str, object]:
    result = _run_jxa_json(
        _DELETE_REMINDER_JXA,
        {
            "id": _normalize_required_text(id, "id"),
            "list": _normalize_required_text(list_name, "list"),
        },
        timeout_s=30.0,
    )
    return {
        "available_lists": _normalize_calendar_names(result.get("available_lists")),
        "selected_list": str(result.get("selected_list") or ""),
        "deleted": dict(result.get("deleted") or {}),
    }

def _parse_create_reminder_args(args: dict[str, object]) -> dict[str, object]:
    raw_name = args.get("name") if "name" in args else args.get("title")
    raw_body = args.get("body") if "body" in args else args.get("notes")
    return {
        "name": raw_name,
        "list": args.get("list") or args.get("list_name"),
        "due_date": args.get("due_date"),
        "body": raw_body if ("body" in args or "notes" in args) else None,
        "priority": args.get("priority") if "priority" in args else None,
    }


def _parse_update_reminder_args(args: dict[str, object]) -> dict[str, object]:
    has_name = "name" in args or "title" in args
    has_body = "body" in args or "notes" in args
    return {
        "id": args.get("id"),
        "list": args.get("list") or args.get("list_name"),
        "name": args.get("name") if "name" in args else args.get("title"),
        "due_date": args.get("due_date"),
        "clear_due_date": bool(args.get("clear_due_date", False)),
        "body": args.get("body") if "body" in args else args.get("notes"),
        "priority": args.get("priority") if "priority" in args else None,
        "completed": args.get("completed") if "completed" in args else None,
        "has_name": has_name,
        "has_due_date": "due_date" in args,
        "has_body": has_body,
        "has_priority": "priority" in args,
        "has_completed": "completed" in args,
    }


def _parse_delete_reminder_args(args: dict[str, object]) -> dict[str, object]:
    return {
        "id": args.get("id"),
        "list": args.get("list") or args.get("list_name"),
    }
