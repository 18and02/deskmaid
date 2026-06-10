"""Standalone trace-event integration test for the maid Agent SDK backend.

Usage:
    .venv/bin/python -u Maid/test_trace_events.py

This verifies that a single prompt can stream coarse-grained trace events from
the Claude Agent SDK session back to the caller while AskUserQuestion is in play.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_chat import (
    AskUserQuestionDecision,
    AskUserQuestionRequest,
    ChatConfigError,
    ChatTraceEvent,
    ask_maid,
    set_ask_user_question_handler,
    shutdown_maid_session,
)


def main():
    events: list[ChatTraceEvent] = []
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

    def on_trace(event: ChatTraceEvent):
        events.append(event)
        print(f"[trace] {event.kind}: {event.title} :: {event.detail}")

    set_ask_user_question_handler(auto_answer)
    try:
        result = ask_maid(
            "这是一次思考流 trace 集成测试。"
            "你必须先使用 AskUserQuestion 工具问我“要记住的饮料是什么？”，"
            "并给我两个选项：“可乐”和“乌龙茶”。"
            "拿到答案后，只回复 drink=<答案>。"
            "不要调用别的工具，也不要直接在文本里提问。",
            trace_handler=on_trace,
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

    kinds = [event.kind for event in events]
    for required in (
        "run_started",
        "tool_use",
        "question_request",
        "question_answer",
        "assistant_text",
        "result",
    ):
        if required not in kinds:
            print(f"[error] missing trace event kind {required!r}", file=sys.stderr)
            sys.exit(1)

    if not any(
        event.kind == "tool_use" and event.tool_name == "AskUserQuestion"
        for event in events
    ):
        print(
            "[error] expected a tool_use trace event for AskUserQuestion",
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
