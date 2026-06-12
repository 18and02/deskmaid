"""Standalone open_url MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_open_url_tool.py
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
from test_integration_helpers import (
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    preserve_resumable_session,
    print_chat_result,
)


OPEN_URL_TOOL_NAMES = {
    "open_url",
    "mcp__deskmaid_local__open_url",
}


def main():
    probe_token = uuid4().hex[:10]
    target = f"example.com/?deskmaid_open_url={probe_token}"
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    with preserve_resumable_session():
        set_permission_handler(auto_allow)
        try:
            prompt = (
                "这是一次 open_url 集成测试。"
                "你必须调用名为 open_url 的工具。"
                f"参数 target={json.dumps(target, ensure_ascii=False)}，activate=false。"
                "调用成功后，只回复 opened。"
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
        tool_names=OPEN_URL_TOOL_NAMES,
        label="open_url",
        allow_remember=False,
        confirm_label="确认打开",
        preview_markers_all=["example.com", probe_token],
        preview_description="the resolved target URL",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=OPEN_URL_TOOL_NAMES,
        label="open_url",
        permission_request_detail_markers_all=["example.com", probe_token],
        permission_request_description="the previewed URL",
        tool_result_markers=["example.com", probe_token],
        tool_result_description="the resolved URL",
    )

    if not final_reply_matches(result.text, "opened"):
        print(
            f"[error] expected final reply 'opened', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
