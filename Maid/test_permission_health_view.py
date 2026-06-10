"""Smoke test for the permission-health recovery guide view."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QPushButton

from maid_permission_recovery import enrich_permission_health_check
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _card_widgets(dialog: maid_main.PermissionHealthDialog) -> list[maid_main.PermissionHealthCardWidget]:
    rows: list[maid_main.PermissionHealthCardWidget] = []
    for index in range(dialog._cards_layout.count()):
        item = dialog._cards_layout.itemAt(index)
        widget = item.widget()
        if isinstance(widget, maid_main.PermissionHealthCardWidget):
            rows.append(widget)
    return rows


def main():
    app = QApplication.instance() or QApplication([])
    check = enrich_permission_health_check(
        {
            "key": "calendar_automation",
            "title": "Calendar 自动化",
            "status": "error",
            "status_label": "未就绪",
            "summary": "Calendar 自动化未授权",
            "detail": "Not authorized to send Apple events to Calendar. (-1743)",
            "hint": "去系统设置里打开自动化。",
            "tools": [],
        }
    )
    snapshot = {
        "checked_at": time.time(),
        "summary_text": "已就绪 10 项，留意 0 项，未就绪 1 项。",
        "checks": [check],
    }

    dialog = maid_main.PermissionHealthDialog()
    dialog.refresh(snapshot)
    cards = _card_widgets(dialog)
    _assert(len(cards) == 2, f"expected guide + check cards, got {len(cards)}")

    guide_card = cards[0]
    failing_card = cards[1]
    _assert(
        guide_card._title.text() == "恢复向导",
        f"expected recovery guide first, got {guide_card._title.text()!r}",
    )
    _assert(
        failing_card._title.text() == "Calendar 自动化",
        f"expected failing card second, got {failing_card._title.text()!r}",
    )
    _assert(
        "恢复向导" in dialog._meta.text(),
        f"dialog meta should mention the guide: {dialog._meta.text()!r}",
    )

    guide_buttons = [
        button.text().strip()
        for button in guide_card.findChildren(QPushButton)
        if button.text().strip()
    ]
    _assert(
        guide_buttons == ["打开自动化", "打开 Calendar", "刷新"],
        f"unexpected guide buttons: {guide_buttons!r}",
    )

    app.processEvents()
    print("ok")


if __name__ == "__main__":
    main()
