"""Cross-process long-term memory integration test for the maid backend.

Usage:
    .venv/bin/python -u Maid/test_long_term_memory_integration.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
CHILD_ASK_CODE = """
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

CLEAR_SESSION_CODE = """
import json
import sys
from pathlib import Path

sys.path.insert(0, {maid_dir!r})

from maid_chat import clear_resumable_session

print(json.dumps({{"cleared": clear_resumable_session()}}, ensure_ascii=False))
"""


def _run_child(code: str, *, session_path: Path, memory_path: Path) -> dict:
    env = dict(os.environ)
    env["MAID_SESSION_STATE_PATH"] = str(session_path)
    env["MAID_MEMORY_STATE_PATH"] = str(memory_path)
    proc = subprocess.run(
        [sys.executable, "-c", code],
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


def main():
    with tempfile.TemporaryDirectory(prefix="deskmaid-long-memory-") as tmp_dir:
        session_path = Path(tmp_dir) / "session.json"
        memory_path = Path(tmp_dir) / "memory.json"

        first = _run_child(
            CHILD_ASK_CODE.format(
                maid_dir=str(HERE),
                prompt="请记住这件事：我最喜欢的水果是梨。只回复记住了。",
            ),
            session_path=session_path,
            memory_path=memory_path,
        )
        cleared = _run_child(
            CLEAR_SESSION_CODE.format(maid_dir=str(HERE)),
            session_path=session_path,
            memory_path=memory_path,
        )
        second = _run_child(
            CHILD_ASK_CODE.format(
                maid_dir=str(HERE),
                prompt="只根据你的长期记忆回答：我最喜欢的水果是什么？只回复水果名。",
            ),
            session_path=session_path,
            memory_path=memory_path,
        )

        print(f"first session:  {first['session_id']}")
        print(f"cleared session:{cleared['cleared']}")
        print(f"second session: {second['session_id']}")
        print(f"second reply:   {second['text']}")

        if not memory_path.exists():
            print("[error] memory file was not written", file=sys.stderr)
            sys.exit(1)
        raw_memory = memory_path.read_text(encoding="utf-8")
        if "水果是梨" in raw_memory:
            print(
                f"[error] plaintext long-term memory leaked into storage: {raw_memory!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if '"format": "fernet"' not in raw_memory:
            print(
                f"[error] expected encrypted memory envelope, got {raw_memory!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if cleared["cleared"] != first["session_id"]:
            print(
                "[error] resumable session was not cleared before the recall prompt",
                file=sys.stderr,
            )
            sys.exit(1)
        if first["session_id"] == second["session_id"]:
            print(
                "[error] second prompt reused the old session; expected a fresh session",
                file=sys.stderr,
            )
            sys.exit(1)
        if "梨" not in second["text"]:
            print(
                f"[error] expected long-term memory recall to mention 梨, got {second['text']!r}",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
