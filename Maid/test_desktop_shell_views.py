"""Smoke tests for sprite-pack and auto-DND shell views.

Usage:
    .venv/bin/python -u Maid/test_desktop_shell_views.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_auto_dnd import AutoDoNotDisturbState
from maid_sprite_packs import resolve_sprite_pack
import main as maid_main


ASSETS = Path(__file__).resolve().parent / "assets"


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _find_card(cards: list[dict[str, object]], title: str) -> dict[str, object]:
    for card in cards:
        if str(card.get("title") or "") == title:
            return card
    raise AssertionError(f"missing card {title!r}")


def main():
    sprite_pack = resolve_sprite_pack(assets_dir=ASSETS, sprite_set="maid", sprite=None)
    sprite_view = maid_main._build_sprite_pack_info_view(sprite_pack, language="zh-CN")
    sprite_view_en = maid_main._build_sprite_pack_info_view(sprite_pack, language="en-US")

    _assert(
        "当前立绘包" in str(sprite_view.get("status_text") or ""),
        f"unexpected zh sprite-pack status: {sprite_view!r}",
    )
    _assert(
        "Current sprite pack" in str(sprite_view_en.get("status_text") or ""),
        f"unexpected en sprite-pack status: {sprite_view_en!r}",
    )

    sprite_cards = [
        dict(item) for item in (sprite_view.get("cards") or []) if isinstance(item, dict)
    ]
    sprite_cards_en = [
        dict(item) for item in (sprite_view_en.get("cards") or []) if isinstance(item, dict)
    ]
    _assert(_find_card(sprite_cards, "状态覆盖"), "missing zh state coverage card")
    _assert(_find_card(sprite_cards_en, "State Coverage"), "missing en state coverage card")

    auto_state = AutoDoNotDisturbState(
        active=True,
        reason_key="screen_share",
        reason_text="共享/演示场景",
        detail="Google Chrome: Weekly review - sharing screen",
        frontmost_app_name="Google Chrome",
        frontmost_bundle_id="com.google.Chrome",
        updated_at=1_717_000_000.0,
    )
    auto_view = maid_main._build_auto_dnd_status_view(
        state=auto_state,
        auto_dnd_enabled=True,
        manual_dnd_enabled=False,
        auto_hide_enabled=True,
        outing_active=True,
        language="zh-CN",
    )
    auto_view_en = maid_main._build_auto_dnd_status_view(
        state=auto_state,
        auto_dnd_enabled=True,
        manual_dnd_enabled=True,
        auto_hide_enabled=True,
        outing_active=True,
        language="en-US",
    )
    auto_view_disabled = maid_main._build_auto_dnd_status_view(
        state=auto_state,
        auto_dnd_enabled=False,
        manual_dnd_enabled=False,
        auto_hide_enabled=True,
        outing_active=False,
        language="zh-CN",
    )

    _assert(
        "当前自动免打扰已开启" in str(auto_view.get("status_text") or ""),
        f"unexpected zh auto-dnd status: {auto_view!r}",
    )
    _assert(
        "Auto DND is active" in str(auto_view_en.get("status_text") or ""),
        f"unexpected en auto-dnd status: {auto_view_en!r}",
    )

    auto_cards = [
        dict(item) for item in (auto_view.get("cards") or []) if isinstance(item, dict)
    ]
    auto_cards_en = [
        dict(item) for item in (auto_view_en.get("cards") or []) if isinstance(item, dict)
    ]
    _assert(_find_card(auto_cards, "当前状态"), "missing zh auto-dnd current-state card")
    _assert(_find_card(auto_cards_en, "Current Status"), "missing en auto-dnd current-state card")
    _assert(
        "自动免打扰检测已关闭" in str(auto_view_disabled.get("status_text") or ""),
        f"unexpected disabled zh auto-dnd status: {auto_view_disabled!r}",
    )
    _assert(
        not bool(auto_view_disabled.get("refresh_enabled", True)),
        "disabled auto-dnd view should disable refresh",
    )

    auto_receipt = maid_main._localized_auto_dnd_toggle_receipt(
        True,
        ui_language="zh-CN",
    )
    auto_receipt_en = maid_main._localized_auto_dnd_toggle_receipt(
        False,
        ui_language="en-US",
    )
    _assert(
        "状态回执 · 自动免打扰检测" in auto_receipt and "状态: 已开启" in auto_receipt,
        f"unexpected zh auto-dnd receipt: {auto_receipt!r}",
    )
    _assert(
        "Receipt · Auto DND Detection" in auto_receipt_en and "Status: Disabled" in auto_receipt_en,
        f"unexpected en auto-dnd receipt: {auto_receipt_en!r}",
    )

    memory_receipt = maid_main._localized_memory_write_receipt(
        {
            "text": "主人最喜欢的水果是葡萄。",
            "source": "请记住这件事：我最喜欢的水果是葡萄。",
            "reason_key": "explicit_instruction",
            "expiry_policy_key": "forever",
            "expiry_days": None,
            "conflict_policy_key": "same_topic",
            "write_action": "updated",
            "replaced_items": [
                {"text": "主人最喜欢的水果是苹果。"},
            ],
            "pruned_expired_count": 1,
        },
        ui_language="zh-CN",
    )
    _assert(
        "状态回执 · 长期记忆" in memory_receipt
        and "动作: 已更新" in memory_receipt
        and "覆盖:" in memory_receipt,
        f"unexpected zh memory receipt: {memory_receipt!r}",
    )

    print("ok")


if __name__ == "__main__":
    main()
