"""Generate placeholder立绘 sprites for stage-1 verification.

Produces a matched pair of expression差分 frames:
  assets/placeholder.png        — eyes open (default state)
  assets/placeholder_blink.png  — eyes closed (used by the blink frame)

Everything outside the eye region is pixel-identical between the two frames,
so the swap doesn't introduce any wobble. Authored @2x for Retina crispness.
Swap in the real立绘 later by replacing both PNGs (same dimensions).
"""
import sys
from pathlib import Path

from PySide6.QtGui import QImage, QPainter, QColor, QPainterPath, QPen
from PySide6.QtCore import Qt, QRectF, QPointF

SCALE = 2
W, H = 200 * SCALE, 320 * SCALE


def draw(closed: bool) -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    cx = W / 2

    # dress / body (opaque)
    p.setBrush(QColor(120, 170, 140))
    dress = QPainterPath()
    dress.moveTo(cx, 118 * SCALE)
    dress.lineTo(cx - 72 * SCALE, 300 * SCALE)
    dress.quadTo(cx, 320 * SCALE, cx + 72 * SCALE, 300 * SCALE)
    dress.closeSubpath()
    p.drawPath(dress)

    # hair cap
    p.setBrush(QColor(190, 70, 60))
    p.drawEllipse(QPointF(cx, 70 * SCALE), 48 * SCALE, 48 * SCALE)

    # face
    p.setBrush(QColor(245, 225, 215))
    p.drawEllipse(QPointF(cx, 84 * SCALE), 38 * SCALE, 40 * SCALE)

    # eyes — the only difference between open / closed frames
    if closed:
        pen = QPen(QColor(60, 50, 50))
        pen.setWidth(int(2 * SCALE))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        # left lid
        p.drawLine(int(cx - 19 * SCALE), int(84 * SCALE),
                   int(cx - 9 * SCALE), int(84 * SCALE))
        # right lid (where the red eye lives)
        p.drawLine(int(cx + 9 * SCALE), int(84 * SCALE),
                   int(cx + 19 * SCALE), int(84 * SCALE))
        p.setPen(Qt.NoPen)
    else:
        # signature single RED eye + muted left eye
        p.setBrush(QColor(220, 30, 40))
        p.drawEllipse(QPointF(cx + 14 * SCALE, 84 * SCALE), 5 * SCALE, 5 * SCALE)
        p.setBrush(QColor(80, 70, 70))
        p.drawEllipse(QPointF(cx - 14 * SCALE, 84 * SCALE), 4 * SCALE, 4 * SCALE)

    # semi-transparent veil band (kept identical across frames)
    p.setBrush(QColor(255, 255, 255, 90))
    p.drawRect(QRectF(cx - 82 * SCALE, 104 * SCALE, 164 * SCALE, 70 * SCALE))

    p.end()
    return img


def main():
    out_dir = Path(__file__).resolve().parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, closed in [("placeholder.png", False), ("placeholder_blink.png", True)]:
        path = out_dir / name
        if not draw(closed).save(str(path), "PNG"):
            print(f"FAILED to save {path}", file=sys.stderr)
            sys.exit(1)
        print(f"wrote {path}  ({W}x{H}px @{SCALE}x)")


if __name__ == "__main__":
    main()
