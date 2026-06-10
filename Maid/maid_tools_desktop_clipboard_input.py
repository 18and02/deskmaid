"""Clipboard and keyboard-input desktop bridge helpers for the maid."""

from __future__ import annotations

import time

from maid_tools_shared import _run_applescript
from maid_tools_desktop_window_open import (
    _APPKIT_BRIDGES_ERR,
    _get_frontmost_app_sync,
    _list_windows_sync,
    _raise_window_with_system_events,
    _require_appkit_bridges,
    _running_app_payload_for_pid,
    NSApplicationActivateAllWindows,
    NSApplicationActivateIgnoringOtherApps,
    NSData,
    NSPasteboard,
    NSPasteboardItem,
    NSPasteboardTypeString,
    NSRunningApplication,
)

CGEventCreateKeyboardEvent = None
CGEventSetFlags = None
CGEventKeyboardSetUnicodeString = None
CGEventPostToPid = None
kCGEventFlagMaskCommand = None
kCGEventFlagMaskControl = None
kCGEventFlagMaskAlternate = None
kCGEventFlagMaskShift = None
try:
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPostToPid,
        CGEventSetFlags,
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskCommand,
        kCGEventFlagMaskControl,
        kCGEventFlagMaskShift,
    )

    HAVE_CG_KEYBOARD_BRIDGES = True
except Exception:
    HAVE_CG_KEYBOARD_BRIDGES = False


DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT = 10000
MAX_CLIPBOARD_TEXT_CHAR_LIMIT = 50000
MAX_PRESS_KEYS_REPEAT = 20
_INPUT_TARGET_MIN_WIDTH = 120
_INPUT_TARGET_MIN_HEIGHT = 80
_INPUT_TARGET_EXCLUDED_BUNDLE_IDS = {
    "com.apple.TextInputUI.xpc.CursorUIViewService",
    "com.apple.controlcenter",
    "com.apple.dock",
    "com.apple.loginwindow",
    "com.apple.notificationcenterui",
    "com.apple.systemuiserver",
    "com.ccswitch.desktop",
    "pro.betterdisplay.BetterDisplay",
}
_INPUT_TARGET_EXCLUDED_OWNER_NAMES = {
    "BetterDisplay",
    "CursorUIViewService",
    "Dock",
    "SystemUIServer",
    "cc-switch",
    "loginwindow",
}

_MODIFIER_ALIASES = {
    "command": "command",
    "cmd": "command",
    "shift": "shift",
    "option": "option",
    "alt": "option",
    "control": "control",
    "ctrl": "control",
    "fn": "fn",
    "function": "fn",
}

_MODIFIER_APPLESCRIPT = {
    "command": "command down",
    "shift": "shift down",
    "option": "option down",
    "control": "control down",
    "fn": "fn down",
}

_MODIFIER_LABELS = {
    "command": "Command",
    "shift": "Shift",
    "option": "Option",
    "control": "Control",
    "fn": "Fn",
}
_MODIFIER_CG_EVENT_FLAGS = {
    "command": kCGEventFlagMaskCommand,
    "control": kCGEventFlagMaskControl,
    "option": kCGEventFlagMaskAlternate,
    "shift": kCGEventFlagMaskShift,
}

_SPECIAL_KEY_CODES = {
    "return": 36,
    "enter": 76,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "esc": 53,
    "delete": 51,
    "backspace": 51,
    "forward_delete": 117,
    "left_arrow": 123,
    "right_arrow": 124,
    "down_arrow": 125,
    "up_arrow": 126,
    "home": 115,
    "end": 119,
    "page_up": 116,
    "page_down": 121,
}

_SPECIAL_KEY_LABELS = {
    "return": "Return",
    "enter": "Enter",
    "tab": "Tab",
    "space": "Space",
    "escape": "Escape",
    "esc": "Escape",
    "delete": "Delete",
    "backspace": "Delete",
    "forward_delete": "Forward Delete",
    "left_arrow": "Left Arrow",
    "right_arrow": "Right Arrow",
    "down_arrow": "Down Arrow",
    "up_arrow": "Up Arrow",
    "home": "Home",
    "end": "End",
    "page_up": "Page Up",
    "page_down": "Page Down",
}


def _window_can_receive_keyboard_input(window: dict[str, object]) -> bool:
    if not isinstance(window, dict):
        return False
    if not bool(window.get("is_onscreen", False)):
        return False

    bundle_id = str(window.get("bundle_id") or "").strip()
    owner_name = str(window.get("owner_name") or "").strip()
    if bundle_id in _INPUT_TARGET_EXCLUDED_BUNDLE_IDS:
        return False
    if owner_name in _INPUT_TARGET_EXCLUDED_OWNER_NAMES:
        return False

    bounds = dict(window.get("bounds") or {})
    try:
        width = int(bounds.get("width") or 0)
        height = int(bounds.get("height") or 0)
    except (TypeError, ValueError):
        return False
    if width < _INPUT_TARGET_MIN_WIDTH or height < _INPUT_TARGET_MIN_HEIGHT:
        return False

    pid = window.get("pid")
    try:
        pid_value = int(pid or 0)
    except (TypeError, ValueError):
        pid_value = 0
    return pid_value > 0


def _resolve_input_target_sync() -> dict[str, object]:
    try:
        snapshot = _list_windows_sync(
            on_screen_only=True,
            include_desktop_elements=False,
            include_nonzero_layer=False,
            limit=25,
        )
    except Exception:
        snapshot = None

    if isinstance(snapshot, dict):
        for raw_window in snapshot.get("windows") or []:
            window = dict(raw_window or {})
            if not _window_can_receive_keyboard_input(window):
                continue
            try:
                pid = int(window.get("pid") or 0) or None
            except (TypeError, ValueError):
                pid = None
            app_payload = _running_app_payload_for_pid(pid) or {
                "localized_name": window.get("owner_name"),
                "bundle_id": window.get("bundle_id"),
                "pid": pid,
                "active": None,
            }
            return {
                "resolved_by": "top_window",
                "frontmost_app": snapshot.get("frontmost_app"),
                "app": app_payload,
                "window": window,
            }

    frontmost_app = _get_frontmost_app_sync()
    return {
        "resolved_by": "frontmost_app",
        "frontmost_app": frontmost_app,
        "app": frontmost_app,
        "window": None,
    }


def _target_pid_from_payload(target: dict[str, object]) -> int | None:
    app_payload = dict(target.get("app") or {})
    window_payload = dict(target.get("window") or {})
    raw_pid = app_payload.get("pid")
    if raw_pid is None:
        raw_pid = window_payload.get("pid")
    try:
        pid = int(raw_pid or 0) or None
    except (TypeError, ValueError):
        pid = None
    return pid


def _activate_input_target_sync(target: dict[str, object]):
    pid = _target_pid_from_payload(target)
    if pid is not None and NSRunningApplication is not None:
        try:
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        except Exception:
            app = None
        if app is not None:
            try:
                options = (
                    int(NSApplicationActivateAllWindows)
                    | int(NSApplicationActivateIgnoringOtherApps)
                )
                app.activateWithOptions_(options)
            except Exception:
                pass

    window_payload = dict(target.get("window") or {})
    if window_payload:
        try:
            _raise_window_with_system_events(window_payload)
        except Exception:
            pass

    if pid is not None or window_payload:
        time.sleep(0.05)


def _run_keypress_sync(parsed: dict[str, object], target_pid: int | None):
    if HAVE_CG_KEYBOARD_BRIDGES and target_pid is not None:
        key = str(parsed.get("key") or "").strip()
        modifiers = list(parsed.get("modifiers") or [])
        repeat = int(parsed.get("repeat", 1) or 1)
        if key in {"return", "enter"} and not modifiers:
            _type_text_to_pid("\n" * max(1, repeat), target_pid)
            return
        if key == "tab" and not modifiers:
            _type_text_to_pid("\t" * max(1, repeat), target_pid)
            return
        if key in _SPECIAL_KEY_CODES:
            _post_special_key_to_pid(
                target_pid,
                _SPECIAL_KEY_CODES[key],
                modifiers,
                repeat,
            )
            return
        if len(key) == 1 and not modifiers:
            _type_text_to_pid(key, target_pid)
            return

    modifier_expr = ""
    if parsed["modifiers"]:
        modifier_expr = " using {" + ", ".join(
            _MODIFIER_APPLESCRIPT[item] for item in parsed["modifiers"]
        ) + "}"

    pid_arg = str(int(target_pid or 0))
    if len(parsed["key"]) == 1:
        script = f"""
on run argv
  set targetPid to item 1 of argv as integer
  set keyValue to item 2 of argv
  set repeatCount to item 3 of argv as integer
  tell application "System Events"
    if targetPid > 0 then
      try
        set targetProcess to first application process whose unix id is targetPid
        set frontmost of targetProcess to true
        delay 0.05
      end try
    end if
    repeat repeatCount times
      keystroke keyValue{modifier_expr}
    end repeat
  end tell
  return "ok"
end run
""".strip()
        _run_applescript(
            script,
            args=[pid_arg, parsed["key"], str(parsed["repeat"])],
            timeout_s=20.0,
        )
        return

    key_code = _SPECIAL_KEY_CODES[parsed["key"]]
    script = f"""
on run argv
  set targetPid to item 1 of argv as integer
  set keyCodeValue to item 2 of argv as integer
  set repeatCount to item 3 of argv as integer
  tell application "System Events"
    if targetPid > 0 then
      try
        set targetProcess to first application process whose unix id is targetPid
        set frontmost of targetProcess to true
        delay 0.05
      end try
    end if
    repeat repeatCount times
      key code keyCodeValue{modifier_expr}
    end repeat
  end tell
  return "ok"
end run
""".strip()
    _run_applescript(
        script,
        args=[pid_arg, str(key_code), str(parsed["repeat"])],
        timeout_s=20.0,
    )


def _modifier_cg_flags(modifiers: list[str]) -> int:
    value = 0
    for item in modifiers:
        flag = _MODIFIER_CG_EVENT_FLAGS.get(item)
        if flag is None:
            continue
        value |= int(flag)
    return value


def _post_special_key_to_pid(
    target_pid: int,
    key_code: int,
    modifiers: list[str],
    repeat: int,
):
    flags = _modifier_cg_flags(modifiers)
    for _ in range(max(1, int(repeat))):
        down = CGEventCreateKeyboardEvent(None, int(key_code), True)
        up = CGEventCreateKeyboardEvent(None, int(key_code), False)
        if flags:
            CGEventSetFlags(down, flags)
            CGEventSetFlags(up, flags)
        CGEventPostToPid(int(target_pid), down)
        CGEventPostToPid(int(target_pid), up)
        time.sleep(0.01)


def _type_text_to_pid(text: str, target_pid: int):
    normalized = str(text or "")
    if not normalized:
        return
    for char in normalized:
        down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(down, 1, char)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(up, 1, char)
        CGEventPostToPid(int(target_pid), down)
        CGEventPostToPid(int(target_pid), up)
        time.sleep(0.005)


def _snapshot_clipboard_items() -> list[dict[str, bytes]]:
    _require_appkit_bridges("clipboard")
    pasteboard = NSPasteboard.generalPasteboard()
    snapshot: list[dict[str, bytes]] = []
    items = pasteboard.pasteboardItems() or []
    for item in items:
        captured: dict[str, bytes] = {}
        for item_type in item.types() or []:
            type_name = str(item_type or "").strip()
            if not type_name:
                continue
            try:
                data = item.dataForType_(item_type)
            except Exception:
                data = None
            if data is None:
                continue
            try:
                captured[type_name] = bytes(data)
            except Exception:
                continue
        if captured:
            snapshot.append(captured)
    return snapshot


def _restore_clipboard_items(snapshot: list[dict[str, bytes]] | None):
    _require_appkit_bridges("clipboard")
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()

    rows = snapshot or []
    if not rows:
        return

    items = []
    for row in rows:
        pasteboard_item = NSPasteboardItem.alloc().init()
        has_any = False
        for item_type, raw in row.items():
            type_name = str(item_type or "").strip()
            if not type_name:
                continue
            blob = bytes(raw or b"")
            data = NSData.dataWithBytes_length_(blob, len(blob))
            pasteboard_item.setData_forType_(data, type_name)
            has_any = True
        if has_any:
            items.append(pasteboard_item)
    if items:
        pasteboard.writeObjects_(items)


def _read_clipboard_text_sync(
    max_chars: int = DEFAULT_CLIPBOARD_TEXT_CHAR_LIMIT,
) -> dict[str, object]:
    _require_appkit_bridges("read_clipboard_text")

    safe_max_chars = int(max_chars)
    if safe_max_chars < 1:
        safe_max_chars = 1
    if safe_max_chars > MAX_CLIPBOARD_TEXT_CHAR_LIMIT:
        safe_max_chars = MAX_CLIPBOARD_TEXT_CHAR_LIMIT

    pasteboard = NSPasteboard.generalPasteboard()
    raw_text = pasteboard.stringForType_(NSPasteboardTypeString)
    text = str(raw_text) if raw_text is not None else ""
    truncated = len(text) > safe_max_chars
    returned = text[:safe_max_chars] if truncated else text

    return {
        "text": returned,
        "full_length": len(text),
        "returned_length": len(returned),
        "truncated": truncated,
        "has_text": bool(raw_text is not None),
        "change_count": int(pasteboard.changeCount()),
    }


def _set_clipboard_text_sync(text: str) -> dict[str, object]:
    _require_appkit_bridges("set_clipboard_text")

    normalized = str(text)
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    wrote = pasteboard.setString_forType_(normalized, NSPasteboardTypeString)
    if not bool(wrote):
        raise RuntimeError("failed to write text to the clipboard")

    return {
        "text": normalized,
        "length": len(normalized),
        "change_count": int(pasteboard.changeCount()),
    }


def _normalize_modifiers(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError("modifiers must be a string or a list of strings")

    modifiers: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        raw = str(item or "").strip().lower()
        if not raw:
            continue
        canonical = _MODIFIER_ALIASES.get(raw)
        if not canonical:
            raise ValueError(f"unsupported modifier: {item!r}")
        if canonical in seen:
            continue
        seen.add(canonical)
        modifiers.append(canonical)
    return modifiers


def _normalize_press_key(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("key is required")
    if len(raw) == 1:
        return raw
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    if normalized in _SPECIAL_KEY_CODES:
        return normalized
    raise ValueError(f"unsupported key: {value!r}")


def _key_label(key: str) -> str:
    if len(key) == 1:
        return key.upper()
    return _SPECIAL_KEY_LABELS.get(key, key)


def _key_combo_label(key: str, modifiers: list[str] | None = None) -> str:
    parts = [_MODIFIER_LABELS[item] for item in (modifiers or [])]
    parts.append(_key_label(key))
    return " + ".join(part for part in parts if part)


def _parse_press_keys_args(args: dict[str, object]) -> dict[str, object]:
    safe_repeat = int(args.get("repeat", 1))
    if safe_repeat < 1:
        safe_repeat = 1
    if safe_repeat > MAX_PRESS_KEYS_REPEAT:
        safe_repeat = MAX_PRESS_KEYS_REPEAT

    key = _normalize_press_key(args.get("key"))
    modifiers = _normalize_modifiers(args.get("modifiers"))
    return {
        "key": key,
        "modifiers": modifiers,
        "repeat": safe_repeat,
        "shortcut": _key_combo_label(key, modifiers),
    }


def _press_keys_sync(
    key: str,
    modifiers: list[str] | None = None,
    repeat: int = 1,
) -> dict[str, object]:
    parsed = _parse_press_keys_args(
        {
            "key": key,
            "modifiers": modifiers or [],
            "repeat": repeat,
        }
    )
    target = _resolve_input_target_sync()
    frontmost_app = dict(target.get("app") or {})
    _activate_input_target_sync(target)
    _run_keypress_sync(parsed, _target_pid_from_payload(target))

    result = dict(parsed)
    result["frontmost_app"] = frontmost_app
    result["target_window"] = dict(target.get("window") or {})
    result["resolved_by"] = str(target.get("resolved_by") or "")
    return result


def _paste_text_sync(
    text: str,
    restore_clipboard: bool = True,
) -> dict[str, object]:
    normalized = str(text)
    target = _resolve_input_target_sync()
    frontmost_app = dict(target.get("app") or {})
    target_pid = _target_pid_from_payload(target)
    use_direct_text_input = bool(HAVE_CG_KEYBOARD_BRIDGES and target_pid is not None)
    clipboard_snapshot = (
        _snapshot_clipboard_items()
        if (restore_clipboard and not use_direct_text_input)
        else None
    )
    clipboard_restored = False
    clipboard_restore_error = None
    paste_error: Exception | None = None

    try:
        _activate_input_target_sync(target)
        if use_direct_text_input:
            _type_text_to_pid(normalized, int(target_pid))
            if restore_clipboard:
                clipboard_restored = True
        else:
            _set_clipboard_text_sync(normalized)
            time.sleep(0.05)
            _run_keypress_sync(
                _parse_press_keys_args(
                    {
                        "key": "v",
                        "modifiers": ["command"],
                        "repeat": 1,
                    }
                ),
                target_pid,
            )
    except Exception as exc:
        paste_error = exc
    finally:
        if restore_clipboard and clipboard_snapshot is not None:
            try:
                time.sleep(0.05)
                _restore_clipboard_items(clipboard_snapshot)
                clipboard_restored = True
            except Exception as exc:
                clipboard_restore_error = str(exc)

    if paste_error is not None:
        if clipboard_restore_error:
            raise RuntimeError(
                f"{paste_error}; clipboard restore also failed: {clipboard_restore_error}"
            )
        raise paste_error

    return {
        "text": normalized,
        "length": len(normalized),
        "restore_clipboard": bool(restore_clipboard),
        "clipboard_restored": clipboard_restored,
        "clipboard_restore_error": clipboard_restore_error,
        "frontmost_app": frontmost_app,
        "target_window": dict(target.get("window") or {}),
        "resolved_by": str(target.get("resolved_by") or ""),
    }
