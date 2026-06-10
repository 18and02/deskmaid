"""Runtime-aware path helpers for Deskmaid."""

from __future__ import annotations

import os
from pathlib import Path
import sys


APP_NAME = "Deskmaid"
APP_ROOT = Path(__file__).resolve().parent.parent


def _looks_like_app_bundle(path: Path) -> bool:
    return any(part.endswith(".app") for part in path.parts)


def _is_probably_writable(path: Path) -> bool:
    target = path
    if not target.exists():
        target = target.parent
    try:
        return os.access(target, os.W_OK)
    except OSError:
        return False


def running_from_app_bundle() -> bool:
    executable = Path(sys.executable)
    return _looks_like_app_bundle(executable) or _looks_like_app_bundle(APP_ROOT)


def default_state_dir() -> Path:
    if sys.platform == "darwin" and (
        running_from_app_bundle() or not _is_probably_writable(APP_ROOT)
    ):
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return APP_ROOT


def default_state_path(filename: str) -> Path:
    return default_state_dir() / filename


def default_user_sprite_packs_dir() -> Path:
    return default_state_dir() / "SpritePacks"


def candidate_env_paths() -> list[Path]:
    paths: list[Path] = []
    for candidate in (APP_ROOT / ".env", default_state_dir() / ".env"):
        if candidate in paths:
            continue
        paths.append(candidate)
    return paths
