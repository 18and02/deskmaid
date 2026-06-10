"""Standalone session test for the maid Agent SDK backend.

Usage:
    .venv/bin/python -u Maid/test_anthropic.py

Sends a few prompts through the shared maid backend and prints the reply,
session id, and token usage so we can verify session continuity without Qt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maid_chat import ChatConfigError, ask_maid, shutdown_maid_session
from persona import MODEL


def main():
    sample_prompts = [
        "先记住一个事实: 我最喜欢的水果是梨。只回复“记住了”。",
        "我刚才最喜欢的水果是什么?",
        "现在再用一句话损我一下。",
    ]

    print(f"model={MODEL}  backend=Claude Agent SDK session\n")
    seen_session_id = None
    for p in sample_prompts:
        try:
            result = ask_maid(p)
        except ChatConfigError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(2)
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(1)
        print(f">>> 主人: {p}")
        print(f"<<< 女仆: {result.text}")
        print(
            f"    (session={result.session_id} in={result.input_tokens} "
            f"out={result.output_tokens} stop={result.stop_reason} "
            f"dur={result.duration_ms}ms cost={result.total_cost_usd})"
        )
        if seen_session_id is None:
            seen_session_id = result.session_id
        elif result.session_id != seen_session_id:
            print(
                f"    [warn] session changed: {seen_session_id} -> {result.session_id}",
                file=sys.stderr,
            )
        print()

    shutdown_maid_session()


if __name__ == "__main__":
    main()
