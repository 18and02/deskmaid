"""Standalone focus_window MCP tool integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_focus_window_tool.py
"""

from __future__ import annotations

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
from maid_tools import (
    _get_frontmost_app_sync,
    _list_windows_sync,
    _resolve_focus_window_target_sync,
)
from test_integration_helpers import (
    assert_permission_request_details,
    assert_permission_trace_and_optional_tool_results,
    build_auto_allow_and_trace_handlers,
    final_reply_matches,
    preserve_resumable_session,
    print_chat_result,
)


FOCUS_WINDOW_TOOL_NAMES = {
    "focus_window",
    "mcp__deskmaid_local__focus_window",
}


def _discover_focus_target() -> tuple[dict[str, object], dict[str, object]]:
    frontmost = _get_frontmost_app_sync()
    pid = frontmost.get("pid")
    localized_name = str(frontmost.get("localized_name") or "").strip()
    windows_state = _list_windows_sync(
        on_screen_only=False,
        include_desktop_elements=False,
        include_nonzero_layer=True,
        limit=100,
    )

    candidates = []
    for item in windows_state.get("windows") or []:
        if not isinstance(item, dict):
            continue
        if item.get("window_id") is None:
            continue
        if pid is not None and int(item.get("pid") or 0) == int(pid):
            candidates.append(dict(item))
    if not candidates and localized_name:
        for item in windows_state.get("windows") or []:
            if not isinstance(item, dict):
                continue
            if item.get("window_id") is None:
                continue
            if str(item.get("owner_name") or "").strip() == localized_name:
                candidates.append(dict(item))
    if not candidates:
        raise RuntimeError(
            f"no focusable window found for the current frontmost app: {frontmost!r}"
        )

    def _candidate_rank(window: dict[str, object]) -> tuple[int, int, int, int]:
        bounds = dict(window.get("bounds") or {})
        width = int(bounds.get("width") or 0)
        height = int(bounds.get("height") or 0)
        area = width * height
        title = str(window.get("title") or "").strip()
        return (
            1 if bool(window.get("is_onscreen")) else 0,
            1 if title else 0,
            area,
            1 if bool(window.get("is_frontmost_owner")) else 0,
        )

    candidates.sort(key=_candidate_rank, reverse=True)

    for candidate in candidates:
        window_id = candidate.get("window_id")
        if window_id is None:
            continue
        try:
            _resolve_focus_window_target_sync({"window_id": int(window_id)})
        except Exception:
            continue
        return frontmost, candidate

    raise RuntimeError(
        f"no resolvable focus target found for the current frontmost app: {frontmost!r}"
    )


def main():
    try:
        frontmost_app, target_window = _discover_focus_target()
    except Exception as exc:
        print(f"[error] unable to discover a focus target: {exc}", file=sys.stderr)
        sys.exit(1)

    window_id = int(target_window.get("window_id") or 0)
    owner_name = str(target_window.get("owner_name") or "").strip()
    title = str(target_window.get("title") or "").strip()
    bundle_id = str(frontmost_app.get("bundle_id") or "").strip()
    seen_requests: list[PermissionRequest] = []
    events: list[ChatTraceEvent] = []
    auto_allow, on_trace = build_auto_allow_and_trace_handlers(seen_requests, events)

    with preserve_resumable_session():
        set_permission_handler(auto_allow)
        try:
            result = ask_maid(
                "这是一次 focus_window 集成测试。"
                "你必须调用名为 focus_window 的工具。"
                f"参数 window_id={window_id}。"
                "调用成功后，只回复 focused。"
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

    print_chat_result(result)

    assert_permission_request_details(
        seen_requests=seen_requests,
        tool_names=FOCUS_WINDOW_TOOL_NAMES,
        label="focus_window",
        allow_remember=False,
        confirm_label="确认切换",
        preview_markers_any=[str(window_id), owner_name],
        preview_description="the target window id or owner",
    )
    assert_permission_trace_and_optional_tool_results(
        seen_requests=seen_requests,
        events=events,
        tool_names=FOCUS_WINDOW_TOOL_NAMES,
        label="focus_window",
        permission_request_detail_markers_any=[str(window_id), owner_name],
        permission_request_description="the target window id or owner",
        tool_result_markers=[
            marker for marker in (str(window_id), owner_name, title, bundle_id) if marker
        ],
        tool_result_description="the target window or app",
    )

    if not final_reply_matches(result.text, "focused"):
        print(
            f"[error] expected final reply 'focused', got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
