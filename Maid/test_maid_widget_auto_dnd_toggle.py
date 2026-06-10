"""Smoke test for the auto-DND master switch in MaidWidget."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication

from bubble import SpeechBubble
from maid_app_state import load_app_state_snapshot
from maid_sprite_packs import resolve_sprite_pack
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="deskmaid-widget-auto-dnd-") as tmp_dir:
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
        widget._enter_until = None

        maid_main.probe_auto_do_not_disturb = lambda: maid_main.AutoDoNotDisturbState(
            active=True,
            reason_key="meeting_focus",
            reason_text="会议/通话场景",
            detail="Zoom: Daily Sync",
            frontmost_app_name="Zoom",
            frontmost_bundle_id="us.zoom.xos",
            updated_at=1_717_000_000.0,
        )

        widget._refresh_auto_do_not_disturb()
        _assert(widget._auto_do_not_disturb_enabled, "auto-dnd detection should default to enabled")
        _assert(widget._auto_do_not_disturb, "auto-dnd should become active after probe")
        _assert(widget._auto_dnd_timer.isActive(), "auto-dnd timer should be running while enabled")
        _assert(widget._outing_active, "auto-dnd activation should enter outing state")

        widget._set_auto_do_not_disturb_enabled(False, announce=False)
        snapshot = load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        _assert(
            not widget._auto_do_not_disturb_enabled,
            "auto-dnd detection should turn off immediately",
        )
        _assert(not widget._auto_do_not_disturb, "auto-dnd active state should clear when disabled")
        _assert(not widget._auto_dnd_timer.isActive(), "auto-dnd timer should stop when disabled")
        _assert(not widget._outing_active, "auto-dnd outing should end when detection is disabled")
        _assert(
            not snapshot.auto_do_not_disturb_enabled,
            "disabled auto-dnd detection should persist to app state",
        )

        widget._set_auto_do_not_disturb_enabled(True, announce=False)
        snapshot = load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        widget._refresh_auto_do_not_disturb()
        _assert(widget._auto_do_not_disturb_enabled, "auto-dnd detection should re-enable")
        _assert(widget._auto_dnd_timer.isActive(), "auto-dnd timer should restart when re-enabled")
        _assert(widget._auto_do_not_disturb, "auto-dnd should probe again after re-enable")
        _assert(
            snapshot.auto_do_not_disturb_enabled,
            "re-enabled auto-dnd detection should persist to app state",
        )

        widget._timer.stop()
        widget._auto_dnd_timer.stop()
        widget._budget_notice_timer.stop()
        widget._auto_dnd_native_observer.stop()

        print("ok")
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
