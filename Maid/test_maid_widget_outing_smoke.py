"""Smoke test for sprite-pack MaidWidget outing pose resolution."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication

from bubble import SpeechBubble
from maid_sprite_packs import resolve_sprite_pack
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="deskmaid-widget-outing-") as tmp_dir:
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
        _assert(not widget._debug_border, "debug border should stay off by default")
        widget._enter_until = None
        widget._state = maid_main.MaidState.IDLE
        widget._last_state_key = widget._current_state_key()
        widget._select_sprite_variant(widget._last_state_key)
        started = widget._begin_outing("manual", auto_return=False, announce=False)
        _assert(started, "manual outing should start")
        _assert(widget._outing_active, "widget should be in outing state")
        _assert(widget._current_state_key() == "outing", f"unexpected state key: {widget._current_state_key()!r}")
        _assert(
            widget._current_pixmap().size().width() > 0,
            "current pixmap should resolve while outing is active",
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
