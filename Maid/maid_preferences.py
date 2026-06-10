"""Shared setup/runtime preference constants for Deskmaid."""

from __future__ import annotations

import locale
import os


CURRENT_SETUP_VERSION = 6

DEFAULT_LANGUAGE = "zh-CN"
SYSTEM_LANGUAGE = "system"
DEFAULT_UI_LANGUAGE = SYSTEM_LANGUAGE

LANGUAGE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "zh-CN",
        "中文",
        "默认用中文回复。",
    ),
    (
        "en-US",
        "English",
        "默认用英文回复。",
    ),
)

LANGUAGE_LABELS = {
    code: label
    for code, label, _description in LANGUAGE_OPTIONS
}

LANGUAGE_DESCRIPTIONS = {
    code: description
    for code, _label, description in LANGUAGE_OPTIONS
}

UI_LANGUAGE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        SYSTEM_LANGUAGE,
        "跟随系统",
        "界面和说明跟随 macOS 语言。",
    ),
    (
        "zh-CN",
        "中文",
        "界面和说明使用中文。",
    ),
    (
        "en-US",
        "English",
        "Use English for the interface and dialogs.",
    ),
)

UI_LANGUAGE_LABELS = {
    code: label
    for code, label, _description in UI_LANGUAGE_OPTIONS
}

UI_LANGUAGE_DESCRIPTIONS = {
    code: description
    for code, _label, description in UI_LANGUAGE_OPTIONS
}

DATA_BOUNDARY_CONFIRMATION_TEXT = (
    "我知道：普通对话、工具摘要、命中的非高敏长期记忆可能会发给云端 Claude；"
    "密码、密钥、证件号、银行卡等高敏内容默认留在本机。"
)

BUDGET_MODE_OPTIONS: tuple[tuple[str, str, str, float], ...] = (
    (
        "cautious",
        "谨慎",
        "单轮更克制，适合常驻挂着用。",
        0.30,
    ),
    (
        "normal",
        "标准",
        "默认档位，日常聊天和工具调用都够用。",
        0.80,
    ),
    (
        "open",
        "放开",
        "给复杂任务留更多余量，花得也更快。",
        2.00,
    ),
)

BUDGET_MODE_LABELS = {
    mode: label
    for mode, label, _description, _max_budget_usd in BUDGET_MODE_OPTIONS
}

BUDGET_MODE_DESCRIPTIONS = {
    mode: description
    for mode, _label, description, _max_budget_usd in BUDGET_MODE_OPTIONS
}

BUDGET_MODE_MAX_BUDGET_USD = {
    mode: max_budget_usd
    for mode, _label, _description, max_budget_usd in BUDGET_MODE_OPTIONS
}

BUDGET_MODE_DAILY_LIMIT_USD = {
    "cautious": 1.50,
    "normal": 4.00,
    "open": 10.00,
}

BUDGET_MODE_WEEKLY_LIMIT_USD = {
    "cautious": 7.50,
    "normal": 20.00,
    "open": 50.00,
}

AUTO_HIDE_REASON_KEYS = {"screen_share", "presentation_focus"}


def normalize_budget_mode(value: str) -> str:
    mode = str(value or "normal").strip().lower()
    if mode in BUDGET_MODE_LABELS:
        return mode
    return "normal"


def normalize_language(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_LANGUAGE

    lowered = raw.lower().replace("_", "-")
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "cn": "zh-CN",
        "chinese": "zh-CN",
        "中文": "zh-CN",
        "简体中文": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
        "english": "en-US",
        "英文": "en-US",
    }
    if lowered in aliases:
        return aliases[lowered]

    if raw in LANGUAGE_LABELS:
        return raw
    return DEFAULT_LANGUAGE


def normalize_ui_language(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_UI_LANGUAGE

    lowered = raw.lower().replace("_", "-")
    aliases = {
        "system": SYSTEM_LANGUAGE,
        "auto": SYSTEM_LANGUAGE,
        "follow-system": SYSTEM_LANGUAGE,
        "follow_system": SYSTEM_LANGUAGE,
        "跟随系统": SYSTEM_LANGUAGE,
        "系统": SYSTEM_LANGUAGE,
        "system default": SYSTEM_LANGUAGE,
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "cn": "zh-CN",
        "chinese": "zh-CN",
        "中文": "zh-CN",
        "简体中文": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
        "english": "en-US",
        "英文": "en-US",
    }
    if lowered in aliases:
        return aliases[lowered]

    if raw in UI_LANGUAGE_LABELS:
        return raw
    return DEFAULT_UI_LANGUAGE


def detect_system_language() -> str:
    try:
        from Foundation import NSLocale, NSUserDefaults

        defaults = NSUserDefaults.standardUserDefaults()
        languages = []
        try:
            languages = list(defaults.stringArrayForKey_("AppleLanguages") or [])
        except Exception:
            languages = list(defaults.arrayForKey_("AppleLanguages") or [])
        for candidate in languages:
            text = str(candidate or "").strip()
            if not text:
                continue
            lowered = text.lower().replace("_", "-")
            if lowered.startswith("zh"):
                return "zh-CN"
            if lowered.startswith("en"):
                return "en-US"

        try:
            current_locale = str(NSLocale.currentLocale().localeIdentifier() or "").strip()
        except Exception:
            current_locale = ""
        if current_locale:
            lowered = current_locale.lower().replace("_", "-")
            if lowered.startswith("zh"):
                return "zh-CN"
            if lowered.startswith("en"):
                return "en-US"
    except Exception:
        pass

    candidates = [
        locale.getlocale()[0],
        locale.getdefaultlocale()[0] if hasattr(locale, "getdefaultlocale") else None,
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        lowered = text.lower().replace("_", "-")
        if lowered.startswith("zh"):
            return "zh-CN"
        if lowered.startswith("en"):
            return "en-US"
    return "zh-CN"


def resolve_ui_language(value: str) -> str:
    normalized = normalize_ui_language(value)
    if normalized == SYSTEM_LANGUAGE:
        return detect_system_language()
    return normalize_language(normalized)
