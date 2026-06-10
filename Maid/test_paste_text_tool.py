"""Standalone paste_text MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_paste_text_tool.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop_input_probe_support import (
    launch_input_probe,
    stop_input_probe,
    wait_for_input_probe_state,
)
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
    assert_display_text_contains,
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    preserve_resumable_session,
    print_chat_result,
)


PASTE_TEXT_TOOL_NAMES = {
    "paste_text",
    "mcp__deskmaid_local__paste_text",
}


def main():
    probe_token = uuid4().hex[:10]
    seed_text = f"deskmaid-paste-seed-{probe_token}\n"
    paste_text = f"deskmaid-paste-content-{probe_token}"
    clipboard_before = f"deskmaid-clipboard-before-{probe_token}"
    receipt_snippet = f"deskmaid-paste-content-{probe_token[:8]}"
    snapshot = _snapshot_clipboard_items()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    document_state = None
    clipboard_after = None
    run_error: tuple[str, int] | None = None
    cleanup_error: str | None = None
    probe = None

    auto_allow, on_trace = build_auto_allow_and_trace_handlers(
        seen_requests,
        events,
        print_preview=True,
    )

    try:
        probe = launch_input_probe(
            title=f"Deskmaid Paste Probe {probe_token}",
            seed_text=seed_text,
        )
        _set_clipboard_text_sync(clipboard_before)
        with preserve_resumable_session():
            set_permission_handler(auto_allow)
            try:
                prompt = (
                    "这是一次 paste_text 集成测试。"
                    "你必须调用名为 paste_text 的工具。"
                    f"参数 text={json.dumps(paste_text, ensure_ascii=False)}，"
                    "restore_clipboard=true。"
                    "调用成功后，只回复 pasted。"
                    "不要调用别的工具，也不要改用 Bash。"
                )
                result = ask_maid(prompt, trace_handler=on_trace)
                document_state = wait_for_input_probe_state(
                    probe.state_path,
                    predicate=lambda state: paste_text in str(state.get("text") or ""),
                    timeout_s=8.0,
                )
                clipboard_after = _read_clipboard_text_sync(len(clipboard_before) + 32)
            except ChatConfigError as exc:
                run_error = (f"[error] {exc}", 2)
            except Exception as exc:
                run_error = (f"[error] {exc}", 1)
            finally:
                set_permission_handler(None)
                shutdown_maid_session()
    finally:
        close_messages = []
        try:
            if probe is not None:
                stop_input_probe(probe)
                close_messages.append("stopped_input_probe=1")
        except Exception as exc:
            cleanup_error = str(exc)
        try:
            _restore_clipboard_items(snapshot)
        except Exception as exc:
            restore_detail = f"clipboard restore failed: {exc}"
            cleanup_error = (
                restore_detail
                if cleanup_error is None
                else f"{cleanup_error}; {restore_detail}"
            )
        if close_messages:
            print(f"[cleanup] {' '.join(close_messages)}")

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] cleanup failed: {cleanup_error}", file=sys.stderr)
        sys.exit(1)

    if document_state is None:
        print("[error] missing desktop input probe state after paste", file=sys.stderr)
        sys.exit(1)

    final_text = str(document_state.get("text") or "")
    if seed_text not in final_text or paste_text not in final_text or not final_text.endswith(paste_text):
        print(
            f"[error] expected input probe text to contain pasted content, got {document_state!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if clipboard_after is None or str(clipboard_after.get("text") or "") != clipboard_before:
        print(
            f"[error] expected clipboard to be restored to {clipboard_before!r}, got {clipboard_after!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=PASTE_TEXT_TOOL_NAMES,
        label="paste_text",
        allow_remember=False,
        confirm_label="确认粘贴",
        preview_markers_all=[probe_token],
        preview_description="the requested pasted text",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=PASTE_TEXT_TOOL_NAMES,
        label="paste_text",
        permission_request_detail_markers_all=[probe_token],
        permission_request_description="the requested pasted text",
        tool_result_markers=[probe_token],
        tool_result_description="the pasted text",
    )
    assert_display_text_contains(
        result=result,
        label="paste_text",
        markers=["文本已粘贴", receipt_snippet],
        description="the paste receipt",
    )

    if result.text.strip() != "pasted":
        print(
            f"[error] expected final reply 'pasted', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
