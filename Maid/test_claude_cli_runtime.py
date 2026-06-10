"""Smoke test for Claude Code CLI discovery.

Usage:
    .venv/bin/python -u Maid/test_claude_cli_runtime.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_claude_cli import (
    CLAUDE_CLI_PATH_ENV_VAR,
    candidate_claude_cli_paths,
    find_claude_cli_path,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    old_value = os.environ.get(CLAUDE_CLI_PATH_ENV_VAR)
    try:
        discovered = find_claude_cli_path()
        _assert(discovered is not None, "expected to discover a Claude Code CLI path")
        _assert(discovered.is_file(), f"expected discovered CLI to exist: {discovered}")

        with tempfile.TemporaryDirectory(prefix="deskmaid-claude-cli-") as tmp_dir:
            fake_cli = Path(tmp_dir) / "claude"
            fake_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_cli.chmod(0o755)

            os.environ[CLAUDE_CLI_PATH_ENV_VAR] = str(fake_cli)
            override = find_claude_cli_path()
            _assert(override == fake_cli, f"expected env override to win, got: {override}")

            candidates = candidate_claude_cli_paths()
            _assert(candidates, "expected at least one candidate CLI path")
            _assert(
                candidates[0] == fake_cli,
                f"expected env override to be first candidate, got: {candidates[0]}",
            )
    finally:
        if old_value is None:
            os.environ.pop(CLAUDE_CLI_PATH_ENV_VAR, None)
        else:
            os.environ[CLAUDE_CLI_PATH_ENV_VAR] = old_value

    print("ok")


if __name__ == "__main__":
    main()
