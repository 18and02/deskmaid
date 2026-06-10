"""Standalone read_clipboard_text MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_read_clipboard_text_tool.py
"""

from __future__ import annotations

import sys
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
from maid_tools import (
    _read_clipboard_text_sync,
    _restore_clipboard_items,
    _set_clipboard_text_sync,
    _snapshot_clipboard_items,
)
from test_integration_helpers import (
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    preserve_resumable_session,
    print_chat_result,
)


READ_CLIPBOARD_TEXT_TOOL_NAMES = {
    "read_clipboard_text",
    "mcp__deskmaid_local__read_clipboard_text",
}


def main():
    probe_token = uuid4().hex[:10]
    probe_text = f"deskmaid-read-clipboard-{probe_token}\nline-{probe_token}"
    max_chars = len(probe_text) + 24
    snapshot = _snapshot_clipboard_items()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    clipboard_after = None
    run_error: tuple[str, int] | None = None
    restore_error: str | None = None

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    try:
        _set_clipboard_text_sync(probe_text)
        with preserve_resumable_session():
            set_permission_handler(auto_allow)
            try:
                prompt = (
                    "这是一次 read_clipboard_text 集成测试。"
                    "你必须调用名为 read_clipboard_text 的工具。"
                    f"参数 max_chars={max_chars}。"
                    "调用成功后，只回复 read。"
                    "不要调用别的工具，也不要改用 Bash。"
                )
                result = ask_maid(prompt, trace_handler=on_trace)
                clipboard_after = _read_clipboard_text_sync(len(probe_text) + 32)
            except ChatConfigError as exc:
                run_error = (f"[error] {exc}", 2)
            except Exception as exc:
                run_error = (f"[error] {exc}", 1)
            finally:
                set_permission_handler(None)
                shutdown_maid_session()
    finally:
        try:
            _restore_clipboard_items(snapshot)
        except Exception as exc:
            restore_error = str(exc)

    if run_error is not None:
        if restore_error:
            print(f"[error] clipboard restore failed after test error: {restore_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if restore_error:
        print(f"[error] failed to restore clipboard snapshot: {restore_error}", file=sys.stderr)
        sys.exit(1)

    if clipboard_after is None or str(clipboard_after.get("text") or "") != probe_text:
        print(
            f"[error] expected clipboard to remain unchanged, got {clipboard_after!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=READ_CLIPBOARD_TEXT_TOOL_NAMES,
        label="read_clipboard_text",
        allow_remember=False,
        confirm_label="确认读取",
        preview_markers_all=[str(max_chars)],
        preview_description="the requested max_chars limit",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=READ_CLIPBOARD_TEXT_TOOL_NAMES,
        label="read_clipboard_text",
        permission_request_detail_markers_all=[str(max_chars)],
        permission_request_description="the requested max_chars limit",
        tool_result_markers=[probe_token],
        tool_result_description="the clipboard probe text",
    )

    if result.text.strip() != "read":
        print(
            f"[error] expected final reply 'read', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
