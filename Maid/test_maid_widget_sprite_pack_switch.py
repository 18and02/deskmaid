"""Smoke test for runtime sprite-pack switching in MaidWidget."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from bubble import SpeechBubble
from maid_app_state import load_app_state_snapshot
from maid_sprite_packs import resolve_sprite_pack
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _visible_render_bounds(widget) -> tuple[int, int, int, int] | None:
    image = _render_widget_image(widget)
    left = image.width()
    top = image.height()
    right = -1
    bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() <= 0:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return None
    return left, top, right, bottom


def _render_widget_image(widget, image: QImage | None = None) -> QImage:
    if image is None:
        image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
    widget.render(image)
    return image


def _assert_same_pixels(left: QImage, right: QImage, message: str):
    _assert(left.size() == right.size(), f"{message}: image size mismatch")
    for y in range(left.height()):
        for x in range(left.width()):
            if left.pixelColor(x, y) != right.pixelColor(x, y):
                print(
                    f"[error] {message}: pixel mismatch at ({x},{y}) "
                    f"{left.pixelColor(x, y).getRgb()} != {right.pixelColor(x, y).getRgb()}",
                    file=sys.stderr,
                )
                sys.exit(1)


def _visible_render_width(widget) -> int:
    bounds = _visible_render_bounds(widget)
    _assert(bounds is not None, "rendered widget should contain visible sprite pixels")
    left, _top, right, _bottom = bounds
    return right - left + 1


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="deskmaid-widget-pack-switch-") as tmp_dir:
        os.environ["MAID_APP_STATE_PATH"] = str(Path(tmp_dir) / "app_state.json")
        os.environ["MAID_BUDGET_STATE_PATH"] = str(Path(tmp_dir) / "budget_state.json")
        os.environ["MAID_OUTING_STATE_PATH"] = str(Path(tmp_dir) / "outing_state.json")
        maid_main.HAVE_AUTO_DND_NATIVE_NOTIFICATIONS = False

        bubble = SpeechBubble()
        sprite_pack = resolve_sprite_pack(
            assets_dir=maid_main.ASSETS,
            sprite_set="placeholder",
            sprite=None,
        )
        widget = maid_main.MaidWidget(sprite_pack, bubble, demo_short=True)
        target_pack = resolve_sprite_pack(
            assets_dir=maid_main.ASSETS,
            sprite_set="maid",
            sprite=None,
        )

        widget._replace_sprite_pack(target_pack, persist=True, announce=False)

        snapshot = load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        _assert(widget._sprite_pack.pack_id == "maid", f"unexpected pack id: {widget._sprite_pack.pack_id!r}")
        _assert(snapshot.sprite_pack_id == "maid", f"unexpected persisted pack id: {snapshot.sprite_pack_id!r}")
        _assert(widget._asset_w > 0 and widget._asset_h > 0, "asset size should stay valid after switching")
        _assert(widget._current_pixmap().size().width() > 0, "pixmap should still resolve after switching")

        widget._enter_until = None
        widget._state = maid_main.MaidState.IDLE
        widget._mood = "default"
        visible_width_before_scale = _visible_render_width(widget)
        old_width = widget.width()
        widget._save_sprite_display_preferences(
            {
                "sprite_size_percent": 150,
                "sprite_position_x_percent": 10,
                "sprite_position_y_percent": 20,
                "sprite_screen_mode": maid_main.SPRITE_SCREEN_MODE_PRIMARY,
            }
        )
        snapshot = load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        widget.end_alert()
        visible_width_after_scale = _visible_render_width(widget)
        _assert(snapshot.sprite_size_percent == 150, "sprite size preference should persist")
        _assert(snapshot.sprite_position_x_percent == 10, "sprite x preference should persist")
        _assert(snapshot.sprite_position_y_percent == 20, "sprite y preference should persist")
        _assert(
            snapshot.sprite_screen_mode == maid_main.SPRITE_SCREEN_MODE_PRIMARY,
            "sprite screen preference should persist",
        )
        _assert(widget.width() > old_width, "sprite display size should apply immediately")
        _assert(
            visible_width_after_scale > visible_width_before_scale,
            "sprite render should scale visible art, not only the debug/window border",
        )
        screen = app.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            expected_x = geo.left() + round(max(0, geo.width() - widget.width()) * 0.10)
            expected_y = geo.top() + round(max(0, geo.height() - widget.height()) * 0.20)
            _assert(abs(widget.x() - expected_x) <= 1, f"unexpected sprite x position: {widget.x()} != {expected_x}")
            _assert(abs(widget.y() - expected_y) <= 1, f"unexpected sprite y position: {widget.y()} != {expected_y}")
        widget.end_alert()

        widget._enter_until = None
        widget._mood = "default"
        now = widget._t0 + 100.0
        widget._last_activity_at = now
        widget._next_peckish_at = now - 1.0
        widget._next_sleepy_at = now + 9999.0
        widget._update_mood(now)
        _assert(widget._mood == "peckish", "peckish should start as a short ambient insert")
        _assert(widget._current_state_key() == "peckish", "peckish sprite should show during its insert window")
        widget._update_mood(widget._mood_until + 0.1)
        _assert(widget._mood == "default", "peckish should return to default instead of permanently hiding idle/blink")
        widget._eye_closed = True
        _assert(widget._current_state_key() == "blink", "blink should be visible again after peckish insert ends")
        widget._eye_closed = False
        widget._dragging = True
        _assert(widget._current_state_key() == "held", "held sprite should show while dragging")
        _assert(not widget._blink_allowed(now), "blink should pause while dragging")
        widget._dragging = False

        petdex_pack = resolve_sprite_pack(
            assets_dir=maid_main.ASSETS,
            sprite_set="petdex-maid-codex",
            sprite=None,
        )
        widget._replace_sprite_pack(petdex_pack, persist=False, announce=False)
        widget._enter_until = None
        widget._state = maid_main.MaidState.IDLE
        widget._outing_active = False
        widget._mood = "default"
        widget._eye_closed = False
        widget._y_offset = 0
        widget._active_sprite_state_key = "idle"
        widget._active_sprite_variant_index = 0
        reused_image = _render_widget_image(widget)
        widget._outing_active = True
        widget._select_sprite_variant("outing")
        reused_image = _render_widget_image(widget, reused_image)
        clean_outing_image = _render_widget_image(widget)
        _assert_same_pixels(
            reused_image,
            clean_outing_image,
            "painting outing over a previous pose should clear stale transparent pixels",
        )
        widget._outing_active = False
        widget._enter_until = widget._t0 + 9999.0 if "enter" in widget._sprites else None

        _assert(widget._enter_until is not None, "petdex pack should start with enter transition")
        widget.show_alert("立即触发提醒测试")
        _assert(widget._enter_until is None, "alert should interrupt enter transition")
        _assert(widget._state == maid_main.MaidState.ALERT, f"unexpected state: {widget._state!r}")
        _assert(widget._current_state_key() == "alert", f"unexpected alert state key: {widget._current_state_key()!r}")
        _assert(bubble.isVisible(), "alert should show speech bubble for petdex pack")

        widget.end_alert()
        widget._do_not_disturb = True
        widget.show_alert("普通提醒会尊重免打扰")
        _assert(not bubble.isVisible(), "normal reminder should stay hidden during manual DND")
        scheduler = maid_main.ReminderScheduler(
            [
                maid_main.ReminderRule(
                    "manual",
                    "manual",
                    9999,
                    "手动立即提醒测试",
                    first_delay_s=9999,
                )
            ]
        )
        scheduler.fired.connect(widget.show_alert)
        scheduler.manual_fired.connect(lambda line: widget.show_alert(line, force=True))
        scheduler.trigger_now()
        _assert(bubble.isVisible(), "manual trigger should show bubble even during manual DND")
        scheduler.stop()

        widget._configure_reminder_scheduler(
            scheduler,
            first_delay_s=9999,
            interval_override_s=9999,
        )
        _assert(scheduler.active_rule_count() == 2, "default reminders should schedule water and activity")
        widget._save_reminder_preferences(
            {
                "reminders_enabled": True,
                "water_reminder_enabled": True,
                "water_reminder_minutes": 7,
                "activity_reminder_enabled": False,
                "activity_reminder_minutes": 9,
                "custom_reminder_enabled": True,
                "custom_reminder_minutes": 11,
                "custom_reminder_text": "自定义测试",
            }
        )
        snapshot = load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        _assert(snapshot.water_reminder_minutes == 7, "water reminder minutes should persist")
        _assert(not snapshot.activity_reminder_enabled, "activity reminder enabled flag should persist")
        _assert(snapshot.custom_reminder_enabled, "custom reminder enabled flag should persist")
        _assert(snapshot.custom_reminder_text == "自定义测试", "custom reminder text should persist")
        _assert(scheduler.active_rule_count() == 2, "saving preferences should reschedule active water and custom rules")
        scheduler.stop()

        widget._timer.stop()
        widget._auto_dnd_timer.stop()
        widget._budget_notice_timer.stop()
        widget._auto_dnd_native_observer.stop()

        print("ok")
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
