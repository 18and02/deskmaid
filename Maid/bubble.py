"""Frameless click-through speech bubble that floats above the maid.

Owns its own top-level NSPanel-style window (frameless, translucent, on-top,
non-activating, mouse-transparent), so clicks pass through to anything
underneath. The bubble auto-sizes to its text (word-wrapped to MAX_TEXT_W)
and is positioned so the tail tip sits just above the maid's hair top —
deliberately *no* overlap with the maid's window, so the maid's higher
NSWindow level can't occlude the tail.
"""

from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QFontMetrics,
)
from PySide6.QtWidgets import QApplication, QWidget

try:
    from ctypes import c_void_p
    import objc
    from AppKit import (
        NSStatusWindowLevel,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowStyleMaskNonactivatingPanel,
    )
    HAVE_OBJC = True
except Exception:  # pragma: no cover - only used for macOS native layering
    c_void_p = None
    objc = None
    NSStatusWindowLevel = 25
    NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0
    NSWindowCollectionBehaviorStationary = 1 << 4
    NSWindowCollectionBehaviorFullScreenAuxiliary = 1 << 8
    NSWindowStyleMaskNonactivatingPanel = 1 << 7
    HAVE_OBJC = False

PADDING = 12
TAIL_H = 10
TAIL_X = 20            # tail base starts at this x (bubble-local)
TAIL_WIDTH = 16        # tail base width
TAIL_LEAN = 18         # tip offset to the LEFT of the base's right end
MAX_TEXT_W = 240
RECEIPT_MAX_TEXT_W = 280
CORNER_R = 9
RECEIPT_BADGE_PAD_X = 8
RECEIPT_BADGE_PAD_Y = 4
RECEIPT_SECTION_GAP = 8

# tail tip x in bubble-local coords (derived; used by reposition)
TAIL_TIP_X = TAIL_X + TAIL_WIDTH - TAIL_LEAN  # = 18


class SpeechBubble(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        f = QFont()
        f.setPointSize(13)
        self.setFont(f)
        self._text = ""
        self._style = "plain"
        self._receipt_title = ""
        self._receipt_body = ""
        self._nswindow = None
        self._native_configured = False

    def show_at(self, text: str, target: QWidget, *, style: str = "plain"):
        self._text = text
        self._style = "receipt" if str(style or "").strip().lower() == "receipt" else "plain"
        if self._style == "receipt":
            self._receipt_title, self._receipt_body = self._split_receipt_text(text)
            w, h = self._measure_receipt_size()
        else:
            self._receipt_title = ""
            self._receipt_body = ""
            fm = QFontMetrics(self.font())
            text_rect = fm.boundingRect(
                QRect(0, 0, MAX_TEXT_W, 9999),
                Qt.AlignLeft | Qt.TextWordWrap,
                text,
            )
            w = max(text_rect.width() + 2 * PADDING, 100)
            h = text_rect.height() + 2 * PADDING + TAIL_H
        self.resize(w, h)
        self.reposition(target)
        self.show()
        self.configure_native()
        self.raise_()
        self.update()

    def _split_receipt_text(self, text: str) -> tuple[str, str]:
        lines = [
            line.strip()
            for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        ]
        if not lines:
            return "回执", ""
        title = lines[0]
        body = "\n".join(lines[1:])
        return title, body

    def _receipt_title_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSize(max(11, font.pointSize() - 1))
        font.setBold(True)
        return font

    def _measure_receipt_size(self) -> tuple[int, int]:
        title_font = self._receipt_title_font()
        title_metrics = QFontMetrics(title_font)
        title_rect = title_metrics.boundingRect(
            QRect(0, 0, RECEIPT_MAX_TEXT_W, 9999),
            Qt.AlignLeft | Qt.TextWordWrap,
            self._receipt_title,
        )
        badge_w = title_rect.width() + RECEIPT_BADGE_PAD_X * 2
        badge_h = title_rect.height() + RECEIPT_BADGE_PAD_Y * 2

        body_w = 0
        body_h = 0
        if self._receipt_body:
            body_metrics = QFontMetrics(self.font())
            body_rect = body_metrics.boundingRect(
                QRect(0, 0, RECEIPT_MAX_TEXT_W, 9999),
                Qt.AlignLeft | Qt.TextWordWrap,
                self._receipt_body,
            )
            body_w = body_rect.width()
            body_h = body_rect.height()

        content_w = max(badge_w, body_w)
        content_h = badge_h
        if body_h > 0:
            content_h += RECEIPT_SECTION_GAP + body_h

        width = max(content_w + 2 * PADDING, 156)
        height = content_h + 2 * PADDING + TAIL_H
        return width, height

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        # tail tip lands just above the maid's hair top, horizontally at her center
        tip_x_global = tg.left() + tg.width() // 2
        tip_y_global = tg.top() + 8
        x = tip_x_global - TAIL_TIP_X
        y = tip_y_global - (self.height() - 1)

        screen = target.screen() or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - self.width() + 1))
            y = max(geo.top(), min(y, geo.bottom() - self.height() + 1))
        self.move(x, y)

    def configure_native(self):
        if self._native_configured or not HAVE_OBJC or objc is None or c_void_p is None:
            return
        app = QApplication.instance()
        if app is not None and app.platformName().lower() != "cocoa":
            return
        try:
            view = objc.objc_object(c_void_p=int(self.winId()))
            win = view.window()
        except Exception:
            return
        if win is None:
            return
        self._nswindow = win
        try:
            win.setLevel_(int(NSStatusWindowLevel) + 1)
            win.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            win.setHidesOnDeactivate_(False)
            win.setStyleMask_(win.styleMask() | NSWindowStyleMaskNonactivatingPanel)
            self._native_configured = True
        except Exception:
            return

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body_h = self.height() - TAIL_H

        body = QPainterPath()
        body.addRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, body_h - 1),
            CORNER_R, CORNER_R,
        )
        tail = QPainterPath()
        tail.moveTo(TAIL_X, body_h - 1)
        tail.lineTo(TAIL_X + TAIL_WIDTH, body_h - 1)
        tail.lineTo(TAIL_TIP_X, self.height() - 1)
        tail.closeSubpath()
        outline = body.united(tail)

        if self._style == "receipt":
            p.setBrush(QColor(249, 250, 252, 246))
            p.setPen(QPen(QColor(96, 104, 118, 185), 1))
        else:
            p.setBrush(QColor(252, 250, 248, 245))
            p.setPen(QPen(QColor(70, 70, 70, 180), 1))
        p.drawPath(outline)

        if self._style == "receipt":
            title_font = self._receipt_title_font()
            title_metrics = QFontMetrics(title_font)
            title_rect = title_metrics.boundingRect(
                QRect(0, 0, RECEIPT_MAX_TEXT_W, 9999),
                Qt.AlignLeft | Qt.TextWordWrap,
                self._receipt_title,
            )
            badge_rect = QRectF(
                PADDING,
                PADDING,
                title_rect.width() + RECEIPT_BADGE_PAD_X * 2,
                title_rect.height() + RECEIPT_BADGE_PAD_Y * 2,
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(236, 240, 247, 255))
            p.drawRoundedRect(badge_rect, 7, 7)

            p.setFont(title_font)
            p.setPen(QColor(72, 86, 112))
            p.drawText(
                QRectF(
                    badge_rect.left() + RECEIPT_BADGE_PAD_X,
                    badge_rect.top() + RECEIPT_BADGE_PAD_Y,
                    badge_rect.width() - RECEIPT_BADGE_PAD_X * 2,
                    badge_rect.height() - RECEIPT_BADGE_PAD_Y * 2,
                ),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                self._receipt_title,
            )

            if self._receipt_body:
                divider_y = badge_rect.bottom() + 4
                p.setPen(QPen(QColor(220, 225, 235, 255), 1))
                p.drawLine(
                    int(PADDING),
                    int(divider_y),
                    int(self.width() - PADDING),
                    int(divider_y),
                )
                p.setFont(self.font())
                p.setPen(QColor(40, 40, 40))
                body_top = badge_rect.bottom() + RECEIPT_SECTION_GAP
                p.drawText(
                    QRectF(
                        PADDING,
                        body_top,
                        self.width() - 2 * PADDING,
                        body_h - body_top - PADDING,
                    ),
                    Qt.AlignLeft | Qt.TextWordWrap,
                    self._receipt_body,
                )
        else:
            p.setPen(QColor(40, 40, 40))
            p.drawText(
                QRectF(
                    PADDING, PADDING,
                    self.width() - 2 * PADDING,
                    body_h - 2 * PADDING,
                ),
                Qt.AlignLeft | Qt.TextWordWrap,
                self._text,
            )
        p.end()
