"""Calendar tool facade for the desktop maid."""

from __future__ import annotations

import maid_tools_calendar_core as _calendar_core
import maid_tools_calendar_format as _calendar_format
import maid_tools_calendar_tools as _calendar_tools


_DOMAIN_MODULES = (
    _calendar_core,
    _calendar_tools,
    _calendar_format,
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

del _module, _name, _value, _DOMAIN_MODULES, _calendar_core, _calendar_tools, _calendar_format
