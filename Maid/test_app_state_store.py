"""Smoke test for persisted app/setup state.

Usage:
    .venv/bin/python -u Maid/test_app_state_store.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_app_state import (
    AppStateStore,
    DEFAULT_ACTIVITY_REMINDER_MINUTES,
    DEFAULT_ACTIVITY_REMINDER_TEXT,
    DEFAULT_CUSTOM_REMINDER_MINUTES,
    DEFAULT_CUSTOM_REMINDER_TEXT,
    DEFAULT_REMINDERS_ENABLED,
    DEFAULT_SPRITE_POSITION_X_PERCENT,
    DEFAULT_SPRITE_POSITION_Y_PERCENT,
    DEFAULT_SPRITE_SCREEN_MODE,
    DEFAULT_SPRITE_SIZE_PERCENT,
    DEFAULT_WATER_REMINDER_MINUTES,
    DEFAULT_WATER_REMINDER_TEXT,
    MAX_SPRITE_SIZE_PERCENT,
    MIN_SPRITE_SIZE_PERCENT,
    SPRITE_SCREEN_MODE_CURSOR,
    load_app_state_snapshot,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    with tempfile.TemporaryDirectory(prefix="deskmaid-app-state-") as tmp_dir:
        path = Path(tmp_dir) / "app_state.json"

        store = AppStateStore(path)
        snapshot = store.apply_setup(
            onboarding_seen=True,
            setup_version_seen=2,
            owner_name="阿律",
            budget_mode="cautious",
            language="英文",
            ui_language="跟随系统",
            data_boundary_acknowledged=True,
            auto_do_not_disturb_enabled=False,
            auto_hide_on_sensitive_scene=False,
        )
        snapshot = store.set_sprite_pack_id("maid")
        snapshot = store.set_sprite_display_preferences(
            sprite_size_percent=135,
            sprite_position_x_percent=75,
            sprite_position_y_percent=82,
            sprite_screen_mode=SPRITE_SCREEN_MODE_CURSOR,
        )
        _assert(snapshot.onboarding_seen, "expected onboarding_seen to persist")
        _assert(snapshot.setup_version_seen == 2, "expected setup version to persist")
        _assert(snapshot.owner_name == "阿律", "expected owner name to persist")
        _assert(snapshot.budget_mode == "cautious", "expected budget mode to persist")
        _assert(snapshot.language == "en-US", "expected language to normalize and persist")
        _assert(snapshot.ui_language == "system", "expected ui language to normalize and persist")
        _assert(snapshot.sprite_pack_id == "maid", "expected sprite pack id to persist")
        _assert(snapshot.sprite_size_percent == 135, "expected sprite size to persist")
        _assert(snapshot.sprite_position_x_percent == 75, "expected sprite x position to persist")
        _assert(snapshot.sprite_position_y_percent == 82, "expected sprite y position to persist")
        _assert(snapshot.sprite_screen_mode == SPRITE_SCREEN_MODE_CURSOR, "expected sprite screen mode to persist")
        _assert(snapshot.data_boundary_acknowledged, "expected boundary ack to persist")
        _assert(
            not snapshot.auto_do_not_disturb_enabled,
            "expected auto-dnd master switch to persist",
        )
        _assert(
            not snapshot.auto_hide_on_sensitive_scene,
            "expected auto-hide preference to persist",
        )
        snapshot = store.set_reminder_preferences(
            reminders_enabled=True,
            water_reminder_enabled=True,
            water_reminder_minutes=25,
            activity_reminder_enabled=False,
            activity_reminder_minutes=50,
            custom_reminder_enabled=True,
            custom_reminder_minutes=15,
            custom_reminder_text="自定义测试",
        )
        _assert(snapshot.reminders_enabled, "expected reminder master switch to persist")
        _assert(snapshot.water_reminder_enabled, "expected water reminder enabled to persist")
        _assert(snapshot.water_reminder_minutes == 25, "expected water reminder minutes to persist")
        _assert(
            snapshot.water_reminder_text == DEFAULT_WATER_REMINDER_TEXT,
            "water reminder text should stay on the preset pool default",
        )
        _assert(not snapshot.activity_reminder_enabled, "expected activity reminder enabled to persist")
        _assert(snapshot.activity_reminder_minutes == 50, "expected activity reminder minutes to persist")
        _assert(
            snapshot.activity_reminder_text == DEFAULT_ACTIVITY_REMINDER_TEXT,
            "activity reminder text should stay on the preset pool default",
        )
        _assert(snapshot.custom_reminder_enabled, "expected custom reminder enabled to persist")
        _assert(snapshot.custom_reminder_minutes == 15, "expected custom reminder minutes to persist")
        _assert(snapshot.custom_reminder_text == "自定义测试", "expected custom reminder text to persist")

        reloaded = load_app_state_snapshot(path)
        _assert(reloaded.owner_name == "阿律", "reloaded owner name mismatch")
        _assert(reloaded.budget_mode == "cautious", "reloaded budget mode mismatch")
        _assert(reloaded.language == "en-US", "reloaded language mismatch")
        _assert(reloaded.ui_language == "system", "reloaded ui language mismatch")
        _assert(reloaded.sprite_pack_id == "maid", "reloaded sprite pack mismatch")
        _assert(reloaded.sprite_size_percent == 135, "reloaded sprite size mismatch")
        _assert(reloaded.sprite_position_x_percent == 75, "reloaded sprite x position mismatch")
        _assert(reloaded.sprite_position_y_percent == 82, "reloaded sprite y position mismatch")
        _assert(reloaded.sprite_screen_mode == SPRITE_SCREEN_MODE_CURSOR, "reloaded sprite screen mode mismatch")
        _assert(reloaded.data_boundary_acknowledged, "reloaded boundary ack mismatch")
        _assert(
            not reloaded.auto_do_not_disturb_enabled,
            "reloaded auto-dnd master switch mismatch",
        )
        _assert(
            not reloaded.auto_hide_on_sensitive_scene,
            "reloaded auto-hide preference mismatch",
        )
        _assert(reloaded.reminders_enabled, "reloaded reminder master switch mismatch")
        _assert(reloaded.water_reminder_enabled, "reloaded water reminder enabled mismatch")
        _assert(reloaded.water_reminder_minutes == 25, "reloaded water reminder minutes mismatch")
        _assert(
            reloaded.water_reminder_text == DEFAULT_WATER_REMINDER_TEXT,
            "reloaded water reminder preset text mismatch",
        )
        _assert(not reloaded.activity_reminder_enabled, "reloaded activity reminder enabled mismatch")
        _assert(reloaded.activity_reminder_minutes == 50, "reloaded activity reminder minutes mismatch")
        _assert(
            reloaded.activity_reminder_text == DEFAULT_ACTIVITY_REMINDER_TEXT,
            "reloaded activity reminder preset text mismatch",
        )
        _assert(reloaded.custom_reminder_enabled, "reloaded custom reminder enabled mismatch")
        _assert(reloaded.custom_reminder_minutes == 15, "reloaded custom reminder minutes mismatch")
        _assert(reloaded.custom_reminder_text == "自定义测试", "reloaded custom reminder text mismatch")

        legacy_path = Path(tmp_dir) / "legacy_app_state.json"
        legacy_payload = {
            "version": 1,
            "onboarding_seen": True,
            "do_not_disturb": True,
            "updated_at": 123.0,
        }
        legacy_path.write_text(
            json.dumps(legacy_payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        legacy = load_app_state_snapshot(legacy_path)
        _assert(legacy.onboarding_seen, "legacy onboarding flag missing")
        _assert(
            legacy.setup_version_seen == 1,
            f"expected legacy setup version migration, got {legacy.setup_version_seen}",
        )
        _assert(legacy.do_not_disturb, "legacy do_not_disturb missing")
        _assert(legacy.budget_mode == "normal", "legacy budget mode default mismatch")
        _assert(legacy.language == "zh-CN", "legacy language default mismatch")
        _assert(legacy.ui_language == "system", "legacy ui language default mismatch")
        _assert(legacy.sprite_pack_id == "", "legacy sprite pack default mismatch")
        _assert(
            legacy.auto_do_not_disturb_enabled,
            "legacy auto-dnd master switch should stay enabled by default",
        )
        _assert(
            legacy.auto_hide_on_sensitive_scene,
            "legacy auto-hide default should stay enabled",
        )
        _assert(
            legacy.sprite_size_percent == DEFAULT_SPRITE_SIZE_PERCENT,
            "legacy sprite size default mismatch",
        )
        _assert(
            legacy.sprite_position_x_percent == DEFAULT_SPRITE_POSITION_X_PERCENT,
            "legacy sprite x position default mismatch",
        )
        _assert(
            legacy.sprite_position_y_percent == DEFAULT_SPRITE_POSITION_Y_PERCENT,
            "legacy sprite y position default mismatch",
        )
        _assert(
            legacy.sprite_screen_mode == DEFAULT_SPRITE_SCREEN_MODE,
            "legacy sprite screen mode default mismatch",
        )
        _assert(
            legacy.reminders_enabled == DEFAULT_REMINDERS_ENABLED,
            "legacy reminder master default mismatch",
        )
        _assert(legacy.water_reminder_enabled, "legacy water reminder should stay enabled")
        _assert(
            legacy.water_reminder_minutes == DEFAULT_WATER_REMINDER_MINUTES,
            "legacy water reminder minutes default mismatch",
        )
        _assert(
            legacy.water_reminder_text == DEFAULT_WATER_REMINDER_TEXT,
            "legacy water reminder text default mismatch",
        )
        _assert(legacy.activity_reminder_enabled, "legacy activity reminder should stay enabled")
        _assert(
            legacy.activity_reminder_minutes == DEFAULT_ACTIVITY_REMINDER_MINUTES,
            "legacy activity reminder minutes default mismatch",
        )
        _assert(
            legacy.activity_reminder_text == DEFAULT_ACTIVITY_REMINDER_TEXT,
            "legacy activity reminder text default mismatch",
        )
        _assert(
            not legacy.custom_reminder_enabled,
            "legacy custom reminder should stay disabled by default",
        )
        _assert(
            legacy.custom_reminder_minutes == DEFAULT_CUSTOM_REMINDER_MINUTES,
            "legacy custom reminder minutes default mismatch",
        )
        _assert(
            legacy.custom_reminder_text == DEFAULT_CUSTOM_REMINDER_TEXT,
            "legacy custom reminder text default mismatch",
        )

        clamped = store.set_sprite_display_preferences(
            sprite_size_percent=999,
            sprite_position_x_percent=-8,
            sprite_position_y_percent=108,
            sprite_screen_mode="somewhere-weird",
        )
        _assert(
            clamped.sprite_size_percent == MAX_SPRITE_SIZE_PERCENT,
            "sprite size should clamp high",
        )
        _assert(clamped.sprite_position_x_percent == 0, "sprite x should clamp low")
        _assert(clamped.sprite_position_y_percent == 100, "sprite y should clamp high")
        _assert(
            clamped.sprite_screen_mode == DEFAULT_SPRITE_SCREEN_MODE,
            "unknown sprite screen mode should fall back",
        )
        clamped = store.set_sprite_display_preferences(
            sprite_size_percent=1,
            sprite_position_x_percent=50,
            sprite_position_y_percent=50,
            sprite_screen_mode=SPRITE_SCREEN_MODE_CURSOR,
        )
        _assert(
            clamped.sprite_size_percent == MIN_SPRITE_SIZE_PERCENT,
            "sprite size should clamp low",
        )

    print("ok")


if __name__ == "__main__":
    main()
