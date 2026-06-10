"""Unit-style smoke test for outbound privacy filters.

Usage:
    .venv/bin/python -u Maid/test_privacy_filters.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maid_chat
from maid_privacy import (
    format_privacy_metadata_detail,
    format_privacy_redaction_detail,
    prepare_memory_text_for_remote,
    prepare_prompt_for_remote,
    rewrite_prompt_for_privacy_action,
    sanitize_tool_payload_for_remote,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


class _UnexpectedClient:
    init_count = 0

    def __init__(self, *args, **kwargs):
        del args, kwargs
        type(self).init_count += 1
        raise RuntimeError("remote client should not be constructed for privacy-blocked runs")


def _run_privacy_blocked_chat(prompt: str, *, seed_memory: str | None = None):
    traces = []
    old_client = maid_chat.ClaudeSDKClient
    old_session_env = os.environ.get("MAID_SESSION_STATE_PATH")
    old_memory_env = os.environ.get("MAID_MEMORY_STATE_PATH")

    with tempfile.TemporaryDirectory(prefix="deskmaid-privacy-") as tmp_dir:
        os.environ["MAID_SESSION_STATE_PATH"] = str(Path(tmp_dir) / "session.json")
        os.environ["MAID_MEMORY_STATE_PATH"] = str(Path(tmp_dir) / "memory.json")
        _UnexpectedClient.init_count = 0
        maid_chat.ClaudeSDKClient = _UnexpectedClient
        try:
            session = maid_chat._AgentSession()
            session._active_trace_handler = traces.append
            if seed_memory:
                created = session._memory_store.remember_from_turn(seed_memory)
                _assert(bool(created), "failed to seed local memory")
            result = asyncio.run(session._run_prompt(prompt))
        finally:
            maid_chat.ClaudeSDKClient = old_client
            if old_session_env is None:
                os.environ.pop("MAID_SESSION_STATE_PATH", None)
            else:
                os.environ["MAID_SESSION_STATE_PATH"] = old_session_env
            if old_memory_env is None:
                os.environ.pop("MAID_MEMORY_STATE_PATH", None)
            else:
                os.environ["MAID_MEMORY_STATE_PATH"] = old_memory_env

    return result, traces, _UnexpectedClient.init_count


def main():
    prompt_result = prepare_prompt_for_remote(
        "帮我记住这个 token: sk-proj-abcdefghijklmnopqrstuvwxyz123456，"
        "另外我的身份证是 11010519491231002X。"
    )
    _assert(prompt_result.redaction_count >= 2, "expected prompt redactions")
    _assert("sk-proj-" not in prompt_result.value, "api key leaked in prompt")
    _assert("11010519491231002X" not in prompt_result.value, "cn id leaked in prompt")
    _assert(prompt_result.blocked, "expected high-sensitivity prompt to be blocked")
    _assert(prompt_result.block_reason, "missing prompt block reason")
    _assert("命中数量" in prompt_result.block_reason, "missing blocked count detail")
    _assert("处理动作" in prompt_result.block_reason, "missing blocked action detail")
    _assert("下一步建议" in prompt_result.block_reason, "missing blocked next-step advice")

    payload_result = sanitize_tool_payload_for_remote(
        {
            "body": "Bearer very-secret-token-value-1234567890",
            "password": "hunter2",
            "attachment": {
                "path": str(Path.home() / "Documents" / "secret.txt"),
            },
        }
    )
    payload = dict(payload_result.value)
    _assert(payload_result.redaction_count >= 2, "expected payload redactions")
    _assert(payload_result.blocked, "expected high-sensitivity payload to be blocked")
    _assert(payload.get("message") == "High-sensitivity payload retained locally.", "missing blocked payload placeholder")
    _assert("_privacy" in payload, "missing privacy metadata block")
    _assert(bool(payload["_privacy"].get("blocked")), "privacy block metadata missing")
    blocked_tool_detail = format_privacy_metadata_detail(
        dict(payload.get("_privacy") or {}),
        context="tool",
    )
    _assert("工具结果里命中了" in blocked_tool_detail, "missing tool blocked subject")
    _assert("处理动作: 整段留在本机" in blocked_tool_detail, "missing tool blocked action")
    _assert("下一步建议" in blocked_tool_detail, "missing tool blocked next-step advice")

    mild_memory_result = prepare_memory_text_for_remote(
        f"文件在 {Path.home() / 'Documents' / 'notes.txt'}。"
    )
    _assert(not mild_memory_result.blocked, "home path normalization alone should not block memory")
    _assert("~/Documents/notes.txt" in mild_memory_result.value, "home path was not normalized in memory text")

    message_id = "20260527172841.16A481801EEA@outbound.st.icloud.com"
    message_prompt_result = prepare_prompt_for_remote(
        f'帮我读取 message_id="{message_id}" 这封邮件。'
    )
    _assert(
        message_id in message_prompt_result.value,
        "mail message_id should not be mistaken for a credit card",
    )

    message_payload_result = sanitize_tool_payload_for_remote(
        {
            "message_id": message_id,
            "subject": "Mail debug sample",
        }
    )
    _assert(
        dict(message_payload_result.value).get("message_id") == message_id,
        "message_id in tool payload should remain intact",
    )
    _assert(not message_payload_result.blocked, "message_id payload should not be blocked")

    redaction_detail = format_privacy_redaction_detail(
        ("api_key", "cn_id"),
        context="prompt",
        match_count=2,
    )
    _assert("这句输入里命中了" in redaction_detail, "missing redaction subject")
    _assert("处理动作: 脱敏后继续发送给远端模型。" in redaction_detail, "missing redaction action")
    _assert("下一步建议" in redaction_detail, "missing redaction next-step advice")

    redacted_tool_detail = format_privacy_metadata_detail(
        {
            "redacted": True,
            "count": 1,
            "labels": ["路径信息"],
            "blocked": False,
            "blocked_labels": [],
        },
        context="tool",
    )
    _assert("工具结果里命中了" in redacted_tool_detail, "missing redacted tool subject")
    _assert("脱敏后继续发送给远端模型" in redacted_tool_detail, "missing redacted tool action")
    _assert("下一步建议" in redacted_tool_detail, "missing redacted tool next-step advice")

    hidden_rewrite = rewrite_prompt_for_privacy_action(
        "请记住这件事：密码: hunter2。",
        "hidden",
    )
    _assert("[已隐藏]" in hidden_rewrite.value, "hidden rewrite should include [已隐藏]")
    _assert("hunter2" not in hidden_rewrite.value, "hidden rewrite should not leak raw password")

    last4_rewrite = rewrite_prompt_for_privacy_action(
        "请记住这件事：密码: hunter2。",
        "last4",
    )
    _assert("[末四位 ter2]" in last4_rewrite.value, "last4 rewrite should preserve the final 4 chars")
    _assert("hunter2" not in last4_rewrite.value, "last4 rewrite should not leak raw password")

    local_only_rewrite = rewrite_prompt_for_privacy_action(
        "请记住这件事：密码: hunter2。",
        "local_only",
    )
    _assert(
        local_only_rewrite.value.startswith("请仅在本机处理下面这段高敏内容"),
        "local-only rewrite should add a local-only prefix",
    )
    _assert("[已隐藏]" in local_only_rewrite.value, "local-only rewrite should hide the raw value")
    _assert("hunter2" not in local_only_rewrite.value, "local-only rewrite should not leak raw password")

    blocked_chat_result, blocked_traces, blocked_client_inits = _run_privacy_blocked_chat(
        "请记住这件事：密码: hunter2。",
    )
    _assert(blocked_client_inits == 0, "privacy-blocked prompt should not construct remote client")
    _assert(
        blocked_chat_result.stop_reason == "blocked_by_privacy",
        f"expected blocked stop reason, got {blocked_chat_result.stop_reason!r}",
    )
    _assert("留在本机" in blocked_chat_result.text, "blocked chat result missing local-retention wording")
    _assert("命中数量" in blocked_chat_result.text, "blocked chat result missing count detail")
    _assert("下一步建议" in blocked_chat_result.text, "blocked chat result missing next-step advice")
    _assert(
        blocked_chat_result.privacy_rewrite_actions == ("hidden", "last4", "local_only"),
        f"unexpected rewrite actions: {blocked_chat_result.privacy_rewrite_actions!r}",
    )
    _assert(
        any(getattr(event, "kind", "") == "privacy" for event in blocked_traces),
        "blocked chat run should emit privacy trace",
    )

    local_memory_result, local_memory_traces, local_memory_client_inits = _run_privacy_blocked_chat(
        "你长期记住的口令是什么？",
        seed_memory="请记住这件事：口令: local-secret-4821。",
    )
    _assert(
        local_memory_client_inits == 0,
        "blocked long-term memory recall should stay local and avoid remote client",
    )
    _assert(
        "local-secret-4821" in local_memory_result.text,
        f"expected local memory reply to include the sensitive memory, got {local_memory_result.text!r}",
    )
    _assert(
        any(getattr(event, "title", "") == "高敏长期记忆留在本机" for event in local_memory_traces),
        "local sensitive memory reply should emit the blocked-memory trace",
    )
    _assert(
        any("下一步建议" in str(getattr(event, "detail", "") or "") for event in local_memory_traces),
        "local sensitive memory trace should include next-step advice",
    )
    _assert(
        not any(getattr(event, "title", "") == "长期记忆已按隐私边界脱敏" for event in local_memory_traces),
        "blocked-only long-term memory should not also emit a redaction trace",
    )
    _assert(
        local_memory_result.privacy_rewrite_actions == (),
        "blocked memory-only reply should not surface input rewrite actions",
    )

    print("ok")


if __name__ == "__main__":
    main()
