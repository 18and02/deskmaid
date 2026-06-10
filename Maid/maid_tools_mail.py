"""Mail tool facade for the desktop maid."""

from __future__ import annotations

import maid_tools_mail_core as _mail_core
import maid_tools_mail_draft as _mail_draft
import maid_tools_mail_read as _mail_read
import maid_tools_mail_send as _mail_send


_DOMAIN_MODULES = (
    _mail_core,
    _mail_read,
    _mail_draft,
    _mail_send,
)

for _module in _DOMAIN_MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__"):
            continue
        if _name in {
            "asyncio",
            "json",
            "time",
            "Annotated",
            "NotRequired",
            "TypedDict",
            "tool",
        }:
            continue
        if _name in globals():
            continue
        globals()[_name] = _value

del (
    _module,
    _name,
    _value,
    _DOMAIN_MODULES,
    _mail_core,
    _mail_read,
    _mail_draft,
    _mail_send,
)
