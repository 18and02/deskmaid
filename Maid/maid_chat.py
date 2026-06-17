"""Shared Claude Agent SDK session helper for the desktop maid."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import threading
import time
from typing import Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
)
from dotenv import load_dotenv

from maid_api_key import ensure_runtime_api_key, load_provider_key
from maid_app_state import load_app_state_snapshot
from maid_providers import (
    build_subprocess_env,
    get_provider,
    resolve_active_provider,
)
from maid_budget import (
    BudgetGuardStatus,
    BudgetUsageStore,
    format_budget_block_message,
    format_budget_tightening_message,
    format_budget_usage_summary,
)
from maid_budget_policy import (
    MemoryBudgetPolicy,
    build_memory_budget_policy,
    tool_risk_quota_rows,
)
from maid_claude_cli import find_claude_cli_path
from maid_guardrails import (
    DEFAULT_MAX_AGENT_RUNTIME_S,
    DEFAULT_MAX_AGENT_TURNS,
    ToolUseGuardrail,
)
from maid_memory import (
    ForgetOutcome,
    LongTermMemoryStore,
    MemoryItem,
    MemoryWriteOutcome,
    memory_item_metadata,
    preview_memories,
)
from maid_paths import APP_ROOT, candidate_env_paths, default_state_path
from maid_preferences import BUDGET_MODE_MAX_BUDGET_USD, normalize_budget_mode
from maid_privacy import (
    format_privacy_metadata_detail,
    format_privacy_redaction_detail,
    prepare_memory_text_for_remote,
    prepare_prompt_for_remote,
)
from maid_tools import (
    MAID_MCP_SERVERS,
    TOOL_PREFERENCE_PROMPT,
    format_create_calendar_event_preview,
    format_create_mail_draft_preview,
    format_focus_window_preview,
    format_list_windows_preview,
    format_open_url_preview,
    format_paste_text_preview,
    format_press_keys_preview,
    format_read_clipboard_text_preview,
    format_create_reminder_preview,
    format_delete_calendar_event_preview,
    format_delete_reminder_preview,
    format_set_clipboard_text_preview,
    format_send_mail_draft_preview,
    format_update_calendar_event_preview,
    format_update_reminder_preview,
    format_write_tool_receipt,
    preview_create_calendar_event_request,
    preview_create_mail_draft_request,
    preview_focus_window_request,
    preview_list_windows_request,
    preview_open_url_request,
    preview_paste_text_request,
    preview_press_keys_request,
    preview_read_clipboard_text_request,
    preview_create_reminder_request,
    preview_delete_calendar_event_request,
    preview_delete_reminder_request,
    preview_set_clipboard_text_request,
    preview_send_mail_draft_request,
    preview_update_calendar_event_request,
    preview_update_reminder_request,
)
from persona import MODEL, SYSTEM_PROMPT

for ENV_PATH in candidate_env_paths():
    load_dotenv(ENV_PATH, override=True)

MAX_AGENT_TURNS = DEFAULT_MAX_AGENT_TURNS
MAX_AGENT_RUNTIME_S = DEFAULT_MAX_AGENT_RUNTIME_S
STARTUP_TIMEOUT_S = 30.0
SHUTDOWN_JOIN_TIMEOUT_S = 5.0
SESSION_STATE_ENV_VAR = "MAID_SESSION_STATE_PATH"
DEFAULT_SESSION_STATE_PATH = default_state_path(".maid_session.json")
_STOP = object()
AGENT_SYSTEM_PROMPT = SYSTEM_PROMPT + TOOL_PREFERENCE_PROMPT
_PRIVACY_MEMORY_QUERY_RE = re.compile(
    r"(?:长期记忆|记得|记住|口令|密码|token|密钥|私钥|授权码|银行卡|信用卡|身份证)",
    re.IGNORECASE,
)
_REMOTE_MEMORY_LIKE_RE = re.compile(r"^主人喜欢(?P<value>[^。！？!?]{1,40})。?$")
_REMOTE_MEMORY_DISLIKE_RE = re.compile(r"^主人不喜欢(?P<value>[^。！？!?]{1,40})。?$")


class ChatConfigError(RuntimeError):
    """Raised when the local Claude Agent SDK session cannot be started."""


@dataclass
class ChatResult:
    text: str
    display_text: str | None
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    session_id: str
    duration_ms: int
    total_cost_usd: float | None
    privacy_rewrite_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatTraceEvent:
    kind: str
    title: str
    detail: str = ""
    session_id: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class PermissionRequest:
    tool_name: str
    input_data: dict
    tool_use_id: str | None
    title: str | None
    display_name: str | None
    description: str | None
    blocked_path: str | None
    decision_reason: str | None
    preview_text: str = ""
    preview_data: dict[str, object] | None = None
    allow_remember: bool = True
    confirm_label: str | None = None
    risk_level: str = ""
    risk_label: str = ""
    risk_limit: int = 0
    risk_used: int = 0
    risk_remaining: int = 0
    total_limit: int = 0
    total_used: int = 0
    total_remaining: int = 0


@dataclass
class PermissionDecision:
    allow: bool
    message: str = ""
    remember_tool: bool = False


@dataclass(frozen=True)
class AskUserQuestionOption:
    label: str
    description: str = ""


@dataclass(frozen=True)
class AskUserQuestionItem:
    question: str
    header: str
    options: list[AskUserQuestionOption]
    multi_select: bool = False


AskUserQuestionAnswer = str | list[str]


@dataclass(frozen=True)
class AskUserQuestionRequest:
    questions: list[AskUserQuestionItem]
    input_data: dict
    tool_use_id: str | None
    title: str | None
    display_name: str | None
    description: str | None


@dataclass
class AskUserQuestionDecision:
    answers: dict[str, AskUserQuestionAnswer] = field(default_factory=dict)
    cancelled: bool = False
    message: str = ""


@dataclass
class _Request:
    prompt: str
    future: Future
    trace_handler: "TraceHandler | None" = None


PermissionHandler = Callable[[PermissionRequest], PermissionDecision]
AskUserQuestionHandler = Callable[[AskUserQuestionRequest], AskUserQuestionDecision]
TraceHandler = Callable[[ChatTraceEvent], None]


_permission_handler: PermissionHandler | None = None
_permission_lock = threading.Lock()
_question_handler: AskUserQuestionHandler | None = None
_question_lock = threading.Lock()


def _memory_item_payload(item: MemoryItem) -> dict[str, object]:
    payload = {
        "key": item.key,
        "text": item.text,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "expires_at": item.expires_at,
        "last_used_at": item.last_used_at,
        "source": item.source,
    }
    payload.update(memory_item_metadata(item))
    return payload


def _memory_write_payload(outcome: MemoryWriteOutcome) -> dict[str, object]:
    payload = _memory_item_payload(outcome.item)
    payload.update(
        {
            "write_action": outcome.action,
            "replaced_items": [
                _memory_item_payload(item) for item in outcome.replaced
            ],
            "pruned_expired_count": outcome.pruned_expired_count,
        }
    )
    return payload


def _session_state_path() -> Path:
    override = os.environ.get(SESSION_STATE_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_SESSION_STATE_PATH


def _current_budget_mode() -> str:
    snapshot = load_app_state_snapshot()
    return normalize_budget_mode(snapshot.budget_mode)


def _current_max_budget_usd() -> float | None:
    mode = _current_budget_mode()
    return BUDGET_MODE_MAX_BUDGET_USD.get(mode)


def _provider_key_env_var(provider_id: str) -> str:
    provider = get_provider(provider_id)
    return provider.key_env_var if provider is not None else ""


def _resolve_provider_runtime() -> tuple[dict[str, str], str, object]:
    """Resolve the active provider into (subprocess_env, model, resolved).

    Anthropic returns an empty env — the key keeps flowing through the inherited
    ``ANTHROPIC_API_KEY`` exactly as before. Third-party providers get an env
    override pointing the CLI at their Anthropic-compatible endpoint + key.
    """
    resolved = resolve_active_provider(load_app_state_snapshot())
    if resolved.is_anthropic:
        return {}, resolved.model, resolved
    key = load_provider_key(resolved.id, env_var=_provider_key_env_var(resolved.id)) or ""
    return build_subprocess_env(resolved, key), resolved.model, resolved


def _active_provider_key_ready() -> tuple[bool, object]:
    """Whether the active provider has a usable key, plus the resolved provider."""
    resolved = resolve_active_provider(load_app_state_snapshot())
    if resolved.is_anthropic:
        return bool(ensure_runtime_api_key()), resolved
    key = load_provider_key(resolved.id, env_var=_provider_key_env_var(resolved.id))
    return bool(key), resolved


def _normalize_startup_error_message(message: str) -> str:
    text = str(message or "").strip()
    if "Claude Code not found" not in text:
        return text

    cli_path = find_claude_cli_path()
    if cli_path is not None:
        return (
            "已经找到 Claude Code 运行时，但 Agent SDK 还是没拉起来。"
            f"\nCLI: {cli_path}"
        )

    return (
        "还没找到 Claude Code 运行时。"
        "\n打包版请使用最新重新构建的 Deskmaid.app；"
        "\n开发态请安装 `claude`，或设置 `MAID_CLAUDE_CLI_PATH` 指向可执行文件。"
    )


def _load_saved_session_id(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[session] failed to read {path}: {exc}")
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[session] failed to parse {path}: {exc}")
        return None

    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return None
    session_id = session_id.strip()
    return session_id or None


def _save_session_id(path: Path, session_id: str | None):
    if not session_id:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"[session] failed to remove {path}: {exc}")
        return

    payload = {
        "version": 1,
        "session_id": session_id,
    }
    serialized = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    tmp_path = path.with_name(f"{path.name}.tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(serialized, encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        print(f"[session] failed to write {path}: {exc}")
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _build_ask_user_question_request(
    input_data: dict,
    context: ToolPermissionContext,
) -> AskUserQuestionRequest | None:
    raw_questions = input_data.get("questions")
    if not isinstance(raw_questions, list):
        return None

    questions: list[AskUserQuestionItem] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict):
            continue

        question_text = raw_question.get("question")
        if isinstance(question_text, str):
            question_text = question_text.strip()
        else:
            question_text = ""

        header = raw_question.get("header")
        if isinstance(header, str):
            header = header.strip()
        else:
            header = ""

        if not header:
            header = f"问题 {index}"
        if not question_text:
            question_text = header

        options: list[AskUserQuestionOption] = []
        raw_options = raw_question.get("options")
        if isinstance(raw_options, list):
            for raw_option in raw_options:
                if not isinstance(raw_option, dict):
                    continue
                label = raw_option.get("label")
                if not isinstance(label, str):
                    continue
                label = label.strip()
                if not label:
                    continue
                description = raw_option.get("description")
                if isinstance(description, str):
                    description = description.strip()
                else:
                    description = ""
                options.append(
                    AskUserQuestionOption(
                        label=label,
                        description=description,
                    )
                )

        questions.append(
            AskUserQuestionItem(
                question=question_text,
                header=header,
                options=options,
                multi_select=bool(raw_question.get("multiSelect")),
            )
        )

    if not questions:
        return None

    return AskUserQuestionRequest(
        questions=questions,
        input_data=input_data,
        tool_use_id=context.tool_use_id,
        title=context.title,
        display_name=context.display_name,
        description=context.description,
    )


def _normalize_ask_user_question_answers(
    request: AskUserQuestionRequest,
    answers: dict[str, AskUserQuestionAnswer] | None,
) -> dict[str, AskUserQuestionAnswer]:
    if not answers:
        return {}

    normalized: dict[str, AskUserQuestionAnswer] = {}
    for question in request.questions:
        raw_answer = answers.get(question.question)
        if isinstance(raw_answer, str):
            value = raw_answer.strip()
            if value:
                normalized[question.question] = value
            continue

        if isinstance(raw_answer, list):
            values = [
                item.strip()
                for item in raw_answer
                if isinstance(item, str) and item.strip()
            ]
            if not values:
                continue
            if question.multi_select:
                normalized[question.question] = values
            else:
                normalized[question.question] = values[0]

    return normalized


def _extract_text(message: AssistantMessage) -> str:
    parts = [block.text for block in message.content if isinstance(block, TextBlock)]
    return "\n".join(part.strip() for part in parts if part.strip()).strip()


def _trim_trace_text(text: str, limit: int = 600) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _trace_preview(value, limit: int = 600) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _trim_trace_text(value, limit=limit)
    try:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        rendered = str(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 4)].rstrip() + "\n..."


def _memory_reason_text(payload: dict[str, object]) -> str:
    reason_key = str(payload.get("reason_key") or "").strip()
    source = str(payload.get("source") or "").strip()
    source_text = ""
    if source and source not in {"manual", "legacy"}:
        source_text = _trim_trace_text(source, limit=34)

    base = {
        "manual": "来自记忆面板里的手动新增或改写",
        "legacy_import": "从旧版本地记忆迁入",
        "explicit_instruction": "你明确要求我记住这件事",
        "address_preference": "这是你明确给出的称呼偏好",
        "identity_statement": "这是你直接告诉我的身份信息",
        "reply_language_preference": "这是你明确给出的回复语言偏好",
        "stated_preference": "这是你直接说出的稳定偏好",
        "stated_fact": "这是你明确给出的事实",
        "conversation_note": "这是你留给我的长期便签",
        "conversation_memory": "这是我从当前对话里抽到的长期记忆",
    }.get(reason_key, "这是我从当前对话里收下的长期记忆")
    if source_text:
        return f"{base}；原话：{source_text}"
    return base


def _memory_expiry_text(payload: dict[str, object]) -> str:
    policy_key = str(payload.get("expiry_policy_key") or "").strip()
    if policy_key == "forever":
        return "不自动过期，只会在你手动改删时变化"

    days = payload.get("expiry_days")
    try:
        day_count = int(days)
    except (TypeError, ValueError):
        day_count = 0

    expires_at = payload.get("expires_at")
    try:
        expires_label = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(expires_at)))
    except (TypeError, ValueError):
        expires_label = ""

    if day_count > 0 and expires_label:
        return f"默认保留 {day_count} 天；预计到 {expires_label}，到期后会在读写时自动清理"
    if day_count > 0:
        return f"默认保留 {day_count} 天；到期后会在读写时自动清理"
    if expires_label:
        return f"预计到 {expires_label}；到期后会在读写时自动清理"
    return "会在读写时自动清理过期内容"


def _memory_conflict_text(payload: dict[str, object]) -> str:
    policy_key = str(payload.get("conflict_policy_key") or "").strip()
    return {
        "opposite_preference": "同一对象的喜欢 / 不喜欢会互相替换，以最近一次为准",
        "same_topic": "同一主题后写覆盖前写，以最新说法为准",
        "parallel_note": "不同便签会并存；完全相同的内容只刷新时间",
    }.get(policy_key, "冲突时会优先保留最近一次确认的内容")


def _memory_action_text(action: str) -> str:
    normalized = str(action or "").strip()
    if normalized == "updated":
        return "已更新"
    if normalized == "replaced":
        return "已替换写入"
    return "已新增"


def _memory_preview_list(items: list[dict[str, object]], *, limit: int = 2) -> str:
    snippets = [
        _trim_trace_text(str(item.get("text") or ""), limit=28)
        for item in items[:limit]
        if str(item.get("text") or "").strip()
    ]
    if len(items) > limit:
        snippets.append(f"... 共 {len(items)} 条")
    return "；".join(snippets)


def _format_memory_write_trace(outcomes: list[MemoryWriteOutcome]) -> str:
    blocks: list[str] = []
    total_pruned = 0
    for outcome in outcomes[:4]:
        payload = _memory_write_payload(outcome)
        lines = [
            f"- {_memory_action_text(outcome.action)}: {_trim_trace_text(str(payload.get('text') or ''), limit=72)}",
            f"  原因: {_memory_reason_text(payload)}",
            f"  过期: {_memory_expiry_text(payload)}",
        ]
        replaced_items = [
            dict(item)
            for item in (payload.get("replaced_items") or [])
            if isinstance(item, dict)
        ]
        if replaced_items:
            lines.append(f"  覆盖: {_memory_preview_list(replaced_items)}")
        else:
            lines.append(f"  冲突: {_memory_conflict_text(payload)}")
        blocks.append("\n".join(lines))
        total_pruned += int(payload.get("pruned_expired_count") or 0)

    if len(outcomes) > 4:
        blocks.append(f"- ... 共 {len(outcomes)} 条")
    if total_pruned > 0:
        blocks.append(f"清理: 顺手清掉 {total_pruned} 条已过期记忆。")
    return "\n\n".join(blocks)


def _forget_mode_label(mode: str) -> str:
    normalized = str(mode or "").strip()
    if normalized == "recent":
        return "按最近一条定位"
    if normalized == "key":
        return "按固定主题定位"
    if normalized == "search":
        return "按关键词搜索"
    return "按自然语言定位"


def _format_forget_trace(outcome: ForgetOutcome) -> str:
    lines = [f"方式: {_forget_mode_label(outcome.mode)}"]
    if outcome.target:
        lines.append(f"目标: {outcome.target}")

    if outcome.removed:
        lines.append("已删除:")
        lines.extend(
            f"- {_trim_trace_text(item.text, limit=72)}"
            for item in outcome.removed[:4]
        )
        if len(outcome.removed) > 4:
            lines.append(f"- ... 共 {len(outcome.removed)} 条")
    elif outcome.ambiguous_matches:
        lines.append(f"结果: 命中 {len(outcome.ambiguous_matches)} 条，暂未删除")
        lines.append("候选:")
        lines.extend(
            f"- {_trim_trace_text(item.text, limit=72)}"
            for item in outcome.ambiguous_matches[:4]
        )
        if len(outcome.ambiguous_matches) > 4:
            lines.append(f"- ... 共 {len(outcome.ambiguous_matches)} 条")
    else:
        lines.append(f"结果: {_trim_trace_text(outcome.message, limit=120)}")

    if outcome.pruned_expired_count > 0:
        lines.append(f"清理: 顺手清掉 {outcome.pruned_expired_count} 条已过期记忆")
    return "\n".join(lines)


def _format_forget_receipt(outcome: ForgetOutcome) -> str:
    title = "状态回执 · 长期记忆治理"
    lines = [f"定位: {_forget_mode_label(outcome.mode)}"]
    if outcome.target:
        lines.append(f"目标: {outcome.target}")

    if outcome.removed:
        lines.insert(0, f"动作: 已删除 {len(outcome.removed)} 条")
        removed_preview = "；".join(
            _trim_trace_text(item.text, limit=26)
            for item in outcome.removed[:2]
        )
        if len(outcome.removed) > 2:
            removed_preview = f"{removed_preview}；... 共 {len(outcome.removed)} 条"
        lines.append(f"内容: {removed_preview}")
    elif outcome.ambiguous_matches:
        lines.insert(0, "动作: 暂未删除")
        lines.append(
            "候选: "
            + "；".join(
                _trim_trace_text(item.text, limit=22)
                for item in outcome.ambiguous_matches[:2]
            )
        )
        lines.append("附记: 命中不止一条，等你再指清楚。")
    else:
        lines.insert(0, "动作: 暂未删除")
        lines.append(f"结果: {_trim_trace_text(outcome.message, limit=72)}")

    if outcome.pruned_expired_count > 0:
        lines.append(f"清理: 顺手清掉 {outcome.pruned_expired_count} 条已过期记忆")
    return "\n".join([title, *lines])


def _tool_result_text_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content).strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return str(content).strip()


def _tool_result_payload(content) -> dict[str, object] | None:
    if isinstance(content, dict):
        return content
    text = _tool_result_text_content(content)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _combine_receipt_texts(receipts: list[str]) -> str | None:
    cleaned = [receipt.strip() for receipt in receipts if receipt and receipt.strip()]
    if not cleaned:
        return None
    if len(cleaned) <= 3:
        return "\n\n".join(cleaned)
    extra_count = len(cleaned) - 3
    return "\n\n".join(cleaned[:3] + [f"另外还有 {extra_count} 项已处理。"])


def _compact_memory_fact(text: str, *, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _merged_preference_memory(
    kind: str,
    values: list[str],
    items: list[MemoryItem],
) -> MemoryItem:
    assert values
    assert items
    prefix = "主人喜欢" if kind == "like" else "主人不喜欢"
    keywords: list[str] = []
    seen_keywords: set[str] = set()
    for item in items:
        for keyword in item.keywords:
            normalized = str(keyword).strip().lower()
            if not normalized or normalized in seen_keywords:
                continue
            seen_keywords.add(normalized)
            keywords.append(str(keyword).strip())

    expires_candidates = [
        float(item.expires_at)
        for item in items
        if item.expires_at is not None
    ]
    last_used_candidates = [
        float(item.last_used_at)
        for item in items
        if item.last_used_at is not None
    ]
    return MemoryItem(
        key=f"merged:{kind}",
        text=f"{prefix}{'、'.join(values)}。",
        keywords=keywords,
        created_at=min(float(item.created_at) for item in items),
        updated_at=max(float(item.updated_at) for item in items),
        expires_at=max(expires_candidates) if expires_candidates else None,
        last_used_at=max(last_used_candidates) if last_used_candidates else None,
        source="merged_remote_memory",
    )


def _prepare_remote_memories(memories: list[MemoryItem]) -> tuple[list[MemoryItem], int]:
    if len(memories) < 2:
        return list(memories), 0

    merged_entries: list[tuple[int, MemoryItem]] = []
    bucket_specs = {
        "like": {
            "pattern": _REMOTE_MEMORY_LIKE_RE,
            "values": [],
            "items": [],
            "seen_values": set(),
            "first_index": None,
        },
        "dislike": {
            "pattern": _REMOTE_MEMORY_DISLIKE_RE,
            "values": [],
            "items": [],
            "seen_values": set(),
            "first_index": None,
        },
    }

    for index, memory in enumerate(memories):
        text = " ".join(str(memory.text or "").split())
        matched_bucket = False
        for bucket in bucket_specs.values():
            match = bucket["pattern"].match(text)
            if not match:
                continue
            value = str(match.group("value") or "").strip()
            if not value:
                break
            normalized_value = value.lower()
            if normalized_value not in bucket["seen_values"]:
                bucket["seen_values"].add(normalized_value)
                bucket["values"].append(value)
                bucket["items"].append(memory)
                if bucket["first_index"] is None:
                    bucket["first_index"] = index
            matched_bucket = True
            break
        if matched_bucket:
            continue
        merged_entries.append((index, memory))

    merged_away_count = 0
    for kind, bucket in bucket_specs.items():
        values = list(bucket["values"])
        items = list(bucket["items"])
        first_index = bucket["first_index"]
        if not values or not items or first_index is None:
            continue
        if len(values) == 1 and len(items) == 1:
            merged_entries.append((int(first_index), items[0]))
            continue
        merged_away_count += len(items) - 1
        merged_entries.append(
            (
                int(first_index),
                _merged_preference_memory(kind, values, items),
            )
        )

    merged_entries.sort(key=lambda pair: pair[0])
    return [item for _, item in merged_entries], merged_away_count


def _build_remote_memory_prompt(
    memories: list[MemoryItem],
    *,
    policy: MemoryBudgetPolicy,
) -> tuple[str, int, tuple[str, ...], list[MemoryItem], tuple[str, ...], int, int, int]:
    if not memories:
        return "", 0, (), [], (), 0, 0, 0

    selected_memories = list(memories[: max(1, int(policy.max_items or 1))])
    if not selected_memories:
        return "", 0, (), [], (), 0, 0, 0

    safe_lines: list[str] = []
    safe_redaction_count = 0
    safe_redaction_labels: list[str] = []
    blocked_items: list[MemoryItem] = []
    blocked_labels: list[str] = []
    blocked_match_count = 0
    compacted_line_count = 0
    for memory in selected_memories:
        privacy_result = prepare_memory_text_for_remote(memory.text)
        if privacy_result.blocked:
            blocked_items.append(memory)
            blocked_labels.extend(privacy_result.blocked_labels or privacy_result.labels)
            blocked_match_count += max(1, int(privacy_result.redaction_count or 0))
            continue
        compacted_line = _compact_memory_fact(
            privacy_result.value,
            limit=max(24, int(policy.clip_chars or 72)),
        )
        if compacted_line != privacy_result.value:
            compacted_line_count += 1
        safe_lines.append(compacted_line)
        safe_redaction_count += privacy_result.redaction_count
        safe_redaction_labels.extend(privacy_result.labels)

    if not safe_lines:
        return (
            "",
            0,
            (),
            blocked_items,
            tuple(dict.fromkeys(blocked_labels)),
            blocked_match_count,
            len(selected_memories),
            compacted_line_count,
        )

    lines = [
        "# 长期记忆",
        "- 下面这些事实来自更早的对话，只在相关时自然使用，不要逐条复述。",
        "- 如果主人在当前这句话里明确更正了旧信息，以当前这句话为准。",
    ]
    lines.extend(f"- {line}" for line in safe_lines)
    return (
        "\n".join(lines),
        safe_redaction_count,
        tuple(dict.fromkeys(safe_redaction_labels)),
        blocked_items,
        tuple(dict.fromkeys(blocked_labels)),
        blocked_match_count,
        len(selected_memories),
        compacted_line_count,
    )


def _format_memory_budget_trace(
    policy: MemoryBudgetPolicy,
    *,
    recalled_count: int,
    prepared_count: int,
    selected_count: int,
    compacted_count: int,
    applied_budget_usd: float | None,
    pre_memory_budget_usd: float | None,
) -> str:
    detail_lines = [
        f"记忆档位: {policy.label}",
        f"命中长期记忆: {recalled_count} 条",
    ]
    merged_count = max(0, int(recalled_count or 0) - int(prepared_count or 0))
    if merged_count > 0:
        detail_lines.append(f"合并后待提炼: {prepared_count} 条")
        detail_lines.append(f"实际合并: {merged_count} 条")
    detail_lines.append(f"本轮最多带上云: {selected_count} 条")
    skipped_count = max(0, int(prepared_count or 0) - int(selected_count or 0))
    if skipped_count > 0:
        detail_lines.append(f"实际省略: {skipped_count} 条")
    if compacted_count > 0:
        detail_lines.append(f"实际压缩: {compacted_count} 条较长事实")
    if pre_memory_budget_usd is not None and applied_budget_usd is not None:
        detail_lines.append(
            f"记忆档前单轮上限: ${pre_memory_budget_usd:.2f} -> ${applied_budget_usd:.2f}"
        )
    elif applied_budget_usd is not None:
        detail_lines.append(f"单轮上限: ${applied_budget_usd:.2f}")
    detail_lines.append(f"记忆预算系数: {int(round(policy.budget_factor * 100))}%")
    detail_lines.extend(str(reason) for reason in policy.reasons if reason)
    return "\n".join(detail_lines)


def _looks_like_privacy_memory_query(prompt: str) -> bool:
    return bool(_PRIVACY_MEMORY_QUERY_RE.search(str(prompt or "")))


def _local_blocked_memory_reply(memories: list[MemoryItem]) -> str:
    if not memories:
        return "命中的高敏长期记忆已留在本机，没有发到远端模型。"
    if len(memories) == 1:
        return (
            f"{memories[0].text}\n\n"
            "这条高敏长期记忆只在本机展示，没有发到远端模型。"
        )

    lines = ["这些高敏长期记忆只在本机展示，没有发到远端模型："]
    lines.extend(f"- {memory.text}" for memory in memories[:4])
    if len(memories) > 4:
        lines.append(f"- ... 共 {len(memories)} 条")
    return "\n".join(lines)


def _local_chat_result(
    text: str,
    *,
    started_at: float,
    session_id: str,
    stop_reason: str,
    display_text: str | None = None,
    privacy_rewrite_actions: tuple[str, ...] = (),
) -> ChatResult:
    return ChatResult(
        text=text,
        display_text=display_text or text,
        input_tokens=0,
        output_tokens=0,
        stop_reason=stop_reason,
        session_id=session_id,
        duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        total_cost_usd=0.0,
        privacy_rewrite_actions=privacy_rewrite_actions,
    )


def _budget_guard_status_payload(status: BudgetGuardStatus) -> dict[str, object]:
    return {
        "mode": status.mode,
        "per_run_limit_usd": status.per_run_limit_usd,
        "effective_max_budget_usd": status.effective_max_budget_usd,
        "daily_limit_usd": status.daily_limit_usd,
        "daily_used_usd": status.daily_used_usd,
        "daily_remaining_usd": status.daily_remaining_usd,
        "weekly_limit_usd": status.weekly_limit_usd,
        "weekly_used_usd": status.weekly_used_usd,
        "weekly_remaining_usd": status.weekly_remaining_usd,
        "raw_idle_seconds": status.raw_idle_seconds,
        "suspended_idle_seconds": status.suspended_idle_seconds,
        "folded_idle_seconds": status.folded_idle_seconds,
        "idle_throttle_factor": status.idle_throttle_factor,
        "idle_throttle_stage": status.idle_throttle_stage,
        "idle_throttle_reason": status.idle_throttle_reason,
        "daily_pressure_level": status.daily_pressure_level,
        "weekly_pressure_level": status.weekly_pressure_level,
        "daily_base_runs_left": status.daily_base_runs_left,
        "weekly_base_runs_left": status.weekly_base_runs_left,
        "remaining_allows_full_base_run": status.remaining_allows_full_base_run,
        "remaining_shortfall_usd": status.remaining_shortfall_usd,
        "next_daily_reset_at": status.next_daily_reset_at,
        "next_weekly_reset_at": status.next_weekly_reset_at,
        "blocked": status.blocked,
        "blocked_scope": status.blocked_scope,
        "summary": format_budget_usage_summary(status),
    }


def _format_question_trace(request: AskUserQuestionRequest) -> str:
    lines = []
    for item in request.questions:
        line = item.header.strip() or item.question.strip()
        question = item.question.strip()
        if question and question != line:
            line = f"{line}: {question}"
        labels = [option.label for option in item.options if option.label]
        if labels:
            line += " [" + " / ".join(labels[:6]) + ("" if len(labels) <= 6 else " / ...") + "]"
        lines.append(line)
    return "\n".join(lines)


def _format_result_trace(result: ResultMessage) -> str:
    usage = result.usage or {}
    parts = [
        f"dur={result.duration_ms}ms",
        f"in={int(usage.get('input_tokens', 0) or 0)}",
        f"out={int(usage.get('output_tokens', 0) or 0)}",
    ]
    if result.stop_reason:
        parts.append(f"stop={result.stop_reason}")
    if result.total_cost_usd is not None:
        parts.append(f"cost={result.total_cost_usd:.6f}")
    if result.result:
        parts.append(_trim_trace_text(result.result, limit=200))
    return "  ".join(parts)


def _tool_name_matches(tool_name: str, leaf_name: str) -> bool:
    if tool_name == leaf_name:
        return True
    return tool_name.endswith(f"__{leaf_name}")


def _permission_preview_spec(tool_name: str):
    preview_specs = [
        (
            "list_windows",
            preview_list_windows_request,
            format_list_windows_preview,
            "确认读取",
            False,
        ),
        (
            "focus_window",
            preview_focus_window_request,
            format_focus_window_preview,
            "确认切换",
            False,
        ),
        (
            "open_url",
            preview_open_url_request,
            format_open_url_preview,
            "确认打开",
            False,
        ),
        (
            "read_clipboard_text",
            preview_read_clipboard_text_request,
            format_read_clipboard_text_preview,
            "确认读取",
            False,
        ),
        (
            "set_clipboard_text",
            preview_set_clipboard_text_request,
            format_set_clipboard_text_preview,
            "确认写入剪贴板",
            False,
        ),
        (
            "paste_text",
            preview_paste_text_request,
            format_paste_text_preview,
            "确认粘贴",
            False,
        ),
        (
            "press_keys",
            preview_press_keys_request,
            format_press_keys_preview,
            "确认按键",
            False,
        ),
        (
            "create_mail_draft",
            preview_create_mail_draft_request,
            format_create_mail_draft_preview,
            "确认保存草稿",
            True,
        ),
        (
            "send_mail_draft",
            preview_send_mail_draft_request,
            format_send_mail_draft_preview,
            "确认发送",
            False,
        ),
        (
            "create_calendar_event",
            preview_create_calendar_event_request,
            format_create_calendar_event_preview,
            "确认创建",
            False,
        ),
        (
            "update_calendar_event",
            preview_update_calendar_event_request,
            format_update_calendar_event_preview,
            "确认更新",
            False,
        ),
        (
            "delete_calendar_event",
            preview_delete_calendar_event_request,
            format_delete_calendar_event_preview,
            "确认删除",
            False,
        ),
        (
            "create_reminder",
            preview_create_reminder_request,
            format_create_reminder_preview,
            "确认创建",
            False,
        ),
        (
            "update_reminder",
            preview_update_reminder_request,
            format_update_reminder_preview,
            "确认更新",
            False,
        ),
        (
            "delete_reminder",
            preview_delete_reminder_request,
            format_delete_reminder_preview,
            "确认删除",
            False,
        ),
    ]
    for leaf_name, preview_fn, format_fn, confirm_label, allow_remember in preview_specs:
        if _tool_name_matches(tool_name, leaf_name):
            return {
                "preview_fn": preview_fn,
                "format_fn": format_fn,
                "confirm_label": confirm_label,
                "allow_remember": allow_remember,
            }
    return None


def _format_permission_trace(request: PermissionRequest) -> str:
    lines: list[str] = []
    if request.risk_label and request.risk_limit > 0:
        lines.append(f"风险档: {request.risk_label}")
        lines.append(
            f"本轮这档剩余: {max(0, int(request.risk_remaining))} / {int(request.risk_limit)}"
        )
    if request.total_limit > 0:
        lines.append(
            f"本轮总工具剩余: {max(0, int(request.total_remaining))} / {int(request.total_limit)}"
        )
    lines.append(
        "允许后可记住到本次会话。"
        if request.allow_remember
        else "这类工具不会记住授权，每次都要再确认。"
    )
    body = request.preview_text or _trace_preview(request.input_data)
    if body:
        lines.append(body)
    return "\n".join(lines)


class _AgentSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests: Queue[object] = Queue()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._startup_error: BaseException | None = None
        self._session_state_path = _session_state_path()
        self._last_session_id: str | None = _load_saved_session_id(
            self._session_state_path
        )
        self._session_allowed_tools: set[str] = set()
        self._memory_store = LongTermMemoryStore()
        self._budget_store = BudgetUsageStore()
        self._active_trace_handler: TraceHandler | None = None
        self._current_run_write_receipts: list[str] = []
        self._current_run_seen_write_receipts: set[str] = set()
        self._current_run_tool_guard: ToolUseGuardrail | None = None

    def ask(
        self,
        prompt: str,
        trace_handler: TraceHandler | None = None,
    ) -> ChatResult:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt is empty")

        self._ensure_started()
        future: Future = Future()
        self._requests.put(
            _Request(
                prompt=prompt,
                future=future,
                trace_handler=trace_handler,
            )
        )
        return future.result()

    def remembered_tool_names(self) -> list[str]:
        with self._lock:
            return sorted(self._session_allowed_tools)

    def clear_remembered_tools(self) -> int:
        with self._lock:
            count = len(self._session_allowed_tools)
            self._session_allowed_tools.clear()
            return count

    def long_term_memories(self) -> list[str]:
        return [item.text for item in self._memory_store.entries()]

    def long_term_memory_items(self) -> list[dict[str, object]]:
        return [_memory_item_payload(item) for item in self._memory_store.entries()]

    def create_long_term_memory_item(self, text: str) -> dict[str, object] | None:
        created = self._memory_store.create_with_outcome(text)
        if created is None:
            return None
        return _memory_write_payload(created)

    def update_long_term_memory_item(self, key: str, text: str) -> dict[str, object] | None:
        updated = self._memory_store.update_text_with_outcome(key, text)
        if updated is None:
            return None
        return _memory_write_payload(updated)

    def delete_long_term_memory_item(self, key: str) -> dict[str, object] | None:
        removed = self._memory_store.delete(key)
        if removed is None:
            return None
        return _memory_item_payload(removed)

    def budget_guard_snapshot(self) -> dict[str, object]:
        budget_mode = _current_budget_mode()
        status = self._budget_store.guard_status(
            budget_mode=budget_mode,
            per_run_limit_usd=_current_max_budget_usd(),
        )
        payload = _budget_guard_status_payload(status)
        memory_policy = build_memory_budget_policy(
            budget_mode=budget_mode,
            budget_status=status,
            recalled_count=4,
            preview=True,
        )
        payload.update(
            {
                "tool_risk_quotas": tool_risk_quota_rows(),
                "memory_budget_tier": memory_policy.tier,
                "memory_budget_label": memory_policy.label,
                "memory_budget_max_items": memory_policy.max_items,
                "memory_budget_clip_chars": memory_policy.clip_chars,
                "memory_budget_factor": memory_policy.budget_factor,
                "memory_budget_reasons": list(memory_policy.reasons),
            }
        )
        return payload

    def record_budget_activity(self):
        self._budget_store.mark_activity()

    def note_budget_suspend(self):
        self._budget_store.note_suspend()

    def note_budget_resume(self):
        self._budget_store.note_resume()

    def consume_budget_reset_notice(self) -> str:
        return self._budget_store.consume_reset_message(
            budget_mode=_current_budget_mode(),
            per_run_limit_usd=_current_max_budget_usd(),
        )

    def resumable_session_id(self) -> str | None:
        with self._lock:
            session_id = self._last_session_id
        if session_id:
            return session_id
        return _load_saved_session_id(self._session_state_path)

    def clear_resumable_session(self) -> str | None:
        self.close()
        with self._lock:
            session_id = self._last_session_id
            self._last_session_id = None
            self._session_allowed_tools.clear()
        _save_session_id(self._session_state_path, None)
        return session_id

    def close(self):
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._thread = None
            self._requests.put(_STOP)
        thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        if not thread.is_alive():
            self._requests = Queue()
            self._session_allowed_tools.clear()

    def _ensure_started(self):
        key_ready, resolved = _active_provider_key_ready()
        if not key_ready:
            if resolved.is_anthropic:
                raise ChatConfigError("还没有配置 Claude API key。先在第一次见面里填上。")
            raise ChatConfigError(
                f"还没有配置「{resolved.name}」的 API key。先在右键菜单 → 模型/服务商里填上。"
            )
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._requests = Queue()
            self._started.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="maid-agent-session",
                daemon=True,
            )
            self._thread.start()

        if not self._started.wait(timeout=STARTUP_TIMEOUT_S):
            raise ChatConfigError("Claude Agent SDK session startup timed out")
        if self._startup_error is not None:
            raise ChatConfigError(
                _normalize_startup_error_message(str(self._startup_error))
            ) from self._startup_error

    def _thread_main(self):
        try:
            asyncio.run(self._async_main())
        except BaseException as exc:  # pragma: no cover - surfaced to callers
            self._startup_error = exc
            self._started.set()

    async def _async_main(self):
        try:
            self._started.set()
            while True:
                item = await asyncio.to_thread(self._requests.get)
                if item is _STOP:
                    return
                assert isinstance(item, _Request)
                try:
                    self._active_trace_handler = item.trace_handler
                    result = await self._run_prompt(item.prompt)
                except BaseException as exc:
                    self._emit_trace(
                        ChatTraceEvent(
                            kind="error",
                            title="这轮对话没跑完",
                            detail=_trim_trace_text(str(exc) or exc.__class__.__name__),
                            session_id=self._last_session_id,
                        )
                    )
                    item.future.set_exception(exc)
                else:
                    item.future.set_result(result)
                finally:
                    self._active_trace_handler = None
        except BaseException as exc:
            self._startup_error = exc
            self._started.set()
            while True:
                try:
                    item = self._requests.get_nowait()
                except Empty:
                    break
                if isinstance(item, _Request):
                    item.future.set_exception(exc)
            raise

    def _build_client_options(
        self,
        memory_prompt: str = "",
        *,
        max_budget_usd: float | None = None,
    ) -> ClaudeAgentOptions:
        system_prompt = AGENT_SYSTEM_PROMPT
        if memory_prompt:
            system_prompt = f"{system_prompt}\n\n{memory_prompt}"
        cli_path = find_claude_cli_path()
        # Active provider decides the model + (for third-party) the endpoint/key
        # env. Anthropic returns env={} so this path stays identical to before.
        provider_env, provider_model, _resolved = _resolve_provider_runtime()
        return ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=provider_model or MODEL,
            env=provider_env,
            cwd=str(APP_ROOT),
            mcp_servers=MAID_MCP_SERVERS,
            permission_mode="default",
            max_turns=MAX_AGENT_TURNS,
            max_budget_usd=(
                _current_max_budget_usd()
                if max_budget_usd is None
                else max_budget_usd
            ),
            resume=self._last_session_id,
            cli_path=str(cli_path) if cli_path is not None else None,
            can_use_tool=self._can_use_tool,
        )

    async def _prompt_stream(self, prompt: str):
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": "default",
        }

    async def _run_prompt(self, prompt: str) -> ChatResult:
        started_at = time.monotonic()
        self._emit_trace(
            ChatTraceEvent(
                kind="run_started",
                title="收到主人输入",
                detail=_trim_trace_text(prompt),
                session_id=self._last_session_id,
            )
        )
        if self._last_session_id:
            self._emit_trace(
                ChatTraceEvent(
                    kind="session",
                    title="沿用续接会话",
                    detail=self._last_session_id,
                    session_id=self._last_session_id,
                )
            )

        forget_outcome: ForgetOutcome = self._memory_store.forget_from_prompt(prompt)
        if forget_outcome.handled:
            if (
                forget_outcome.removed
                or forget_outcome.ambiguous_matches
                or forget_outcome.pruned_expired_count > 0
            ):
                self._emit_trace(
                    ChatTraceEvent(
                        kind="memory_store",
                        title="删掉长期记忆",
                        detail=_format_forget_trace(forget_outcome),
                        session_id=self._last_session_id,
                    )
                )
            self._emit_trace(
                ChatTraceEvent(
                    kind="result",
                    title="本轮走本机记忆治理",
                    detail=_format_forget_trace(forget_outcome),
                    session_id=self._last_session_id,
                )
            )
            return _local_chat_result(
                forget_outcome.message,
                started_at=started_at,
                session_id=self._last_session_id or "",
                stop_reason="local_memory_edit",
                display_text=_format_forget_receipt(forget_outcome),
            )

        _memory_prompt, recalled_memories = self._memory_store.build_prompt(prompt)
        prepared_memories, merged_memory_count = _prepare_remote_memories(recalled_memories)
        if recalled_memories:
            self._emit_trace(
                ChatTraceEvent(
                    kind="memory_recall",
                    title="翻到长期记忆",
                    detail=preview_memories(recalled_memories),
                    session_id=self._last_session_id,
                )
            )

        remote_prompt_result = prepare_prompt_for_remote(prompt)
        if remote_prompt_result.blocked:
            self._emit_trace(
                ChatTraceEvent(
                    kind="privacy",
                    title="高敏输入留在本机",
                    detail=remote_prompt_result.block_reason,
                    session_id=self._last_session_id,
                )
            )
            saved_memories = self._memory_store.remember_from_turn_outcomes(
                prompt,
                assistant_text="",
            )
            if saved_memories:
                self._emit_trace(
                    ChatTraceEvent(
                        kind="memory_store",
                        title="写入长期记忆",
                        detail=_format_memory_write_trace(saved_memories),
                        session_id=self._last_session_id,
                    )
                )
            text = remote_prompt_result.block_reason
            if saved_memories:
                text += "\n\n命中的长期记忆已仅在本机加密保存。"
            self._emit_trace(
                ChatTraceEvent(
                    kind="result",
                    title="本轮被隐私边界拦下",
                    detail=_trim_trace_text(text),
                    session_id=self._last_session_id,
                )
            )
            return _local_chat_result(
                text,
                started_at=started_at,
                session_id=self._last_session_id or "",
                stop_reason="blocked_by_privacy",
                privacy_rewrite_actions=("hidden", "last4", "local_only"),
            )
        remote_prompt = remote_prompt_result.value
        if remote_prompt_result.redaction_count > 0:
            self._emit_trace(
                ChatTraceEvent(
                    kind="privacy",
                    title="离机前做了脱敏",
                    detail=format_privacy_redaction_detail(
                        remote_prompt_result.labels,
                        context="prompt",
                        match_count=remote_prompt_result.redaction_count,
                    ),
                    session_id=self._last_session_id,
                )
            )

        budget_mode = _current_budget_mode()
        base_max_budget_usd = _current_max_budget_usd()
        budget_status = self._budget_store.guard_status(
            budget_mode=budget_mode,
            per_run_limit_usd=base_max_budget_usd,
        )
        memory_budget_policy = build_memory_budget_policy(
            budget_mode=budget_mode,
            budget_status=budget_status,
            recalled_count=len(prepared_memories),
        )
        (
            remote_memory_prompt,
            remote_memory_redactions,
            remote_memory_labels,
            blocked_memory_items,
            blocked_memory_labels,
            blocked_memory_match_count,
            selected_memory_count,
            compacted_memory_count,
        ) = (
            _build_remote_memory_prompt(
                prepared_memories,
                policy=memory_budget_policy,
            )
        )
        if remote_memory_redactions > 0:
            self._emit_trace(
                ChatTraceEvent(
                    kind="privacy",
                    title="长期记忆已按隐私边界脱敏",
                    detail=format_privacy_redaction_detail(
                        remote_memory_labels,
                        context="memory",
                        match_count=remote_memory_redactions,
                    ),
                    session_id=self._last_session_id,
                )
            )
        if blocked_memory_items:
            self._emit_trace(
                ChatTraceEvent(
                    kind="privacy",
                    title="高敏长期记忆留在本机",
                    detail=format_privacy_metadata_detail(
                        {
                            "blocked": True,
                            "count": max(
                                int(blocked_memory_match_count or 0),
                                len(blocked_memory_items),
                            ),
                            "blocked_labels": list(blocked_memory_labels),
                        },
                        context="memory",
                    ),
                    session_id=self._last_session_id,
                )
            )
            if not remote_memory_prompt and _looks_like_privacy_memory_query(prompt):
                text = _local_blocked_memory_reply(blocked_memory_items)
                self._emit_trace(
                    ChatTraceEvent(
                        kind="result",
                        title="本轮走本机高敏记忆答复",
                        detail=_trim_trace_text(text),
                        session_id=self._last_session_id,
                    )
                )
                return _local_chat_result(
                    text,
                    started_at=started_at,
                    session_id=self._last_session_id or "",
                    stop_reason="blocked_by_privacy",
                )

        if budget_status.blocked:
            detail = format_budget_usage_summary(budget_status)
            self._emit_trace(
                ChatTraceEvent(
                    kind="guardrail",
                    title=(
                        "碰到本周预算上限"
                        if budget_status.blocked_scope == "week"
                        else "碰到今日预算上限"
                    ),
                    detail=detail,
                    session_id=self._last_session_id,
                )
            )
            text = format_budget_block_message(budget_status)
            self._emit_trace(
                ChatTraceEvent(
                    kind="result",
                    title="本轮被预算闸拦下",
                    detail=_trim_trace_text(text),
                    session_id=self._last_session_id,
                )
            )
            return _local_chat_result(
                text,
                started_at=started_at,
                session_id=self._last_session_id or "",
                stop_reason="blocked_by_budget",
            )

        run_max_budget_usd = budget_status.effective_max_budget_usd
        if (
            remote_memory_prompt
            and run_max_budget_usd is not None
            and memory_budget_policy.budget_factor < 1.0 - 1e-6
        ):
            run_max_budget_usd = max(
                0.0,
                float(run_max_budget_usd) * float(memory_budget_policy.budget_factor),
            )
        memory_prompt_trimmed = (
            merged_memory_count > 0
            or selected_memory_count < len(prepared_memories)
            or compacted_memory_count > 0
        )
        memory_budget_reduced = (
            budget_status.effective_max_budget_usd is not None
            and run_max_budget_usd is not None
            and run_max_budget_usd
            < budget_status.effective_max_budget_usd - 1e-6
        )
        if recalled_memories and (
            memory_prompt_trimmed or memory_budget_reduced
        ):
            self._emit_trace(
                ChatTraceEvent(
                    kind="budget",
                    title="记忆提炼走省预算档",
                    detail=_format_memory_budget_trace(
                        memory_budget_policy,
                        recalled_count=len(recalled_memories),
                        prepared_count=len(prepared_memories),
                        selected_count=selected_memory_count,
                        compacted_count=compacted_memory_count,
                        applied_budget_usd=run_max_budget_usd,
                        pre_memory_budget_usd=budget_status.effective_max_budget_usd,
                    ),
                    session_id=self._last_session_id,
                )
            )

        tightening_message = format_budget_tightening_message(
            budget_status,
            base_per_run_limit_usd=base_max_budget_usd,
        )
        if tightening_message:
            self._emit_trace(
                ChatTraceEvent(
                    kind="guardrail",
                    title="本轮预算已收紧",
                    detail=tightening_message,
                    session_id=self._last_session_id,
                )
            )

        client = ClaudeSDKClient(
            self._build_client_options(
                memory_prompt=remote_memory_prompt,
                max_budget_usd=run_max_budget_usd,
            )
        )
        connected = False

        texts: list[str] = []
        final: ResultMessage | None = None
        session_id = self._last_session_id
        tool_names_by_id: dict[str, str] = {}
        write_receipts: list[str] = []
        seen_receipts: set[str] = set()
        self._current_run_write_receipts = []
        self._current_run_seen_write_receipts = set()
        self._current_run_tool_guard = ToolUseGuardrail()

        try:
            async with asyncio.timeout(MAX_AGENT_RUNTIME_S):
                await client.connect(prompt=self._prompt_stream(remote_prompt))
                connected = True
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        if message.session_id:
                            session_id = message.session_id
                        self._collect_write_receipts(
                            message,
                            tool_names_by_id,
                            write_receipts,
                            seen_receipts,
                        )
                        self._emit_assistant_trace(message)
                        text = _extract_text(message)
                        if text:
                            texts.append(text)
                    elif isinstance(message, TaskStartedMessage):
                        self._emit_trace(
                            ChatTraceEvent(
                                kind="task_started",
                                title="任务开始",
                                detail=_trim_trace_text(message.description),
                                session_id=message.session_id,
                                tool_use_id=message.tool_use_id,
                            )
                        )
                    elif isinstance(message, TaskProgressMessage):
                        detail = _trim_trace_text(message.description)
                        if message.last_tool_name:
                            if detail:
                                detail = f"{detail}\nlast_tool={message.last_tool_name}"
                            else:
                                detail = f"last_tool={message.last_tool_name}"
                        self._emit_trace(
                            ChatTraceEvent(
                                kind="task_progress",
                                title="任务进行中",
                                detail=detail,
                                session_id=message.session_id,
                                tool_name=message.last_tool_name,
                                tool_use_id=message.tool_use_id,
                            )
                        )
                    elif isinstance(message, TaskNotificationMessage):
                        status_title = {
                            "completed": "任务完成",
                            "failed": "任务失败",
                            "stopped": "任务已停",
                        }.get(message.status, "任务更新")
                        detail = _trim_trace_text(message.summary)
                        if message.output_file:
                            if detail:
                                detail = f"{detail}\noutput={message.output_file}"
                            else:
                                detail = f"output={message.output_file}"
                        self._emit_trace(
                            ChatTraceEvent(
                                kind="task_notification",
                                title=status_title,
                                detail=detail,
                                session_id=message.session_id,
                                tool_use_id=message.tool_use_id,
                            )
                        )
                    elif isinstance(message, ResultMessage):
                        final = message
                        session_id = message.session_id or session_id
        except TimeoutError as exc:
            self._emit_trace(
                ChatTraceEvent(
                    kind="guardrail",
                    title="这轮对话超时了",
                    detail=(
                        f"单轮运行超过 {int(MAX_AGENT_RUNTIME_S)} 秒，被护栏主动截停。"
                    ),
                    session_id=session_id,
                )
            )
            raise RuntimeError("这轮对话跑太久了。我先停住，拆小一点再来。") from exc
        finally:
            if connected:
                await client.disconnect()
            self._current_run_tool_guard = None

        if final is None:
            raise RuntimeError("Claude Agent SDK returned no result message")

        self._last_session_id = session_id
        _save_session_id(self._session_state_path, session_id)

        text = "\n\n".join(chunk for chunk in texts if chunk).strip()
        if not text:
            text = (final.result or "").strip()
        if not text:
            text = "..."

        usage = final.usage or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        recorded_budget = self._budget_store.record_usage(
            final.total_cost_usd,
            budget_mode=budget_mode,
            session_id=session_id or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=str(final.stop_reason or ""),
        )
        if recorded_budget is not None:
            refreshed_budget_status = self._budget_store.guard_status(
                budget_mode=budget_mode,
                per_run_limit_usd=base_max_budget_usd,
            )
            self._emit_trace(
                ChatTraceEvent(
                    kind="budget",
                    title="记下本轮成本",
                    detail=(
                        f"本轮花费 ${recorded_budget.cost_usd:.6f}。"
                        f"\n{format_budget_usage_summary(refreshed_budget_status)}。"
                    ),
                    session_id=session_id,
                )
            )

        if final.is_error:
            detail = (final.result or text or final.stop_reason or "Claude Agent SDK request failed").strip()
            raise RuntimeError(detail)

        if str(final.stop_reason or "").strip() == "max_turns":
            self._emit_trace(
                ChatTraceEvent(
                    kind="guardrail",
                    title="碰到单轮回合上限",
                    detail=(
                        f"这轮最多只让 Agent 走 {MAX_AGENT_TURNS} 个回合。"
                    ),
                    session_id=session_id,
                )
            )

        saved_memories = self._memory_store.remember_from_turn_outcomes(
            prompt,
            assistant_text=text,
        )
        if saved_memories:
            self._emit_trace(
                ChatTraceEvent(
                    kind="memory_store",
                    title="写入长期记忆",
                    detail=_format_memory_write_trace(saved_memories),
                    session_id=session_id,
                )
            )

        self._emit_trace(
            ChatTraceEvent(
                kind="result",
                title="本轮完成",
                detail=_format_result_trace(final),
                session_id=session_id,
            )
        )

        merged_receipts = list(self._current_run_write_receipts)
        for receipt in write_receipts:
            if receipt not in self._current_run_seen_write_receipts:
                merged_receipts.append(receipt)
        display_text = _combine_receipt_texts(merged_receipts) or text

        return ChatResult(
            text=text,
            display_text=display_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=final.stop_reason,
            session_id=session_id or "",
            duration_ms=final.duration_ms,
            total_cost_usd=final.total_cost_usd,
        )

    def _emit_trace(self, event: ChatTraceEvent):
        handler = self._active_trace_handler
        if handler is None:
            return
        try:
            handler(event)
        except Exception as exc:
            print(f"[trace] handler failed: {exc}")

    def _guard_tool_use(
        self,
        tool_name: str,
        tool_use_id: str | None,
    ) -> str | None:
        guard = self._current_run_tool_guard
        if guard is None:
            return None
        denied_message = guard.observe(tool_name)
        if not denied_message:
            return None
        self._emit_trace(
            ChatTraceEvent(
                kind="guardrail",
                title=f"护栏拦下了 {tool_name}",
                detail=denied_message,
                session_id=self._last_session_id,
                tool_name=tool_name,
                tool_use_id=tool_use_id,
            )
        )
        return denied_message

    def _collect_write_receipts(
        self,
        message: AssistantMessage,
        tool_names_by_id: dict[str, str],
        write_receipts: list[str],
        seen_receipts: set[str],
    ):
        for block in message.content:
            if isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
                tool_names_by_id[block.id] = block.name
                continue

            if isinstance(block, ToolResultBlock):
                if block.is_error:
                    continue
                tool_name = tool_names_by_id.get(block.tool_use_id, "")
                payload = _tool_result_payload(block.content)
                receipt = format_write_tool_receipt(tool_name, payload or {})
                if receipt and receipt not in seen_receipts:
                    seen_receipts.add(receipt)
                    write_receipts.append(receipt)
                continue

            if isinstance(block, ServerToolResultBlock):
                tool_name = tool_names_by_id.get(block.tool_use_id, "")
                payload = _tool_result_payload(block.content)
                receipt = format_write_tool_receipt(tool_name, payload or {})
                if receipt and receipt not in seen_receipts:
                    seen_receipts.add(receipt)
                    write_receipts.append(receipt)

    def _emit_tool_payload_privacy_trace(
        self,
        payload: dict[str, object] | None,
        *,
        session_id: str | None,
        tool_use_id: str | None,
        builtin: bool = False,
    ):
        if not isinstance(payload, dict):
            return
        metadata = payload.get("_privacy")
        if not isinstance(metadata, dict):
            return
        detail = format_privacy_metadata_detail(metadata, context="tool")
        if not detail:
            return
        blocked = bool(metadata.get("blocked"))
        title = (
            "内置工具结果留在本机"
            if builtin and blocked
            else "内置工具结果已脱敏"
            if builtin
            else "工具结果留在本机"
            if blocked
            else "工具结果已脱敏"
        )
        self._emit_trace(
            ChatTraceEvent(
                kind="privacy",
                title=title,
                detail=detail,
                session_id=session_id,
                tool_use_id=tool_use_id,
            )
        )

    def _emit_assistant_trace(self, message: AssistantMessage):
        session_id = message.session_id or self._last_session_id
        if message.error:
            self._emit_trace(
                ChatTraceEvent(
                    kind="error",
                    title="女仆回复出错",
                    detail=message.error,
                    session_id=session_id,
                )
            )
        for block in message.content:
            if isinstance(block, TextBlock):
                text = block.text.strip()
                if not text:
                    continue
                self._emit_trace(
                    ChatTraceEvent(
                        kind="assistant_text",
                        title="女仆回复",
                        detail=_trim_trace_text(text),
                        session_id=session_id,
                    )
                )
                continue

            # Do not surface raw reasoning text; keep the trace to coarse,
            # user-facing step markers instead of chain-of-thought dumps.
            if isinstance(block, ThinkingBlock):
                self._emit_trace(
                    ChatTraceEvent(
                        kind="thinking",
                        title="正在思考",
                        detail="模型进入推理阶段。",
                        session_id=session_id,
                    )
                )
                continue

            if isinstance(block, ToolUseBlock):
                self._emit_trace(
                    ChatTraceEvent(
                        kind="tool_use",
                        title=f"调用工具 {block.name}",
                        detail=_trace_preview(block.input),
                        session_id=session_id,
                        tool_name=block.name,
                        tool_use_id=block.id,
                    )
                )
                continue

            if isinstance(block, ToolResultBlock):
                payload = _tool_result_payload(block.content)
                self._emit_tool_payload_privacy_trace(
                    payload,
                    session_id=session_id,
                    tool_use_id=block.tool_use_id,
                    builtin=False,
                )
                self._emit_trace(
                    ChatTraceEvent(
                        kind="tool_result",
                        title="工具报错" if block.is_error else "工具返回",
                        detail=_trace_preview(block.content),
                        session_id=session_id,
                        tool_use_id=block.tool_use_id,
                    )
                )
                continue

            if isinstance(block, ServerToolUseBlock):
                self._emit_trace(
                    ChatTraceEvent(
                        kind="tool_use",
                        title=f"调用内置工具 {block.name}",
                        detail=_trace_preview(block.input),
                        session_id=session_id,
                        tool_name=block.name,
                        tool_use_id=block.id,
                    )
                )
                continue

            if isinstance(block, ServerToolResultBlock):
                payload = _tool_result_payload(block.content)
                self._emit_tool_payload_privacy_trace(
                    payload,
                    session_id=session_id,
                    tool_use_id=block.tool_use_id,
                    builtin=True,
                )
                self._emit_trace(
                    ChatTraceEvent(
                        kind="tool_result",
                        title="内置工具返回",
                        detail=_trace_preview(block.content),
                        session_id=session_id,
                        tool_use_id=block.tool_use_id,
                    )
                )

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict,
        context: ToolPermissionContext,
    ):
        denied_message = self._guard_tool_use(tool_name, context.tool_use_id)
        if denied_message:
            return PermissionResultDeny(message=denied_message)

        if tool_name == "AskUserQuestion":
            request = _build_ask_user_question_request(input_data, context)
            if request is None:
                self._emit_trace(
                    ChatTraceEvent(
                        kind="question_answer",
                        title="澄清问题格式不对",
                        detail="AskUserQuestion 的输入格式不符合预期。",
                        session_id=self._last_session_id,
                        tool_name=tool_name,
                        tool_use_id=context.tool_use_id,
                    )
                )
                return PermissionResultDeny(
                    message="收到了格式不对的澄清问题。"
                )

            self._emit_trace(
                ChatTraceEvent(
                    kind="question_request",
                    title=request.title or "女仆想先补一句",
                    detail=_format_question_trace(request),
                    session_id=self._last_session_id,
                    tool_name=tool_name,
                    tool_use_id=context.tool_use_id,
                )
            )

            with _question_lock:
                handler = _question_handler

            if handler is None:
                self._emit_trace(
                    ChatTraceEvent(
                        kind="question_answer",
                        title="当前没有澄清弹窗",
                        detail="AskUserQuestion 被拒绝了。",
                        session_id=self._last_session_id,
                        tool_name=tool_name,
                        tool_use_id=context.tool_use_id,
                    )
                )
                return PermissionResultDeny(
                    message="当前没有澄清问题弹窗。"
                )

            decision = await asyncio.to_thread(handler, request)
            if decision.cancelled:
                self._emit_trace(
                    ChatTraceEvent(
                        kind="question_answer",
                        title="主人取消了澄清",
                        detail=decision.message or "",
                        session_id=self._last_session_id,
                        tool_name=tool_name,
                        tool_use_id=context.tool_use_id,
                    )
                )
                return PermissionResultDeny(
                    message=decision.message or "主人取消了这次澄清。"
                )

            updated_input = dict(input_data)
            updated_input["answers"] = _normalize_ask_user_question_answers(
                request,
                decision.answers,
            )
            self._emit_trace(
                ChatTraceEvent(
                    kind="question_answer",
                    title="收到主人的补充",
                    detail=_trace_preview(updated_input["answers"]),
                    session_id=self._last_session_id,
                    tool_name=tool_name,
                    tool_use_id=context.tool_use_id,
                )
            )
            return PermissionResultAllow(updated_input=updated_input)

        preview_spec = _permission_preview_spec(tool_name)
        require_fresh_confirmation = preview_spec is not None
        with self._lock:
            remembered = (
                (
                    preview_spec is None
                    or bool(preview_spec.get("allow_remember"))
                )
                and tool_name in self._session_allowed_tools
            )
        if remembered:
            self._emit_trace(
                ChatTraceEvent(
                    kind="permission_decision",
                    title=f"沿用已记住的授权 {tool_name}",
                    detail="本次会话里这个工具已经被允许过了。",
                    session_id=self._last_session_id,
                    tool_name=tool_name,
                    tool_use_id=context.tool_use_id,
                )
            )
            return PermissionResultAllow()

        preview_text = ""
        preview_data: dict[str, object] | None = None
        allow_remember = not require_fresh_confirmation
        confirm_label = None
        guard_snapshot: dict[str, int | str] = {}
        guard = self._current_run_tool_guard
        if guard is not None:
            guard_snapshot = guard.quota_snapshot(tool_name)
        if preview_spec is not None:
            try:
                preview_data = await asyncio.to_thread(
                    preview_spec["preview_fn"],
                    input_data,
                )
                preview_text = preview_spec["format_fn"](preview_data)
                confirm_label = preview_spec["confirm_label"]
                allow_remember = bool(preview_spec["allow_remember"])
            except Exception as exc:
                detail = f"操作前无法预览 {tool_name}: {exc}"
                self._emit_trace(
                    ChatTraceEvent(
                        kind="permission_decision",
                        title=f"无法确认 {tool_name}",
                        detail=detail,
                        session_id=self._last_session_id,
                        tool_name=tool_name,
                        tool_use_id=context.tool_use_id,
                    )
                )
                return PermissionResultDeny(message=detail)

        request = PermissionRequest(
            tool_name=tool_name,
            input_data=input_data,
            tool_use_id=context.tool_use_id,
            title=context.title,
            display_name=context.display_name,
            description=context.description,
            blocked_path=context.blocked_path,
            decision_reason=context.decision_reason,
            preview_text=preview_text,
            preview_data=preview_data,
            allow_remember=allow_remember,
            confirm_label=confirm_label,
            risk_level=str(guard_snapshot.get("risk_level") or ""),
            risk_label=str(guard_snapshot.get("risk_label") or ""),
            risk_limit=max(0, int(guard_snapshot.get("risk_limit") or 0)),
            risk_used=max(0, int(guard_snapshot.get("risk_used") or 0)),
            risk_remaining=max(0, int(guard_snapshot.get("risk_remaining") or 0)),
            total_limit=max(0, int(guard_snapshot.get("total_limit") or 0)),
            total_used=max(0, int(guard_snapshot.get("total_used") or 0)),
            total_remaining=max(0, int(guard_snapshot.get("total_remaining") or 0)),
        )
        self._emit_trace(
            ChatTraceEvent(
                kind="permission_request",
                title=request.title or f"请求权限 {tool_name}",
                detail=_format_permission_trace(request),
                session_id=self._last_session_id,
                tool_name=tool_name,
                tool_use_id=context.tool_use_id,
            )
        )

        with _permission_lock:
            handler = _permission_handler

        if handler is None:
            self._emit_trace(
                ChatTraceEvent(
                    kind="permission_decision",
                    title=f"没有权限弹窗，拒绝 {tool_name}",
                    detail="当前没有权限确认界面。",
                    session_id=self._last_session_id,
                    tool_name=tool_name,
                    tool_use_id=context.tool_use_id,
                )
            )
            return PermissionResultDeny(
                message="当前没有权限确认界面。"
            )

        decision = await asyncio.to_thread(handler, request)
        if decision.allow:
            remember_tool = bool(decision.remember_tool and request.allow_remember)
            if remember_tool:
                with self._lock:
                    self._session_allowed_tools.add(tool_name)
            receipt = format_write_tool_receipt(tool_name, preview_data or {})
            if (
                receipt
                and receipt not in self._current_run_seen_write_receipts
            ):
                self._current_run_seen_write_receipts.add(receipt)
                self._current_run_write_receipts.append(receipt)
            detail = "主人刚刚点了允许。"
            if remember_tool:
                detail += "\n本次会话会记住这项授权。"
            self._emit_trace(
                ChatTraceEvent(
                    kind="permission_decision",
                    title=f"已允许 {tool_name}",
                    detail=detail,
                    session_id=self._last_session_id,
                    tool_name=tool_name,
                    tool_use_id=context.tool_use_id,
                )
            )
            return PermissionResultAllow()
        self._emit_trace(
            ChatTraceEvent(
                kind="permission_decision",
                title=f"已拒绝 {tool_name}",
                detail=decision.message or "主人拒绝了这次操作。",
                session_id=self._last_session_id,
                tool_name=tool_name,
                tool_use_id=context.tool_use_id,
            )
        )
        return PermissionResultDeny(
            message=decision.message or "主人拒绝了这次操作。"
        )


_SESSION = _AgentSession()


def ask_maid(
    prompt: str,
    trace_handler: TraceHandler | None = None,
) -> ChatResult:
    return _SESSION.ask(prompt, trace_handler=trace_handler)


def shutdown_maid_session():
    _SESSION.close()


def reset_maid_session():
    """Stop the running session and forget the resume id.

    Used when the active provider / model changes so the next message starts a
    fresh session instead of resuming a transcript built on another backend.
    """
    _SESSION.close()
    with _SESSION._lock:
        _SESSION._last_session_id = None


def set_permission_handler(handler: PermissionHandler | None):
    global _permission_handler
    with _permission_lock:
        _permission_handler = handler


def set_ask_user_question_handler(handler: AskUserQuestionHandler | None):
    global _question_handler
    with _question_lock:
        _question_handler = handler


def get_remembered_tool_permissions() -> list[str]:
    return _SESSION.remembered_tool_names()


def clear_remembered_tool_permissions() -> int:
    return _SESSION.clear_remembered_tools()


def get_resumable_session_id() -> str | None:
    return _SESSION.resumable_session_id()


def clear_resumable_session() -> str | None:
    return _SESSION.clear_resumable_session()


def get_long_term_memory() -> list[str]:
    return _SESSION.long_term_memories()


def get_long_term_memory_items() -> list[dict[str, object]]:
    return _SESSION.long_term_memory_items()


def create_long_term_memory_item(text: str) -> dict[str, object] | None:
    return _SESSION.create_long_term_memory_item(text)


def update_long_term_memory_item(
    key: str,
    text: str,
) -> dict[str, object] | None:
    return _SESSION.update_long_term_memory_item(key, text)


def delete_long_term_memory_item(key: str) -> dict[str, object] | None:
    return _SESSION.delete_long_term_memory_item(key)


def get_budget_guard_snapshot() -> dict[str, object]:
    return _SESSION.budget_guard_snapshot()


def record_budget_activity():
    _SESSION.record_budget_activity()


def note_budget_suspend():
    _SESSION.note_budget_suspend()


def note_budget_resume():
    _SESSION.note_budget_resume()


def consume_budget_reset_notice() -> str:
    return _SESSION.consume_budget_reset_notice()
