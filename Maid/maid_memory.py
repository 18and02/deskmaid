"""Local long-term memory store for the desktop maid."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from dataclasses import asdict, dataclass, field
from hashlib import sha1
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from maid_paths import default_state_path

MEMORY_STATE_ENV_VAR = "MAID_MEMORY_STATE_PATH"
DEFAULT_MEMORY_STATE_PATH = default_state_path(".maid_memory.json")
MEMORY_KEY_ENV_VAR = "MAID_MEMORY_KEY"
MEMORY_KEYCHAIN_MODE_ENV_VAR = "MAID_MEMORY_KEYCHAIN_MODE"
MEMORY_KEYCHAIN_SERVICE = "com.regulus.deskmaid.long_term_memory"
MAX_MEMORY_ITEMS = 200
MAX_RECALL_ITEMS = 6
_RECENT_FORGET_WINDOW_S = 20 * 60
_NOTE_MEMORY_TTL_S = 30 * 24 * 60 * 60
_FACT_MEMORY_TTL_S = 90 * 24 * 60 * 60
_PREFERENCE_MEMORY_TTL_S = 180 * 24 * 60 * 60

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?;\n]+")
_NORMALIZE_RE = re.compile(r"[\s\u3000`~!@#$%^&*()+=\-[\]{}\\|;:'\",.<>/?，。！？；：、“”‘’（）【】《》]+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{2,}")
_REQUEST_VERB_RE = re.compile(
    r"(?:帮|给|替|解释|说明|告诉|写|看看|找|查|分析|打开|切到|生成|做|回答|回复|总结)"
)
_QUESTION_RE = re.compile(
    r"(?:什么|多少|几|哪|哪个|哪种|哪位|谁|怎么|怎样|咋|为何|为什么|是否|是不是|吗|嘛|呢)$"
)
_MEMORY_QUERY_RE = re.compile(
    r"(?:记得|记住|长期记忆|偏好|喜欢|不喜欢|讨厌|名字|叫我|口令|习惯|设置|默认|水果|颜色)"
)
_REMEMBER_RE = re.compile(
    r"^(?:请|麻烦你|帮我)?记住(?:一下|这件事|这个事实|这个口令|这个偏好|这句原样内容)?[：:，,\s]*(.+)$"
)
_FAVORITE_RE = re.compile(r"^我最喜欢的(?P<topic>[^，,。！？!?]{1,20})是(?P<value>[^，,。！？!?]{1,60})$")
_COMMON_RE = re.compile(r"^我最常用的(?P<topic>[^，,。！？!?]{1,20})是(?P<value>[^，,。！？!?]{1,60})$")
_DISLIKE_RE = re.compile(r"^我(?:不喜欢|讨厌)(?P<value>[^，,。！？!?]{1,40})$")
_LIKE_RE = re.compile(r"^我喜欢(?P<value>[^，,。！？!?]{1,40})$")
_CALL_ME_RE = re.compile(r"^(?:以后|之后)?(?:都|就)?(?:请)?叫我(?P<value>[^，,。！？!?]{1,20})$")
_NAME_RE = re.compile(r"^(?:我的名字是|我叫)(?P<value>[^，,。！？!?]{1,20})$")
_LANGUAGE_RE = re.compile(
    r"^(?:以后|之后)(?:都|就)?(?:默认)?用(?P<value>中文|英文)(?:回复|回答|跟我说话)?$"
)
_GENERIC_FACT_RE = re.compile(r"^(?P<subject>[^，,。！？!?]{1,24})是(?P<value>[^，,。！？!?]{1,80})$")
_FORGET_VERB_RE = re.compile(
    r"(?:忘掉|忘了|忘记|删掉(?!阶段)|删除(?!阶段)|清掉|清除|抹掉|别记(?:着)?|不要记(?:着)?)"
)
_FORGET_RECENT_RE = re.compile(r"(?:刚才|刚刚|上条|上一条|这条|这件事|那件事|刚刚那件事)")
_FORGET_FAVORITE_RE = re.compile(r"(?:最喜欢的(?P<topic>[^，,。！？!?]{1,20}))")
_FORGET_COMMON_RE = re.compile(r"(?:最常用的(?P<topic>[^，,。！？!?]{1,20}))")
_FORGET_ABOUT_RE = re.compile(r"(?:关于|有关)(?P<target>[^，,。！？!?]{1,24})")
_FORGET_QUOTED_TARGET_RE = re.compile(r"[\"“](?P<target>[^\"”]{1,40})[\"”]")
_STORED_FAVORITE_RE = re.compile(r"^主人最喜欢的(?P<topic>[^，,。！？!?]{1,20})是(?P<value>[^，,。！？!?]{1,60})$")
_STORED_COMMON_RE = re.compile(r"^主人最常用的(?P<topic>[^，,。！？!?]{1,20})是(?P<value>[^，,。！？!?]{1,60})$")
_STORED_CALL_ME_RE = re.compile(r"^主人希望被叫作(?P<value>[^，,。！？!?]{1,20})$")
_STORED_NAME_RE = re.compile(r"^主人的名字是(?P<value>[^，,。！？!?]{1,20})$")
_STORED_LANGUAGE_RE = re.compile(r"^主人偏好我用(?P<value>中文|英文)回复$")
_STORED_DISLIKE_RE = re.compile(r"^主人不喜欢(?P<value>[^，,。！？!?]{1,40})$")
_STORED_LIKE_RE = re.compile(r"^主人喜欢(?P<value>[^，,。！？!?]{1,40})$")
_TEXT_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,12}")


@dataclass(frozen=True)
class MemoryItem:
    key: str
    text: str
    keywords: list[str]
    created_at: float
    updated_at: float
    expires_at: float | None = None
    last_used_at: float | None = None
    source: str = ""


@dataclass(frozen=True)
class MemoryCandidate:
    key: str
    text: str
    keywords: list[str]
    source: str = ""


@dataclass(frozen=True)
class MemoryWriteOutcome:
    item: MemoryItem
    action: str = "created"
    replaced: list[MemoryItem] = field(default_factory=list)
    pruned_expired_count: int = 0


@dataclass(frozen=True)
class ForgetOutcome:
    handled: bool = False
    removed: list[MemoryItem] = field(default_factory=list)
    message: str = ""
    mode: str = ""
    target: str = ""
    ambiguous_matches: list[MemoryItem] = field(default_factory=list)
    pruned_expired_count: int = 0


def _memory_state_path() -> Path:
    override = os.environ.get(MEMORY_STATE_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_MEMORY_STATE_PATH


def _normalize_text(text: str) -> str:
    return _NORMALIZE_RE.sub("", text).lower()


def _clip(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _stable_key(prefix: str, value: str) -> str:
    digest = sha1(_normalize_text(value).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _clean_value(text: str) -> str:
    value = text.strip().strip("\"'“”‘’")
    value = value.strip()
    return value


def _clean_fact_text(text: str) -> str:
    value = text.strip()
    value = re.split(r"(?:只回复|只要回复|回复|回答|不要|别|并且|然后|谢谢)", value, maxsplit=1)[0]
    value = value.strip(" \t\r\n，,；;：:")
    value = value.strip("\"'“”‘’")
    value = value.strip()
    if not value:
        return ""
    if value[-1] not in "。！？!?":
        value += "。"
    return value


def _sentence_chunks(text: str) -> list[str]:
    chunks = []
    for piece in _SENTENCE_SPLIT_RE.split(text):
        piece = piece.strip()
        if piece:
            chunks.append(piece)
    return chunks


def _keyword_list(*values: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = _clean_value(value)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _derive_keywords_from_memory_text(text: str) -> list[str]:
    sentence = _clean_fact_text(text).rstrip("。！？!?")
    if not sentence:
        return []

    match = _STORED_FAVORITE_RE.match(sentence)
    if match:
        return _keyword_list(
            match.group("topic"),
            match.group("value"),
            "最喜欢",
        )

    match = _STORED_COMMON_RE.match(sentence)
    if match:
        return _keyword_list(
            match.group("topic"),
            match.group("value"),
            "最常用",
        )

    match = _STORED_CALL_ME_RE.match(sentence)
    if match:
        return _keyword_list(match.group("value"), "称呼", "叫作")

    match = _STORED_NAME_RE.match(sentence)
    if match:
        return _keyword_list(match.group("value"), "名字", "姓名")

    match = _STORED_LANGUAGE_RE.match(sentence)
    if match:
        return _keyword_list(match.group("value"), "回复", "语言")

    match = _STORED_DISLIKE_RE.match(sentence)
    if match:
        return _keyword_list(match.group("value"), "不喜欢", "讨厌")

    match = _STORED_LIKE_RE.match(sentence)
    if match:
        return _keyword_list(match.group("value"), "喜欢")

    match = _GENERIC_FACT_RE.match(sentence)
    if match:
        return _keyword_list(match.group("subject"), match.group("value"))

    return _keyword_list(*_TEXT_TOKEN_RE.findall(sentence)[:10])


def _manual_memory_key(text: str) -> str:
    sentence = _clean_fact_text(text).rstrip("。！？!?")
    if not sentence:
        return ""

    match = _STORED_FAVORITE_RE.match(sentence)
    if match:
        return _stable_key("favorite", _clean_value(match.group("topic")))

    match = _STORED_COMMON_RE.match(sentence)
    if match:
        return _stable_key("common", _clean_value(match.group("topic")))

    if _STORED_CALL_ME_RE.match(sentence):
        return "preferred_name"

    if _STORED_NAME_RE.match(sentence):
        return "name"

    if _STORED_LANGUAGE_RE.match(sentence):
        return "reply_language"

    match = _STORED_DISLIKE_RE.match(sentence)
    if match:
        return _stable_key("dislike", _clean_value(match.group("value")))

    match = _STORED_LIKE_RE.match(sentence)
    if match:
        return _stable_key("like", _clean_value(match.group("value")))

    match = _GENERIC_FACT_RE.match(sentence)
    if match:
        return _stable_key("fact", _clean_value(match.group("subject")))

    return _stable_key("note", sentence)


def _manual_memory_candidate(text: str) -> MemoryCandidate | None:
    normalized = _clean_fact_text(text)
    if not normalized:
        return None

    key = _manual_memory_key(normalized)
    if not key:
        return None

    return MemoryCandidate(
        key=key,
        text=normalized,
        keywords=_derive_keywords_from_memory_text(normalized),
        source="manual",
    )


def _memory_ttl_seconds(key: str) -> float | None:
    key = str(key or "").strip()
    if key in {"preferred_name", "name", "reply_language"}:
        return None
    if key.startswith("favorite:") or key.startswith("common:"):
        return None
    if key.startswith("like:") or key.startswith("dislike:"):
        return _PREFERENCE_MEMORY_TTL_S
    if key.startswith("fact:"):
        return _FACT_MEMORY_TTL_S
    return _NOTE_MEMORY_TTL_S


def _memory_expires_at(key: str, now: float) -> float | None:
    ttl_s = _memory_ttl_seconds(key)
    if ttl_s is None:
        return None
    return now + ttl_s


def memory_kind_for_key(key: str) -> str:
    key = str(key or "").strip()
    if key in {"preferred_name", "name", "reply_language"}:
        return "identity"
    if key.startswith("favorite:") or key.startswith("common:"):
        return "preference"
    if key.startswith("like:") or key.startswith("dislike:"):
        return "preference"
    if key.startswith("fact:"):
        return "fact"
    return "note"


def memory_expiry_policy_key(key: str) -> str:
    ttl_s = _memory_ttl_seconds(key)
    if ttl_s is None:
        return "forever"
    days = int(round(float(ttl_s) / (24.0 * 60.0 * 60.0)))
    return f"{days}d"


def memory_expiry_days(key: str) -> int | None:
    policy_key = memory_expiry_policy_key(key)
    if policy_key == "forever":
        return None
    try:
        return int(policy_key.rstrip("d"))
    except ValueError:
        return None


def memory_reason_key(item: MemoryItem) -> str:
    source = str(item.source or "").strip()
    key = str(item.key or "").strip()
    if source == "manual":
        return "manual"
    if source == "legacy":
        return "legacy_import"
    if _REMEMBER_RE.match(source):
        return "explicit_instruction"
    if key == "preferred_name":
        return "address_preference"
    if key == "name":
        return "identity_statement"
    if key == "reply_language":
        return "reply_language_preference"
    if memory_kind_for_key(key) == "preference":
        return "stated_preference"
    if memory_kind_for_key(key) == "fact":
        return "stated_fact"
    if source:
        return "conversation_note"
    return "conversation_memory"


def memory_conflict_policy_key(key: str) -> str:
    key = str(key or "").strip()
    if key.startswith("like:") or key.startswith("dislike:"):
        return "opposite_preference"
    if (
        key in {"preferred_name", "name", "reply_language"}
        or key.startswith("favorite:")
        or key.startswith("common:")
        or key.startswith("fact:")
    ):
        return "same_topic"
    return "parallel_note"


def memory_item_metadata(item: MemoryItem) -> dict[str, object]:
    return {
        "memory_kind": memory_kind_for_key(item.key),
        "reason_key": memory_reason_key(item),
        "expiry_policy_key": memory_expiry_policy_key(item.key),
        "expiry_days": memory_expiry_days(item.key),
        "conflict_policy_key": memory_conflict_policy_key(item.key),
    }


def _is_expired(item: MemoryItem, now: float | None = None) -> bool:
    expires_at = item.expires_at
    if expires_at is None:
        return False
    return float(expires_at) <= float(now or time.time())


def _conflicting_memory_keys(candidate: MemoryCandidate) -> set[str]:
    sentence = _clean_fact_text(candidate.text).rstrip("。！？!?")
    if not sentence:
        return set()

    match = _STORED_DISLIKE_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        return {_stable_key("like", value)}

    match = _STORED_LIKE_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        return {_stable_key("dislike", value)}

    return set()


def _forget_target_from_prompt(prompt: str) -> dict[str, str] | None:
    for sentence in _sentence_chunks(prompt):
        sentence = sentence.strip()
        if not sentence or not _FORGET_VERB_RE.search(sentence):
            continue

        if _FORGET_RECENT_RE.search(sentence):
            return {"mode": "recent"}

        match = _FORGET_FAVORITE_RE.search(sentence)
        if match:
            topic = _clean_value(_FORGET_VERB_RE.sub(" ", match.group("topic")))
            if topic:
                return {"mode": "key", "key": _stable_key("favorite", topic), "topic": topic}

        match = _FORGET_COMMON_RE.search(sentence)
        if match:
            topic = _clean_value(_FORGET_VERB_RE.sub(" ", match.group("topic")))
            if topic:
                return {"mode": "key", "key": _stable_key("common", topic), "topic": topic}

        if "叫我" in sentence or "称呼" in sentence:
            return {"mode": "key", "key": "preferred_name", "topic": "称呼"}
        if "名字" in sentence:
            return {"mode": "key", "key": "name", "topic": "名字"}
        if "回复" in sentence or "语言" in sentence:
            if "中文" in sentence or "英文" in sentence or "语言" in sentence:
                return {"mode": "key", "key": "reply_language", "topic": "回复偏好"}

        match = _FORGET_ABOUT_RE.search(sentence)
        if match:
            target = _clean_value(match.group("target"))
            if target:
                return {"mode": "search", "target": target}

        match = _FORGET_QUOTED_TARGET_RE.search(sentence)
        if match:
            target = _clean_value(match.group("target"))
            if target:
                return {"mode": "search", "target": target}

        cleaned = _FORGET_VERB_RE.sub(" ", sentence)
        cleaned = re.sub(r"(?:长期记忆|这条|那条|一下|一下子|给我|帮我|请你|请|麻烦你|麻烦)", " ", cleaned)
        cleaned = _clean_value(cleaned.strip("，,。！？!?：: "))
        if cleaned:
            return {"mode": "search", "target": cleaned}

    return None


def _looks_like_request(value: str) -> bool:
    if _REQUEST_VERB_RE.search(value):
        return True
    return False


def _looks_like_question(value: str) -> bool:
    return bool(_QUESTION_RE.search(value.strip()))


def _extract_structured_fact(text: str, *, explicit: bool) -> list[MemoryCandidate]:
    sentence = _clean_fact_text(text).rstrip("。！？!?")
    if not sentence:
        return []

    match = _FAVORITE_RE.match(sentence)
    if match:
        topic = _clean_value(match.group("topic"))
        value = _clean_value(match.group("value"))
        if _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key=_stable_key("favorite", topic),
                text=f"主人最喜欢的{topic}是{value}。",
                keywords=_keyword_list(topic, value, "最喜欢"),
                source=sentence,
            )
        ]

    match = _COMMON_RE.match(sentence)
    if match:
        topic = _clean_value(match.group("topic"))
        value = _clean_value(match.group("value"))
        if _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key=_stable_key("common", topic),
                text=f"主人最常用的{topic}是{value}。",
                keywords=_keyword_list(topic, value, "最常用"),
                source=sentence,
            )
        ]

    match = _CALL_ME_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key="preferred_name",
                text=f"主人希望被叫作{value}。",
                keywords=_keyword_list(value, "称呼", "叫我"),
                source=sentence,
            )
        ]

    match = _NAME_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key="name",
                text=f"主人的名字是{value}。",
                keywords=_keyword_list(value, "名字", "姓名"),
                source=sentence,
            )
        ]

    match = _LANGUAGE_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        return [
            MemoryCandidate(
                key="reply_language",
                text=f"主人偏好我用{value}回复。",
                keywords=_keyword_list(value, "回复", "语言"),
                source=sentence,
            )
        ]

    match = _DISLIKE_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if _looks_like_request(value) or _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key=_stable_key("dislike", value),
                text=f"主人不喜欢{value}。",
                keywords=_keyword_list(value, "不喜欢", "讨厌"),
                source=sentence,
            )
        ]

    match = _LIKE_RE.match(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if _looks_like_request(value) or _looks_like_question(value):
            return []
        return [
            MemoryCandidate(
                key=_stable_key("like", value),
                text=f"主人喜欢{value}。",
                keywords=_keyword_list(value, "喜欢"),
                source=sentence,
            )
        ]

    if explicit:
        match = _GENERIC_FACT_RE.match(sentence)
        if match:
            subject = _clean_value(match.group("subject"))
            value = _clean_value(match.group("value"))
            if _looks_like_question(subject) or _looks_like_question(value):
                return []
            return [
                MemoryCandidate(
                    key=_stable_key("fact", subject),
                    text=f"{subject}是{value}。",
                    keywords=_keyword_list(subject, value),
                    source=sentence,
                )
            ]

    return []


def extract_memory_candidates(user_prompt: str, assistant_text: str = "") -> list[MemoryCandidate]:
    del assistant_text  # reserved for future richer extraction
    candidates: list[MemoryCandidate] = []

    for sentence in _sentence_chunks(user_prompt):
        match = _REMEMBER_RE.match(sentence)
        if match:
            remembered = _clean_fact_text(match.group(1))
            if remembered:
                inner = _extract_structured_fact(remembered, explicit=True)
                if inner:
                    for candidate in inner:
                        candidates.append(
                            MemoryCandidate(
                                key=candidate.key,
                                text=candidate.text,
                                keywords=list(candidate.keywords),
                                source=sentence,
                            )
                        )
                else:
                    candidates.append(
                        MemoryCandidate(
                            key=_stable_key("note", remembered),
                            text=remembered,
                            keywords=_keyword_list(remembered),
                            source=sentence,
                        )
                    )
            continue

        candidates.extend(_extract_structured_fact(sentence, explicit=False))

    deduped: list[MemoryCandidate] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        if not candidate.text or candidate.key in seen_keys:
            continue
        seen_keys.add(candidate.key)
        deduped.append(candidate)
    return deduped


def format_memory_prompt(memories: list[MemoryItem]) -> str:
    if not memories:
        return ""
    lines = [
        "# 长期记忆",
        "- 下面这些事实来自更早的对话，只在相关时自然使用，不要逐条复述。",
        "- 如果主人在当前这句话里明确更正了旧信息，以当前这句话为准。",
    ]
    for memory in memories:
        lines.append(f"- {memory.text}")
    return "\n".join(lines)


def _memory_payload(items: list[MemoryItem]) -> dict[str, object]:
    return {
        "version": 1,
        "memories": [asdict(item) for item in items],
    }


def _serialize_legacy_payload(items: list[MemoryItem]) -> str:
    return json.dumps(_memory_payload(items), ensure_ascii=True, indent=2) + "\n"


def _memory_key_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.key")


def _write_private_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _normalize_fernet_key(value: str) -> bytes:
    key = str(value or "").strip().encode("ascii")
    Fernet(key)
    return key


def _keychain_mode() -> str:
    return str(os.environ.get(MEMORY_KEYCHAIN_MODE_ENV_VAR) or "").strip().lower()


def _should_use_keychain(path: Path) -> bool:
    if sys.platform != "darwin":
        return False

    mode = _keychain_mode()
    if mode in {"0", "false", "off", "no", "sidecar"}:
        return False
    if mode in {"1", "true", "on", "yes", "keychain"}:
        return True

    try:
        return path.expanduser().resolve() == DEFAULT_MEMORY_STATE_PATH.resolve()
    except OSError:
        return path.expanduser() == DEFAULT_MEMORY_STATE_PATH


def _memory_keychain_account(path: Path) -> str:
    digest = sha1(str(path.expanduser()).encode("utf-8")).hexdigest()[:16]
    return f"store:{digest}"


def _run_security_command(args: list[str]) -> str:
    proc = subprocess.run(
        ["security", *args],
        capture_output=True,
        text=True,
        timeout=8.0,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"security exited with code {proc.returncode}")
    return (proc.stdout or "").strip()


def _load_key_from_keychain(path: Path) -> bytes | None:
    service = MEMORY_KEYCHAIN_SERVICE
    account = _memory_keychain_account(path)
    try:
        raw_key = _run_security_command(
            ["find-generic-password", "-w", "-s", service, "-a", account]
        )
    except Exception:
        return None
    if not raw_key:
        return None
    try:
        return _normalize_fernet_key(raw_key)
    except Exception as exc:
        print(f"[memory] invalid keychain key for {path}: {exc}")
        return None


def _store_key_in_keychain(path: Path, key: bytes) -> bool:
    service = MEMORY_KEYCHAIN_SERVICE
    account = _memory_keychain_account(path)
    try:
        _run_security_command(
            [
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                key.decode("ascii"),
            ]
        )
    except Exception as exc:
        print(f"[memory] failed to write keychain key for {path}: {exc}")
        return False
    return True


def _load_or_create_sidecar_key(path: Path) -> tuple[bytes, str]:
    key_path = _memory_key_path(path)
    try:
        raw_key = key_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raw_key = ""
    except OSError as exc:
        print(f"[memory] failed to read key file {key_path}: {exc}")
        raw_key = ""

    if raw_key:
        try:
            return _normalize_fernet_key(raw_key), "sidecar"
        except Exception as exc:
            print(f"[memory] invalid sidecar key {key_path}: {exc}")

    key = Fernet.generate_key()
    try:
        _write_private_text(key_path, key.decode("ascii") + "\n")
    except OSError as exc:
        print(f"[memory] failed to write key file {key_path}: {exc}")
    return key, "sidecar"


def _resolve_memory_key(path: Path) -> tuple[bytes, str]:
    override = str(os.environ.get(MEMORY_KEY_ENV_VAR) or "").strip()
    if override:
        return _normalize_fernet_key(override), "env"

    if _should_use_keychain(path):
        key = _load_key_from_keychain(path)
        if key is not None:
            return key, "keychain"
        created = Fernet.generate_key()
        if _store_key_in_keychain(path, created):
            return created, "keychain"

    return _load_or_create_sidecar_key(path)


def _serialize(items: list[MemoryItem], path: Path) -> str:
    payload = _serialize_legacy_payload(items).encode("utf-8")
    key, key_source = _resolve_memory_key(path)
    token = Fernet(key).encrypt(payload).decode("ascii")
    payload = {
        "version": 2,
        "format": "fernet",
        "key_source": key_source,
        "ciphertext": token,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2) + "\n"


def _parse_memory_items(payload: dict[str, object]) -> list[MemoryItem]:
    raw_items = payload.get("memories")
    if not isinstance(raw_items, list):
        return []

    items: list[MemoryItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            item = MemoryItem(
                key=str(raw_item["key"]),
                text=str(raw_item["text"]),
                keywords=[
                    str(keyword).strip()
                    for keyword in raw_item.get("keywords", [])
                    if str(keyword).strip()
                ],
                created_at=float(raw_item.get("created_at") or time.time()),
                updated_at=float(raw_item.get("updated_at") or time.time()),
                expires_at=(
                    float(raw_item["expires_at"])
                    if raw_item.get("expires_at") is not None
                    else None
                ),
                last_used_at=(
                    float(raw_item["last_used_at"])
                    if raw_item.get("last_used_at") is not None
                    else None
                ),
                source=str(raw_item.get("source") or ""),
            )
        except Exception:
            continue
        if not item.key or not item.text:
            continue
        items.append(item)
    return items[:MAX_MEMORY_ITEMS]


def _load_items(path: Path) -> tuple[list[MemoryItem], bool]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], True
    except OSError as exc:
        print(f"[memory] failed to read {path}: {exc}")
        return [], True

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[memory] failed to parse {path}: {exc}")
        return [], True

    if not isinstance(payload, dict):
        return [], True

    if str(payload.get("format") or "").strip() == "fernet":
        token = str(payload.get("ciphertext") or "").strip()
        if not token:
            return [], True
        try:
            key, _key_source = _resolve_memory_key(path)
            decrypted = Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
            inner_payload = json.loads(decrypted)
        except InvalidToken:
            print(f"[memory] failed to decrypt {path}: invalid key or ciphertext")
            return [], True
        except Exception as exc:
            print(f"[memory] failed to decrypt {path}: {exc}")
            return [], True
        if not isinstance(inner_payload, dict):
            return [], True
        return _parse_memory_items(inner_payload), True

    return _parse_memory_items(payload), False


def _dedupe_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    deduped: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.key in seen:
            continue
        seen.add(item.key)
        deduped.append(item)
    return deduped


class LongTermMemoryStore:
    def __init__(self, path: Path | None = None):
        self._path = path or _memory_state_path()
        self._lock = threading.Lock()
        self._items, encrypted = _load_items(self._path)
        with self._lock:
            save_after_load = False
            if self._items:
                save_after_load = self._hydrate_expirations_locked(time.time()) or save_after_load
                save_after_load = bool(self._prune_expired_locked(time.time())) or save_after_load
            if self._items and not encrypted:
                save_after_load = True
            if save_after_load:
                self._save_locked()

    def _hydrate_expirations_locked(self, now: float) -> bool:
        changed = False
        hydrated: list[MemoryItem] = []
        for item in self._items:
            expires_at = item.expires_at
            if expires_at is None:
                expires_at = _memory_expires_at(item.key, item.updated_at or now)
                if expires_at != item.expires_at:
                    changed = True
            hydrated.append(
                MemoryItem(
                    key=item.key,
                    text=item.text,
                    keywords=list(item.keywords),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    expires_at=expires_at,
                    last_used_at=item.last_used_at,
                    source=item.source,
                )
            )
        if changed:
            self._items = hydrated
        return changed

    def _prune_expired_locked(self, now: float) -> int:
        kept = [item for item in self._items if not _is_expired(item, now)]
        removed = len(self._items) - len(kept)
        if removed <= 0:
            return 0
        self._items = kept
        return removed

    def _save_locked(self):
        if not self._items:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"[memory] failed to remove {self._path}: {exc}")
            return

        tmp_path = self._path.with_name(f"{self._path.name}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(_serialize(self._items, self._path), encoding="utf-8")
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            tmp_path.replace(self._path)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            print(f"[memory] failed to write {self._path}: {exc}")
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def entries(self) -> list[MemoryItem]:
        with self._lock:
            if self._prune_expired_locked(time.time()):
                self._save_locked()
            return list(self._items)

    def count(self) -> int:
        with self._lock:
            if self._prune_expired_locked(time.time()):
                self._save_locked()
            return len(self._items)

    def _upsert_candidate_locked(
        self,
        candidate: MemoryCandidate,
        now: float,
        old_key: str | None = None,
    ) -> MemoryItem:
        old_item = None
        if old_key:
            filtered_items: list[MemoryItem] = []
            for item in self._items:
                if item.key == old_key and old_item is None:
                    old_item = item
                    continue
                filtered_items.append(item)
            self._items = filtered_items

        existing_index = None
        existing_item = None
        for index, item in enumerate(self._items):
            if item.key != candidate.key:
                continue
            existing_index = index
            existing_item = item
            break

        if existing_item is not None:
            created_at = existing_item.created_at
            if old_item is not None:
                created_at = min(created_at, old_item.created_at)
            last_used_at = existing_item.last_used_at
            if last_used_at is None and old_item is not None:
                last_used_at = old_item.last_used_at
            updated = MemoryItem(
                key=candidate.key,
                text=candidate.text,
                keywords=list(candidate.keywords),
                created_at=created_at,
                updated_at=now,
                expires_at=_memory_expires_at(candidate.key, now),
                last_used_at=last_used_at,
                source=candidate.source or existing_item.source or (old_item.source if old_item else ""),
            )
            assert existing_index is not None
            self._items[existing_index] = updated
            return updated

        created_at = old_item.created_at if old_item is not None else now
        updated = MemoryItem(
            key=candidate.key,
            text=candidate.text,
            keywords=list(candidate.keywords),
            created_at=created_at,
            updated_at=now,
            expires_at=_memory_expires_at(candidate.key, now),
            last_used_at=old_item.last_used_at if old_item is not None else None,
            source=candidate.source or (old_item.source if old_item is not None else ""),
        )
        self._items.append(updated)
        return updated

    def _write_candidate_locked(
        self,
        candidate: MemoryCandidate,
        now: float,
        *,
        old_key: str | None = None,
        conflict_exclusions: set[str] | None = None,
        pruned_expired_count: int = 0,
    ) -> MemoryWriteOutcome:
        conflict_keys = _conflicting_memory_keys(candidate) - set(conflict_exclusions or set())
        existing_item = next(
            (item for item in self._items if item.key == candidate.key),
            None,
        )
        old_item = None
        if old_key:
            old_item = next((item for item in self._items if item.key == old_key), None)
        conflict_items = [item for item in self._items if item.key in conflict_keys]
        replaced: list[MemoryItem] = list(conflict_items)
        if existing_item is not None and existing_item.text != candidate.text:
            replaced.append(existing_item)
        if (
            old_item is not None
            and old_item.key != candidate.key
            and old_item.text != candidate.text
        ):
            replaced.append(old_item)

        if conflict_keys:
            self._items = [item for item in self._items if item.key not in conflict_keys]

        updated = self._upsert_candidate_locked(candidate, now, old_key=old_key)
        action = "created"
        if existing_item is not None or old_item is not None:
            action = "updated"
        elif conflict_items:
            action = "replaced"
        return MemoryWriteOutcome(
            item=updated,
            action=action,
            replaced=_dedupe_memory_items(replaced),
            pruned_expired_count=int(pruned_expired_count or 0),
        )

    def get(self, key: str) -> MemoryItem | None:
        with self._lock:
            if self._prune_expired_locked(time.time()):
                self._save_locked()
            for item in self._items:
                if item.key == key:
                    return item
        return None

    def clear(self) -> int:
        with self._lock:
            count = len(self._items)
            self._items = []
            self._save_locked()
            return count

    def create_with_outcome(self, text: str) -> MemoryWriteOutcome | None:
        candidate = _manual_memory_candidate(text)
        if candidate is None:
            return None

        now = time.time()
        with self._lock:
            pruned_expired_count = self._prune_expired_locked(now)
            outcome = self._write_candidate_locked(
                candidate,
                now,
                conflict_exclusions={candidate.key},
                pruned_expired_count=pruned_expired_count,
            )
            self._items.sort(
                key=lambda item: (item.updated_at, item.created_at),
                reverse=True,
            )
            self._items = self._items[:MAX_MEMORY_ITEMS]
            self._save_locked()
            return outcome

    def create(self, text: str) -> MemoryItem | None:
        outcome = self.create_with_outcome(text)
        if outcome is None:
            return None
        return outcome.item

    def update_text_with_outcome(self, key: str, text: str) -> MemoryWriteOutcome | None:
        candidate = _manual_memory_candidate(text)
        if candidate is None:
            return None

        now = time.time()
        with self._lock:
            pruned_expired_count = self._prune_expired_locked(now)
            if not any(item.key == key for item in self._items):
                return None
            outcome = self._write_candidate_locked(
                candidate,
                now,
                old_key=key,
                conflict_exclusions={key},
                pruned_expired_count=pruned_expired_count,
            )
            self._items.sort(
                key=lambda item: (item.updated_at, item.created_at),
                reverse=True,
            )
            self._items = self._items[:MAX_MEMORY_ITEMS]
            self._save_locked()
            return outcome

    def update_text(self, key: str, text: str) -> MemoryItem | None:
        outcome = self.update_text_with_outcome(key, text)
        if outcome is None:
            return None
        return outcome.item

    def delete(self, key: str) -> MemoryItem | None:
        with self._lock:
            self._prune_expired_locked(time.time())
            for index, item in enumerate(self._items):
                if item.key != key:
                    continue
                removed = self._items.pop(index)
                self._save_locked()
                return removed
        return None

    def remember_from_turn_outcomes(
        self,
        user_prompt: str,
        assistant_text: str = "",
    ) -> list[MemoryWriteOutcome]:
        candidates = extract_memory_candidates(user_prompt, assistant_text=assistant_text)
        if not candidates:
            return []

        now = time.time()
        saved: list[MemoryWriteOutcome] = []
        with self._lock:
            pruned_expired_count = self._prune_expired_locked(now)
            for candidate in candidates:
                outcome = self._write_candidate_locked(
                    candidate,
                    now,
                    conflict_exclusions={candidate.key},
                    pruned_expired_count=pruned_expired_count if not saved else 0,
                )
                saved.append(outcome)

            self._items.sort(
                key=lambda item: (item.updated_at, item.created_at),
                reverse=True,
            )
            self._items = self._items[:MAX_MEMORY_ITEMS]
            self._save_locked()

        return saved

    def remember_from_turn(self, user_prompt: str, assistant_text: str = "") -> list[MemoryItem]:
        return [
            outcome.item
            for outcome in self.remember_from_turn_outcomes(
                user_prompt,
                assistant_text=assistant_text,
            )
        ]

    def _score_item(self, item: MemoryItem, prompt: str) -> float:
        prompt_norm = _normalize_text(prompt)
        if not prompt_norm:
            return 0.0

        memory_norm = _normalize_text(item.text)
        score = 0.0

        if memory_norm and memory_norm in prompt_norm:
            score += 5.0
        if prompt_norm and prompt_norm in memory_norm:
            score += 3.0

        for keyword in item.keywords:
            keyword_norm = _normalize_text(keyword)
            if not keyword_norm:
                continue
            if keyword_norm in prompt_norm:
                score += 4.0 if len(keyword_norm) >= 2 else 1.0

        prompt_bigrams = {
            prompt_norm[index : index + 2]
            for index in range(max(0, len(prompt_norm) - 1))
        }
        memory_bigrams = {
            memory_norm[index : index + 2]
            for index in range(max(0, len(memory_norm) - 1))
        }
        if prompt_bigrams and memory_bigrams:
            score += min(8.0, len(prompt_bigrams & memory_bigrams) * 0.4)

        for token in _ASCII_TOKEN_RE.findall(prompt.lower()):
            if token in memory_norm:
                score += 3.0

        return score

    def recall(self, prompt: str, limit: int = MAX_RECALL_ITEMS) -> list[MemoryItem]:
        prompt = prompt.strip()
        if not prompt:
            return []

        now = time.time()
        with self._lock:
            if self._prune_expired_locked(now):
                self._save_locked()
            scored = []
            for item in self._items:
                score = self._score_item(item, prompt)
                if score > 0:
                    scored.append((score, item))

            scored.sort(
                key=lambda pair: (
                    pair[0],
                    pair[1].updated_at,
                    pair[1].created_at,
                ),
                reverse=True,
            )

            selected = [item for _, item in scored[:limit]]
            if not selected and _MEMORY_QUERY_RE.search(prompt):
                selected = sorted(
                    self._items,
                    key=lambda item: (item.updated_at, item.created_at),
                    reverse=True,
                )[: min(limit, 3)]

            if not selected:
                return []

            selected_keys = {item.key for item in selected}
            refreshed: list[MemoryItem] = []
            changed = False
            for item in self._items:
                if item.key not in selected_keys:
                    refreshed.append(item)
                    continue
                changed = True
                refreshed.append(
                    MemoryItem(
                        key=item.key,
                        text=item.text,
                        keywords=list(item.keywords),
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        expires_at=item.expires_at,
                        last_used_at=now,
                        source=item.source,
                    )
                )

            if changed:
                self._items = refreshed
                self._save_locked()

            latest = {item.key: item for item in self._items}
            return [latest[item.key] for item in selected if item.key in latest]

    def build_prompt(self, prompt: str, limit: int = MAX_RECALL_ITEMS) -> tuple[str, list[MemoryItem]]:
        memories = self.recall(prompt, limit=limit)
        return format_memory_prompt(memories), memories

    def forget_from_prompt(self, prompt: str) -> ForgetOutcome:
        target = _forget_target_from_prompt(prompt)
        if target is None:
            return ForgetOutcome()

        now = time.time()
        with self._lock:
            pruned_expired_count = self._prune_expired_locked(now)
            if pruned_expired_count:
                self._save_locked()
            if not self._items:
                return ForgetOutcome(
                    handled=True,
                    message="我翻了一下长期记忆，现在本来就是空的。",
                    mode=str(target.get("mode") or "").strip(),
                    target=str(
                        target.get("topic")
                        or target.get("target")
                        or "长期记忆"
                    ).strip(),
                    pruned_expired_count=pruned_expired_count,
                )

            mode = str(target.get("mode") or "").strip()
            target_label = str(
                target.get("topic")
                or target.get("target")
                or ("刚才那条" if mode == "recent" else "那条")
            ).strip()
            if mode == "recent":
                recent_items = [
                    item
                    for item in self._items
                    if (now - max(item.updated_at, item.created_at)) <= _RECENT_FORGET_WINDOW_S
                ]
                if not recent_items:
                    return ForgetOutcome(
                        handled=True,
                        message="你说“刚才那条”，可我这边翻不到足够新的那条记忆。",
                        mode=mode,
                        target="刚才那条",
                        pruned_expired_count=pruned_expired_count,
                    )
                recent_items.sort(
                    key=lambda item: (item.updated_at, item.created_at),
                    reverse=True,
                )
                removed = recent_items[:1]
            elif mode == "key":
                key = str(target.get("key") or "").strip()
                removed = [item for item in self._items if item.key == key]
                if not removed:
                    topic = str(target.get("topic") or "那条").strip()
                    return ForgetOutcome(
                        handled=True,
                        message=f"我翻了一下，没找到和{topic}对应的那条长期记忆。",
                        mode=mode,
                        target=topic,
                        pruned_expired_count=pruned_expired_count,
                    )
            else:
                search_target = _normalize_text(str(target.get("target") or ""))
                removed = [
                    item
                    for item in self._items
                    if search_target
                    and (
                        search_target in _normalize_text(item.text)
                        or any(search_target in _normalize_text(keyword) for keyword in item.keywords)
                    )
                ]
                if not removed:
                    target_text = str(target.get("target") or "那条").strip()
                    return ForgetOutcome(
                        handled=True,
                        message=f"我翻了一下，没找到和“{target_text}”沾边的长期记忆。",
                        mode=mode,
                        target=target_text,
                        pruned_expired_count=pruned_expired_count,
                    )
                if len(removed) > 1:
                    preview = "；".join(_clip(item.text, 22) for item in removed[:2])
                    return ForgetOutcome(
                        handled=True,
                        message=f"我翻到不止一条：{preview}。你再说清楚要抹哪条。",
                        mode=mode,
                        target=target_label,
                        ambiguous_matches=removed,
                        pruned_expired_count=pruned_expired_count,
                    )

            removed_keys = {item.key for item in removed}
            self._items = [item for item in self._items if item.key not in removed_keys]
            self._save_locked()
            preview = _clip(removed[0].text, 36) if removed else "那条长期记忆"
            if mode == "recent":
                message = f"行，刚才那条长期记忆已经删了：{preview}"
            else:
                message = f"好，那条长期记忆已经删掉了：{preview}"
            return ForgetOutcome(
                handled=True,
                removed=removed,
                message=message,
                mode=mode,
                target=target_label,
                pruned_expired_count=pruned_expired_count,
            )


def preview_memories(memories: list[MemoryItem], limit: int = 4) -> str:
    lines = []
    for memory in memories[:limit]:
        lines.append(f"- {_clip(memory.text)}")
    if len(memories) > limit:
        lines.append(f"- ... 共 {len(memories)} 条")
    return "\n".join(lines)
