"""Local privacy filters for content that is about to leave the machine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


HOME_DIR = str(Path.home())
REDACTED_TEXT = "[REDACTED]"
USER_HIDDEN_TEXT = "[已隐藏]"
PROMPT_REDACTION_NOTE = (
    "\n\n[系统注记：上面输入里的部分敏感内容已在离开本机前脱敏。"
    "如果必须处理高敏信息，请改走本地确认链路。]"
)

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [^-]+-----.*?-----END [^-]+-----",
    re.DOTALL,
)
_API_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE)),
)
_LABELED_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "labeled_secret",
        re.compile(
            r"(?P<label>\b(?:password|passwd|passcode|token|secret|api[_ -]?key|authorization)\b\s*[:=]\s*)(?P<value>[^\s,;]{4,})",
            re.IGNORECASE,
        ),
    ),
    (
        "labeled_secret_cn",
        re.compile(
            r"(?P<label>(?:密码|口令|密钥|令牌|授权码|访问令牌)\s*[:：=]\s*)(?P<value>\S{4,})",
            re.IGNORECASE,
        ),
    ),
    (
        "labeled_account",
        re.compile(
            r"(?P<label>\b(?:bank account|account(?: number| no)?|iban)\b\s*[:=]\s*)(?P<value>[0-9A-Za-z -]{8,40})",
            re.IGNORECASE,
        ),
    ),
    (
        "labeled_account_cn",
        re.compile(
            r"(?P<label>(?:银行卡|银行卡号|账号|账户号)\s*[:：=]\s*)(?P<value>[0-9A-Za-z -]{8,40})",
            re.IGNORECASE,
        ),
    ),
)
_CHINA_ID_RE = re.compile(
    r"\b[1-9]\d{5}(?:18|19|20)?\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"
)
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_MAIL_MESSAGE_ID_TAIL_RE = re.compile(
    r"\.[A-Za-z0-9._%+-]{4,}@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
)
_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "authorization",
    "key_material",
    "passcode",
    "passwd",
    "password",
    "private_key",
    "secret",
    "token",
}
_HIGH_SENSITIVITY_LABELS = {
    "pem_block",
    "api_key",
    "anthropic_key",
    "github_token",
    "slack_token",
    "aws_access_key",
    "bearer_token",
    "labeled_secret",
    "labeled_secret_cn",
    "labeled_account",
    "labeled_account_cn",
    "cn_id",
    "credit_card",
}
_HIGH_SENSITIVITY_FIELD_PREFIXES = (
    "field:api_key",
    "field:authorization",
    "field:key_material",
    "field:passcode",
    "field:passwd",
    "field:password",
    "field:private_key",
    "field:secret",
    "field:token",
)
_HIGH_SENSITIVITY_LABEL_DISPLAY = {
    "pem_block": "私钥/证书",
    "api_key": "API 密钥",
    "anthropic_key": "Anthropic 密钥",
    "github_token": "GitHub 令牌",
    "slack_token": "Slack 令牌",
    "aws_access_key": "AWS 凭证",
    "bearer_token": "Bearer 令牌",
    "labeled_secret": "密码/口令",
    "labeled_secret_cn": "密码/口令",
    "labeled_account": "账户号",
    "labeled_account_cn": "账户号",
    "cn_id": "身份证号",
    "credit_card": "银行卡/信用卡",
    "field:api_key": "API 密钥字段",
    "field:authorization": "授权字段",
    "field:key_material": "密钥字段",
    "field:passcode": "口令字段",
    "field:passwd": "密码字段",
    "field:password": "密码字段",
    "field:private_key": "私钥字段",
    "field:secret": "密文字段",
    "field:token": "令牌字段",
}
_KEY_MATERIAL_ADVICE_LABELS = {
    "pem_block",
    "field:key_material",
    "field:private_key",
}
_SECRET_ADVICE_LABELS = {
    "api_key",
    "anthropic_key",
    "github_token",
    "slack_token",
    "aws_access_key",
    "bearer_token",
    "labeled_secret",
    "labeled_secret_cn",
    "field:api_key",
    "field:authorization",
    "field:passcode",
    "field:passwd",
    "field:password",
    "field:secret",
    "field:token",
}
_ACCOUNT_ADVICE_LABELS = {
    "credit_card",
    "labeled_account",
    "labeled_account_cn",
}
_ID_ADVICE_LABELS = {
    "cn_id",
}


@dataclass(frozen=True)
class PrivacyFilterResult:
    value: str
    redaction_count: int
    labels: tuple[str, ...]
    blocked: bool = False
    blocked_labels: tuple[str, ...] = ()
    block_reason: str = ""


@dataclass(frozen=True)
class PrivacySanitizeResult:
    value: Any
    redaction_count: int
    labels: tuple[str, ...]
    blocked: bool = False
    blocked_labels: tuple[str, ...] = ()
    block_reason: str = ""


@dataclass(frozen=True)
class PrivacyQuickRewriteResult:
    value: str
    change_count: int
    action: str


def _dedupe_labels(labels: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for label in labels:
        item = str(label or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _normalize_home_paths(text: str) -> str:
    normalized = str(text or "")
    if HOME_DIR and HOME_DIR != "/":
        normalized = normalized.replace(HOME_DIR, "~")
    return normalized


def _is_high_sensitivity_label(label: str) -> bool:
    normalized = str(label or "").strip().lower()
    if not normalized:
        return False
    if normalized in _HIGH_SENSITIVITY_LABELS:
        return True
    return normalized.startswith(_HIGH_SENSITIVITY_FIELD_PREFIXES)


def _blocked_labels(labels: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return _dedupe_labels(
        [label for label in labels if _is_high_sensitivity_label(str(label or ""))]
    )


def _high_sensitivity_label_names(labels: tuple[str, ...] | list[str]) -> str:
    rendered: list[str] = []
    seen: set[str] = set()
    for label in labels:
        normalized = str(label or "").strip().lower()
        if not normalized:
            continue
        display = _HIGH_SENSITIVITY_LABEL_DISPLAY.get(normalized, normalized)
        if display in seen:
            continue
        seen.add(display)
        rendered.append(display)
    return "、".join(rendered[:3])


def _context_subject(context: str) -> str:
    if context == "prompt":
        return "这句输入"
    if context == "memory":
        return "命中的长期记忆"
    if context == "tool":
        return "工具结果"
    return "这段内容"


def _normalized_label_values(labels: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for label in labels:
        normalized = str(label or "").strip().lower()
        if normalized:
            values.append(normalized)
    return tuple(values)


def _privacy_value_advice(labels: tuple[str, ...] | list[str]) -> str:
    normalized = _normalized_label_values(labels)
    if any(label in _KEY_MATERIAL_ADVICE_LABELS for label in normalized):
        return "不要直接贴原始私钥或证书，改成指纹、公钥或用途描述"
    if any(label in _ACCOUNT_ADVICE_LABELS for label in normalized):
        return "只保留末四位、别名或用途描述"
    if any(label in _ID_ADVICE_LABELS for label in normalized):
        return "只保留末四位、出生年月或代号"
    if any(label in _SECRET_ADVICE_LABELS for label in normalized):
        return "把真实值换成 [已隐藏]、代号或末四位"
    return "只保留必要字段、摘要或代号"


def _privacy_context_advice(context: str, *, blocked: bool) -> str:
    if context == "prompt":
        if blocked:
            return "如果必须保留原文，请改走本机处理"
        return "改完后可以直接重发这句"
    if context == "memory":
        if blocked:
            return "如果想让她继续把这条长期记忆带去云端推理，请先把真实值改成代称再保存"
        return "后续引用这条长期记忆时，继续用代称，不要补回原始值"
    if context == "tool":
        if blocked:
            return "如果还要继续处理，让工具只返回摘要、字段名或脱敏字段后再试"
        return "后续让她继续处理时，优先只传字段名、摘要或白名单字段"
    if blocked:
        return "如果必须保留原文，请留在本机处理"
    return "后续继续时，尽量也用摘要或代号"


def _privacy_next_step_advice(
    labels: tuple[str, ...] | list[str],
    *,
    context: str,
    blocked: bool,
) -> str:
    pieces: list[str] = []
    value_advice = _privacy_value_advice(labels)
    if value_advice:
        pieces.append(value_advice)
    context_advice = _privacy_context_advice(context, blocked=blocked)
    if context_advice and context_advice not in pieces:
        pieces.append(context_advice)
    if not pieces:
        return ""
    return "；".join(pieces) + "。"


def _last4_hint(value: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z]+", "", str(value or ""))
    if len(compact) < 4:
        return USER_HIDDEN_TEXT
    return f"[末四位 {compact[-4:]}]"


def _rewrite_text_with_placeholder(
    text: str,
    *,
    placeholder_factory,
) -> tuple[str, int]:
    working = _normalize_home_paths(str(text or ""))
    change_count = 0

    def replace_pattern(
        pattern: re.Pattern[str],
        replacement_factory,
    ):
        nonlocal working, change_count
        match_count = 0

        def repl(match: re.Match[str]) -> str:
            nonlocal match_count
            match_count += 1
            return replacement_factory(match)

        updated = pattern.sub(repl, working)
        if match_count <= 0:
            return
        working = updated
        change_count += match_count

    def replace_labeled_pattern(pattern: re.Pattern[str]):
        nonlocal working, change_count
        match_count = 0

        def repl(match: re.Match[str]) -> str:
            nonlocal match_count
            match_count += 1
            return f"{match.group('label')}{placeholder_factory(match.group('value'))}"

        updated = pattern.sub(repl, working)
        if match_count <= 0:
            return
        working = updated
        change_count += match_count

    replace_pattern(
        _PEM_BLOCK_RE,
        lambda _match: USER_HIDDEN_TEXT,
    )
    for _label, pattern in _LABELED_SECRET_PATTERNS:
        replace_labeled_pattern(pattern)
    for _label, pattern in _API_KEY_PATTERNS:
        replace_pattern(
            pattern,
            lambda match: placeholder_factory(match.group(0)),
        )
    replace_pattern(
        _CHINA_ID_RE,
        lambda match: placeholder_factory(match.group(0)),
    )

    def card_repl(match: re.Match[str]) -> str:
        tail = working[match.end() : match.end() + 120]
        if _MAIL_MESSAGE_ID_TAIL_RE.match(tail):
            return match.group(0)
        digits = re.sub(r"\D+", "", match.group(0))
        if not _luhn_ok(digits):
            return match.group(0)
        return placeholder_factory(match.group(0))

    updated_cards, card_count = _replace_cards(working, card_repl)
    if card_count > 0:
        working = updated_cards
        change_count += card_count

    return working, change_count


def _replace_cards(
    text: str,
    replacer,
) -> tuple[str, int]:
    match_count = 0

    def wrapped(match: re.Match[str]) -> str:
        nonlocal match_count
        replacement = replacer(match)
        if replacement != match.group(0):
            match_count += 1
        return replacement

    return _CREDIT_CARD_RE.sub(wrapped, text), match_count


def rewrite_prompt_for_privacy_action(
    text: str,
    action: str,
) -> PrivacyQuickRewriteResult:
    normalized_action = str(action or "").strip().lower()
    source_text = _normalize_home_paths(str(text or ""))

    if normalized_action == "hidden":
        value, change_count = _rewrite_text_with_placeholder(
            source_text,
            placeholder_factory=lambda _value: USER_HIDDEN_TEXT,
        )
        return PrivacyQuickRewriteResult(
            value=value,
            change_count=change_count,
            action=normalized_action,
        )

    if normalized_action == "last4":
        value, change_count = _rewrite_text_with_placeholder(
            source_text,
            placeholder_factory=_last4_hint,
        )
        return PrivacyQuickRewriteResult(
            value=value,
            change_count=change_count,
            action=normalized_action,
        )

    if normalized_action == "local_only":
        hidden = rewrite_prompt_for_privacy_action(source_text, "hidden")
        prefix = (
            "请仅在本机处理下面这段高敏内容；"
            "如果后续还要继续讨论，请只保留 [已隐藏]、代号或末四位，不要带原始值。"
        )
        stripped = hidden.value.strip()
        if stripped.startswith("请仅在本机处理下面这段高敏内容"):
            value = hidden.value
        elif stripped:
            value = f"{prefix}\n\n{hidden.value}"
        else:
            value = prefix
        return PrivacyQuickRewriteResult(
            value=value,
            change_count=hidden.change_count,
            action=normalized_action,
        )

    return PrivacyQuickRewriteResult(
        value=source_text,
        change_count=0,
        action=normalized_action,
    )


def format_privacy_block_detail(
    blocked_labels: tuple[str, ...] | list[str],
    *,
    context: str,
    match_count: int | None = None,
) -> str:
    kinds = _high_sensitivity_label_names(blocked_labels) or "高敏信息"
    parts = [f"{_context_subject(context)}里命中了{kinds}。"]
    if match_count is not None and int(match_count) > 0:
        parts.append(f"命中数量: {int(match_count)} 处。")
    parts.append("处理动作: 整段留在本机，不发送给远端模型。")
    advice = _privacy_next_step_advice(blocked_labels, context=context, blocked=True)
    if advice:
        parts.append(f"下一步建议: {advice}")
    return "\n".join(parts)


def format_privacy_redaction_detail(
    labels: tuple[str, ...] | list[str],
    *,
    context: str,
    match_count: int | None = None,
) -> str:
    kinds = _high_sensitivity_label_names(labels) or "敏感内容"
    parts = [f"{_context_subject(context)}里命中了{kinds}。"]
    if match_count is not None and int(match_count) > 0:
        parts.append(f"命中数量: {int(match_count)} 处。")
    parts.append("处理动作: 脱敏后继续发送给远端模型。")
    advice = _privacy_next_step_advice(labels, context=context, blocked=False)
    if advice:
        parts.append(f"下一步建议: {advice}")
    return "\n".join(parts)


def format_privacy_metadata_detail(
    metadata: dict[str, object] | None,
    *,
    context: str = "tool",
) -> str:
    payload = dict(metadata or {})
    if bool(payload.get("blocked")):
        return format_privacy_block_detail(
            payload.get("blocked_labels") or payload.get("labels") or (),
            context=context,
            match_count=int(payload.get("count") or 0),
        )
    if bool(payload.get("redacted")):
        return format_privacy_redaction_detail(
            payload.get("labels") or (),
            context=context,
            match_count=int(payload.get("count") or 0),
        )
    return ""


def _block_reason(
    blocked_labels: tuple[str, ...],
    *,
    context: str,
    match_count: int | None = None,
) -> str:
    return format_privacy_block_detail(
        blocked_labels,
        context=context,
        match_count=match_count,
    )


def _luhn_ok(digits: str) -> bool:
    if len(digits) < 13 or len(digits) > 19 or not digits.isdigit():
        return False
    total = 0
    reverse_digits = list(reversed(digits))
    for index, char in enumerate(reverse_digits):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def redact_sensitive_text(text: str) -> PrivacyFilterResult:
    working = _normalize_home_paths(str(text or ""))
    redaction_count = 0
    labels: list[str] = []

    def replace_pattern(
        pattern: re.Pattern[str],
        label: str,
        replacement: str = REDACTED_TEXT,
    ):
        nonlocal working, redaction_count
        matches = list(pattern.finditer(working))
        if not matches:
            return
        working = pattern.sub(replacement, working)
        redaction_count += len(matches)
        labels.extend([label] * len(matches))

    def replace_labeled_pattern(pattern: re.Pattern[str], label: str):
        nonlocal working, redaction_count
        match_count = 0

        def repl(match: re.Match[str]) -> str:
            nonlocal match_count
            match_count += 1
            return f"{match.group('label')}{REDACTED_TEXT}"

        updated = pattern.sub(repl, working)
        if match_count <= 0:
            return
        working = updated
        redaction_count += match_count
        labels.extend([label] * match_count)

    replace_pattern(_PEM_BLOCK_RE, "pem_block")
    for label, pattern in _API_KEY_PATTERNS:
        replace_pattern(pattern, label)
    for label, pattern in _LABELED_SECRET_PATTERNS:
        replace_labeled_pattern(pattern, label)
    replace_pattern(_CHINA_ID_RE, "cn_id")

    card_match_count = 0

    def card_repl(match: re.Match[str]) -> str:
        nonlocal card_match_count
        tail = working[match.end() : match.end() + 120]
        if _MAIL_MESSAGE_ID_TAIL_RE.match(tail):
            return match.group(0)
        digits = re.sub(r"\D+", "", match.group(0))
        if not _luhn_ok(digits):
            return match.group(0)
        card_match_count += 1
        return REDACTED_TEXT

    updated_cards = _CREDIT_CARD_RE.sub(card_repl, working)
    if card_match_count > 0:
        working = updated_cards
        redaction_count += card_match_count
        labels.extend(["credit_card"] * card_match_count)

    return PrivacyFilterResult(
        value=working,
        redaction_count=redaction_count,
        labels=_dedupe_labels(labels),
    )


def prepare_text_for_remote(
    text: str,
    *,
    context: str = "content",
    append_redaction_note: bool = False,
) -> PrivacyFilterResult:
    result = redact_sensitive_text(text)
    blocked = _blocked_labels(result.labels)
    if blocked:
        return PrivacyFilterResult(
            value=result.value,
            redaction_count=result.redaction_count,
            labels=result.labels,
            blocked=True,
            blocked_labels=blocked,
            block_reason=_block_reason(
                blocked,
                context=context,
                match_count=result.redaction_count,
            ),
        )

    value = result.value
    if append_redaction_note and result.redaction_count > 0:
        value += PROMPT_REDACTION_NOTE
    return PrivacyFilterResult(
        value=value,
        redaction_count=result.redaction_count,
        labels=result.labels,
    )


def prepare_prompt_for_remote(prompt: str) -> PrivacyFilterResult:
    return prepare_text_for_remote(
        prompt,
        context="prompt",
        append_redaction_note=True,
    )


def prepare_memory_text_for_remote(text: str) -> PrivacyFilterResult:
    return prepare_text_for_remote(text, context="memory")


def sanitize_value_for_remote(value: Any) -> PrivacySanitizeResult:
    if isinstance(value, str):
        text_result = redact_sensitive_text(value)
        blocked = _blocked_labels(text_result.labels)
        return PrivacySanitizeResult(
            value=text_result.value,
            redaction_count=text_result.redaction_count,
            labels=text_result.labels,
            blocked=bool(blocked),
            blocked_labels=blocked,
            block_reason=(
                _block_reason(
                    blocked,
                    context="tool",
                    match_count=text_result.redaction_count,
                )
                if blocked
                else ""
            ),
        )

    if isinstance(value, list):
        out: list[Any] = []
        redaction_count = 0
        labels: list[str] = []
        blocked = False
        blocked_labels: list[str] = []
        for item in value:
            sanitized = sanitize_value_for_remote(item)
            out.append(sanitized.value)
            redaction_count += sanitized.redaction_count
            labels.extend(sanitized.labels)
            blocked = blocked or sanitized.blocked
            blocked_labels.extend(sanitized.blocked_labels)
        return PrivacySanitizeResult(
            value=out,
            redaction_count=redaction_count,
            labels=_dedupe_labels(labels),
            blocked=blocked,
            blocked_labels=_dedupe_labels(blocked_labels),
            block_reason=(
                _block_reason(
                    _dedupe_labels(blocked_labels),
                    context="tool",
                    match_count=redaction_count,
                )
                if blocked_labels
                else ""
            ),
        )

    if isinstance(value, tuple):
        sanitized = sanitize_value_for_remote(list(value))
        return PrivacySanitizeResult(
            value=sanitized.value,
            redaction_count=sanitized.redaction_count,
            labels=sanitized.labels,
            blocked=sanitized.blocked,
            blocked_labels=sanitized.blocked_labels,
            block_reason=sanitized.block_reason,
        )

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        redaction_count = 0
        labels: list[str] = []
        blocked = False
        blocked_labels: list[str] = []
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.lower() in _SENSITIVE_FIELD_NAMES:
                out[key] = REDACTED_TEXT
                redaction_count += 1
                field_label = f"field:{key.lower()}"
                labels.append(field_label)
                if _is_high_sensitivity_label(field_label):
                    blocked = True
                    blocked_labels.append(field_label)
                continue
            sanitized = sanitize_value_for_remote(raw_value)
            out[key] = sanitized.value
            redaction_count += sanitized.redaction_count
            labels.extend(sanitized.labels)
            blocked = blocked or sanitized.blocked
            blocked_labels.extend(sanitized.blocked_labels)
        return PrivacySanitizeResult(
            value=out,
            redaction_count=redaction_count,
            labels=_dedupe_labels(labels),
            blocked=blocked,
            blocked_labels=_dedupe_labels(blocked_labels),
            block_reason=(
                _block_reason(
                    _dedupe_labels(blocked_labels),
                    context="tool",
                    match_count=redaction_count,
                )
                if blocked_labels
                else ""
            ),
        )

    return PrivacySanitizeResult(
        value=value,
        redaction_count=0,
        labels=(),
        blocked=False,
        blocked_labels=(),
        block_reason="",
    )


def sanitize_tool_payload_for_remote(
    payload: dict[str, object],
) -> PrivacySanitizeResult:
    sanitized = sanitize_value_for_remote(dict(payload))
    if sanitized.blocked:
        value = {
            "message": "High-sensitivity payload retained locally.",
            "_privacy": {
                "redacted": sanitized.redaction_count > 0,
                "count": sanitized.redaction_count,
                "labels": list(sanitized.labels),
                "blocked": True,
                "blocked_labels": list(sanitized.blocked_labels),
                "reason": sanitized.block_reason,
            },
        }
        return PrivacySanitizeResult(
            value=value,
            redaction_count=sanitized.redaction_count,
            labels=sanitized.labels,
            blocked=True,
            blocked_labels=sanitized.blocked_labels,
            block_reason=sanitized.block_reason,
        )

    value = sanitized.value
    if (
        isinstance(value, dict)
        and sanitized.redaction_count > 0
        and "_privacy" not in value
    ):
        value = dict(value)
        value["_privacy"] = {
            "redacted": True,
            "count": sanitized.redaction_count,
            "labels": list(sanitized.labels),
            "blocked": False,
            "blocked_labels": [],
            "reason": "",
        }
    return PrivacySanitizeResult(
        value=value,
        redaction_count=sanitized.redaction_count,
        labels=sanitized.labels,
        blocked=False,
        blocked_labels=(),
        block_reason="",
    )
