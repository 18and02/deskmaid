"""Core health/regression entry for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_core_health_regression.py

This runner executes the highest-signal backend health/regression scripts in a
stable order:
- outbound privacy filters
- agent runaway guardrails
- permission health self-check
- AskUserQuestion / trace integration
- resumable session persistence
- long-term memory cross-process recall
- desktop input / bridge regression
- Calendar / Reminders / Mail regression
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

REGRESSION_CASES: tuple[tuple[str, str], ...] = (
    ("api_key_store", "test_api_key_store.py"),
    ("app_state_store", "test_app_state_store.py"),
    ("budget_guard_store", "test_budget_guard_store.py"),
    ("budget_guard_integration", "test_budget_guard_integration.py"),
    ("budget_status_view", "test_budget_status_view.py"),
    ("permission_dialog_view", "test_permission_dialog_view.py"),
    ("build_macos_app_release", "test_build_macos_app_release.py"),
    ("claude_cli_runtime", "test_claude_cli_runtime.py"),
    ("privacy_filters", "test_privacy_filters.py"),
    ("privacy_boundary_view", "test_privacy_boundary_view.py"),
    ("privacy_quick_actions", "test_privacy_quick_actions.py"),
    ("speech_bubble_receipt_view", "test_speech_bubble_receipt_view.py"),
    ("sprite_pack_loader", "test_sprite_pack_loader.py"),
    ("desktop_shell_views", "test_desktop_shell_views.py"),
    ("maid_widget_auto_dnd_toggle", "test_maid_widget_auto_dnd_toggle.py"),
    ("maid_widget_sprite_pack_switch", "test_maid_widget_sprite_pack_switch.py"),
    ("outing_flow", "test_outing_flow.py"),
    ("maid_widget_outing_smoke", "test_maid_widget_outing_smoke.py"),
    ("agent_guardrails", "test_agent_guardrails.py"),
    ("auto_do_not_disturb", "test_auto_do_not_disturb.py"),
    ("permission_health", "test_permission_health.py"),
    ("permission_health_view", "test_permission_health_view.py"),
    ("permission_recovery_messages", "test_permission_recovery_messages.py"),
    ("permission_recovery_guide", "test_permission_recovery_guide.py"),
    ("trace_events", "test_trace_events.py"),
    ("session_persistence", "test_session_persistence.py"),
    ("long_term_memory_store", "test_long_term_memory_store.py"),
    ("long_term_memory", "test_long_term_memory_integration.py"),
    ("desktop_input_regression", "test_desktop_input_regression.py"),
    ("apple_apps_regression", "test_apple_apps_regression.py"),
)


def _run_case(label: str, filename: str) -> tuple[int, float]:
    path = SCRIPT_DIR / filename
    if not path.is_file():
        print(f"[error] missing regression script for {label}: {path}", file=sys.stderr)
        return 1, 0.0

    cmd = [PYTHON, "-u", str(path)]
    print(f"\n=== {label} :: start ===")
    print(f"[cmd] {' '.join(cmd)}")
    started = time.monotonic()
    env = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix=f"deskmaid-{label}-") as tmp_dir:
        env["MAID_SESSION_STATE_PATH"] = str(Path(tmp_dir) / "session_state.json")
        env["MAID_APP_STATE_PATH"] = str(Path(tmp_dir) / "app_state.json")
        env["MAID_BUDGET_STATE_PATH"] = str(Path(tmp_dir) / "budget_state.json")
        env["MAID_OUTING_STATE_PATH"] = str(Path(tmp_dir) / "outing_state.json")
        completed = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR.parent),
            check=False,
            env=env,
        )
    duration_s = time.monotonic() - started
    print(
        f"=== {label} :: {'ok' if completed.returncode == 0 else 'failed'} "
        f"({duration_s:.2f}s) ==="
    )
    return completed.returncode, duration_s


def main():
    started = time.monotonic()
    failures: list[str] = []

    for label, filename in REGRESSION_CASES:
        returncode, _ = _run_case(label, filename)
        if returncode != 0:
            failures.append(label)

    total_duration_s = time.monotonic() - started
    if failures:
        print(
            f"\n[error] core health/regression failed: {', '.join(failures)} "
            f"(total {total_duration_s:.2f}s)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n[ok] core health/regression passed ({total_duration_s:.2f}s)")


if __name__ == "__main__":
    main()
