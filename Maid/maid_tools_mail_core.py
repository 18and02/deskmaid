"""Mail.app core helpers for the desktop maid."""

from __future__ import annotations

import time
from typing import Annotated, NotRequired, TypedDict

from maid_tools_apple_common import (
    _format_address_line,
    _format_attachment_preview_lines,
    _format_mail_receipt_lines,
    _format_mail_subject_label,
    _format_mailbox_label,
    _trim_preview_block,
)
from maid_tools_shared import (
    _attachment_metadata_from_paths,
    _normalize_attachment_paths,
    _normalize_calendar_names,
    _run_applescript,
    _run_jxa_json,
)

class ReadUnreadMailHeadersArgs(TypedDict, total=False):
    accounts: NotRequired[
        Annotated[
            list[str],
            "Optional macOS Mail account names to inspect. Defaults to every account.",
        ]
    ]
    mailboxes: NotRequired[
        Annotated[
            list[str],
            "Optional mailbox names to inspect. Defaults to ['INBOX'].",
        ]
    ]
    limit: NotRequired[
        Annotated[
            int,
            "Maximum number of unread mail headers to return. Defaults to 20 and is capped at 100.",
        ]
    ]
    newest_first: NotRequired[
        Annotated[
            bool,
            "Whether to sort the unread headers newest first. Defaults to true.",
        ]
    ]


class ReadMailMessageArgs(TypedDict, total=False):
    id: NotRequired[
        Annotated[
            str,
            "Optional local Mail message id, such as the id returned by read_unread_mail_headers.",
        ]
    ]
    message_id: NotRequired[
        Annotated[
            str,
            "Optional RFC 822 Message-ID header value for the target message.",
        ]
    ]
    account: NotRequired[
        Annotated[
            str,
            "Optional Mail account name to narrow the search to one account.",
        ]
    ]
    accounts: NotRequired[
        Annotated[
            list[str],
            "Optional Mail account names to narrow the search.",
        ]
    ]
    mailbox: NotRequired[
        Annotated[
            str,
            "Optional mailbox name to narrow the search to one mailbox.",
        ]
    ]
    mailboxes: NotRequired[
        Annotated[
            list[str],
            "Optional mailbox names to narrow the search.",
        ]
    ]
    max_body_chars: NotRequired[
        Annotated[
            int,
            "Maximum number of body characters to return. Defaults to 12000 and is capped at 50000.",
        ]
    ]


class MarkMailReadArgs(TypedDict, total=False):
    id: NotRequired[
        Annotated[
            str,
            "Optional local Mail message id, such as the id returned by read_unread_mail_headers.",
        ]
    ]
    message_id: NotRequired[
        Annotated[
            str,
            "Optional RFC 822 Message-ID header value for the target message.",
        ]
    ]
    account: NotRequired[
        Annotated[
            str,
            "Optional Mail account name to narrow the search to one account.",
        ]
    ]
    accounts: NotRequired[
        Annotated[
            list[str],
            "Optional Mail account names to narrow the search.",
        ]
    ]
    mailbox: NotRequired[
        Annotated[
            str,
            "Optional mailbox name to narrow the search to one mailbox.",
        ]
    ]
    mailboxes: NotRequired[
        Annotated[
            list[str],
            "Optional mailbox names to narrow the search.",
        ]
    ]


class CreateMailDraftArgs(TypedDict, total=False):
    to: NotRequired[
        Annotated[
            list[str],
            "Optional To recipient addresses for a new draft or to append on a reply draft.",
        ]
    ]
    cc: NotRequired[
        Annotated[
            list[str],
            "Optional CC recipient addresses for a new draft or reply draft.",
        ]
    ]
    bcc: NotRequired[
        Annotated[
            list[str],
            "Optional BCC recipient addresses for a new draft or reply draft.",
        ]
    ]
    subject: NotRequired[
        Annotated[
            str,
            "Optional subject line. For reply drafts, defaults to Mail.app's generated reply subject.",
        ]
    ]
    body: NotRequired[
        Annotated[
            str,
            "Optional plain-text body content for the draft.",
        ]
    ]
    attachments: NotRequired[
        Annotated[
            list[str],
            "Optional absolute or ~/ local file paths to attach to the draft.",
        ]
    ]
    attachment_paths: NotRequired[
        Annotated[
            list[str],
            "Alias of attachments: local file paths to attach to the draft.",
        ]
    ]
    reply_to_id: NotRequired[
        Annotated[
            str,
            "Optional local Mail message id to reply to.",
        ]
    ]
    reply_to_message_id: NotRequired[
        Annotated[
            str,
            "Optional RFC 822 Message-ID header value for the message to reply to.",
        ]
    ]
    reply_account: NotRequired[
        Annotated[
            str,
            "Optional Mail account name to narrow reply target lookup to one account.",
        ]
    ]
    reply_accounts: NotRequired[
        Annotated[
            list[str],
            "Optional Mail account names to narrow reply target lookup.",
        ]
    ]
    reply_mailbox: NotRequired[
        Annotated[
            str,
            "Optional mailbox name to narrow reply target lookup to one mailbox.",
        ]
    ]
    reply_mailboxes: NotRequired[
        Annotated[
            list[str],
            "Optional mailbox names to narrow reply target lookup.",
        ]
    ]


class SendMailDraftArgs(TypedDict, total=False):
    id: NotRequired[
        Annotated[
            str,
            "Optional local Mail draft id, such as the id returned by create_mail_draft.",
        ]
    ]
    message_id: NotRequired[
        Annotated[
            str,
            "Optional RFC 822 Message-ID header value for the saved draft to send.",
        ]
    ]
    outgoing_id: NotRequired[
        Annotated[
            str,
            "Optional live Mail outgoing draft id, such as the outgoing_id returned by create_mail_draft.",
        ]
    ]
    account: NotRequired[
        Annotated[
            str,
            "Optional Mail account name to narrow the saved draft lookup to one account.",
        ]
    ]
    accounts: NotRequired[
        Annotated[
            list[str],
            "Optional Mail account names to narrow the saved draft lookup.",
        ]
    ]
    mailbox: NotRequired[
        Annotated[
            str,
            "Optional mailbox name to narrow the saved draft lookup to one mailbox. Defaults to Drafts.",
        ]
    ]
    mailboxes: NotRequired[
        Annotated[
            list[str],
            "Optional mailbox names to narrow the saved draft lookup. Defaults to ['Drafts'].",
        ]
    ]

DEFAULT_MAIL_HEADER_LIMIT = 20
MAX_MAIL_HEADER_LIMIT = 100
DEFAULT_MAIL_BODY_CHAR_LIMIT = 12000
MAX_MAIL_BODY_CHAR_LIMIT = 50000
DEFAULT_MAILBOX_NAMES = ["INBOX"]
DEFAULT_DRAFT_MAILBOX_NAMES = ["Drafts"]

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


_READ_UNREAD_MAIL_HEADERS_JXA = r"""
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
  var limit = Number(config.limit || 20);
  var newestFirst = config.newest_first !== false;
  var requestedMailboxes = Array.isArray(config.mailboxes) && config.mailboxes.length
    ? config.mailboxes
    : ["INBOX"];

  var app = Application("Mail");
  var allAccounts = app.accounts();
  var availableAccounts = [];
  var accountByName = {};
  for (var i = 0; i < allAccounts.length; i++) {
    var account = allAccounts[i];
    var name = account.name();
    availableAccounts.push(name);
    if (!Object.prototype.hasOwnProperty.call(accountByName, name)) {
      accountByName[name] = account;
    }
  }

  var requestedAccounts = Array.isArray(config.accounts) && config.accounts.length
    ? config.accounts
    : availableAccounts;
  var selectedAccounts = [];
  var missingAccounts = [];
  for (var a = 0; a < requestedAccounts.length; a++) {
    var requestedAccount = String(requestedAccounts[a] || "").trim();
    if (!requestedAccount.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(accountByName, requestedAccount)) {
      selectedAccounts.push(requestedAccount);
    } else {
      missingAccounts.push(requestedAccount);
    }
  }

  var missingMailboxes = [];
  var messages = [];
  for (var s = 0; s < selectedAccounts.length; s++) {
    var accountName = selectedAccounts[s];
    var account = accountByName[accountName];
    for (var m = 0; m < requestedMailboxes.length; m++) {
      var requestedMailbox = String(requestedMailboxes[m] || "").trim();
      if (!requestedMailbox.length) {
        continue;
      }

      var mailbox = null;
      try {
        mailbox = account.mailboxes.byName(requestedMailbox)();
      } catch (error) {
        mailbox = null;
      }
      if (!mailbox) {
        missingMailboxes.push(accountName + "/" + requestedMailbox);
        continue;
      }

      var unread = mailbox.messages.whose({readStatus: false})();
      for (var u = 0; u < unread.length; u++) {
        var message = unread[u];
        messages.push({
          account: accountName,
          mailbox: requestedMailbox,
          id: normalizeText(message.id()),
          message_id: normalizeText(message.messageId()),
          subject: normalizeText(message.subject()) || "",
          sender: normalizeText(message.sender()),
          date_received: isoOrNull(message.dateReceived()),
          flagged: !!message.flaggedStatus(),
          unread: true
        });
      }
    }
  }

  messages.sort(function(a, b) {
    var aDate = sortKey(a.date_received, newestFirst ? "" : "9999-12-31T23:59:59.999Z");
    var bDate = sortKey(b.date_received, newestFirst ? "" : "9999-12-31T23:59:59.999Z");
    if (aDate < bDate) {
      return newestFirst ? 1 : -1;
    }
    if (aDate > bDate) {
      return newestFirst ? -1 : 1;
    }
    if ((a.account || "") < (b.account || "")) {
      return -1;
    }
    if ((a.account || "") > (b.account || "")) {
      return 1;
    }
    if ((a.mailbox || "") < (b.mailbox || "")) {
      return -1;
    }
    if ((a.mailbox || "") > (b.mailbox || "")) {
      return 1;
    }
    if ((a.subject || "") < (b.subject || "")) {
      return -1;
    }
    if ((a.subject || "") > (b.subject || "")) {
      return 1;
    }
    return 0;
  });

  var totalMatches = messages.length;
  if (limit >= 0 && messages.length > limit) {
    messages = messages.slice(0, limit);
  }

  return JSON.stringify({
    available_accounts: availableAccounts,
    selected_accounts: selectedAccounts,
    requested_mailboxes: requestedMailboxes,
    missing_accounts: missingAccounts,
    missing_mailboxes: missingMailboxes,
    newest_first: newestFirst,
    total_matches: totalMatches,
    returned_count: messages.length,
    messages: messages
  });
}
"""


_READ_MAIL_MESSAGE_JXA = r"""
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
    .replace(/\uFFFC/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim();
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
  var targetId = normalizeText(config.id);
  var targetMessageId = normalizeText(config.message_id);
  var maxBodyChars = Number(config.max_body_chars || 12000);
  if (!targetId && !targetMessageId) {
    throw new Error("either id or message_id is required");
  }
  if (isNaN(maxBodyChars) || maxBodyChars < 1) {
    throw new Error("invalid max_body_chars");
  }

  var app = Application("Mail");
  var allAccounts = app.accounts();
  var availableAccounts = [];
  var accountByName = {};
  for (var i = 0; i < allAccounts.length; i++) {
    var account = allAccounts[i];
    var accountName = account.name();
    availableAccounts.push(accountName);
    if (!Object.prototype.hasOwnProperty.call(accountByName, accountName)) {
      accountByName[accountName] = account;
    }
  }

  var requestedAccounts = Array.isArray(config.accounts) && config.accounts.length
    ? config.accounts
    : availableAccounts;
  var selectedAccounts = [];
  var missingAccounts = [];
  for (var a = 0; a < requestedAccounts.length; a++) {
    var requestedAccount = String(requestedAccounts[a] || "").trim();
    if (!requestedAccount.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(accountByName, requestedAccount)) {
      selectedAccounts.push(requestedAccount);
    } else {
      missingAccounts.push(requestedAccount);
    }
  }

  var requestedMailboxes = Array.isArray(config.mailboxes) && config.mailboxes.length
    ? config.mailboxes
    : null;
  var searchedMailboxes = [];
  var missingMailboxes = [];
  var matches = [];

  for (var s = 0; s < selectedAccounts.length; s++) {
    var accountName = selectedAccounts[s];
    var selectedAccount = accountByName[accountName];
    var accountMailboxes = selectedAccount.mailboxes();
    var availableMailboxNames = [];
    var mailboxByName = {};
    for (var m = 0; m < accountMailboxes.length; m++) {
      var mailbox = accountMailboxes[m];
      var mailboxName = mailbox.name();
      availableMailboxNames.push(mailboxName);
      if (!Object.prototype.hasOwnProperty.call(mailboxByName, mailboxName)) {
        mailboxByName[mailboxName] = mailbox;
      }
    }

    var mailboxNamesToSearch = requestedMailboxes || availableMailboxNames;
    for (var n = 0; n < mailboxNamesToSearch.length; n++) {
      var requestedMailbox = String(mailboxNamesToSearch[n] || "").trim();
      if (!requestedMailbox.length) {
        continue;
      }

      if (!Object.prototype.hasOwnProperty.call(mailboxByName, requestedMailbox)) {
        missingMailboxes.push(accountName + "/" + requestedMailbox);
        continue;
      }

      var selectedMailbox = mailboxByName[requestedMailbox];
      searchedMailboxes.push(accountName + "/" + requestedMailbox);

      var candidates;
      if (targetId) {
        var numericId = Number(targetId);
        if (isNaN(numericId)) {
          candidates = selectedMailbox.messages();
        } else {
          candidates = selectedMailbox.messages.whose({id: numericId})();
        }
      } else if (targetMessageId) {
        candidates = selectedMailbox.messages.whose({messageId: targetMessageId})();
      } else {
        candidates = selectedMailbox.messages();
      }

      for (var c = 0; c < candidates.length; c++) {
        var message = candidates[c];
        var candidateId = normalizeText(message.id());
        var candidateMessageId = normalizeText(message.messageId());
        if (targetId && candidateId !== targetId) {
          continue;
        }
        if (targetMessageId && candidateMessageId !== targetMessageId) {
          continue;
        }

        var body = "";
        var bodyFormat = "content";
        try {
          body = normalizeBody(message.content());
        } catch (contentError) {
          try {
            body = normalizeBody(message.source());
            bodyFormat = "source";
          } catch (sourceError) {
            body = "";
            bodyFormat = "unavailable";
          }
        }

        var bodyLength = body.length;
        var bodyTruncated = false;
        if (bodyLength > maxBodyChars) {
          body = body.slice(0, maxBodyChars);
          bodyTruncated = true;
        }

        matches.push({
          account: accountName,
          mailbox: requestedMailbox,
          id: candidateId,
          message_id: candidateMessageId,
          subject: normalizeText(message.subject()) || "",
          sender: normalizeText(message.sender()),
          date_received: isoOrNull(message.dateReceived()),
          date_sent: isoOrNull(message.dateSent()),
          flagged: !!message.flaggedStatus(),
          unread: !message.readStatus(),
          body: body,
          body_format: bodyFormat,
          body_length: bodyLength,
          body_truncated: bodyTruncated
        });
      }
    }
  }

  matches.sort(function(a, b) {
    if ((a.date_received || "") < (b.date_received || "")) {
      return 1;
    }
    if ((a.date_received || "") > (b.date_received || "")) {
      return -1;
    }
    if ((a.account || "") < (b.account || "")) {
      return -1;
    }
    if ((a.account || "") > (b.account || "")) {
      return 1;
    }
    if ((a.mailbox || "") < (b.mailbox || "")) {
      return -1;
    }
    if ((a.mailbox || "") > (b.mailbox || "")) {
      return 1;
    }
    return 0;
  });

  return JSON.stringify({
    available_accounts: availableAccounts,
    selected_accounts: selectedAccounts,
    requested_mailboxes: requestedMailboxes || [],
    searched_mailboxes: searchedMailboxes,
    missing_accounts: missingAccounts,
    missing_mailboxes: missingMailboxes,
    target_id: targetId,
    target_message_id: targetMessageId,
    total_matches: matches.length,
    matches: matches
  });
}
"""


_LOOKUP_MAIL_DRAFT_JXA = r"""
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
    .replace(/\uFFFC/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim();
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

function sortedCopy(values) {
  var copy = values.slice();
  copy.sort();
  return copy;
}

function sameTextList(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  var leftSorted = sortedCopy(left);
  var rightSorted = sortedCopy(right);
  for (var i = 0; i < leftSorted.length; i++) {
    if (leftSorted[i] !== rightSorted[i]) {
      return false;
    }
  }
  return true;
}

function safeText(getter) {
  try {
    return normalizeText(getter());
  } catch (error) {
    return null;
  }
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
      var rawSize = attachment.fileSize();
      if (rawSize !== null && rawSize !== undefined) {
        var numericSize = Number(rawSize);
        if (!isNaN(numericSize)) {
          sizeBytes = numericSize;
        }
      }
    } catch (error) {
      sizeBytes = null;
    }

    details.push({
      id: safeText(function() { return attachment.id(); }),
      name: safeText(function() { return attachment.name(); }) || "",
      size_bytes: sizeBytes,
      downloaded: (function() {
        try {
          return !!attachment.downloaded();
        } catch (error) {
          return null;
        }
      })()
    });
  }
  return details;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var targetId = normalizeText(config.id);
  var targetMessageId = normalizeText(config.message_id);
  var targetSubject = normalizeText(config.subject);
  var targetSender = normalizeText(config.sender);
  var hasExpectedTo = Array.isArray(config.to);
  var expectedTo = hasExpectedTo ? config.to : [];
  var hasExpectedCc = Array.isArray(config.cc);
  var expectedCc = hasExpectedCc ? config.cc : [];
  var hasExpectedBcc = Array.isArray(config.bcc);
  var expectedBcc = hasExpectedBcc ? config.bcc : [];
  var expectedBody = config.body === null || config.body === undefined
    ? null
    : normalizeBody(config.body);
  var hasContentMatch = targetSubject !== null
    || targetSender !== null
    || hasExpectedTo
    || hasExpectedCc
    || hasExpectedBcc
    || expectedBody !== null;
  if (!targetId && !targetMessageId && !hasContentMatch) {
    throw new Error("lookup requires id, message_id, or draft content criteria");
  }

  var app = Application("Mail");
  var allAccounts = app.accounts();
  var availableAccounts = [];
  var accountByName = {};
  for (var i = 0; i < allAccounts.length; i++) {
    var account = allAccounts[i];
    var accountName = account.name();
    availableAccounts.push(accountName);
    if (!Object.prototype.hasOwnProperty.call(accountByName, accountName)) {
      accountByName[accountName] = account;
    }
  }

  var requestedAccounts = Array.isArray(config.accounts) && config.accounts.length
    ? config.accounts
    : availableAccounts;
  var selectedAccounts = [];
  var missingAccounts = [];
  for (var a = 0; a < requestedAccounts.length; a++) {
    var requestedAccount = String(requestedAccounts[a] || "").trim();
    if (!requestedAccount.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(accountByName, requestedAccount)) {
      selectedAccounts.push(requestedAccount);
    } else {
      missingAccounts.push(requestedAccount);
    }
  }

  var requestedMailboxes = Array.isArray(config.mailboxes) && config.mailboxes.length
    ? config.mailboxes
    : ["Drafts"];
  var searchedMailboxes = [];
  var missingMailboxes = [];
  var matches = [];

  for (var s = 0; s < selectedAccounts.length; s++) {
    var accountName = selectedAccounts[s];
    var selectedAccount = accountByName[accountName];
    var accountMailboxes = selectedAccount.mailboxes();
    var mailboxByName = {};
    for (var m = 0; m < accountMailboxes.length; m++) {
      var mailbox = accountMailboxes[m];
      var mailboxName = mailbox.name();
      if (!Object.prototype.hasOwnProperty.call(mailboxByName, mailboxName)) {
        mailboxByName[mailboxName] = mailbox;
      }
    }

    for (var n = 0; n < requestedMailboxes.length; n++) {
      var requestedMailbox = String(requestedMailboxes[n] || "").trim();
      if (!requestedMailbox.length) {
        continue;
      }

      if (!Object.prototype.hasOwnProperty.call(mailboxByName, requestedMailbox)) {
        missingMailboxes.push(accountName + "/" + requestedMailbox);
        continue;
      }

      var selectedMailbox = mailboxByName[requestedMailbox];
      searchedMailboxes.push(accountName + "/" + requestedMailbox);

      var candidates;
      if (targetId) {
        var numericId = Number(targetId);
        if (isNaN(numericId)) {
          candidates = selectedMailbox.messages();
        } else {
          candidates = selectedMailbox.messages.whose({id: numericId})();
        }
      } else if (targetMessageId) {
        candidates = selectedMailbox.messages.whose({messageId: targetMessageId})();
      } else {
        candidates = selectedMailbox.messages();
      }

      for (var c = 0; c < candidates.length; c++) {
        var message = candidates[c];
        var candidateId = normalizeText(message.id());
        var candidateMessageId = normalizeText(message.messageId());
        var body = "";
        try {
          body = normalizeBody(message.content());
        } catch (error) {
          body = "";
        }
        var candidateSubject = normalizeText(message.subject()) || "";
        var candidateSender = normalizeText(message.sender());
        var candidateTo = recipientAddresses(message.toRecipients);
        var candidateCc = recipientAddresses(message.ccRecipients);
        var candidateBcc = recipientAddresses(message.bccRecipients);

        if (targetId || targetMessageId) {
          if (targetId && candidateId !== targetId) {
            continue;
          }
          if (targetMessageId && candidateMessageId !== targetMessageId) {
            continue;
          }
        } else {
          if (targetSubject !== null && candidateSubject !== targetSubject) {
            continue;
          }
          if (targetSender !== null && candidateSender !== targetSender) {
            continue;
          }
          if (hasExpectedTo && !sameTextList(candidateTo, expectedTo)) {
            continue;
          }
          if (hasExpectedCc && !sameTextList(candidateCc, expectedCc)) {
            continue;
          }
          if (hasExpectedBcc && !sameTextList(candidateBcc, expectedBcc)) {
            continue;
          }
          if (expectedBody !== null && body.indexOf(expectedBody) === -1) {
            continue;
          }
        }
        var attachments = attachmentDetails(message);

        matches.push({
          account: accountName,
          mailbox: requestedMailbox,
          id: candidateId,
          message_id: candidateMessageId,
          subject: candidateSubject,
          sender: candidateSender,
          to: candidateTo,
          cc: candidateCc,
          bcc: candidateBcc,
          body: body,
          body_length: body.length,
          attachments: attachments,
          attachment_count: attachments.length,
          date_received: isoOrNull(message.dateReceived()),
          date_sent: isoOrNull(message.dateSent())
        });
      }
    }
  }

  matches.sort(function(a, b) {
    if ((a.date_received || "") < (b.date_received || "")) {
      return 1;
    }
    if ((a.date_received || "") > (b.date_received || "")) {
      return -1;
    }
    if ((a.account || "") < (b.account || "")) {
      return -1;
    }
    if ((a.account || "") > (b.account || "")) {
      return 1;
    }
    if ((a.mailbox || "") < (b.mailbox || "")) {
      return -1;
    }
    if ((a.mailbox || "") > (b.mailbox || "")) {
      return 1;
    }
    return 0;
  });

  return JSON.stringify({
    available_accounts: availableAccounts,
    selected_accounts: selectedAccounts,
    requested_mailboxes: requestedMailboxes,
    searched_mailboxes: searchedMailboxes,
    missing_accounts: missingAccounts,
    missing_mailboxes: missingMailboxes,
    target_id: targetId,
    target_message_id: targetMessageId,
    total_matches: matches.length,
    matches: matches
  });
}
"""


_SEND_OUTGOING_MAIL_DRAFT_JXA = r"""
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
    .replace(/\uFFFC/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim();
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

function sortedCopy(values) {
  var copy = values.slice();
  copy.sort();
  return copy;
}

function sameTextList(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  var leftSorted = sortedCopy(left);
  var rightSorted = sortedCopy(right);
  for (var i = 0; i < leftSorted.length; i++) {
    if (leftSorted[i] !== rightSorted[i]) {
      return false;
    }
  }
  return true;
}

function findMatches(app, lookupConfig) {
  var targetOutgoingId = normalizeText(lookupConfig.outgoing_id);
  var expectedSubject = normalizeText(lookupConfig.subject);
  var expectedSender = normalizeText(lookupConfig.sender);
  var expectedTo = Array.isArray(lookupConfig.to) ? lookupConfig.to : [];
  var expectedCc = Array.isArray(lookupConfig.cc) ? lookupConfig.cc : [];
  var expectedBcc = Array.isArray(lookupConfig.bcc) ? lookupConfig.bcc : [];
  var expectedBody = lookupConfig.body === null || lookupConfig.body === undefined
    ? null
    : normalizeBody(lookupConfig.body);

  var hasContentMatch = expectedSubject !== null
    || expectedSender !== null
    || expectedTo.length > 0
    || expectedCc.length > 0
    || expectedBcc.length > 0
    || expectedBody !== null;
  if (!targetOutgoingId && !hasContentMatch) {
    throw new Error("outgoing draft lookup requires outgoing_id or draft content");
  }

  var drafts = app.outgoingMessages();
  var matches = [];
  for (var i = 0; i < drafts.length; i++) {
    var draft = drafts[i];
    var outgoingId = normalizeText(draft.id());
    if (targetOutgoingId && outgoingId !== targetOutgoingId) {
      continue;
    }

    var subject = normalizeText(draft.subject()) || "";
    var sender = normalizeText(draft.sender());
    var toRecipients = recipientAddresses(draft.toRecipients);
    var ccRecipients = recipientAddresses(draft.ccRecipients);
    var bccRecipients = recipientAddresses(draft.bccRecipients);
    var body = "";
    try {
      body = normalizeBody(draft.content());
    } catch (error) {
      body = "";
    }

    if (!targetOutgoingId) {
      if (expectedSubject !== null && subject !== expectedSubject) {
        continue;
      }
      if (expectedSender !== null && sender !== expectedSender) {
        continue;
      }
      if (!sameTextList(expectedTo, toRecipients)) {
        continue;
      }
      if (!sameTextList(expectedCc, ccRecipients)) {
        continue;
      }
      if (!sameTextList(expectedBcc, bccRecipients)) {
        continue;
      }
      if (expectedBody !== null && body !== expectedBody) {
        continue;
      }
    }

    matches.push({
      outgoing_id: outgoingId,
      subject: subject,
      sender: sender,
      to: toRecipients,
      cc: ccRecipients,
      bcc: bccRecipients,
      body: body,
      body_length: body.length,
      visible: (function() {
        try {
          return !!draft.visible();
        } catch (error) {
          return false;
        }
      })(),
      _draft: draft
    });
  }

  matches.sort(function(a, b) {
    if ((a.outgoing_id || "") < (b.outgoing_id || "")) {
      return -1;
    }
    if ((a.outgoing_id || "") > (b.outgoing_id || "")) {
      return 1;
    }
    return 0;
  });
  return matches;
}

function serializeMatches(matches) {
  var serializable = [];
  for (var i = 0; i < matches.length; i++) {
    var match = matches[i];
    serializable.push({
      outgoing_id: match.outgoing_id,
      subject: match.subject,
      sender: match.sender,
      to: match.to,
      cc: match.cc,
      bcc: match.bcc,
      body: match.body,
      body_length: match.body_length,
      visible: match.visible
    });
  }
  return serializable;
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var shouldSend = !!config.send;
  var app = Application("Mail");
  var matches = findMatches(app, config);
  var serializableMatches = serializeMatches(matches);

  if (!shouldSend) {
    return JSON.stringify({
      total_matches: serializableMatches.length,
      matches: serializableMatches
    });
  }

  if (matches.length !== 1) {
    return JSON.stringify({
      sent: false,
      total_matches: serializableMatches.length,
      matches: serializableMatches
    });
  }

  var target = matches[0];
  target._draft.send();
  delay(0.8);

  var remaining = findMatches(app, {outgoing_id: target.outgoing_id});
  return JSON.stringify({
    sent: true,
    outgoing_id: target.outgoing_id,
    subject: target.subject,
    sender: target.sender,
    to: target.to,
    cc: target.cc,
    bcc: target.bcc,
    body: target.body,
    body_length: target.body_length,
    visible: target.visible,
    sent_at: (new Date()).toISOString(),
    remaining_outgoing_matches: remaining.length
  });
}
"""


_MARK_MAIL_READ_JXA = r"""
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
  var targetId = normalizeText(config.id);
  var targetMessageId = normalizeText(config.message_id);
  if (!targetId && !targetMessageId) {
    throw new Error("either id or message_id is required");
  }

  var app = Application("Mail");
  var allAccounts = app.accounts();
  var availableAccounts = [];
  var accountByName = {};
  for (var i = 0; i < allAccounts.length; i++) {
    var account = allAccounts[i];
    var accountName = account.name();
    availableAccounts.push(accountName);
    if (!Object.prototype.hasOwnProperty.call(accountByName, accountName)) {
      accountByName[accountName] = account;
    }
  }

  var requestedAccounts = Array.isArray(config.accounts) && config.accounts.length
    ? config.accounts
    : availableAccounts;
  var selectedAccounts = [];
  var missingAccounts = [];
  for (var a = 0; a < requestedAccounts.length; a++) {
    var requestedAccount = String(requestedAccounts[a] || "").trim();
    if (!requestedAccount.length) {
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(accountByName, requestedAccount)) {
      selectedAccounts.push(requestedAccount);
    } else {
      missingAccounts.push(requestedAccount);
    }
  }

  var requestedMailboxes = Array.isArray(config.mailboxes) && config.mailboxes.length
    ? config.mailboxes
    : null;
  var searchedMailboxes = [];
  var missingMailboxes = [];
  var matches = [];

  for (var s = 0; s < selectedAccounts.length; s++) {
    var accountName = selectedAccounts[s];
    var selectedAccount = accountByName[accountName];
    var accountMailboxes = selectedAccount.mailboxes();
    var availableMailboxNames = [];
    var mailboxByName = {};
    for (var m = 0; m < accountMailboxes.length; m++) {
      var mailbox = accountMailboxes[m];
      var mailboxName = mailbox.name();
      availableMailboxNames.push(mailboxName);
      if (!Object.prototype.hasOwnProperty.call(mailboxByName, mailboxName)) {
        mailboxByName[mailboxName] = mailbox;
      }
    }

    var mailboxNamesToSearch = requestedMailboxes || availableMailboxNames;
    for (var n = 0; n < mailboxNamesToSearch.length; n++) {
      var requestedMailbox = String(mailboxNamesToSearch[n] || "").trim();
      if (!requestedMailbox.length) {
        continue;
      }

      if (!Object.prototype.hasOwnProperty.call(mailboxByName, requestedMailbox)) {
        missingMailboxes.push(accountName + "/" + requestedMailbox);
        continue;
      }

      var selectedMailbox = mailboxByName[requestedMailbox];
      searchedMailboxes.push(accountName + "/" + requestedMailbox);

      var candidates;
      if (targetId) {
        var numericId = Number(targetId);
        if (isNaN(numericId)) {
          candidates = selectedMailbox.messages();
        } else {
          candidates = selectedMailbox.messages.whose({id: numericId})();
        }
      } else {
        candidates = selectedMailbox.messages.whose({messageId: targetMessageId})();
      }

      for (var c = 0; c < candidates.length; c++) {
        var message = candidates[c];
        var candidateId = normalizeText(message.id());
        var candidateMessageId = normalizeText(message.messageId());
        if (targetId && candidateId !== targetId) {
          continue;
        }
        if (targetMessageId && candidateMessageId !== targetMessageId) {
          continue;
        }

        matches.push({
          account: accountName,
          mailbox: requestedMailbox,
          id: candidateId,
          message_id: candidateMessageId,
          subject: normalizeText(message.subject()) || "",
          sender: normalizeText(message.sender()),
          date_received: isoOrNull(message.dateReceived()),
          date_sent: isoOrNull(message.dateSent()),
          flagged: !!message.flaggedStatus(),
          read_before: !!message.readStatus(),
          _message: message
        });
      }
    }
  }

  matches.sort(function(a, b) {
    if ((a.date_received || "") < (b.date_received || "")) {
      return 1;
    }
    if ((a.date_received || "") > (b.date_received || "")) {
      return -1;
    }
    if ((a.account || "") < (b.account || "")) {
      return -1;
    }
    if ((a.account || "") > (b.account || "")) {
      return 1;
    }
    if ((a.mailbox || "") < (b.mailbox || "")) {
      return -1;
    }
    if ((a.mailbox || "") > (b.mailbox || "")) {
      return 1;
    }
    return 0;
  });

  if (matches.length === 1) {
    var target = matches[0];
    target._message.readStatus = true;
    delay(0.1);
    target.read_after = !!target._message.readStatus();
    target.changed = target.read_before !== target.read_after;
  } else {
    for (var k = 0; k < matches.length; k++) {
      matches[k].read_after = matches[k].read_before;
      matches[k].changed = false;
    }
  }

  var serializableMatches = [];
  for (var r = 0; r < matches.length; r++) {
    var match = matches[r];
    serializableMatches.push({
      account: match.account,
      mailbox: match.mailbox,
      id: match.id,
      message_id: match.message_id,
      subject: match.subject,
      sender: match.sender,
      date_received: match.date_received,
      date_sent: match.date_sent,
      flagged: match.flagged,
      read_before: match.read_before,
      read_after: match.read_after,
      changed: match.changed
    });
  }

  return JSON.stringify({
    available_accounts: availableAccounts,
    selected_accounts: selectedAccounts,
    requested_mailboxes: requestedMailboxes || [],
    searched_mailboxes: searchedMailboxes,
    missing_accounts: missingAccounts,
    missing_mailboxes: missingMailboxes,
    target_id: targetId,
    target_message_id: targetMessageId,
    total_matches: serializableMatches.length,
    matches: serializableMatches
  });
}
"""


_CREATE_MAIL_DRAFT_JXA = r"""
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

function addRecipients(collection, addresses, app) {
  for (var i = 0; i < addresses.length; i++) {
    var address = String(addresses[i] || "").trim();
    if (!address.length) {
      continue;
    }
    collection.push(app.Recipient({address: address}));
  }
}

function sortedCopy(values) {
  var copy = values.slice();
  copy.sort();
  return copy;
}

function sameTextList(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  var leftSorted = sortedCopy(left);
  var rightSorted = sortedCopy(right);
  for (var i = 0; i < leftSorted.length; i++) {
    if (leftSorted[i] !== rightSorted[i]) {
      return false;
    }
  }
  return true;
}

function safeText(getter) {
  try {
    return normalizeText(getter());
  } catch (error) {
    return null;
  }
}

function resolveSavedDraft(draft, app) {
  var actualSubject = safeText(function() { return draft.subject(); }) || "";
  var actualSender = safeText(function() { return draft.sender(); });
  var actualTo = recipientAddresses(draft.toRecipients);
  var actualCc = recipientAddresses(draft.ccRecipients);
  var actualBcc = recipientAddresses(draft.bccRecipients);
  var actualBody = "";
  try {
    actualBody = normalizeBody(draft.content());
  } catch (error) {
    actualBody = "";
  }

  var accounts = app.accounts();
  var matches = [];
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

    var messages = draftsMailbox.messages();
    for (var j = 0; j < messages.length; j++) {
      var message = messages[j];
      var candidateSubject = safeText(function() { return message.subject(); }) || "";
      if (candidateSubject !== actualSubject) {
        continue;
      }

      var candidateSender = safeText(function() { return message.sender(); });
      if (actualSender && candidateSender !== actualSender) {
        continue;
      }

      var candidateTo = recipientAddresses(message.toRecipients);
      var candidateCc = recipientAddresses(message.ccRecipients);
      var candidateBcc = recipientAddresses(message.bccRecipients);
      if (!sameTextList(candidateTo, actualTo)) {
        continue;
      }
      if (!sameTextList(candidateCc, actualCc)) {
        continue;
      }
      if (!sameTextList(candidateBcc, actualBcc)) {
        continue;
      }

      var candidateBody = "";
      try {
        candidateBody = normalizeBody(message.content());
      } catch (error) {
        candidateBody = "";
      }
      if (actualBody.length && candidateBody.indexOf(actualBody) === -1) {
        continue;
      }

      matches.push({
        account: account.name(),
        mailbox: draftsMailbox.name(),
        id: safeText(function() { return message.id(); }),
        message_id: safeText(function() { return message.messageId(); }),
        date_sent: isoOrNull(message.dateSent()),
        date_received: isoOrNull(message.dateReceived())
      });
    }
  }

  matches.sort(function(a, b) {
    var aStamp = a.date_sent || a.date_received || "";
    var bStamp = b.date_sent || b.date_received || "";
    if (aStamp < bStamp) {
      return 1;
    }
    if (aStamp > bStamp) {
      return -1;
    }
    if ((a.id || "") < (b.id || "")) {
      return 1;
    }
    if ((a.id || "") > (b.id || "")) {
      return -1;
    }
    return 0;
  });

  return matches.length ? matches[0] : null;
}

function buildDraftRecord(mode, draft, extra) {
  var body = "";
  try {
    body = normalizeBody(draft.content());
  } catch (error) {
    body = "";
  }
  var savedDraft = resolveSavedDraft(draft, Application("Mail"));

  return {
    mode: mode,
    id: savedDraft ? savedDraft.id : safeText(function() { return draft.id(); }),
    message_id: savedDraft ? savedDraft.message_id : safeText(function() { return draft.messageId(); }),
    outgoing_id: safeText(function() { return draft.id(); }),
    subject: safeText(function() { return draft.subject(); }) || "",
    sender: safeText(function() { return draft.sender(); }),
    to: recipientAddresses(draft.toRecipients),
    cc: recipientAddresses(draft.ccRecipients),
    bcc: recipientAddresses(draft.bccRecipients),
    body: body,
    body_length: body.length,
    created_at: (new Date()).toISOString(),
    visible: (function() {
      try {
        return !!draft.visible();
      } catch (error) {
        return false;
      }
    })(),
    account: savedDraft ? savedDraft.account : null,
    mailbox: savedDraft ? savedDraft.mailbox : null,
    date_sent: savedDraft ? savedDraft.date_sent : null,
    date_received: savedDraft ? savedDraft.date_received : null,
    reply_target: extra.reply_target || null,
    selected_reply_accounts: extra.selected_reply_accounts || [],
    requested_reply_mailboxes: extra.requested_reply_mailboxes || [],
    searched_reply_mailboxes: extra.searched_reply_mailboxes || [],
    missing_reply_accounts: extra.missing_reply_accounts || [],
    missing_reply_mailboxes: extra.missing_reply_mailboxes || []
  };
}

function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var requestedTo = Array.isArray(config.to) ? config.to : [];
  var requestedCc = Array.isArray(config.cc) ? config.cc : [];
  var requestedBcc = Array.isArray(config.bcc) ? config.bcc : [];
  var subjectValue = config.subject === null || config.subject === undefined
    ? ""
    : String(config.subject);
  var bodyProvided = config.body !== null && config.body !== undefined;
  var bodyValue = bodyProvided ? normalizeBody(config.body) : "";
  var replyToId = normalizeText(config.reply_to_id);
  var replyToMessageId = normalizeText(config.reply_to_message_id);
  var isReply = !!replyToId || !!replyToMessageId;

  if (
    !isReply
    && !requestedTo.length
    && !requestedCc.length
    && !requestedBcc.length
    && !subjectValue.length
    && !bodyValue.length
  ) {
    throw new Error("new draft requires at least one of to/cc/bcc/subject/body");
  }

  var app = Application("Mail");
  var draft = null;
  var resultExtra = {
    reply_target: null,
    selected_reply_accounts: [],
    requested_reply_mailboxes: [],
    searched_reply_mailboxes: [],
    missing_reply_accounts: [],
    missing_reply_mailboxes: []
  };

  if (isReply) {
    var allAccounts = app.accounts();
    var availableAccounts = [];
    var accountByName = {};
    for (var i = 0; i < allAccounts.length; i++) {
      var account = allAccounts[i];
      var accountName = account.name();
      availableAccounts.push(accountName);
      if (!Object.prototype.hasOwnProperty.call(accountByName, accountName)) {
        accountByName[accountName] = account;
      }
    }

    var requestedReplyAccounts = Array.isArray(config.reply_accounts) && config.reply_accounts.length
      ? config.reply_accounts
      : availableAccounts;
    var selectedReplyAccounts = [];
    var missingReplyAccounts = [];
    for (var a = 0; a < requestedReplyAccounts.length; a++) {
      var requestedReplyAccount = String(requestedReplyAccounts[a] || "").trim();
      if (!requestedReplyAccount.length) {
        continue;
      }
      if (Object.prototype.hasOwnProperty.call(accountByName, requestedReplyAccount)) {
        selectedReplyAccounts.push(requestedReplyAccount);
      } else {
        missingReplyAccounts.push(requestedReplyAccount);
      }
    }

    var requestedReplyMailboxes = Array.isArray(config.reply_mailboxes) && config.reply_mailboxes.length
      ? config.reply_mailboxes
      : null;
    var searchedReplyMailboxes = [];
    var missingReplyMailboxes = [];
    var matches = [];

    for (var s = 0; s < selectedReplyAccounts.length; s++) {
      var selectedAccountName = selectedReplyAccounts[s];
      var selectedAccount = accountByName[selectedAccountName];
      var accountMailboxes = selectedAccount.mailboxes();
      var availableMailboxNames = [];
      var mailboxByName = {};
      for (var m = 0; m < accountMailboxes.length; m++) {
        var mailbox = accountMailboxes[m];
        var mailboxName = mailbox.name();
        availableMailboxNames.push(mailboxName);
        if (!Object.prototype.hasOwnProperty.call(mailboxByName, mailboxName)) {
          mailboxByName[mailboxName] = mailbox;
        }
      }

      var mailboxNamesToSearch = requestedReplyMailboxes || availableMailboxNames;
      for (var n = 0; n < mailboxNamesToSearch.length; n++) {
        var requestedReplyMailbox = String(mailboxNamesToSearch[n] || "").trim();
        if (!requestedReplyMailbox.length) {
          continue;
        }

        if (!Object.prototype.hasOwnProperty.call(mailboxByName, requestedReplyMailbox)) {
          missingReplyMailboxes.push(selectedAccountName + "/" + requestedReplyMailbox);
          continue;
        }

        var selectedMailbox = mailboxByName[requestedReplyMailbox];
        searchedReplyMailboxes.push(selectedAccountName + "/" + requestedReplyMailbox);

        var candidates;
        if (replyToId) {
          var numericId = Number(replyToId);
          if (isNaN(numericId)) {
            candidates = selectedMailbox.messages();
          } else {
            candidates = selectedMailbox.messages.whose({id: numericId})();
          }
        } else {
          candidates = selectedMailbox.messages.whose({messageId: replyToMessageId})();
        }

        for (var c = 0; c < candidates.length; c++) {
          var message = candidates[c];
          var candidateId = normalizeText(message.id());
          var candidateMessageId = normalizeText(message.messageId());
          if (replyToId && candidateId !== replyToId) {
            continue;
          }
          if (replyToMessageId && candidateMessageId !== replyToMessageId) {
            continue;
          }

          matches.push({
            account: selectedAccountName,
            mailbox: requestedReplyMailbox,
            id: candidateId,
            message_id: candidateMessageId,
            subject: normalizeText(message.subject()) || "",
            sender: normalizeText(message.sender()),
            date_received: isoOrNull(message.dateReceived()),
            _message: message
          });
        }
      }
    }

    matches.sort(function(a, b) {
      if ((a.date_received || "") < (b.date_received || "")) {
        return 1;
      }
      if ((a.date_received || "") > (b.date_received || "")) {
        return -1;
      }
      if ((a.account || "") < (b.account || "")) {
        return -1;
      }
      if ((a.account || "") > (b.account || "")) {
        return 1;
      }
      if ((a.mailbox || "") < (b.mailbox || "")) {
        return -1;
      }
      if ((a.mailbox || "") > (b.mailbox || "")) {
        return 1;
      }
      return 0;
    });

    if (!matches.length) {
      throw new Error("no reply target matched the provided id/message_id");
    }
    if (matches.length > 1) {
      throw new Error("multiple reply targets matched the provided id/message_id");
    }

    var replyTarget = matches[0];
    draft = replyTarget._message.reply();
    try {
      draft.visible = false;
    } catch (error) {
    }
    if (subjectValue.length) {
      draft.subject = subjectValue;
    }
    if (bodyProvided) {
      draft.content = bodyValue;
    }
    addRecipients(draft.toRecipients, requestedTo, app);
    addRecipients(draft.ccRecipients, requestedCc, app);
    addRecipients(draft.bccRecipients, requestedBcc, app);
    draft.save();
    delay(0.2);

    resultExtra = {
      reply_target: {
        account: replyTarget.account,
        mailbox: replyTarget.mailbox,
        id: replyTarget.id,
        message_id: replyTarget.message_id,
        subject: replyTarget.subject,
        sender: replyTarget.sender
      },
      selected_reply_accounts: selectedReplyAccounts,
      requested_reply_mailboxes: requestedReplyMailboxes || [],
      searched_reply_mailboxes: searchedReplyMailboxes,
      missing_reply_accounts: missingReplyAccounts,
      missing_reply_mailboxes: missingReplyMailboxes
    };
  } else {
    draft = app.OutgoingMessage({
      subject: subjectValue,
      content: bodyValue,
      visible: false
    });
    app.outgoingMessages.push(draft);
    addRecipients(draft.toRecipients, requestedTo, app);
    addRecipients(draft.ccRecipients, requestedCc, app);
    addRecipients(draft.bccRecipients, requestedBcc, app);
    draft.save();
    delay(0.2);
  }

  return JSON.stringify(buildDraftRecord(isReply ? "reply" : "new", draft, resultExtra));
}
"""

def _read_unread_mail_headers_sync(
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
    limit: int = DEFAULT_MAIL_HEADER_LIMIT,
    newest_first: bool = True,
) -> dict[str, object]:
    safe_limit = int(limit)
    if safe_limit < 1:
        safe_limit = 1
    if safe_limit > MAX_MAIL_HEADER_LIMIT:
        safe_limit = MAX_MAIL_HEADER_LIMIT

    account_names = _normalize_calendar_names(accounts)
    mailbox_names = _normalize_calendar_names(mailboxes) or list(DEFAULT_MAILBOX_NAMES)
    result = _run_jxa_json(
        _READ_UNREAD_MAIL_HEADERS_JXA,
        {
            "accounts": account_names,
            "mailboxes": mailbox_names,
            "limit": safe_limit,
            "newest_first": bool(newest_first),
        },
    )
    if account_names and not result.get("selected_accounts"):
        available = ", ".join(result.get("available_accounts") or [])
        raise LookupError(
            "none of the requested mail accounts were found"
            + (f"; available accounts: {available}" if available else "")
        )
    return result


def _read_mail_message_sync(
    id: str | None = None,
    message_id: str | None = None,
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
    max_body_chars: int = DEFAULT_MAIL_BODY_CHAR_LIMIT,
) -> dict[str, object]:
    target_id = str(id or "").strip() or None
    target_message_id = str(message_id or "").strip() or None
    if not target_id and not target_message_id:
        raise ValueError("either id or message_id is required")

    safe_max_body_chars = int(max_body_chars)
    if safe_max_body_chars < 1:
        safe_max_body_chars = 1
    if safe_max_body_chars > MAX_MAIL_BODY_CHAR_LIMIT:
        safe_max_body_chars = MAX_MAIL_BODY_CHAR_LIMIT

    account_names = _normalize_calendar_names(accounts)
    mailbox_names = _normalize_calendar_names(mailboxes)
    result = _run_jxa_json(
        _READ_MAIL_MESSAGE_JXA,
        {
            "id": target_id,
            "message_id": target_message_id,
            "accounts": account_names,
            "mailboxes": mailbox_names,
            "max_body_chars": safe_max_body_chars,
        },
        timeout_s=30.0,
    )
    if account_names and not result.get("selected_accounts"):
        available = ", ".join(result.get("available_accounts") or [])
        raise LookupError(
            "none of the requested mail accounts were found"
            + (f"; available accounts: {available}" if available else "")
        )
    if mailbox_names and not result.get("searched_mailboxes"):
        raise LookupError("none of the requested mailboxes were found in the selected accounts")

    matches = result.get("matches") or []
    if not matches:
        searched = ", ".join(result.get("searched_mailboxes") or [])
        search_scope = f" within {searched}" if searched else ""
        raise LookupError(
            "no mail message matched the provided id/message_id" + search_scope
        )
    if len(matches) > 1:
        matched_locations = ", ".join(
            f"{match.get('account')}/{match.get('mailbox')}"
            for match in matches[:8]
        )
        extra_count = len(matches) - 8
        if extra_count > 0:
            matched_locations += f", and {extra_count} more"
        raise LookupError(
            "multiple mail messages matched the provided id/message_id; "
            f"narrow the search with account or mailbox. Matches: {matched_locations}"
        )

    match = matches[0]
    return {
        "target_id": result.get("target_id"),
        "target_message_id": result.get("target_message_id"),
        "selected_accounts": result.get("selected_accounts") or [],
        "requested_mailboxes": result.get("requested_mailboxes") or [],
        "searched_mailboxes": result.get("searched_mailboxes") or [],
        "missing_mailboxes": result.get("missing_mailboxes") or [],
        "account": match.get("account"),
        "mailbox": match.get("mailbox"),
        "id": match.get("id"),
        "message_id": match.get("message_id"),
        "subject": match.get("subject"),
        "sender": match.get("sender"),
        "date_received": match.get("date_received"),
        "date_sent": match.get("date_sent"),
        "flagged": match.get("flagged"),
        "unread": match.get("unread"),
        "body": match.get("body"),
        "body_format": match.get("body_format"),
        "body_length": match.get("body_length"),
        "body_truncated": match.get("body_truncated"),
    }


def _mark_mail_read_sync(
    id: str | None = None,
    message_id: str | None = None,
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
) -> dict[str, object]:
    target_id = str(id or "").strip() or None
    target_message_id = str(message_id or "").strip() or None
    if not target_id and not target_message_id:
        raise ValueError("either id or message_id is required")

    account_names = _normalize_calendar_names(accounts)
    mailbox_names = _normalize_calendar_names(mailboxes)
    result = _run_jxa_json(
        _MARK_MAIL_READ_JXA,
        {
            "id": target_id,
            "message_id": target_message_id,
            "accounts": account_names,
            "mailboxes": mailbox_names,
        },
        timeout_s=30.0,
    )
    if account_names and not result.get("selected_accounts"):
        available = ", ".join(result.get("available_accounts") or [])
        raise LookupError(
            "none of the requested mail accounts were found"
            + (f"; available accounts: {available}" if available else "")
        )
    if mailbox_names and not result.get("searched_mailboxes"):
        raise LookupError("none of the requested mailboxes were found in the selected accounts")

    matches = result.get("matches") or []
    if not matches:
        searched = ", ".join(result.get("searched_mailboxes") or [])
        search_scope = f" within {searched}" if searched else ""
        raise LookupError(
            "no mail message matched the provided id/message_id" + search_scope
        )
    if len(matches) > 1:
        matched_locations = ", ".join(
            f"{match.get('account')}/{match.get('mailbox')}"
            for match in matches[:8]
        )
        extra_count = len(matches) - 8
        if extra_count > 0:
            matched_locations += f", and {extra_count} more"
        raise LookupError(
            "multiple mail messages matched the provided id/message_id; "
            f"narrow the search with account or mailbox. Matches: {matched_locations}"
        )

    match = matches[0]
    if not bool(match.get("read_after")):
        raise RuntimeError("failed to mark the target mail message as read")

    return {
        "target_id": result.get("target_id"),
        "target_message_id": result.get("target_message_id"),
        "selected_accounts": result.get("selected_accounts") or [],
        "requested_mailboxes": result.get("requested_mailboxes") or [],
        "searched_mailboxes": result.get("searched_mailboxes") or [],
        "missing_mailboxes": result.get("missing_mailboxes") or [],
        "account": match.get("account"),
        "mailbox": match.get("mailbox"),
        "id": match.get("id"),
        "message_id": match.get("message_id"),
        "subject": match.get("subject"),
        "sender": match.get("sender"),
        "date_received": match.get("date_received"),
        "date_sent": match.get("date_sent"),
        "flagged": match.get("flagged"),
        "read_before": match.get("read_before"),
        "read_after": match.get("read_after"),
        "changed": match.get("changed"),
    }


def _create_mail_draft_sync(
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    body: str | None = None,
    attachments: list[str] | None = None,
    reply_to_id: str | None = None,
    reply_to_message_id: str | None = None,
    reply_accounts: list[str] | None = None,
    reply_mailboxes: list[str] | None = None,
) -> dict[str, object]:
    to_addresses = _normalize_calendar_names(to)
    cc_addresses = _normalize_calendar_names(cc)
    bcc_addresses = _normalize_calendar_names(bcc)
    attachment_paths = _normalize_attachment_paths(attachments)
    reply_account_names = _normalize_calendar_names(reply_accounts)
    reply_mailbox_names = _normalize_calendar_names(reply_mailboxes)
    target_reply_id = str(reply_to_id or "").strip() or None
    target_reply_message_id = str(reply_to_message_id or "").strip() or None
    has_reply_target = bool(target_reply_id or target_reply_message_id)

    if (
        not has_reply_target
        and not to_addresses
        and not cc_addresses
        and not bcc_addresses
        and not str(subject or "")
        and not str(body or "")
    ):
        raise ValueError("new draft requires at least one of to/cc/bcc/subject/body")

    result = _run_jxa_json(
        _CREATE_MAIL_DRAFT_JXA,
        {
            "to": to_addresses,
            "cc": cc_addresses,
            "bcc": bcc_addresses,
            "subject": subject,
            "body": body,
            "reply_to_id": target_reply_id,
            "reply_to_message_id": target_reply_message_id,
            "reply_accounts": reply_account_names,
            "reply_mailboxes": reply_mailbox_names,
        },
        timeout_s=30.0,
    )

    if has_reply_target and reply_account_names and not result.get("selected_reply_accounts"):
        missing = ", ".join(result.get("missing_reply_accounts") or [])
        raise LookupError(
            "none of the requested reply mail accounts were found"
            + (f"; missing accounts: {missing}" if missing else "")
        )
    if has_reply_target and reply_mailbox_names and not result.get("searched_reply_mailboxes"):
        raise LookupError(
            "none of the requested reply mailboxes were found in the selected accounts"
        )

    if attachment_paths:
        outgoing_id = str(result.get("outgoing_id") or "").strip()
        if not outgoing_id:
            raise RuntimeError("draft created without an outgoing_id, so attachments could not be added")
        _attach_files_to_outgoing_mail_draft_sync(outgoing_id, attachment_paths)
        refreshed = _wait_for_saved_draft_attachments(
            accounts=[str(result.get("account")).strip()] if str(result.get("account") or "").strip() else None,
            mailboxes=[str(result.get("mailbox")).strip()] if str(result.get("mailbox") or "").strip() else list(DEFAULT_DRAFT_MAILBOX_NAMES),
            subject=str(result.get("subject") or "").strip() or None,
            sender=str(result.get("sender") or "").strip() or None,
            to=result.get("to") or [],
            cc=result.get("cc") or [],
            bcc=result.get("bcc") or [],
            body=result.get("body"),
            expected_count=len(attachment_paths),
        )
        result.update(
            {
                "account": refreshed.get("account"),
                "mailbox": refreshed.get("mailbox"),
                "id": refreshed.get("id"),
                "message_id": refreshed.get("message_id"),
                "attachments": refreshed.get("attachments") or [],
                "attachment_count": int(refreshed.get("attachment_count") or 0),
                "date_received": refreshed.get("date_received"),
                "date_sent": refreshed.get("date_sent"),
            }
        )
    else:
        result["attachments"] = []
        result["attachment_count"] = 0

    return result


def _attach_files_to_outgoing_mail_draft_sync(
    outgoing_id: str,
    attachment_paths: list[str] | None,
) -> list[dict[str, object]]:
    target_outgoing_id = str(outgoing_id or "").strip()
    normalized_paths = _normalize_attachment_paths(attachment_paths)
    if not target_outgoing_id:
        raise ValueError("outgoing_id is required to attach files to a draft")
    if not normalized_paths:
        return []

    script = """
on run argv
  if (count of argv) < 2 then error "outgoing_id and at least one attachment path are required"
  set targetIdText to item 1 of argv
  set targetId to targetIdText as integer
  tell application "Mail"
    set matches to every outgoing message whose id is targetId
    if (count of matches) is 0 then error "no outgoing draft matched id " & targetIdText
    if (count of matches) > 1 then error "multiple outgoing drafts matched id " & targetIdText
    set msg to item 1 of matches
    tell msg
      if content is "" then set content to return
      repeat with i from 2 to count of argv
        set posixPath to item i of argv
        make new attachment with properties {file name:POSIX file posixPath} at after the last paragraph of content
      end repeat
      save
    end tell
    delay 0.3
  end tell
  return ((count of argv) - 1) as string
end run
""".strip()
    _run_applescript(
        script,
        args=[target_outgoing_id, *normalized_paths],
        timeout_s=30.0,
    )
    return _attachment_metadata_from_paths(normalized_paths)


def _lookup_mail_draft_sync(
    id: str | None = None,
    message_id: str | None = None,
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
    subject: str | None = None,
    sender: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    body: str | None = None,
) -> dict[str, object]:
    target_id = str(id or "").strip() or None
    target_message_id = str(message_id or "").strip() or None
    target_subject = str(subject or "").strip() or None
    target_sender = str(sender or "").strip() or None
    target_to = _normalize_calendar_names(to)
    target_cc = _normalize_calendar_names(cc)
    target_bcc = _normalize_calendar_names(bcc)
    target_body = body
    if (
        not target_id
        and not target_message_id
        and not target_subject
        and not target_sender
        and not target_to
        and not target_cc
        and not target_bcc
        and target_body is None
    ):
        raise ValueError("draft lookup requires id, message_id, or draft content criteria")

    account_names = _normalize_calendar_names(accounts)
    mailbox_names = _normalize_calendar_names(mailboxes) or list(DEFAULT_DRAFT_MAILBOX_NAMES)
    result = _run_jxa_json(
        _LOOKUP_MAIL_DRAFT_JXA,
        {
            "id": target_id,
            "message_id": target_message_id,
            "accounts": account_names,
            "mailboxes": mailbox_names,
            "subject": target_subject,
            "sender": target_sender,
            "to": target_to if to is not None else None,
            "cc": target_cc if cc is not None else None,
            "bcc": target_bcc if bcc is not None else None,
            "body": target_body,
        },
        timeout_s=30.0,
    )
    if account_names and not result.get("selected_accounts"):
        available = ", ".join(result.get("available_accounts") or [])
        raise LookupError(
            "none of the requested mail accounts were found"
            + (f"; available accounts: {available}" if available else "")
        )
    if mailbox_names and not result.get("searched_mailboxes"):
        raise LookupError("none of the requested mailboxes were found in the selected accounts")

    matches = result.get("matches") or []
    if not matches:
        searched = ", ".join(result.get("searched_mailboxes") or [])
        search_scope = f" within {searched}" if searched else ""
        raise LookupError(
            "no saved draft matched the provided lookup criteria" + search_scope
        )
    if len(matches) > 1:
        matched_locations = ", ".join(
            f"{match.get('account')}/{match.get('mailbox')}"
            for match in matches[:8]
        )
        extra_count = len(matches) - 8
        if extra_count > 0:
            matched_locations += f", and {extra_count} more"
        raise LookupError(
            "multiple saved drafts matched the provided lookup criteria; "
            f"narrow the search with account or mailbox. Matches: {matched_locations}"
        )

    match = matches[0]
    return {
        "target_id": result.get("target_id"),
        "target_message_id": result.get("target_message_id"),
        "selected_accounts": result.get("selected_accounts") or [],
        "requested_mailboxes": result.get("requested_mailboxes") or [],
        "searched_mailboxes": result.get("searched_mailboxes") or [],
        "missing_mailboxes": result.get("missing_mailboxes") or [],
        "account": match.get("account"),
        "mailbox": match.get("mailbox"),
        "id": match.get("id"),
        "message_id": match.get("message_id"),
        "subject": match.get("subject"),
        "sender": match.get("sender"),
        "to": match.get("to") or [],
        "cc": match.get("cc") or [],
        "bcc": match.get("bcc") or [],
        "body": match.get("body") or "",
        "body_length": match.get("body_length") or 0,
        "attachments": match.get("attachments") or [],
        "attachment_count": int(match.get("attachment_count") or 0),
        "date_received": match.get("date_received"),
        "date_sent": match.get("date_sent"),
    }


def _resolve_outgoing_mail_draft_sync(
    outgoing_id: str | None = None,
    subject: str | None = None,
    sender: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    body: str | None = None,
) -> dict[str, object]:
    target_outgoing_id = str(outgoing_id or "").strip() or None
    to_addresses = _normalize_calendar_names(to)
    cc_addresses = _normalize_calendar_names(cc)
    bcc_addresses = _normalize_calendar_names(bcc)
    if (
        not target_outgoing_id
        and not str(subject or "")
        and not str(sender or "")
        and not to_addresses
        and not cc_addresses
        and not bcc_addresses
        and body is None
    ):
        raise ValueError("outgoing draft lookup requires outgoing_id or draft content")

    result = _run_jxa_json(
        _SEND_OUTGOING_MAIL_DRAFT_JXA,
        {
            "outgoing_id": target_outgoing_id,
            "subject": subject,
            "sender": sender,
            "to": to_addresses,
            "cc": cc_addresses,
            "bcc": bcc_addresses,
            "body": body,
            "send": False,
        },
        timeout_s=30.0,
    )

    matches = result.get("matches") or []
    if not matches:
        raise LookupError("no live outgoing draft matched the provided criteria")
    if len(matches) > 1:
        outgoing_ids = ", ".join(
            str(match.get("outgoing_id") or "")
            for match in matches[:8]
            if str(match.get("outgoing_id") or "")
        )
        extra_count = len(matches) - 8
        if extra_count > 0:
            outgoing_ids += f", and {extra_count} more"
        raise LookupError(
            "multiple live outgoing drafts matched the provided criteria; "
            f"narrow the lookup with outgoing_id. Matches: {outgoing_ids}"
        )

    match = matches[0]
    return {
        "outgoing_id": match.get("outgoing_id"),
        "subject": match.get("subject"),
        "sender": match.get("sender"),
        "to": match.get("to") or [],
        "cc": match.get("cc") or [],
        "bcc": match.get("bcc") or [],
        "body": match.get("body") or "",
        "body_length": match.get("body_length") or 0,
        "visible": bool(match.get("visible")),
    }


def _send_outgoing_mail_draft_sync(outgoing_id: str) -> dict[str, object]:
    target_outgoing_id = str(outgoing_id or "").strip() or None
    if not target_outgoing_id:
        raise ValueError("outgoing_id is required to send a draft")

    result = _run_jxa_json(
        _SEND_OUTGOING_MAIL_DRAFT_JXA,
        {
            "outgoing_id": target_outgoing_id,
            "send": True,
        },
        timeout_s=30.0,
    )

    if not bool(result.get("sent")):
        matches = result.get("matches") or []
        if not matches:
            raise LookupError("no live outgoing draft matched the provided outgoing_id")
        raise LookupError(
            "multiple live outgoing drafts matched the provided outgoing_id"
        )

    return {
        "sent": True,
        "outgoing_id": result.get("outgoing_id"),
        "subject": result.get("subject"),
        "sender": result.get("sender"),
        "to": result.get("to") or [],
        "cc": result.get("cc") or [],
        "bcc": result.get("bcc") or [],
        "body": result.get("body") or "",
        "body_length": result.get("body_length") or 0,
        "visible": bool(result.get("visible")),
        "sent_at": result.get("sent_at"),
        "remaining_outgoing_matches": int(result.get("remaining_outgoing_matches") or 0),
    }


def _wait_for_saved_draft_attachments(
    accounts: list[str] | None,
    mailboxes: list[str] | None,
    subject: str | None,
    sender: str | None,
    to: list[str] | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    body: str | None,
    expected_count: int,
    timeout_s: float = 10.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last_state: dict[str, object] | None = None
    while time.time() < deadline:
        state = _lookup_mail_draft_sync(
            accounts=accounts,
            mailboxes=mailboxes,
            subject=subject,
            sender=sender,
            to=to,
            cc=cc,
            bcc=bcc,
            body=body,
        )
        last_state = state
        if int(state.get("attachment_count") or 0) >= expected_count:
            return state
        time.sleep(0.4)
    raise RuntimeError(
        "draft attachments did not finish saving to Mail; "
        f"expected at least {expected_count}, got {int((last_state or {}).get('attachment_count') or 0)}"
    )


def _same_text_list(left: list[str] | None, right: list[str] | None) -> bool:
    normalized_left = sorted(_normalize_calendar_names(left))
    normalized_right = sorted(_normalize_calendar_names(right))
    return normalized_left == normalized_right


def _mail_draft_preview_from_input(
    id: str | None = None,
    message_id: str | None = None,
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
    outgoing_id: str | None = None,
) -> dict[str, object]:
    target_id = str(id or "").strip() or None
    target_message_id = str(message_id or "").strip() or None
    target_outgoing_id = str(outgoing_id or "").strip() or None
    if not target_id and not target_message_id and not target_outgoing_id:
        raise ValueError("send_mail_draft requires id, message_id, or outgoing_id")

    saved_draft = None
    if target_id or target_message_id:
        try:
            saved_draft = _lookup_mail_draft_sync(
                target_id,
                target_message_id,
                accounts,
                mailboxes,
            )
        except LookupError:
            if not target_outgoing_id:
                raise

    outgoing_draft = _resolve_outgoing_mail_draft_sync(
        outgoing_id=target_outgoing_id,
        subject=saved_draft.get("subject") if saved_draft else None,
        sender=saved_draft.get("sender") if saved_draft else None,
        to=saved_draft.get("to") if saved_draft else None,
        cc=saved_draft.get("cc") if saved_draft else None,
        bcc=saved_draft.get("bcc") if saved_draft else None,
        body=saved_draft.get("body") if saved_draft else None,
    )

    if saved_draft is None:
        try:
            saved_draft = _lookup_mail_draft_sync(
                accounts=accounts,
                mailboxes=mailboxes,
                subject=outgoing_draft.get("subject"),
                sender=outgoing_draft.get("sender"),
                to=outgoing_draft.get("to"),
                cc=outgoing_draft.get("cc"),
                bcc=outgoing_draft.get("bcc"),
                body=outgoing_draft.get("body"),
            )
        except LookupError:
            saved_draft = None

    if saved_draft:
        if saved_draft.get("subject") != outgoing_draft.get("subject"):
            raise RuntimeError("saved draft and outgoing draft subject do not match")
        if saved_draft.get("sender") != outgoing_draft.get("sender"):
            raise RuntimeError("saved draft and outgoing draft sender do not match")
        if not _same_text_list(saved_draft.get("to"), outgoing_draft.get("to")):
            raise RuntimeError("saved draft and outgoing draft recipients do not match")
        if not _same_text_list(saved_draft.get("cc"), outgoing_draft.get("cc")):
            raise RuntimeError("saved draft and outgoing draft cc recipients do not match")
        if not _same_text_list(saved_draft.get("bcc"), outgoing_draft.get("bcc")):
            raise RuntimeError("saved draft and outgoing draft bcc recipients do not match")
        if str(saved_draft.get("body") or "") != str(outgoing_draft.get("body") or ""):
            raise RuntimeError("saved draft and outgoing draft body do not match")

    preview = {
        "target_id": target_id,
        "target_message_id": target_message_id,
        "target_outgoing_id": target_outgoing_id,
        "selected_accounts": saved_draft.get("selected_accounts") if saved_draft else [],
        "requested_mailboxes": saved_draft.get("requested_mailboxes") if saved_draft else list(DEFAULT_DRAFT_MAILBOX_NAMES),
        "searched_mailboxes": saved_draft.get("searched_mailboxes") if saved_draft else [],
        "missing_mailboxes": saved_draft.get("missing_mailboxes") if saved_draft else [],
        "account": saved_draft.get("account") if saved_draft else None,
        "mailbox": saved_draft.get("mailbox") if saved_draft else None,
        "id": saved_draft.get("id") if saved_draft else None,
        "message_id": saved_draft.get("message_id") if saved_draft else None,
        "outgoing_id": outgoing_draft.get("outgoing_id"),
        "subject": saved_draft.get("subject") if saved_draft else outgoing_draft.get("subject"),
        "sender": saved_draft.get("sender") if saved_draft else outgoing_draft.get("sender"),
        "to": saved_draft.get("to") if saved_draft else outgoing_draft.get("to"),
        "cc": saved_draft.get("cc") if saved_draft else outgoing_draft.get("cc"),
        "bcc": saved_draft.get("bcc") if saved_draft else outgoing_draft.get("bcc"),
        "body": saved_draft.get("body") if saved_draft else outgoing_draft.get("body"),
        "body_length": saved_draft.get("body_length") if saved_draft else outgoing_draft.get("body_length"),
        "attachments": saved_draft.get("attachments") if saved_draft else [],
        "attachment_count": saved_draft.get("attachment_count") if saved_draft else 0,
        "visible": outgoing_draft.get("visible"),
        "preview_source": "saved+outgoing" if saved_draft else "outgoing",
        "can_send": True,
    }
    return preview


def _wait_until_saved_draft_absent(
    id: str | None,
    message_id: str | None,
    accounts: list[str] | None,
    mailboxes: list[str] | None,
    timeout_s: float = 10.0,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _lookup_mail_draft_sync(
                id=id,
                message_id=message_id,
                accounts=accounts,
                mailboxes=mailboxes,
            )
        except LookupError:
            return True
        time.sleep(0.4)
    return False


def _send_mail_draft_sync(
    id: str | None = None,
    message_id: str | None = None,
    accounts: list[str] | None = None,
    mailboxes: list[str] | None = None,
    outgoing_id: str | None = None,
) -> dict[str, object]:
    preview = _mail_draft_preview_from_input(
        id=id,
        message_id=message_id,
        accounts=accounts,
        mailboxes=mailboxes,
        outgoing_id=outgoing_id,
    )
    sent = _send_outgoing_mail_draft_sync(str(preview.get("outgoing_id") or ""))
    result = dict(preview)
    draft_removed_from_mailbox = None
    if preview.get("id") or preview.get("message_id"):
        draft_removed_from_mailbox = _wait_until_saved_draft_absent(
            id=str(preview.get("id") or "") or None,
            message_id=str(preview.get("message_id") or "") or None,
            accounts=preview.get("selected_accounts") or None,
            mailboxes=preview.get("requested_mailboxes") or list(DEFAULT_DRAFT_MAILBOX_NAMES),
        )
        if not draft_removed_from_mailbox:
            raise RuntimeError("Mail accepted send(), but the saved draft is still present in Drafts")
    result.update(
        {
            "sent": True,
            "sent_at": sent.get("sent_at"),
            "remaining_outgoing_matches": sent.get("remaining_outgoing_matches"),
            "draft_removed_from_mailbox": draft_removed_from_mailbox,
        }
    )
    return result

def _parse_create_mail_draft_args(args: dict[str, object]) -> dict[str, object]:
    raw_reply_accounts = (
        args.get("reply_accounts")
        or args.get("reply_account_names")
        or args.get("reply_account")
    )
    raw_reply_mailboxes = (
        args.get("reply_mailboxes")
        or args.get("reply_mailbox_names")
        or args.get("reply_mailbox")
    )
    raw_reply_message_id = (
        args.get("reply_to_message_id")
        or args.get("in_reply_to_message_id")
        or args.get("replyToMessageId")
    )
    raw_attachments = (
        args.get("attachments")
        or args.get("attachment_paths")
        or args.get("attachment")
    )
    body = args.get("body")
    return {
        "to": _normalize_calendar_names(args.get("to")),
        "cc": _normalize_calendar_names(args.get("cc")),
        "bcc": _normalize_calendar_names(args.get("bcc")),
        "subject": None if args.get("subject") is None else str(args.get("subject")),
        "body": None if body is None else str(body),
        "attachments": _normalize_attachment_paths(raw_attachments),
        "reply_to_id": args.get("reply_to_id") or args.get("in_reply_to_id"),
        "reply_to_message_id": raw_reply_message_id,
        "reply_accounts": _normalize_calendar_names(raw_reply_accounts),
        "reply_mailboxes": _normalize_calendar_names(raw_reply_mailboxes),
    }


def preview_create_mail_draft_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_create_mail_draft_args(args)
    reply_to_id = str(parsed.get("reply_to_id") or "").strip() or None
    reply_to_message_id = str(parsed.get("reply_to_message_id") or "").strip() or None
    has_reply_target = bool(reply_to_id or reply_to_message_id)

    if (
        not has_reply_target
        and not parsed["to"]
        and not parsed["cc"]
        and not parsed["bcc"]
        and not str(parsed["subject"] or "")
        and not str(parsed["body"] or "")
    ):
        raise ValueError("new draft requires at least one of to/cc/bcc/subject/body")

    attachments = _attachment_metadata_from_paths(parsed["attachments"])
    preview = {
        "mode": "reply" if has_reply_target else "new",
        "subject": parsed["subject"] or "",
        "to": parsed["to"],
        "cc": parsed["cc"],
        "bcc": parsed["bcc"],
        "body": parsed["body"] or "",
        "body_length": len(parsed["body"] or ""),
        "attachments": attachments,
        "attachment_count": len(attachments),
        "reply_target": None,
        "reply_to_id": reply_to_id,
        "reply_to_message_id": reply_to_message_id,
    }

    if has_reply_target:
        reply_target = _read_mail_message_sync(
            id=reply_to_id,
            message_id=reply_to_message_id,
            accounts=parsed["reply_accounts"] or None,
            mailboxes=parsed["reply_mailboxes"] or None,
            max_body_chars=1,
        )
        preview["reply_target"] = {
            "account": reply_target.get("account"),
            "mailbox": reply_target.get("mailbox"),
            "id": reply_target.get("id"),
            "message_id": reply_target.get("message_id"),
            "subject": reply_target.get("subject"),
            "sender": reply_target.get("sender"),
        }
        preview["selected_reply_accounts"] = reply_target.get("selected_accounts") or []
        preview["requested_reply_mailboxes"] = reply_target.get("requested_mailboxes") or []
        preview["searched_reply_mailboxes"] = reply_target.get("searched_mailboxes") or []
        preview["missing_reply_mailboxes"] = reply_target.get("missing_mailboxes") or []

    return preview


def format_create_mail_draft_preview(preview: dict[str, object]) -> str:
    lines = ["将要保存的邮件草稿："]
    if str(preview.get("mode") or "").strip() == "reply":
        lines.append("类型: 回复草稿")
        reply_target = dict(preview.get("reply_target") or {})
        if reply_target:
            lines.append(
                f"原邮件主题: {str(reply_target.get('subject') or '').strip() or '（无主题）'}"
            )
            sender = str(reply_target.get("sender") or "").strip()
            if sender:
                lines.append(f"原邮件发件人: {sender}")
            mailbox_label = _format_mailbox_label(
                reply_target.get("account"),
                reply_target.get("mailbox"),
                fallback="",
            )
            if mailbox_label:
                lines.append(f"原邮件位置: {mailbox_label}")
    else:
        lines.append("类型: 新草稿")

    lines.extend(
        [
            f"主题: {_format_mail_subject_label(preview)}",
            f"收件人: {_format_address_line(preview.get('to'))}",
            f"抄送: {_format_address_line(preview.get('cc'))}",
            f"密送: {_format_address_line(preview.get('bcc'))}",
            *_format_attachment_preview_lines(preview.get("attachments")),
            "",
            "正文预览:",
            _trim_preview_block(str(preview.get("body") or "")),
        ]
    )
    return "\n".join(lines)


def format_send_mail_draft_preview(preview: dict[str, object]) -> str:
    mailbox_label = _format_mailbox_label(
        preview.get("account"),
        preview.get("mailbox"),
    )
    lines = [
        "将要发送的邮件草稿：",
        f"主题: {str(preview.get('subject') or '').strip() or '（无主题）'}",
        f"邮箱: {mailbox_label}",
        f"发件人: {str(preview.get('sender') or '').strip() or '（未知）'}",
        f"收件人: {_format_address_line(preview.get('to'))}",
        f"抄送: {_format_address_line(preview.get('cc'))}",
        f"密送: {_format_address_line(preview.get('bcc'))}",
        *_format_attachment_preview_lines(preview.get("attachments")),
        f"草稿 id: {str(preview.get('id') or '（无）')}",
        f"message_id: {str(preview.get('message_id') or '（无）')}",
        f"outgoing_id: {str(preview.get('outgoing_id') or '（无）')}",
        "",
        "正文预览:",
        _trim_preview_block(str(preview.get("body") or "")),
    ]
    return "\n".join(lines)


def _parse_send_mail_draft_args(args: dict[str, object]) -> dict[str, object]:
    raw_accounts = args.get("accounts") or args.get("account_names") or args.get("account")
    raw_mailboxes = args.get("mailboxes") or args.get("mailbox_names") or args.get("mailbox")
    return {
        "id": args.get("id"),
        "message_id": args.get("message_id") or args.get("messageId"),
        "outgoing_id": args.get("outgoing_id") or args.get("outgoingId"),
        "accounts": _normalize_calendar_names(raw_accounts),
        "mailboxes": _normalize_calendar_names(raw_mailboxes),
    }


def preview_send_mail_draft_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_send_mail_draft_args(args)
    return _mail_draft_preview_from_input(
        id=parsed["id"],
        message_id=parsed["message_id"],
        accounts=parsed["accounts"],
        mailboxes=parsed["mailboxes"],
        outgoing_id=parsed["outgoing_id"],
    )
