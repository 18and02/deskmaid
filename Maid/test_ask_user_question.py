"""Standalone AskUserQuestion integration test for the maid Agent SDK backend.

Usage:
    .venv/bin/python -u Maid/test_ask_user_question.py

The prompt explicitly asks the model to use AskUserQuestion. We auto-answer the
question through the new callback bridge and verify the answer shows up in the
final reply.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import (
    AskUserQuestionDecision,
    AskUserQuestionRequest,
    ChatConfigError,
    ask_maid,
    set_ask_user_question_handler,
    shutdown_maid_session,
)


def main():
    seen_requests: list[AskUserQuestionRequest] = []

    def auto_answer(request: AskUserQuestionRequest) -> AskUserQuestionDecision:
        seen_requests.append(request)
        answers: dict[str, str | list[str]] = {}
        for question in request.questions:
            if "饮料" in question.question:
                answers[question.question] = "乌龙茶"
            elif question.options:
                answers[question.question] = question.options[0].label
            else:
                answers[question.question] = "测试答案"
        print(f"[ask] auto answers={answers!r}")
        return AskUserQuestionDecision(answers=answers)

    set_ask_user_question_handler(auto_answer)
    try:
        result = ask_maid(
            "这是一次 AskUserQuestion 集成测试。"
            "你必须先使用 AskUserQuestion 工具问我“要记住的饮料是什么？”，"
            "并给我两个选项：“可乐”和“乌龙茶”。"
            "拿到答案后，只回复 drink=<答案>。"
            "不要调用别的工具，也不要直接在文本里提问。"
        )
    except ChatConfigError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        set_ask_user_question_handler(None)
        shutdown_maid_session()

    print(f"<<< 女仆: {result.text}")
    print(
        f"    (session={result.session_id} in={result.input_tokens} "
        f"out={result.output_tokens} stop={result.stop_reason} "
        f"dur={result.duration_ms}ms cost={result.total_cost_usd})"
    )

    if not seen_requests:
        print("[error] AskUserQuestion was not triggered", file=sys.stderr)
        sys.exit(1)

    first_request = seen_requests[0]
    if not any("饮料" in question.question for question in first_request.questions):
        print(
            f"[error] unexpected AskUserQuestion payload: {first_request.questions!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    if "乌龙茶" not in result.text:
        print(
            f"[error] expected final reply to include 乌龙茶, got {result.text!r}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
