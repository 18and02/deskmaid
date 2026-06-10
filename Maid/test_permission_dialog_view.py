"""Smoke test for permission-dialog guardrail copy."""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import PermissionRequest
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    medium_request = PermissionRequest(
        tool_name="open_app",
        input_data={"target": "Calculator"},
        tool_use_id=None,
        title=None,
        display_name=None,
        description=None,
        blocked_path=None,
        decision_reason=None,
        allow_remember=True,
        risk_level="medium",
        risk_label="中风险",
        risk_limit=4,
        risk_used=1,
        risk_remaining=3,
        total_limit=8,
        total_used=1,
        total_remaining=7,
    )
    medium_view = maid_main._build_permission_guardrail_view(medium_request)
    _assert(
        medium_view.get("title") == "中风险 · 单轮护栏",
        f"unexpected medium guardrail title: {medium_view!r}",
    )
    medium_detail = str(medium_view.get("detail") or "")
    _assert("这档还剩 3 / 4 次" in medium_detail, f"missing risk quota detail: {medium_view!r}")
    _assert("整轮工具还剩 7 / 8 次" in medium_detail, f"missing total quota detail: {medium_view!r}")
    _assert("本次会话始终允许此工具" in medium_detail, f"missing remember hint: {medium_view!r}")

    critical_request = PermissionRequest(
        tool_name="paste_text",
        input_data={"text": "deskmaid"},
        tool_use_id=None,
        title=None,
        display_name=None,
        description=None,
        blocked_path=None,
        decision_reason=None,
        allow_remember=False,
        risk_level="critical",
        risk_label="极高风险",
        risk_limit=1,
        risk_used=1,
        risk_remaining=0,
        total_limit=8,
        total_used=1,
        total_remaining=7,
    )
    critical_view = maid_main._build_permission_guardrail_view(critical_request)
    critical_detail = str(critical_view.get("detail") or "")
    _assert(
        "这类工具不会记住授权" in critical_detail,
        f"missing fresh-confirm hint: {critical_view!r}",
    )
    _assert(
        "这档还剩 0 / 1 次" in critical_detail,
        f"missing critical quota detail: {critical_view!r}",
    )

    print("ok")


if __name__ == "__main__":
    main()
