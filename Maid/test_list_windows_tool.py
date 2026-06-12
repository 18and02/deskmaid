"""Standalone list_windows MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_list_windows_tool.py
"""

from __future__ import annotations

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
from maid_tools import _list_windows_sync
from test_integration_helpers import (
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    preserve_resumable_session,
    print_chat_result,
)


LIST_WINDOWS_TOOL_NAMES = {
    "list_windows",
    "mcp__deskmaid_local__list_windows",
}


def _discover_sample_window() -> dict[str, object]:
    snapshot = _list_windows_sync(
        on_screen_only=False,
        include_desktop_elements=False,
        include_nonzero_layer=True,
        limit=40,
    )
    for item in snapshot.get("windows") or []:
        if not isinstance(item, dict):
            continue
        owner_name = str(item.get("owner_name") or "").strip()
        if owner_name and item.get("window_id") is not None:
            return dict(item)
    raise RuntimeError(f"no sample desktop window found: {snapshot!r}")


def main():
    try:
        sample_window = _discover_sample_window()
    except Exception as exc:
        print(f"[error] unable to discover a sample desktop window: {exc}", file=sys.stderr)
        sys.exit(1)

    owner_name = str(sample_window.get("owner_name") or "").strip()
    title = str(sample_window.get("title") or "").strip()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    with preserve_resumable_session():
        set_permission_handler(auto_allow)
        try:
            prompt = (
                "这是一次 list_windows 集成测试。"
                "你必须调用名为 list_windows 的工具。"
                f"参数 owner_names=[{json.dumps(owner_name, ensure_ascii=False)}]，"
                "on_screen_only=false，include_nonzero_layer=true，limit=5。"
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

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=LIST_WINDOWS_TOOL_NAMES,
        label="list_windows",
        allow_remember=False,
        confirm_label="确认读取",
        risk_label="低风险",
        risk_remaining=5,
        total_remaining=7,
        preview_markers_all=[owner_name],
        preview_description="the owner filter",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=LIST_WINDOWS_TOOL_NAMES,
        label="list_windows",
        permission_request_detail_markers_all=[owner_name],
        permission_request_description="the owner filter",
        tool_result_markers=[marker for marker in (owner_name, title) if marker],
        tool_result_description="the sample owner or title",
    )

    if not final_reply_matches(result.text, "listed"):
        print(
            f"[error] expected final reply 'listed', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
