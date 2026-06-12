"""Standalone open_app MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_open_app_tool.py

The test asks Claude to explicitly call open_app for Calculator with
activate=false, auto-allows the permission prompt, and verifies the tool call
showed up in the trace stream.
"""

import sys
from pathlib import Path

from AppKit import NSRunningApplication

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


CALCULATOR_BUNDLE_ID = "com.apple.calculator"
OPEN_APP_TOOL_NAMES = {
    "open_app",
    "mcp__deskmaid_local__open_app",
}


def _running_pids(bundle_id: str) -> set[int]:
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) or []
    pids = set()
    for app in apps:
        try:
            pids.add(int(app.processIdentifier()))
        except Exception:
            pass
    return pids


def _terminate_new_apps(bundle_id: str, baseline: set[int]):
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) or []
    for app in apps:
        try:
            pid = int(app.processIdentifier())
        except Exception:
            continue
        if pid in baseline:
            continue
        try:
            app.terminate()
        except Exception:
            pass


def main():
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    before_pids = _running_pids(CALCULATOR_BUNDLE_ID)
    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    with preserve_resumable_session():
        set_permission_handler(auto_allow)
        try:
            result = ask_maid(
                "这是一次 open_app 集成测试。"
                "你必须调用名为 open_app 的工具，参数 target=Calculator 且 activate=false。"
                "调用成功后，只回复 opened。"
                "不要调用别的工具，也不要改用 Bash。",
                trace_handler=on_trace,
            )
        except ChatConfigError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(2)
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            set_permission_handler(None)
            shutdown_maid_session()

    after_pids = _running_pids(CALCULATOR_BUNDLE_ID)
    _terminate_new_apps(CALCULATOR_BUNDLE_ID, before_pids)

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=OPEN_APP_TOOL_NAMES,
        label="open_app",
        risk_label="中风险",
        risk_remaining=3,
        total_remaining=7,
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=OPEN_APP_TOOL_NAMES,
        label="open_app",
        tool_result_markers=[CALCULATOR_BUNDLE_ID],
        tool_result_description=CALCULATOR_BUNDLE_ID,
    )

    if not final_reply_matches(result.text, "opened"):
        print(
            f"[error] expected final reply 'opened', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not before_pids and not after_pids:
        print(
            "[error] Calculator does not appear to have launched",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
