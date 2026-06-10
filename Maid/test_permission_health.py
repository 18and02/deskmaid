"""Smoke test for the local permission/environment self-check layer.

Usage:
    .venv/bin/python -u Maid/test_permission_health.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_health import collect_permission_health


EXPECTED_KEYS = {
    "appkit_bridge",
    "window_bridge",
    "camera_probe",
    "osascript_runtime",
    "claude_code_cli",
    "bundle_runtime",
    "bundle_tcc_metadata",
    "bundle_signature_identity",
    "current_process_accessibility",
    "system_events_ui",
    "calendar_automation",
    "reminders_automation",
    "mail_automation",
}

EXPECTED_STATUSES = {"ok", "warning", "error"}


def main():
    snapshot = collect_permission_health()
    checks = list(snapshot.get("checks") or [])
    if not checks:
        print("[error] expected at least one health check", file=sys.stderr)
        sys.exit(1)

    keys = {str(check.get("key") or "") for check in checks if isinstance(check, dict)}
    missing = sorted(EXPECTED_KEYS - keys)
    if missing:
        print(f"[error] missing expected health check keys: {missing}", file=sys.stderr)
        sys.exit(1)

    status_counts = {"ok": 0, "warning": 0, "error": 0}
    for check in checks:
        if not isinstance(check, dict):
            print(f"[error] invalid health check payload: {check!r}", file=sys.stderr)
            sys.exit(1)
        key = str(check.get("key") or "")
        title = str(check.get("title") or "")
        status = str(check.get("status") or "")
        label = str(check.get("status_label") or "")
        summary = str(check.get("summary") or "")
        if not key or not title or not label or not summary:
            print(f"[error] incomplete health check payload: {check!r}", file=sys.stderr)
            sys.exit(1)
        if status not in EXPECTED_STATUSES:
            print(f"[error] unexpected status for {key}: {status!r}", file=sys.stderr)
            sys.exit(1)
        status_counts[status] += 1

    for name, expected in (
        ("ok_count", status_counts["ok"]),
        ("warning_count", status_counts["warning"]),
        ("error_count", status_counts["error"]),
    ):
        if int(snapshot.get(name, -1) or 0) != expected:
            print(
                f"[error] snapshot {name} mismatch: expected {expected}, "
                f"got {snapshot.get(name)!r}",
                file=sys.stderr,
            )
            sys.exit(1)

    summary_text = str(snapshot.get("summary_text") or "").strip()
    if not summary_text:
        print("[error] missing summary_text", file=sys.stderr)
        sys.exit(1)

    print(summary_text)
    for check in checks:
        print(
            f"- {check['title']}: {check['status_label']} :: "
            f"{check['summary']}"
        )


if __name__ == "__main__":
    main()
