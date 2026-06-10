"""Shared TextEdit helpers for desktop input integration tests."""

from __future__ import annotations

import time

from maid_tools import _run_jxa_json


TEXTEDIT_BUNDLE_ID = "com.apple.TextEdit"


_PREPARE_TEXTEDIT_DOCUMENT_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var text = String(config.text || "");
  var app = Application("TextEdit");
  app.activate();
  var doc = app.Document().make();
  doc.text = text;
  return JSON.stringify({
    ok: true,
    document_count: app.documents().length,
    text_length: text.length
  });
}
"""


_LOOKUP_TEXTEDIT_DOCUMENT_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var markers = Array.isArray(config.markers) ? config.markers : [];
  var normalized = [];
  for (var i = 0; i < markers.length; i++) {
    var marker = String(markers[i] || "");
    if (marker.length) {
      normalized.push(marker);
    }
  }

  var app = Application("TextEdit");
  var docs = app.documents();
  for (var j = 0; j < docs.length; j++) {
    var text = "";
    try {
      text = String(docs[j].text());
    } catch (error) {
      continue;
    }

    if (!normalized.length) {
      return JSON.stringify({
        found: true,
        text: text,
        index: j + 1,
        document_count: docs.length
      });
    }

    for (var k = 0; k < normalized.length; k++) {
      if (text.indexOf(normalized[k]) !== -1) {
        return JSON.stringify({
          found: true,
          text: text,
          index: j + 1,
          matched_marker: normalized[k],
          document_count: docs.length
        });
      }
    }
  }

  return JSON.stringify({
    found: false,
    document_count: docs.length
  });
}
"""


_CLOSE_TEXTEDIT_DOCUMENTS_JXA = r"""
function run(argv) {
  var config = JSON.parse(argv[0] || "{}");
  var markers = Array.isArray(config.markers) ? config.markers : [];
  var normalized = [];
  for (var i = 0; i < markers.length; i++) {
    var marker = String(markers[i] || "");
    if (marker.length) {
      normalized.push(marker);
    }
  }

  var app = Application("TextEdit");
  var docs = app.documents();
  var closed = 0;
  for (var j = docs.length - 1; j >= 0; j--) {
    var text = "";
    try {
      text = String(docs[j].text());
    } catch (error) {
      text = "";
    }

    var shouldClose = normalized.length === 0;
    if (!shouldClose) {
      for (var k = 0; k < normalized.length; k++) {
        if (text.indexOf(normalized[k]) !== -1) {
          shouldClose = true;
          break;
        }
      }
    }

    if (!shouldClose) {
      continue;
    }

    try {
      docs[j].close({saving: "no"});
      closed += 1;
    } catch (error) {
    }
  }

  return JSON.stringify({
    closed: closed,
    remaining: app.documents().length
  });
}
"""


def prepare_textedit_document(text: str = "", *, settle_s: float = 0.5) -> dict[str, object]:
    result = _run_jxa_json(_PREPARE_TEXTEDIT_DOCUMENT_JXA, {"text": text})
    time.sleep(settle_s)
    return result


def lookup_textedit_document(markers: list[str] | tuple[str, ...]) -> dict[str, object]:
    return _run_jxa_json(
        _LOOKUP_TEXTEDIT_DOCUMENT_JXA,
        {"markers": list(markers)},
    )


def wait_for_textedit_document(
    markers: list[str] | tuple[str, ...],
    *,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.25,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last_state: dict[str, object] | None = None
    while time.time() < deadline:
        state = lookup_textedit_document(markers)
        last_state = state
        if state.get("found"):
            return state
        time.sleep(poll_interval_s)
    raise RuntimeError(
        f"TextEdit document matching {list(markers)!r} not found; "
        f"last state was {last_state!r}"
    )


def close_textedit_documents(markers: list[str] | tuple[str, ...]) -> int:
    result = _run_jxa_json(
        _CLOSE_TEXTEDIT_DOCUMENTS_JXA,
        {"markers": list(markers)},
    )
    return int(result.get("closed") or 0)
