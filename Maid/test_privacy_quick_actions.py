"""Smoke test for privacy quick-rewrite actions in the input dialog."""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication

import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    app = QApplication.instance()
    created_app = False
    if app is None:
        app = QApplication([])
        created_app = True

    dialog = maid_main.ChatInputDialog()
    dialog._input.setPlainText("请记住这件事：密码: hunter2。")
    dialog.show_privacy_rewrite_actions(
        "这句输入里命中了密码字段。",
        ("hidden", "last4", "local_only"),
    )

    _assert(not dialog._privacy_actions_host.isHidden(), "privacy action row should be shown")
    _assert(not dialog._privacy_hint.isHidden(), "privacy hint should be shown")
    _assert(
        dialog._privacy_actions_title.text() == "安全改写建议",
        "privacy panel should expose the new section title",
    )
    _assert(
        "点下面任一按钮" in dialog._privacy_hint.text(),
        "privacy panel hint should explain the quick rewrite flow",
    )

    dialog._apply_privacy_rewrite("hidden")
    hidden_text = dialog._input.toPlainText()
    _assert("[已隐藏]" in hidden_text, "hidden action should rewrite the input")
    _assert("hunter2" not in hidden_text, "hidden action should remove the raw secret")
    _assert(
        "font-weight" in dialog._status.styleSheet(),
        "rewrite success should use the emphasized status style",
    )

    dialog._apply_privacy_rewrite("last4")
    last4_text = dialog._input.toPlainText()
    _assert("[末四位 ter2]" in last4_text, "last4 action should keep only the final 4 chars")
    _assert("hunter2" not in last4_text, "last4 action should remove the raw secret")

    dialog._apply_privacy_rewrite("local_only")
    local_only_text = dialog._input.toPlainText()
    _assert(
        local_only_text.startswith("请仅在本机处理下面这段高敏内容"),
        "local-only action should add the local-only prefix",
    )
    _assert("[已隐藏]" in local_only_text, "local-only action should hide the raw secret")
    _assert("hunter2" not in local_only_text, "local-only action should remove the raw secret")

    dialog.clear_draft()
    _assert(dialog._privacy_actions_host.isHidden(), "privacy action row should hide after clearing")

    dialog.deleteLater()
    if created_app:
        app.quit()

    print("ok")


if __name__ == "__main__":
    main()
