"""Smoke test for receipt-style speech bubble rendering."""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QWidget

from bubble import SpeechBubble


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    app = QApplication.instance() or QApplication([])
    target = QWidget()
    target.setGeometry(100, 120, 240, 320)

    bubble = SpeechBubble()
    bubble.show_at(
        "出门回执 · 收藏品\n收获: 旧铜色键帽\n稀有度: 少见\n累计: 2",
        target,
        style="receipt",
    )

    try:
        app.processEvents()
        _assert(bubble._style == "receipt", f"expected receipt style, got {bubble._style!r}")
        _assert(bubble._receipt_title == "出门回执 · 收藏品", f"unexpected title: {bubble._receipt_title!r}")
        _assert("收获: 旧铜色键帽" in bubble._receipt_body, f"unexpected body: {bubble._receipt_body!r}")
        _assert(bubble.width() >= 156, f"receipt bubble width too small: {bubble.width()}")
        _assert(bubble.height() > 60, f"receipt bubble height too small: {bubble.height()}")

        target.move(100, 0)
        bubble.show_at("贴边提醒测试", target)
        app.processEvents()
        screen = target.screen() or app.primaryScreen()
        if screen is not None:
            _assert(
                bubble.frameGeometry().top() >= screen.availableGeometry().top(),
                f"bubble should stay on-screen: {bubble.frameGeometry()}",
            )
    finally:
        bubble.hide()
        bubble.close()
        target.close()

    print("ok")


if __name__ == "__main__":
    main()
