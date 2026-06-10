"""Integration-style tests for Deskmaid's session-level budget guard.

Usage:
    .venv/bin/python -u Maid/test_budget_guard_integration.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_agent_sdk import ResultMessage

import maid_chat
from maid_app_state import AppStateStore
from maid_preferences import CURRENT_SETUP_VERSION


ENV_KEYS = (
    "MAID_SESSION_STATE_PATH",
    "MAID_APP_STATE_PATH",
    "MAID_BUDGET_STATE_PATH",
    "MAID_MEMORY_STATE_PATH",
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _configure_temp_state(tmp_dir: str, *, budget_mode: str = "normal"):
    tmp_path = Path(tmp_dir)
    session_path = tmp_path / "session_state.json"
    app_state_path = tmp_path / "app_state.json"
    budget_path = tmp_path / "budget_state.json"
    memory_path = tmp_path / "memory_state.json"

    os.environ["MAID_SESSION_STATE_PATH"] = str(session_path)
    os.environ["MAID_APP_STATE_PATH"] = str(app_state_path)
    os.environ["MAID_BUDGET_STATE_PATH"] = str(budget_path)
    os.environ["MAID_MEMORY_STATE_PATH"] = str(memory_path)

    AppStateStore(app_state_path).apply_setup(
        onboarding_seen=True,
        setup_version_seen=CURRENT_SETUP_VERSION,
        owner_name="Budget Test",
        budget_mode=budget_mode,
        language="zh-CN",
        ui_language="zh-CN",
        data_boundary_acknowledged=True,
        auto_do_not_disturb_enabled=True,
        auto_hide_on_sensitive_scene=True,
    )


class _UnexpectedClient:
    init_count = 0

    def __init__(self, *args, **kwargs):
        del args, kwargs
        type(self).init_count += 1
        raise RuntimeError("remote client should not be constructed for budget-blocked runs")


class _CapturingClient:
    init_options = []
    connect_payloads = []
    disconnect_count = 0

    def __init__(self, options):
        self.options = options
        type(self).init_options.append(options)

    async def connect(self, *, prompt):
        payload = []
        async for item in prompt:
            payload.append(item)
        type(self).connect_payloads.append(payload)

    async def receive_response(self):
        yield ResultMessage(
            subtype="result",
            duration_ms=123,
            duration_api_ms=120,
            is_error=False,
            num_turns=1,
            session_id="sess-tightened",
            stop_reason="end_turn",
            total_cost_usd=0.12,
            usage={
                "input_tokens": 123,
                "output_tokens": 45,
            },
            result="tightened ok",
        )

    async def disconnect(self):
        type(self).disconnect_count += 1


def _run_budget_block_case():
    traces = []
    old_client = maid_chat.ClaudeSDKClient
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-block-") as tmp_dir:
        _configure_temp_state(tmp_dir)
        _UnexpectedClient.init_count = 0
        maid_chat.ClaudeSDKClient = _UnexpectedClient
        try:
            session = maid_chat._AgentSession()
            session._active_trace_handler = traces.append
            session._budget_store.record_usage(
                4.20,
                budget_mode="normal",
                session_id="sess-over-budget",
            )
            result = asyncio.run(session._run_prompt("给我讲个冷笑话。"))
        finally:
            maid_chat.ClaudeSDKClient = old_client
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    _assert(
        _UnexpectedClient.init_count == 0,
        "budget-blocked run should not construct the remote client",
    )
    _assert(
        result.stop_reason == "blocked_by_budget",
        f"expected blocked_by_budget, got {result.stop_reason!r}",
    )
    _assert(
        "今天的预算已经到上限了" in result.text,
        f"blocked result missing daily hard-gate wording: {result.text!r}",
    )
    _assert(result.total_cost_usd == 0.0, "blocked local run should not report remote cost")
    _assert(
        any(
            getattr(event, "kind", "") == "guardrail"
            and "预算上限" in getattr(event, "title", "")
            for event in traces
        ),
        "budget-blocked run should emit a guardrail trace",
    )
    _assert(
        any(
            getattr(event, "kind", "") == "result"
            and getattr(event, "title", "") == "本轮被预算闸拦下"
            for event in traces
        ),
        "budget-blocked run should emit the local blocked result trace",
    )
    _assert(
        not any(getattr(event, "kind", "") == "budget" for event in traces),
        "budget-blocked run should not record a budget spend trace",
    )


def _run_budget_tightening_case():
    traces = []
    old_client = maid_chat.ClaudeSDKClient
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-tighten-") as tmp_dir:
        _configure_temp_state(tmp_dir)
        _CapturingClient.init_options = []
        _CapturingClient.connect_payloads = []
        _CapturingClient.disconnect_count = 0
        maid_chat.ClaudeSDKClient = _CapturingClient
        try:
            session = maid_chat._AgentSession()
            session._active_trace_handler = traces.append
            session._budget_store.record_usage(
                3.60,
                budget_mode="normal",
                session_id="sess-preloaded",
            )
            result = asyncio.run(session._run_prompt("继续这个话题。"))
            snapshot = session.budget_guard_snapshot()
        finally:
            maid_chat.ClaudeSDKClient = old_client
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    _assert(
        len(_CapturingClient.init_options) == 1,
        "tightened run should construct exactly one remote client",
    )
    max_budget_usd = float(_CapturingClient.init_options[0].max_budget_usd or 0.0)
    _assert(
        abs(max_budget_usd - 0.40) < 1e-6,
        f"expected tightened max_budget_usd=0.40, got {max_budget_usd!r}",
    )
    _assert(
        len(_CapturingClient.connect_payloads) == 1,
        "tightened run should connect once and consume the prompt stream",
    )
    _assert(
        _CapturingClient.disconnect_count == 1,
        "tightened run should disconnect the remote client",
    )
    _assert(result.text == "tightened ok", f"unexpected tightened result text: {result.text!r}")
    _assert(result.session_id == "sess-tightened", "tightened run should persist the new session id")
    _assert(
        abs(float(result.total_cost_usd or 0.0) - 0.12) < 1e-6,
        f"unexpected total cost after tightened run: {result.total_cost_usd!r}",
    )
    _assert(
        abs(float(snapshot.get("daily_used_usd") or 0.0) - 3.72) < 1e-6,
        f"budget snapshot did not include the recorded spend: {snapshot!r}",
    )
    _assert(
        abs(float(snapshot.get("effective_max_budget_usd") or 0.0) - 0.28) < 1e-6,
        f"expected next effective max budget to tighten again after spend: {snapshot!r}",
    )
    _assert(
        any(
            getattr(event, "kind", "") == "guardrail"
            and getattr(event, "title", "") == "本轮预算已收紧"
            for event in traces
        ),
        "tightened run should emit the tightening trace",
    )
    _assert(
        any(
            getattr(event, "kind", "") == "budget"
            and "本轮花费 $0.120000" in getattr(event, "detail", "")
            for event in traces
        ),
        "tightened run should emit the recorded-cost trace",
    )


def _run_memory_budget_compaction_case():
    traces = []
    old_client = maid_chat.ClaudeSDKClient
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-memory-") as tmp_dir:
        _configure_temp_state(tmp_dir)
        _CapturingClient.init_options = []
        _CapturingClient.connect_payloads = []
        _CapturingClient.disconnect_count = 0
        maid_chat.ClaudeSDKClient = _CapturingClient
        try:
            session = maid_chat._AgentSession()
            session._active_trace_handler = traces.append
            for fact in (
                "主人喜欢苹果。",
                "主人喜欢梨。",
                "主人喜欢葡萄。",
                "主人喜欢乌龙茶。",
                "主人喜欢薄荷糖。",
            ):
                created = session._memory_store.create(fact)
                _assert(created is not None, f"failed to seed long-term memory: {fact!r}")
            result = asyncio.run(
                session._run_prompt("只根据你的长期记忆回答：主人喜欢什么？可以简短概括。")
            )
            snapshot = session.budget_guard_snapshot()
        finally:
            maid_chat.ClaudeSDKClient = old_client
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    _assert(
        len(_CapturingClient.init_options) == 1,
        "memory compaction run should construct exactly one remote client",
    )
    max_budget_usd = float(_CapturingClient.init_options[0].max_budget_usd or 0.0)
    _assert(
        abs(max_budget_usd - 0.80) < 1e-6,
        f"expected merged-memory max_budget_usd=0.80, got {max_budget_usd!r}",
    )
    system_prompt = str(_CapturingClient.init_options[0].system_prompt or "")
    _assert(
        "# 长期记忆" in system_prompt,
        "memory compaction run should still append the memory prompt",
    )
    _assert(
        system_prompt.count("主人喜欢") == 1,
        f"expected merged memory prompt to collapse likes into one fact, got {system_prompt!r}",
    )
    for marker in ("苹果", "梨", "葡萄", "乌龙茶", "薄荷糖"):
        _assert(
            marker in system_prompt,
            f"expected merged memory prompt to preserve {marker!r}: {system_prompt!r}",
        )
    _assert(
        result.text == "tightened ok",
        f"unexpected memory compaction result text: {result.text!r}",
    )
    _assert(
        str(snapshot.get("memory_budget_label") or "") == "轻量",
        f"snapshot should expose the memory budget label: {snapshot!r}",
    )
    _assert(
        int(snapshot.get("memory_budget_max_items") or 0) == 4,
        f"snapshot should expose the compact memory window: {snapshot!r}",
    )
    _assert(
        any(
            getattr(event, "kind", "") == "budget"
            and getattr(event, "title", "") == "记忆提炼走省预算档"
            and "实际合并: 4 条" in str(getattr(event, "detail", "") or "")
            for event in traces
        ),
        "memory compaction run should emit the memory-budget trace",
    )


def _run_memory_budget_noop_trace_case():
    traces = []
    old_client = maid_chat.ClaudeSDKClient
    old_env = {key: os.environ.get(key) for key in ENV_KEYS}

    with tempfile.TemporaryDirectory(prefix="deskmaid-budget-memory-noop-") as tmp_dir:
        _configure_temp_state(tmp_dir)
        _CapturingClient.init_options = []
        _CapturingClient.connect_payloads = []
        _CapturingClient.disconnect_count = 0
        maid_chat.ClaudeSDKClient = _CapturingClient
        try:
            session = maid_chat._AgentSession()
            session._active_trace_handler = traces.append
            created = session._memory_store.create("主人喜欢乌龙茶。")
            _assert(created is not None, "failed to seed short long-term memory")
            result = asyncio.run(
                session._run_prompt("只根据你的长期记忆回答：主人喜欢什么？")
            )
        finally:
            maid_chat.ClaudeSDKClient = old_client
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    _assert(
        len(_CapturingClient.init_options) == 1,
        "single-memory run should construct exactly one remote client",
    )
    max_budget_usd = float(_CapturingClient.init_options[0].max_budget_usd or 0.0)
    _assert(
        abs(max_budget_usd - 0.80) < 1e-6,
        f"single short memory should keep the base max_budget_usd, got {max_budget_usd!r}",
    )
    system_prompt = str(_CapturingClient.init_options[0].system_prompt or "")
    _assert(
        system_prompt.count("主人喜欢乌龙茶。") == 1,
        f"single-memory run should still include the short memory fact: {system_prompt!r}",
    )
    _assert(
        result.text == "tightened ok",
        f"unexpected single-memory result text: {result.text!r}",
    )
    _assert(
        not any(
            getattr(event, "kind", "") == "budget"
            and getattr(event, "title", "") == "记忆提炼走省预算档"
            for event in traces
        ),
        "single short memory should not emit the memory-budget trace",
    )


def main():
    _run_budget_block_case()
    _run_budget_tightening_case()
    _run_memory_budget_compaction_case()
    _run_memory_budget_noop_trace_case()
    print("ok")


if __name__ == "__main__":
    main()
