"""生成应用图标 app/ui/assets/icon.png（无需设计软件）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import (QGuiApplication, QImage, QPainter, QColor,
                           QLinearGradient, QFont, QPen, QBrush)

app = QGuiApplication([])

for size in (256, 128, 64, 32, 16):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    r = QRectF(0, 0, size, size)
    radius = size * 0.24
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0.0, QColor("#5b8bff"))
    g.setColorAt(0.55, QColor("#4b6ff3"))
    g.setColorAt(1.0, QColor("#8b5cff"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(r, radius, radius)

    # 顶部高光
    hl = QLinearGradient(0, 0, 0, size * 0.55)
    hl.setColorAt(0.0, QColor(255, 255, 255, 46))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hl))
    p.drawRoundedRect(r, radius, radius)

    f = QFont("Segoe UI", int(size * 0.40))
    f.setWeight(QFont.Black)
    f.setLetterSpacing(QFont.PercentageSpacing, 96)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 240))
    p.drawText(r, Qt.AlignCenter, "LD")
    p.end()

    out = Path(__file__).resolve().parent.parent / "app/ui/assets" / (
        "icon.png" if size == 256 else f"icon_{size}.png")
    img.save(str(out))
    print("saved", out, img.width())

# 生成 .ico（Windows 多尺寸）
try:
    from PySide6.QtGui import QPixmap
    big = QPixmap(str(Path(__file__).resolve().parent.parent / "app/ui/assets/icon.png"))
    ico = Path(__file__).resolve().parent.parent / "app/ui/assets/icon.ico"
    if big.save(str(ico), "ICO"):
        print("saved", ico)
except Exception as e:
    print("ico skip:", e)
