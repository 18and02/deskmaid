"""Standalone permission-callback test for the maid Agent SDK backend.

Usage:
    .venv/bin/python -u Maid/test_permissions.py

This triggers two Write tool calls and remembers the first approval so we can
verify the per-session "always allow this tool" path is wired.
"""

import sys
from pathlib import Path
import os

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import (
    clear_remembered_tool_permissions,
    ChatConfigError,
    get_remembered_tool_permissions,
    PermissionDecision,
    PermissionRequest,
    ask_maid,
    set_permission_handler,
    shutdown_maid_session,
)


def main():
    seen_requests: list[PermissionRequest] = []
    probe_path_1 = "/private/tmp/deskmaid-permission-probe-1.txt"
    probe_path_2 = "/private/tmp/deskmaid-permission-probe-2.txt"
    probe_path_3 = "/private/tmp/deskmaid-permission-probe-3.txt"

    def auto_allow(request: PermissionRequest) -> PermissionDecision:
        seen_requests.append(request)
        print(
            f"[perm] tool={request.tool_name} "
            f"title={request.title!r} input={request.input_data!r}"
        )
        return PermissionDecision(allow=True, remember_tool=True)

    set_permission_handler(auto_allow)
    try:
        first = ask_maid(
            f"请新建文件 {probe_path_1}，内容只有 deskmaid-permission-ok-1。"
            "完成后只回复 done。"
        )
        second = ask_maid(
            f"请新建文件 {probe_path_2}，内容只有 deskmaid-permission-ok-2。"
            "完成后只回复 done。"
        )
        remembered_before_clear = get_remembered_tool_permissions()
        cleared = clear_remembered_tool_permissions()
        remembered_after_clear = get_remembered_tool_permissions()
        third = ask_maid(
            f"请新建文件 {probe_path_3}，内容只有 deskmaid-permission-ok-3。"
            "完成后只回复 done。"
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
        for probe_path in (probe_path_1, probe_path_2, probe_path_3):
            if os.path.exists(probe_path):
                os.remove(probe_path)

    print(f"<<< 女仆(1): {first.text}")
    print(
        f"    (session={first.session_id} in={first.input_tokens} "
        f"out={first.output_tokens} stop={first.stop_reason} "
        f"dur={first.duration_ms}ms cost={first.total_cost_usd})"
    )
    print(f"<<< 女仆(2): {second.text}")
    print(
        f"    (session={second.session_id} in={second.input_tokens} "
        f"out={second.output_tokens} stop={second.stop_reason} "
        f"dur={second.duration_ms}ms cost={second.total_cost_usd})"
    )
    print(f"remembered before clear: {remembered_before_clear}")
    print(f"cleared count: {cleared}")
    print(f"remembered after clear: {remembered_after_clear}")
    print(f"<<< 女仆(3): {third.text}")
    print(
        f"    (session={third.session_id} in={third.input_tokens} "
        f"out={third.output_tokens} stop={third.stop_reason} "
        f"dur={third.duration_ms}ms cost={third.total_cost_usd})"
    )

    if not seen_requests:
        print("[error] can_use_tool was not triggered", file=sys.stderr)
        sys.exit(1)
    if len(seen_requests) != 2:
        print(
            f"[error] expected exactly 2 permission prompts, got {len(seen_requests)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if first.session_id != second.session_id:
        print(
            f"[error] session changed: {first.session_id} -> {second.session_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    if second.session_id != third.session_id:
        print(
            f"[error] session changed: {second.session_id} -> {third.session_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    if remembered_before_clear != ["Write"]:
        print(
            f"[error] expected remembered tools ['Write'], got {remembered_before_clear}",
            file=sys.stderr,
        )
        sys.exit(1)
    if cleared != 1:
        print(f"[error] expected cleared count 1, got {cleared}", file=sys.stderr)
        sys.exit(1)
    if remembered_after_clear:
        print(
            f"[error] expected remembered tools to be empty, got {remembered_after_clear}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
