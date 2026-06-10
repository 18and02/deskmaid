"""Unified desktop-input regression entry for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_desktop_input_regression.py

This runner executes the desktop input / bridge regression scripts in a stable order:
- desktop bridge smoke
- open_app integration
- list_windows integration
- focus_window integration
- open_url integration
- read_clipboard_text integration
- set_clipboard_text integration
- paste_text integration
- press_keys integration
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
    ("desktop_smoke", "test_desktop_bridges.py"),
    ("open_app", "test_open_app_tool.py"),
    ("list_windows", "test_list_windows_tool.py"),
    ("focus_window", "test_focus_window_tool.py"),
    ("open_url", "test_open_url_tool.py"),
    ("read_clipboard_text", "test_read_clipboard_text_tool.py"),
    ("set_clipboard_text", "test_set_clipboard_text_tool.py"),
    ("paste_text", "test_paste_text_tool.py"),
    ("press_keys", "test_press_keys_tool.py"),
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
            f"\n[error] desktop input regression failed: {', '.join(failures)} "
            f"(total {total_duration_s:.2f}s)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n[ok] desktop input regression passed ({total_duration_s:.2f}s)")


if __name__ == "__main__":
    main()
