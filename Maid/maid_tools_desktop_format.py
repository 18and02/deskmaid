"""Preview and receipt formatting for desktop maid tools."""

from __future__ import annotations

from maid_tools_apple_common import (
    _format_boolean_label,
    _format_frontmost_app_label,
    _format_receipt_text_snippet,
    _format_text_length_label,
    _trim_preview_block,
)
from maid_tools_shared import (
    _normalize_calendar_names,
    _normalize_required_text,
)
from maid_tools_desktop_clipboard_input import (
    DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT,
    MAX_CLIPBOARD_TEXT_CHAR_LIMIT,
    _key_combo_label,
    _normalize_modifiers,
    _parse_press_keys_args,
    _resolve_input_target_sync,
)
from maid_tools_desktop_window_open import (
    DEFAULT_WINDOW_LIST_LIMIT,
    _get_frontmost_app_sync,
    _parse_list_windows_args,
    _resolve_focus_window_target_sync,
    _resolve_url_target,
)


def preview_focus_window_request(args: dict[str, object]) -> dict[str, object]:
    return _resolve_focus_window_target_sync(args)


def format_focus_window_preview(preview: dict[str, object]) -> str:
    app_payload = dict(preview.get("app") or {})
    window_payload = dict(preview.get("window") or {})
    mode = str(preview.get("mode") or "window").strip() or "window"
    lines = [
        "将要切换窗口：",
        f"模式: {'指定窗口' if mode == 'window' else '应用当前窗口'}",
        f"应用: {_format_frontmost_app_label(app_payload)}",
    ]
    if window_payload:
        title = str(window_payload.get("title") or "").strip()
        if title:
            lines.append(f"窗口: {title}")
        window_id = window_payload.get("window_id")
        if window_id is not None:
            lines.append(f"窗口 id: {window_id}")
    candidate_count = int(preview.get("candidate_count", 0) or 0)
    if mode == "app" and candidate_count > 1:
        lines.append(f"可见窗口: {candidate_count} 个（会交给系统切到该应用当前主窗口）")
    return "\n".join(lines)


def preview_open_url_request(args: dict[str, object]) -> dict[str, object]:
    target = _normalize_required_text(args.get("target"), "target")
    _, matched_by, resolved_url = _resolve_url_target(target)
    return {
        "target": target,
        "matched_by": matched_by,
        "resolved_url": resolved_url,
        "activate": bool(args.get("activate", True)),
    }


def format_open_url_preview(preview: dict[str, object]) -> str:
    return "\n".join(
        [
            "将要打开链接：",
            f"链接: {str(preview.get('resolved_url') or '').strip() or '（无）'}",
            f"来源: {str(preview.get('matched_by') or '').strip() or '（未知）'}",
            f"激活目标应用: {_format_boolean_label(preview.get('activate'))}",
        ]
    )


def preview_list_windows_request(args: dict[str, object]) -> dict[str, object]:
    return _parse_list_windows_args(args)


def format_list_windows_preview(preview: dict[str, object]) -> str:
    owner_names = _normalize_calendar_names(preview.get("owner_names"))
    lines = [
        "将要读取当前桌面窗口列表。",
        f"仅屏幕内窗口: {_format_boolean_label(preview.get('on_screen_only'))}",
        f"包含桌面元素: {_format_boolean_label(preview.get('include_desktop_elements'))}",
        f"包含非标准层级: {_format_boolean_label(preview.get('include_nonzero_layer'))}",
        f"最多返回: {int(preview.get('limit', DEFAULT_WINDOW_LIST_LIMIT) or DEFAULT_WINDOW_LIST_LIMIT)} 个",
    ]
    if owner_names:
        lines.append(f"应用过滤: {'，'.join(owner_names)}")
    title_filter = str(preview.get("title_contains") or "").strip()
    if title_filter:
        lines.append(f"标题包含: {title_filter}")
    return "\n".join(lines)


def _parse_read_clipboard_text_args(args: dict[str, object]) -> dict[str, object]:
    safe_max_chars = int(args.get("max_chars", DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT))
    if safe_max_chars < 1:
        safe_max_chars = 1
    if safe_max_chars > MAX_CLIPBOARD_TEXT_CHAR_LIMIT:
        safe_max_chars = MAX_CLIPBOARD_TEXT_CHAR_LIMIT
    return {"max_chars": safe_max_chars}


def preview_read_clipboard_text_request(args: dict[str, object]) -> dict[str, object]:
    return _parse_read_clipboard_text_args(args)


def format_read_clipboard_text_preview(preview: dict[str, object]) -> str:
    return "\n".join(
        [
            "将要读取系统剪贴板中的纯文本内容。",
            f"最多返回: {int(preview.get('max_chars', DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT) or DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT)} 字",
        ]
    )


def _parse_set_clipboard_text_args(args: dict[str, object]) -> dict[str, object]:
    if "text" not in args:
        raise ValueError("text is required")
    text = str(args.get("text") or "")
    return {
        "text": text,
        "length": len(text),
    }


def preview_set_clipboard_text_request(args: dict[str, object]) -> dict[str, object]:
    return _parse_set_clipboard_text_args(args)


def format_set_clipboard_text_preview(preview: dict[str, object]) -> str:
    return "\n".join(
        [
            "将要写入系统剪贴板：",
            f"长度: {_format_text_length_label(length=preview.get('length'), text=preview.get('text'))}",
            "",
            "内容预览:",
            _trim_preview_block(str(preview.get("text") or "")),
        ]
    )


def _parse_paste_text_args(args: dict[str, object]) -> dict[str, object]:
    if "text" not in args:
        raise ValueError("text is required")
    text = str(args.get("text") or "")
    return {
        "text": text,
        "length": len(text),
        "restore_clipboard": bool(args.get("restore_clipboard", True)),
    }


def preview_paste_text_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_paste_text_args(args)
    target = _resolve_input_target_sync()
    parsed["frontmost_app"] = target.get("app") or _get_frontmost_app_sync()
    return parsed


def format_paste_text_preview(preview: dict[str, object]) -> str:
    return "\n".join(
        [
            "将要粘贴到当前前台应用：",
            f"应用: {_format_frontmost_app_label(preview.get('frontmost_app'))}",
            f"长度: {_format_text_length_label(length=preview.get('length'), text=preview.get('text'))}",
            f"粘贴后恢复剪贴板: {_format_boolean_label(preview.get('restore_clipboard'))}",
            "",
            "内容预览:",
            _trim_preview_block(str(preview.get("text") or "")),
        ]
    )


def preview_press_keys_request(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_press_keys_args(args)
    target = _resolve_input_target_sync()
    parsed["frontmost_app"] = target.get("app") or _get_frontmost_app_sync()
    return parsed


def format_press_keys_preview(preview: dict[str, object]) -> str:
    lines = [
        "将要发送键盘操作：",
        f"应用: {_format_frontmost_app_label(preview.get('frontmost_app'))}",
        f"按键: {str(preview.get('shortcut') or '').strip() or '（未指定）'}",
    ]
    repeat = int(preview.get("repeat", 1) or 1)
    if repeat > 1:
        lines.append(f"次数: {repeat}")
    return "\n".join(lines)


def format_write_tool_receipt(tool_name: str, payload: dict[str, object]) -> str | None:
    if not tool_name or not isinstance(payload, dict):
        return None

    if tool_name == "set_clipboard_text" or tool_name.endswith("__set_clipboard_text"):
        return "\n".join(
            [
                "剪贴板已更新",
                f"长度: {_format_text_length_label(length=payload.get('length'), text=payload.get('text'))}",
                f"内容: {_format_receipt_text_snippet(payload.get('text'))}",
            ]
        )

    if tool_name == "paste_text" or tool_name.endswith("__paste_text"):
        lines = [
            "文本已粘贴",
            f"应用: {_format_frontmost_app_label(payload.get('frontmost_app'))}",
            f"长度: {_format_text_length_label(length=payload.get('length'), text=payload.get('text'))}",
            f"内容: {_format_receipt_text_snippet(payload.get('text'))}",
        ]
        if payload.get("restore_clipboard") and (
            "clipboard_restored" in payload or "clipboard_restore_error" in payload
        ):
            lines.append(
                "剪贴板: "
                + ("已恢复" if bool(payload.get("clipboard_restored")) else "未恢复")
            )
        return "\n".join(lines)

    if tool_name == "press_keys" or tool_name.endswith("__press_keys"):
        shortcut = str(payload.get("shortcut") or "").strip()
        key = str(payload.get("key") or "").strip()
        modifiers = _normalize_modifiers(payload.get("modifiers"))
        if not shortcut and key:
            shortcut = _key_combo_label(key, modifiers)
        lines = [
            "按键已发送",
            f"应用: {_format_frontmost_app_label(payload.get('frontmost_app'))}",
            f"按键: {shortcut or '（未指定）'}",
        ]
        repeat = int(payload.get("repeat", 1) or 1)
        if repeat > 1:
            lines.append(f"次数: {repeat}")
        return "\n".join(lines)

    if tool_name == "focus_window" or tool_name.endswith("__focus_window"):
        app_payload = dict(payload.get("app") or {})
        window_payload = dict(payload.get("window") or {})
        lines = [
            "窗口已切到前台",
            f"应用: {_format_frontmost_app_label(app_payload)}",
        ]
        title = str(window_payload.get("title") or "").strip()
        if title:
            lines.append(f"窗口: {title}")
        window_id = window_payload.get("window_id")
        if window_id is not None:
            lines.append(f"窗口 id: {window_id}")
        return "\n".join(lines)

    if tool_name == "open_url" or tool_name.endswith("__open_url"):
        return "\n".join(
            [
                "链接已打开",
                f"链接: {str(payload.get('resolved_url') or payload.get('target') or '').strip() or '（无）'}",
            ]
        )

    return None
