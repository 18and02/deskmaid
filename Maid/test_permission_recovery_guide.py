"""Regression checks for the packaged permission-recovery guide."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_permission_recovery import (
    build_permission_recovery_guide,
    enrich_permission_health_check,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _action_labels(check: dict[str, object]) -> list[str]:
    return [
        str(action.get("label") or "").strip()
        for action in (check.get("actions") or [])
        if isinstance(action, dict)
    ]


def main():
    accessibility_check = enrich_permission_health_check(
        {
            "key": "current_process_accessibility",
            "title": "辅助功能（当前进程）",
            "status": "warning",
            "status_label": "留意",
            "summary": "当前 Python 进程没有辅助功能授权",
            "detail": "当前解释器: Deskmaid",
            "hint": "去系统设置里打开辅助功能。",
            "tools": [],
        }
    )
    accessibility_labels = _action_labels(accessibility_check)
    _assert(
        accessibility_labels == ["打开辅助功能", "刷新"],
        f"unexpected accessibility actions: {accessibility_labels!r}",
    )

    calendar_check = enrich_permission_health_check(
        {
            "key": "calendar_automation",
            "title": "Calendar 自动化",
            "status": "error",
            "status_label": "未就绪",
            "summary": "Calendar 自动化未授权",
            "detail": "Not authorized to send Apple events to Calendar. (-1743)",
            "hint": "去系统设置里打开自动化。",
            "tools": [],
        }
    )
    calendar_labels = _action_labels(calendar_check)
    _assert(
        calendar_labels == ["打开自动化", "打开 Calendar", "刷新"],
        f"unexpected calendar actions: {calendar_labels!r}",
    )
    _assert(
        "create_calendar_event" in list(calendar_check.get("tools") or []),
        f"calendar tools should be backfilled: {calendar_check!r}",
    )

    guide = build_permission_recovery_guide([accessibility_check, calendar_check])
    _assert(guide is not None, "expected a recovery guide for permission issues")
    guide_summary = str(guide.get("summary") or "")
    _assert(
        "辅助功能" in guide_summary and "自动化" in guide_summary,
        f"guide summary should mention both scopes: {guide!r}",
    )
    guide_detail = str(guide.get("detail") or "")
    _assert(
        "辅助功能" in guide_detail and "Calendar" in guide_detail,
        f"guide detail should mention the concrete target app: {guide!r}",
    )
    guide_labels = _action_labels(guide)
    _assert(
        guide_labels == ["打开辅助功能", "打开自动化", "打开 Calendar", "刷新"],
        f"guide actions should merge and dedupe in order: {guide_labels!r}",
    )

    empty_mail_check = enrich_permission_health_check(
        {
            "key": "mail_automation",
            "title": "Mail 自动化",
            "status": "warning",
            "status_label": "留意",
            "summary": "Mail 可访问，但还没有任何邮箱账号",
            "detail": "没有列出具体名称",
            "hint": "先在 Mail.app 里登录至少一个邮箱账号。",
            "tools": [],
        }
    )
    empty_mail_labels = _action_labels(empty_mail_check)
    _assert(
        empty_mail_labels == ["打开 Mail", "刷新"],
        f"unexpected empty-mail actions: {empty_mail_labels!r}",
    )
    _assert(
        build_permission_recovery_guide([empty_mail_check]) is None,
        "empty app setup warnings should not spawn the permission-recovery guide",
    )

    print("ok")


if __name__ == "__main__":
    main()
