"""Shared helpers for standalone Maid integration tests."""

from __future__ import annotations

from contextlib import contextmanager
import sys

from maid_chat import (
    ChatResult,
    ChatTraceEvent,
    PermissionDecision,
    PermissionRequest,
    _SESSION,
    _save_session_id,
    _session_state_path,
    get_resumable_session_id,
)


REQUIRED_TRACE_EVENT_KINDS = (
    "run_started",
    "permission_request",
    "permission_decision",
    "tool_use",
    "result",
)


def _fail(message: str):
    print(f"[error] {message}", file=sys.stderr)
    sys.exit(1)


def _normalized_markers(markers: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(marker) for marker in (markers or []) if str(marker)]


def _detail_matches_markers(
    detail: str,
    *,
    markers_all: list[str] | tuple[str, ...] | None = None,
    markers_any: list[str] | tuple[str, ...] | None = None,
) -> bool:
    expected_all = _normalized_markers(markers_all)
    expected_any = _normalized_markers(markers_any)
    if expected_all and not all(marker in detail for marker in expected_all):
        return False
    if expected_any and not any(marker in detail for marker in expected_any):
        return False
    return True


@contextmanager
def preserve_resumable_session():
    session_state_path = _session_state_path()
    previous_session_id = get_resumable_session_id()
    _SESSION._last_session_id = None
    try:
        yield previous_session_id
    finally:
        _save_session_id(session_state_path, previous_session_id)
        _SESSION._last_session_id = previous_session_id


def build_auto_allow_and_trace_handlers(
    seen_requests: list[PermissionRequest],
    events: list[ChatTraceEvent],
    *,
    remember_tool: bool = False,
    print_preview: bool = False,
):
    def auto_allow(request: PermissionRequest) -> PermissionDecision:
        seen_requests.append(request)
        if print_preview:
            print(
                f"[perm] tool={request.tool_name} allow_remember={request.allow_remember} "
                f"confirm_label={request.confirm_label!r}"
            )
            print(f"[perm] preview=\n{request.preview_text}")
        else:
            print(
                f"[perm] tool={request.tool_name} "
                f"title={request.title!r} input={request.input_data!r}"
            )
        return PermissionDecision(allow=True, remember_tool=remember_tool)

    def on_trace(event: ChatTraceEvent):
        events.append(event)
        print(f"[trace] {event.kind}: {event.title} :: {event.detail}")

    return auto_allow, on_trace


def assert_permission_request_details(
    *,
    seen_requests: list[PermissionRequest],
    tool_names: set[str],
    label: str,
    allow_remember: bool | None = None,
    confirm_label: str | None = None,
    risk_label: str | None = None,
    risk_remaining: int | None = None,
    total_remaining: int | None = None,
    preview_markers_all: list[str] | tuple[str, ...] | None = None,
    preview_markers_any: list[str] | tuple[str, ...] | None = None,
    preview_description: str | None = None,
) -> PermissionRequest:
    matching_requests = [
        request for request in seen_requests if request.tool_name in tool_names
    ]
    if not matching_requests:
        _fail(
            f"expected permission request for {label} MCP tool, got {seen_requests!r}"
        )

    request = matching_requests[0]
    if allow_remember is not None and bool(request.allow_remember) != allow_remember:
        mode = "allow remembering" if allow_remember else "require fresh confirmation"
        _fail(f"expected {label} to {mode}, got {request!r}")
    if confirm_label is not None and request.confirm_label != confirm_label:
        _fail(f"unexpected confirm label for {label}: {request.confirm_label!r}")
    if risk_label is not None and str(request.risk_label or "") != risk_label:
        _fail(f"unexpected risk label for {label}: {request.risk_label!r}")
    if risk_remaining is not None and int(request.risk_remaining or 0) != risk_remaining:
        _fail(f"unexpected risk remaining for {label}: {request.risk_remaining!r}")
    if total_remaining is not None and int(request.total_remaining or 0) != total_remaining:
        _fail(f"unexpected total remaining for {label}: {request.total_remaining!r}")

    preview_text = request.preview_text or ""
    if (
        _normalized_markers(preview_markers_all)
        or _normalized_markers(preview_markers_any)
    ) and not _detail_matches_markers(
        preview_text,
        markers_all=preview_markers_all,
        markers_any=preview_markers_any,
    ):
        detail = preview_description or label
        _fail(
            f"expected {label} preview text to mention {detail}, got {preview_text!r}"
        )

    return request


def print_chat_result(result: ChatResult, *, label: str = "女仆"):
    print(f"<<< {label}: {result.text}")
    print(
        f"    (session={result.session_id} in={result.input_tokens} "
        f"out={result.output_tokens} stop={result.stop_reason} "
        f"dur={result.duration_ms}ms cost={result.total_cost_usd})"
    )
    if result.display_text and result.display_text != result.text:
        print(f"    display=\n{result.display_text}")


def assert_display_text_contains(
    *,
    result: ChatResult,
    label: str,
    markers: list[str] | tuple[str, ...],
    description: str | None = None,
) -> str:
    display_text = str(result.display_text or "").strip()
    if not display_text:
        _fail(f"{label}: expected non-empty display_text receipt")

    expected = _normalized_markers(markers)
    if expected and not all(marker in display_text for marker in expected):
        detail = description or label
        _fail(
            f"expected display_text for {label} to mention {detail}, "
            f"got {display_text!r}"
        )
    return display_text


def assert_permission_trace_and_optional_tool_results(
    *,
    seen_requests: list[PermissionRequest],
    events: list[ChatTraceEvent],
    tool_names: set[str],
    label: str,
    tool_result_markers: list[str] | None = None,
    tool_result_description: str | None = None,
    permission_request_detail_markers_all: list[str] | tuple[str, ...] | None = None,
    permission_request_detail_markers_any: list[str] | tuple[str, ...] | None = None,
    permission_request_description: str | None = None,
    required_trace_event_kinds: tuple[str, ...] = REQUIRED_TRACE_EVENT_KINDS,
):
    if not seen_requests:
        _fail(f"{label} did not trigger a permission request")

    if not any(request.tool_name in tool_names for request in seen_requests):
        _fail(
            f"expected permission request for {label} MCP tool, got {seen_requests!r}"
        )

    kinds = [event.kind for event in events]
    for required in required_trace_event_kinds:
        if required not in kinds:
            _fail(f"missing trace event kind {required!r}")

    if not any(
        event.kind == "tool_use" and event.tool_name in tool_names
        for event in events
    ):
        _fail(f"expected a tool_use trace event for {label}")

    permission_events = [event for event in events if event.kind == "permission_request"]
    if permission_events and (
        _normalized_markers(permission_request_detail_markers_all)
        or _normalized_markers(permission_request_detail_markers_any)
    ) and not any(
        _detail_matches_markers(
            event.detail,
            markers_all=permission_request_detail_markers_all,
            markers_any=permission_request_detail_markers_any,
        )
        for event in permission_events
    ):
        detail = permission_request_description or label
        _fail(
            f"expected permission_request trace for {label} to mention {detail}, "
            f"got {permission_events!r}"
        )

    expected_markers = [marker for marker in (tool_result_markers or []) if marker]
    tool_results = [event for event in events if event.kind == "tool_result"]
    if tool_results and expected_markers and not any(
        any(marker in event.detail for marker in expected_markers)
        for event in tool_results
    ):
        detail = tool_result_description or label
        _fail(
            f"expected {label} tool_result to mention {detail}, got {tool_results!r}"
        )
