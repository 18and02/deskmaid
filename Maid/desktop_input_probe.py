"""Simple desktop text-input probe app for keyboard/paste integration tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMainWindow, QPlainTextEdit


class InputProbeWindow(QMainWindow):
    def __init__(self, *, title: str, seed_text: str, state_path: Path):
        super().__init__()
        self._state_path = state_path
        self._editor = QPlainTextEdit()
        self._editor.setPlainText(seed_text)
        self._editor.textChanged.connect(self._write_state)
        self.setWindowTitle(title)
        self.setCentralWidget(self._editor)
        self.resize(720, 520)
        self._move_cursor_to_end()
        QTimer.singleShot(0, self._prime_window)

    def _move_cursor_to_end(self):
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._editor.setTextCursor(cursor)

    def _prime_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self._editor.setFocus()
        self._move_cursor_to_end()
        self._write_state()

    def _write_state(self):
        payload = {
            "pid": os.getpid(),
            "ready": True,
            "text": self._editor.toPlainText(),
            "title": self.windowTitle(),
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._state_path)

    def closeEvent(self, event):
        self._write_state()
        super().closeEvent(event)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--seed-text", default="")
    parser.add_argument("--state-file", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    signal.signal(signal.SIGTERM, lambda *_args: app.quit())
    signal.signal(signal.SIGINT, lambda *_args: app.quit())

    window = InputProbeWindow(
        title=str(args.title),
        seed_text=str(args.seed_text),
        state_path=Path(args.state_file),
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
