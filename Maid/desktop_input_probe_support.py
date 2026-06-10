"""Helpers for launching and inspecting the desktop input probe app."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from maid_tools_desktop_window_open import _focus_window_sync


SCRIPT_PATH = Path(__file__).with_name("desktop_input_probe.py")


@dataclass
class InputProbeHandle:
    process: subprocess.Popen
    state_path: Path
    temp_dir: Path
    title: str


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def read_input_probe_state(state_path: Path) -> dict[str, object] | None:
    return _read_json(Path(state_path))


def wait_for_input_probe_state(
    state_path: Path,
    *,
    predicate=None,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.1,
) -> dict[str, object]:
    deadline = time.time() + timeout_s
    last_state = None
    while time.time() < deadline:
        state = read_input_probe_state(Path(state_path))
        last_state = state
        if state is not None and (predicate is None or predicate(state)):
            return state
        time.sleep(poll_interval_s)
    raise RuntimeError(
        f"desktop input probe state did not satisfy predicate in {timeout_s:.1f}s; "
        f"last state was {last_state!r}"
    )


def launch_input_probe(*, title: str, seed_text: str) -> InputProbeHandle:
    temp_dir = Path(tempfile.mkdtemp(prefix="deskmaid-input-probe-"))
    state_path = temp_dir / "state.json"
    cmd = [
        sys.executable,
        "-u",
        str(SCRIPT_PATH),
        "--title",
        title,
        "--seed-text",
        seed_text,
        "--state-file",
        str(state_path),
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle = InputProbeHandle(
        process=process,
        state_path=state_path,
        temp_dir=temp_dir,
        title=title,
    )
    wait_for_input_probe_state(
        state_path,
        predicate=lambda state: bool(state.get("ready")),
        timeout_s=10.0,
    )
    try:
        _focus_probe_window(handle)
    except Exception:
        time.sleep(0.3)
    return handle


def _focus_probe_window(handle: InputProbeHandle):
    deadline = time.time() + 5.0
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            _focus_window_sync({"title_contains": handle.title})
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    if last_error is not None:
        raise last_error


def stop_input_probe(handle: InputProbeHandle):
    process = handle.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
    shutil.rmtree(handle.temp_dir, ignore_errors=True)
