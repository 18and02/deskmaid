"""Claude Code CLI discovery helpers for source and packaged Deskmaid runs."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
import shutil
import sys

import claude_agent_sdk


CLAUDE_CLI_PATH_ENV_VAR = "MAID_CLAUDE_CLI_PATH"
CLAUDE_CLI_NAME = "claude.exe" if sys.platform == "win32" else "claude"


def _bundle_root_from_executable(executable: Path | None = None) -> Path | None:
    target = (executable or Path(sys.executable)).resolve()
    for candidate in [target, *target.parents]:
        if candidate.suffix == ".app":
            return candidate
    return None


def _sdk_package_root() -> Path | None:
    try:
        return Path(inspect.getfile(claude_agent_sdk)).resolve().parent
    except Exception:
        return None


def bundled_claude_cli_source_path() -> Path | None:
    package_root = _sdk_package_root()
    if package_root is None:
        return None
    candidate = package_root / "_bundled" / CLAUDE_CLI_NAME
    if candidate.is_file():
        return candidate
    return None


def candidate_claude_cli_paths(
    *,
    env: dict[str, str] | None = None,
    executable: Path | None = None,
    meipass: str | os.PathLike[str] | None = None,
) -> list[Path]:
    current_env = env if env is not None else os.environ
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None):
        if path is None:
            return
        expanded = path.expanduser()
        key = str(expanded)
        if key in seen:
            return
        seen.add(key)
        candidates.append(expanded)

    override = str(current_env.get(CLAUDE_CLI_PATH_ENV_VAR) or "").strip()
    if override:
        add(Path(override))

    bundled_source = bundled_claude_cli_source_path()
    add(bundled_source)

    path_env = str(current_env.get("PATH") or "").strip()
    if path_env:
        resolved = shutil.which(CLAUDE_CLI_NAME, path=path_env)
        if resolved:
            add(Path(resolved))

    packaged_root = meipass
    if packaged_root is None:
        packaged_root = getattr(sys, "_MEIPASS", None)
    if packaged_root:
        packaged_path = Path(str(packaged_root)).resolve()
        add(packaged_path / "claude_agent_sdk" / "_bundled" / CLAUDE_CLI_NAME)
        add(packaged_path / "_bundled" / CLAUDE_CLI_NAME)
        add(packaged_path / "claude_bundled" / CLAUDE_CLI_NAME)

    bundle_root = _bundle_root_from_executable(executable)
    if bundle_root is not None:
        add(
            bundle_root
            / "Contents"
            / "Frameworks"
            / "claude_agent_sdk"
            / "_bundled"
            / CLAUDE_CLI_NAME
        )
        add(
            bundle_root
            / "Contents"
            / "Resources"
            / "claude_agent_sdk"
            / "_bundled"
            / CLAUDE_CLI_NAME
        )
        add(bundle_root / "Contents" / "Frameworks" / "claude_bundled" / CLAUDE_CLI_NAME)
        add(bundle_root / "Contents" / "Resources" / "claude_bundled" / CLAUDE_CLI_NAME)

    for path in (
        Path.home() / ".npm-global" / "bin" / CLAUDE_CLI_NAME,
        Path("/usr/local/bin") / CLAUDE_CLI_NAME,
        Path("/opt/homebrew/bin") / CLAUDE_CLI_NAME,
        Path.home() / ".local" / "bin" / CLAUDE_CLI_NAME,
        Path.home() / "node_modules" / ".bin" / CLAUDE_CLI_NAME,
        Path.home() / ".yarn" / "bin" / CLAUDE_CLI_NAME,
        Path.home() / ".claude" / "local" / CLAUDE_CLI_NAME,
    ):
        add(path)

    return candidates


def find_claude_cli_path(
    *,
    env: dict[str, str] | None = None,
    executable: Path | None = None,
    meipass: str | os.PathLike[str] | None = None,
) -> Path | None:
    for candidate in candidate_claude_cli_paths(
        env=env,
        executable=executable,
        meipass=meipass,
    ):
        try:
            if candidate.is_file() and (
                sys.platform == "win32" or os.access(candidate, os.X_OK)
            ):
                return candidate
        except OSError:
            continue
    return None
