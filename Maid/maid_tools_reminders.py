"""Reminders tool facade for the desktop maid."""

from __future__ import annotations

import maid_tools_reminders_core as _reminders_core
import maid_tools_reminders_format as _reminders_format
import maid_tools_reminders_tools as _reminders_tools


_DOMAIN_MODULES = (
    _reminders_core,
    _reminders_tools,
    _reminders_format,
)

for _module in _DOMAIN_MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__"):
            continue
        if _name in {
            "asyncio",
            "json",
            "Annotated",
            "NotRequired",
            "Required",
            "TypedDict",
            "tool",
        }:
            continue
        if _name in globals():
            continue
        globals()[_name] = _value

del _module, _name, _value, _DOMAIN_MODULES, _reminders_core, _reminders_tools, _reminders_format
