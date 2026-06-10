"""Desktop tool definitions for the desktop maid."""

from __future__ import annotations

import asyncio
from typing import Annotated, NotRequired, Required, TypedDict

from claude_agent_sdk import tool

from maid_tools_desktop_clipboard_input import (
    _parse_press_keys_args,
    _paste_text_sync,
    _press_keys_sync,
    _read_clipboard_text_sync,
    _set_clipboard_text_sync,
)
from maid_tools_desktop_format import (
    _parse_paste_text_args,
    _parse_read_clipboard_text_args,
    _parse_set_clipboard_text_args,
)
from maid_tools_desktop_window_open import (
    _focus_window_sync,
    _get_frontmost_app_sync,
    _list_windows_sync,
    _open_app_sync,
    _open_url_sync,
    _parse_list_windows_args,
)
from maid_tools_shared import _normalize_required_text, _tool_error_result, _tool_success_result


class OpenAppArgs(TypedDict, total=False):
    target: Required[Annotated[
        str,
        "The macOS app to open. Accepts an app name like 'Calendar', a bundle id "
        "like 'com.apple.iCal', or an absolute/~/ path to an .app bundle.",
    ]]
    activate: NotRequired[
        Annotated[bool, "Bring the app to the front. Defaults to true."]
    ]
    new_instance: NotRequired[
        Annotated[
            bool,
            "Launch a new instance instead of reusing the current one when possible. "
            "Defaults to false.",
        ]
    ]


class OpenUrlArgs(TypedDict, total=False):
    target: Required[Annotated[
        str,
        "A URL, deep link, bare domain, host:port, or an existing absolute/~/ local path to open.",
    ]]
    activate: NotRequired[
        Annotated[
            bool,
            "Whether the target app should be activated after opening. Defaults to true.",
        ]
    ]


class GetFrontmostAppArgs(TypedDict, total=False):
    pass


class ListWindowsArgs(TypedDict, total=False):
    owner_names: NotRequired[
        Annotated[
            list[str],
            "Optional app names to filter windows by owner, such as ['Safari', 'Finder'].",
        ]
    ]
    title_contains: NotRequired[
        Annotated[
            str,
            "Optional case-insensitive substring to match inside window titles.",
        ]
    ]
    on_screen_only: NotRequired[
        Annotated[
            bool,
            "Whether to return only currently on-screen windows. Defaults to true.",
        ]
    ]
    include_desktop_elements: NotRequired[
        Annotated[
            bool,
            "Whether to include desktop-level windows. Defaults to false.",
        ]
    ]
    include_nonzero_layer: NotRequired[
        Annotated[
            bool,
            "Whether to include nonstandard window layers such as overlays and menus. Defaults to false.",
        ]
    ]
    limit: NotRequired[
        Annotated[
            int,
            "Maximum number of windows to return. Defaults to 60 and is capped at 200.",
        ]
    ]


class FocusWindowArgs(TypedDict, total=False):
    window_id: NotRequired[
        Annotated[
            int,
            "Optional window id returned by list_windows. Passing window_id by itself is enough when it uniquely identifies the target window.",
        ]
    ]
    id: NotRequired[
        Annotated[
            int,
            "Alias of window_id: window id returned by list_windows.",
        ]
    ]
    pid: NotRequired[
        Annotated[
            int,
            "Optional process id of the target app window.",
        ]
    ]
    bundle_id: NotRequired[
        Annotated[
            str,
            "Optional bundle id of the target app window, such as com.google.Chrome.",
        ]
    ]
    owner_name: NotRequired[
        Annotated[
            str,
            "Optional owner app name, such as 'Google Chrome' or 'Codex'.",
        ]
    ]
    app: NotRequired[
        Annotated[
            str,
            "Alias of owner_name: app name whose window should be focused.",
        ]
    ]
    app_name: NotRequired[
        Annotated[
            str,
            "Alias of owner_name: app name whose window should be focused.",
        ]
    ]
    title: NotRequired[
        Annotated[
            str,
            "Optional exact window title to focus.",
        ]
    ]
    window_title: NotRequired[
        Annotated[
            str,
            "Alias of title: exact window title to focus.",
        ]
    ]
    title_contains: NotRequired[
        Annotated[
            str,
            "Optional case-insensitive substring to match inside the target window title.",
        ]
    ]


class ReadClipboardTextArgs(TypedDict, total=False):
    max_chars: NotRequired[
        Annotated[
            int,
            "Maximum number of clipboard characters to return. Defaults to 10000.",
        ]
    ]


class SetClipboardTextArgs(TypedDict, total=False):
    text: Required[Annotated[
        str,
        "Plain text to write to the macOS system clipboard.",
    ]]


class PasteTextArgs(TypedDict, total=False):
    text: Required[Annotated[
        str,
        "Plain text to paste into the current frontmost macOS app.",
    ]]
    restore_clipboard: NotRequired[
        Annotated[
            bool,
            "Whether to restore the previous clipboard contents after paste. Defaults to true.",
        ]
    ]


class PressKeysArgs(TypedDict, total=False):
    key: Required[Annotated[
        str,
        "A single printable key like 'v' or a named key like 'return', 'tab', 'escape', 'up_arrow'.",
    ]]
    modifiers: NotRequired[
        Annotated[
            list[str],
            "Optional modifier keys such as ['command', 'shift', 'option', 'control', 'fn'].",
        ]
    ]
    repeat: NotRequired[
        Annotated[
            int,
            "How many times to send the key press. Defaults to 1 and is capped at 20.",
        ]
    ]


@tool(
    name="open_app",
    description=(
        "Open or bring a macOS application to the front. Use this when the user "
        "asks to open, launch, switch to, or focus an app."
    ),
    input_schema=OpenAppArgs,
)
async def open_app(args: OpenAppArgs) -> dict:
    try:
        result = await asyncio.to_thread(
            _open_app_sync,
            str(args.get("target", "")).strip(),
            bool(args.get("activate", True)),
            bool(args.get("new_instance", False)),
        )
    except Exception as exc:
        return _tool_error_result("open_app", exc)

    return _tool_success_result("open_app", result)


@tool(
    name="open_url",
    description=(
        "Open a URL, deep link, bare domain, host:port, or existing local path with "
        "the default macOS app. Use this when the user asks to open a web page or link."
    ),
    input_schema=OpenUrlArgs,
)
async def open_url(args: OpenUrlArgs) -> dict:
    try:
        result = await asyncio.to_thread(
            _open_url_sync,
            _normalize_required_text(args.get("target"), "target"),
            bool(args.get("activate", True)),
        )
    except Exception as exc:
        return _tool_error_result("open_url", exc)

    return _tool_success_result("open_url", result)


@tool(
    name="get_frontmost_app",
    description=(
        "Return the current frontmost macOS app. Use this when the user asks "
        "which app is active right now or before sending follow-up keyboard actions."
    ),
    input_schema=GetFrontmostAppArgs,
)
async def get_frontmost_app(args: GetFrontmostAppArgs) -> dict:
    try:
        result = await asyncio.to_thread(_get_frontmost_app_sync)
    except Exception as exc:
        return _tool_error_result("get_frontmost_app", exc)

    return _tool_success_result("get_frontmost_app", result)


@tool(
    name="list_windows",
    description=(
        "List visible macOS windows on the desktop. Use this when the user asks "
        "which windows are open, what app windows are visible, or to locate a named window."
    ),
    input_schema=ListWindowsArgs,
)
async def list_windows(args: ListWindowsArgs) -> dict:
    parsed = _parse_list_windows_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _list_windows_sync,
            parsed["owner_names"],
            parsed["title_contains"],
            parsed["on_screen_only"],
            parsed["include_desktop_elements"],
            parsed["include_nonzero_layer"],
            parsed["limit"],
        )
    except Exception as exc:
        return _tool_error_result("list_windows", exc)

    return _tool_success_result("list_windows", result)


@tool(
    name="focus_window",
    description=(
        "Bring a specific macOS window or app window to the front. Prefer using a "
        "window_id from list_windows when possible. A window_id alone is sufficient "
        "when it uniquely identifies the target window; otherwise narrow by app and title."
    ),
    input_schema=FocusWindowArgs,
)
async def focus_window(args: FocusWindowArgs) -> dict:
    try:
        result = await asyncio.to_thread(_focus_window_sync, dict(args))
    except Exception as exc:
        return _tool_error_result("focus_window", exc)

    return _tool_success_result("focus_window", result)


@tool(
    name="read_clipboard_text",
    description=(
        "Read the current macOS system clipboard as plain text. Use this when the "
        "user asks what text is currently copied."
    ),
    input_schema=ReadClipboardTextArgs,
)
async def read_clipboard_text(args: ReadClipboardTextArgs) -> dict:
    parsed = _parse_read_clipboard_text_args(dict(args))

    try:
        result = await asyncio.to_thread(_read_clipboard_text_sync, parsed["max_chars"])
    except Exception as exc:
        return _tool_error_result("read_clipboard_text", exc)

    return _tool_success_result("read_clipboard_text", result)


@tool(
    name="set_clipboard_text",
    description=(
        "Write plain text into the macOS system clipboard. Use this when the user "
        "asks to copy text for later paste."
    ),
    input_schema=SetClipboardTextArgs,
)
async def set_clipboard_text(args: SetClipboardTextArgs) -> dict:
    parsed = _parse_set_clipboard_text_args(dict(args))

    try:
        result = await asyncio.to_thread(_set_clipboard_text_sync, parsed["text"])
    except Exception as exc:
        return _tool_error_result("set_clipboard_text", exc)

    return _tool_success_result("set_clipboard_text", result)


@tool(
    name="paste_text",
    description=(
        "Paste plain text into the current frontmost macOS app by temporarily "
        "setting the clipboard and sending Command-V."
    ),
    input_schema=PasteTextArgs,
)
async def paste_text(args: PasteTextArgs) -> dict:
    parsed = _parse_paste_text_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _paste_text_sync,
            parsed["text"],
            parsed["restore_clipboard"],
        )
    except Exception as exc:
        return _tool_error_result("paste_text", exc)

    return _tool_success_result("paste_text", result)


@tool(
    name="press_keys",
    description=(
        "Send a key press or keyboard shortcut to the current frontmost macOS app. "
        "Use this for Return, Tab, Escape, arrow keys, or shortcuts like Command-V."
    ),
    input_schema=PressKeysArgs,
)
async def press_keys(args: PressKeysArgs) -> dict:
    parsed = _parse_press_keys_args(dict(args))

    try:
        result = await asyncio.to_thread(
            _press_keys_sync,
            parsed["key"],
            parsed["modifiers"],
            parsed["repeat"],
        )
    except Exception as exc:
        return _tool_error_result("press_keys", exc)

    return _tool_success_result("press_keys", result)
