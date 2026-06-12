"""Standalone press_keys MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_press_keys_tool.py
"""

from __future__ import annotations

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
from test_integration_helpers import (
    assert_display_text_contains,
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    preserve_resumable_session,
    print_chat_result,
)


PRESS_KEYS_TOOL_NAMES = {
    "press_keys",
    "mcp__deskmaid_local__press_keys",
}


def main():
    probe_token = uuid4().hex[:10]
    seed_text = f"deskmaid-press-seed-{probe_token}"
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    result = None
    document_state = None
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
            title=f"Deskmaid Press Probe {probe_token}",
            seed_text=seed_text,
        )
        with preserve_resumable_session():
            set_permission_handler(auto_allow)
            try:
                prompt = (
                    "这是一次 press_keys 集成测试。"
                    "你必须调用名为 press_keys 的工具。"
                    "参数 key=return，repeat=2。"
                    "调用成功后，只回复 pressed。"
                    "不要调用别的工具，也不要改用 Bash。"
                )
                result = ask_maid(prompt, trace_handler=on_trace)
                expected_text = seed_text + "\n\n"
                document_state = wait_for_input_probe_state(
                    probe.state_path,
                    predicate=lambda state: str(state.get("text") or "") == expected_text,
                    timeout_s=8.0,
                )
            except ChatConfigError as exc:
                run_error = (f"[error] {exc}", 2)
            except Exception as exc:
                run_error = (f"[error] {exc}", 1)
            finally:
                set_permission_handler(None)
                shutdown_maid_session()
    finally:
        try:
            if probe is not None:
                stop_input_probe(probe)
                print("[cleanup] stopped_input_probe=1")
        except Exception as exc:
            cleanup_error = str(exc)

    if run_error is not None:
        if cleanup_error:
            print(f"[error] cleanup failed after test error: {cleanup_error}", file=sys.stderr)
        print(run_error[0], file=sys.stderr)
        sys.exit(run_error[1])

    if cleanup_error:
        print(f"[error] cleanup failed: {cleanup_error}", file=sys.stderr)
        sys.exit(1)

    if document_state is None:
        print("[error] missing desktop input probe state after press_keys", file=sys.stderr)
        sys.exit(1)

    final_text = str(document_state.get("text") or "")
    expected_text = seed_text + "\n\n"
    if final_text != expected_text:
        print(
            f"[error] expected TextEdit document text {expected_text!r}, got {final_text!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=PRESS_KEYS_TOOL_NAMES,
        label="press_keys",
        allow_remember=False,
        confirm_label="确认按键",
        preview_markers_all=["Return", "次数: 2"],
        preview_description="the requested key shortcut and repeat count",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=PRESS_KEYS_TOOL_NAMES,
        label="press_keys",
        permission_request_detail_markers_all=["Return", "次数: 2"],
        permission_request_description="the requested key shortcut and repeat count",
        tool_result_markers=["Return"],
        tool_result_description="the keypress payload",
    )
    assert_display_text_contains(
        result=result,
        label="press_keys",
        markers=["按键已发送", "Return", "次数: 2"],
        description="the keypress receipt",
    )

    if not final_reply_matches(result.text, "pressed"):
        print(
            f"[error] expected final reply 'pressed', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
