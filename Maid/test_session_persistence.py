"""Cross-process session persistence test for the maid Agent SDK backend.

Usage:
    .venv/bin/python -u Maid/test_session_persistence.py

This spawns two fresh Python processes that share the same session-state file.
The second process should resume the first process's Claude session from disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
CHILD_CODE = """
import json
import sys
from pathlib import Path

sys.path.insert(0, {maid_dir!r})

from maid_chat import ask_maid, shutdown_maid_session

result = None
try:
    result = ask_maid({prompt!r})
finally:
    shutdown_maid_session()

print(json.dumps({{"session_id": result.session_id, "text": result.text}}, ensure_ascii=False))
"""

CLEAR_CHILD_CODE = """
import json
import sys
from pathlib import Path

sys.path.insert(0, {maid_dir!r})

from maid_chat import clear_resumable_session, get_resumable_session_id

before = get_resumable_session_id()
cleared = clear_resumable_session()
after = get_resumable_session_id()
print(json.dumps({{"before": before, "cleared": cleared, "after": after}}, ensure_ascii=False))
"""


def _run_child(prompt: str, state_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["MAID_SESSION_STATE_PATH"] = str(state_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_CODE.format(
                maid_dir=str(HERE),
                prompt=prompt,
            ),
        ],
        cwd=str(HERE.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"child exited with {proc.returncode}")

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("child produced no stdout")
    return json.loads(lines[-1])


def _run_clear_child(state_path: Path) -> dict[str, str | None]:
    env = dict(os.environ)
    env["MAID_SESSION_STATE_PATH"] = str(state_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            CLEAR_CHILD_CODE.format(
                maid_dir=str(HERE),
            ),
        ],
        cwd=str(HERE.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"clear child exited with {proc.returncode}")

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("clear child produced no stdout")
    return json.loads(lines[-1])


def main():
    remember_token = "deskmaid-persist-token-4729"
    with tempfile.TemporaryDirectory(prefix="deskmaid-session-") as tmp_dir:
        state_path = Path(tmp_dir) / "session_state.json"

        first = _run_child(
            (
                f"Please remember this exact token for later: {remember_token}. "
                "Reply with only STORED."
            ),
            state_path,
        )
        second = _run_child(
            "What exact token did I ask you to remember? Reply with only the token.",
            state_path,
        )

        print(f"first session:  {first['session_id']}")
        print(f"second session: {second['session_id']}")
        print(f"second reply:   {second['text']}")

        if not state_path.exists():
            print("[error] state file was not written", file=sys.stderr)
            sys.exit(1)

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        saved_session_id = payload.get("session_id")
        print(f"saved session:  {saved_session_id}")

        if first["session_id"] != second["session_id"]:
            print(
                "[error] session id changed across process restart",
                file=sys.stderr,
            )
            sys.exit(1)
        if saved_session_id != first["session_id"]:
            print(
                "[error] saved session id does not match runtime session id",
                file=sys.stderr,
            )
            sys.exit(1)
        if remember_token not in second["text"]:
            print(
                f"[error] expected resumed reply to include {remember_token!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        cleared = _run_clear_child(state_path)
        print(f"cleared session: {cleared['cleared']}")
        if cleared["before"] != first["session_id"]:
            print(
                "[error] clear child did not see the saved resumable session",
                file=sys.stderr,
            )
            sys.exit(1)
        if cleared["cleared"] != first["session_id"]:
            print(
                "[error] clear child returned the wrong cleared session id",
                file=sys.stderr,
            )
            sys.exit(1)
        if cleared["after"] is not None:
            print(
                "[error] resumable session still exists after clear",
                file=sys.stderr,
            )
            sys.exit(1)
        if state_path.exists():
            print(
                "[error] state file still exists after clear",
                file=sys.stderr,
            )
            sys.exit(1)

        third = _run_child("Reply with only FRESH.", state_path)
        print(f"third session:  {third['session_id']}")
        if third["session_id"] == first["session_id"]:
            print(
                "[error] session id did not change after clearing resume state",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
