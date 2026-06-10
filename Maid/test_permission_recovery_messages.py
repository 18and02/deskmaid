"""Regression checks for packaged-permission recovery messages."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_tools_shared import _tool_error_result


def _extract_text(result: dict[str, object]) -> str:
    content = list(result.get("content") or [])
    if not content:
        raise AssertionError("tool result is missing content")
    first = dict(content[0] or {})
    text = str(first.get("text") or "")
    if not text:
        raise AssertionError("tool result text is empty")
    return text


def _assert_contains(text: str, fragments: list[str], *, label: str):
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise AssertionError(f"{label} missing fragments: {missing}\n{text}")


def main():
    cases = (
        (
            "desktop_accessibility",
            "focus_window",
            RuntimeError(
                "focus_window needs Accessibility permission for System Events / osascript to raise a specific window"
            ),
            ["辅助功能授权", "Permission health", "辅助功能"],
        ),
        (
            "desktop_automation",
            "press_keys",
            RuntimeError("Not authorized to send Apple events to System Events. (-1743)"),
            ["System Events", "自动化授权", "Permission health"],
        ),
        (
            "calendar_automation",
            "create_calendar_event",
            RuntimeError("Not authorized to send Apple events to Calendar. (-1743)"),
            ["Calendar", "自动化授权", "Permission health"],
        ),
        (
            "reminders_timeout",
            "create_reminder",
            RuntimeError("osascript timed out"),
            ["这次超时了", "权限", "Permission health"],
        ),
        (
            "mail_automation",
            "read_mail_message",
            RuntimeError("Not authorized to send Apple events to Mail. (-1743)"),
            ["Mail", "自动化授权", "Permission health"],
        ),
    )

    for label, tool_name, exc, fragments in cases:
        result = _tool_error_result(tool_name, exc)
        if not bool(result.get("is_error")):
            print(f"[error] {label}: expected is_error=true", file=sys.stderr)
            sys.exit(1)
        text = _extract_text(result)
        try:
            _assert_contains(text, list(fragments), label=label)
        except AssertionError as failure:
            print(f"[error] {failure}", file=sys.stderr)
            sys.exit(1)

    generic = _tool_error_result("open_url", RuntimeError("unsupported URL"))
    generic_text = _extract_text(generic)
    if generic_text != "open_url failed: unsupported URL":
        print(
            f"[error] generic error text changed unexpectedly: {generic_text!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("[ok] permission recovery messages passed")


if __name__ == "__main__":
    main()
