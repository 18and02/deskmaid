"""Local smoke tests for the desktop bridge helpers.

Usage:
    .venv/bin/python -u Maid/test_desktop_bridges.py

This covers the low-risk parts of the new desktop bridge layer:
- frontmost app detection
- visible window listing
- clipboard snapshot -> write -> read -> restore
- permission preview wiring for windows / focus / URL / clipboard / paste / keypress actions
- receipt formatting for the write-style desktop bridges

It intentionally does not send real key presses, paste into another app,
open a real URL in the user's browser, or steal focus from another app window.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import _permission_preview_spec
from maid_tools import (
    _get_frontmost_app_sync,
    _list_windows_sync,
    _read_clipboard_text_sync,
    _resolve_focus_window_target_sync,
    _restore_clipboard_items,
    _set_clipboard_text_sync,
    _snapshot_clipboard_items,
    format_focus_window_preview,
    format_list_windows_preview,
    format_open_url_preview,
    format_paste_text_preview,
    format_press_keys_preview,
    format_read_clipboard_text_preview,
    format_set_clipboard_text_preview,
    format_write_tool_receipt,
    preview_focus_window_request,
    preview_list_windows_request,
    preview_open_url_request,
    preview_paste_text_request,
    preview_press_keys_request,
    preview_read_clipboard_text_request,
    preview_set_clipboard_text_request,
)


def main():
    frontmost = _get_frontmost_app_sync()
    if not frontmost.get("localized_name") and not frontmost.get("bundle_id"):
        print(f"[error] failed to resolve the frontmost app: {frontmost!r}", file=sys.stderr)
        sys.exit(1)

    windows_state = _list_windows_sync(limit=20)
    if int(windows_state.get("count") or 0) < 1:
        print(f"[error] expected at least one visible window, got {windows_state!r}", file=sys.stderr)
        sys.exit(1)
    if not windows_state.get("windows"):
        print(f"[error] missing windows payload: {windows_state!r}", file=sys.stderr)
        sys.exit(1)
    sample_window: dict[str, object] | None = None
    resolved_focus_target: dict[str, object] | None = None
    for item in windows_state.get("windows") or []:
        candidate = dict(item or {})
        if not candidate.get("window_id"):
            continue
        try:
            resolved_focus_target = _resolve_focus_window_target_sync(
                {
                    "window_id": candidate["window_id"],
                }
            )
        except Exception:
            continue
        sample_window = candidate
        break

    if sample_window is None or resolved_focus_target is None:
        print(
            f"[error] no focusable sample window found: {windows_state!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if str(resolved_focus_target.get("mode") or "") != "window":
        print(f"[error] expected window focus mode, got {resolved_focus_target!r}", file=sys.stderr)
        sys.exit(1)

    snapshot = _snapshot_clipboard_items()
    probe_text = "deskmaid desktop bridge smoke"
    try:
        wrote = _set_clipboard_text_sync(probe_text)
        if wrote.get("text") != probe_text:
            print(f"[error] clipboard write mismatch: {wrote!r}", file=sys.stderr)
            sys.exit(1)

        read = _read_clipboard_text_sync(200)
        if read.get("text") != probe_text:
            print(f"[error] clipboard read mismatch: {read!r}", file=sys.stderr)
            sys.exit(1)
    finally:
        _restore_clipboard_items(snapshot)

    preview_cases = [
        (
            "list_windows",
            preview_list_windows_request({"owner_names": ["Codex"], "limit": 12}),
            format_list_windows_preview,
            "确认读取",
        ),
        (
            "focus_window",
            preview_focus_window_request({"window_id": sample_window["window_id"]}),
            format_focus_window_preview,
            "确认切换",
        ),
        (
            "open_url",
            preview_open_url_request({"target": "example.com", "activate": False}),
            format_open_url_preview,
            "确认打开",
        ),
        (
            "read_clipboard_text",
            preview_read_clipboard_text_request({"max_chars": 123}),
            format_read_clipboard_text_preview,
            "确认读取",
        ),
        (
            "set_clipboard_text",
            preview_set_clipboard_text_request({"text": "hello\nworld"}),
            format_set_clipboard_text_preview,
            "确认写入剪贴板",
        ),
        (
            "paste_text",
            preview_paste_text_request({"text": "贴到这里", "restore_clipboard": True}),
            format_paste_text_preview,
            "确认粘贴",
        ),
        (
            "press_keys",
            preview_press_keys_request({"key": "return", "modifiers": ["command"], "repeat": 2}),
            format_press_keys_preview,
            "确认按键",
        ),
    ]

    for tool_name, preview_payload, formatter, confirm_label in preview_cases:
        spec = _permission_preview_spec(tool_name)
        if spec is None:
            print(f"[error] missing permission preview spec for {tool_name}", file=sys.stderr)
            sys.exit(1)
        if spec.get("allow_remember") is not False:
            print(
                f"[error] expected {tool_name} to require fresh confirmation, got {spec!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if spec.get("confirm_label") != confirm_label:
            print(
                f"[error] unexpected confirm label for {tool_name}: {spec!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        preview_text = formatter(preview_payload)
        if not preview_text.strip():
            print(
                f"[error] expected non-empty preview text for {tool_name}: {preview_payload!r}",
                file=sys.stderr,
            )
            sys.exit(1)

    set_receipt = format_write_tool_receipt(
        "set_clipboard_text",
        {
            "text": "abc",
            "length": 3,
        },
    )
    paste_receipt = format_write_tool_receipt(
        "paste_text",
        {
            "text": "abc",
            "length": 3,
            "restore_clipboard": True,
            "clipboard_restored": True,
            "frontmost_app": {
                "localized_name": "Codex",
                "bundle_id": "com.openai.codex",
            },
        },
    )
    press_receipt = format_write_tool_receipt(
        "press_keys",
        {
            "key": "return",
            "shortcut": "Command + Return",
            "modifiers": ["command"],
            "repeat": 1,
            "frontmost_app": {
                "localized_name": "Codex",
                "bundle_id": "com.openai.codex",
            },
        },
    )
    open_url_receipt = format_write_tool_receipt(
        "open_url",
        {
            "resolved_url": "https://example.com",
        },
    )
    focus_receipt = format_write_tool_receipt(
        "focus_window",
        {
            "app": {
                "localized_name": str(sample_window.get("owner_name") or "Codex"),
                "bundle_id": str(sample_window.get("bundle_id") or "com.openai.codex"),
            },
            "window": {
                "window_id": sample_window.get("window_id"),
                "title": str(sample_window.get("title") or ""),
            },
        },
    )

    for label, receipt in (
        ("focus_window", focus_receipt),
        ("open_url", open_url_receipt),
        ("set_clipboard_text", set_receipt),
        ("paste_text", paste_receipt),
        ("press_keys", press_receipt),
    ):
        if not receipt or not receipt.strip():
            print(f"[error] missing receipt for {label}", file=sys.stderr)
            sys.exit(1)

    print("ok")


if __name__ == "__main__":
    main()
