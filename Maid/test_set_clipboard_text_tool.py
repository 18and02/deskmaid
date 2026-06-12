"""Standalone set_clipboard_text MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_set_clipboard_text_tool.py
"""

from __future__ import annotations

import json
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
    _snapshot_clipboard_items,
)
from test_integration_helpers import (
    assert_display_text_contains,
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    preserve_resumable_session,
    print_chat_result,
)


SET_CLIPBOARD_TEXT_TOOL_NAMES = {
    "set_clipboard_text",
    "mcp__deskmaid_local__set_clipboard_text",
}


def main():
    probe_token = uuid4().hex[:10]
    clipboard_text = (
        f"deskmaid-set-clipboard-{probe_token}\n"
        f"line-{probe_token}"
    )
    receipt_snippet = f"deskmaid-set-clipboard-{probe_token[:8]}"
    snapshot = _snapshot_clipboard_items()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    clipboard_after = None
    run_error: tuple[str, int] | None = None
    restore_error: str | None = None

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(
        seen_requests,
        events,
        print_preview=True,
    )

    try:
        with preserve_resumable_session():
            set_permission_handler(auto_allow)
            try:
                prompt = (
                    "这是一次 set_clipboard_text 集成测试。"
                    "你必须调用名为 set_clipboard_text 的工具。"
                    f"参数 text={json.dumps(clipboard_text, ensure_ascii=False)}。"
                    "调用成功后，只回复 copied。"
                    "不要调用别的工具，也不要改用 Bash。"
                )
                result = ask_maid(prompt, trace_handler=on_trace)
                clipboard_after = _read_clipboard_text_sync(len(clipboard_text) + 32)
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

    if clipboard_after is None or str(clipboard_after.get("text") or "") != clipboard_text:
        print(
            f"[error] expected clipboard text {clipboard_text!r}, got {clipboard_after!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=SET_CLIPBOARD_TEXT_TOOL_NAMES,
        label="set_clipboard_text",
        allow_remember=False,
        confirm_label="确认写入剪贴板",
        risk_label="高风险",
        risk_remaining=1,
        total_remaining=7,
        preview_markers_all=[probe_token],
        preview_description="the requested clipboard text",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=SET_CLIPBOARD_TEXT_TOOL_NAMES,
        label="set_clipboard_text",
        permission_request_detail_markers_all=[probe_token],
        permission_request_description="the requested clipboard text",
        tool_result_markers=[probe_token],
        tool_result_description="the clipboard write payload",
    )
    assert_display_text_contains(
        result=result,
        label="set_clipboard_text",
        markers=["剪贴板已更新", receipt_snippet],
        description="the clipboard receipt",
    )

    if not final_reply_matches(result.text, "copied"):
        print(
            f"[error] expected final reply 'copied', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
