"""小部件：音量电平条、状态圆点、历史条目卡片。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPen, QBrush
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel


class LevelMeter(QWidget):
    """VAD 概率 / 音量电平条（带渐亮与头部光点）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = 0.0
        self._speech = False
        self._peak = 0.0
        self.setFixedHeight(8)
        self.setMinimumWidth(120)

    def set_level(self, v: float, speech: bool = False) -> None:
        self._v = max(0.0, min(1.0, float(v)))
        self._speech = speech
        self._peak = max(self._peak * 0.9, self._v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        radius = r.height() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawRoundedRect(r, radius, radius)

        w = r.width() * self._v
        if w > 2:
            g = QLinearGradient(0, 0, r.width(), 0)
            if self._speech:
                g.setColorAt(0.0, QColor(56, 211, 159))
                g.setColorAt(0.65, QColor(96, 160, 255))
                g.setColorAt(1.0, QColor(150, 120, 255))
            else:
                g.setColorAt(0.0, QColor(60, 74, 98))
                g.setColorAt(1.0, QColor(90, 110, 145))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, max(w, r.height()), r.height()),
                              radius, radius)

            if self._speech and w > r.height():
                # 头部光点
                head = QPointF(w - radius, r.center().y())
                glow = QColor(190, 210, 255, 90)
                p.setBrush(glow)
                p.drawEllipse(head, radius * 1.5, radius * 1.5)
                p.setBrush(QColor(255, 255, 255, 210))
                p.drawEllipse(head, radius * 0.55, radius * 0.55)


class Dot(QWidget):
    """状态圆点（带光晕）。"""

    def __init__(self, color="#6b7280", size=10, parent=None):
        super().__init__(parent)
        self._c = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self._c = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        halo = QColor(self._c)
        halo.setAlpha(60)
        p.setBrush(halo)
        p.drawEllipse(0, 0, self.width(), self.height())
        p.setBrush(self._c)
        m = self.width() * 0.28
        p.drawEllipse(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m))


class HistoryCard(QFrame):
    """一条历史字幕：原文 / 译文 / 时间。"""

    def __init__(self, src: str, tgt: str, ts: str, direction: str = "inbound",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("hist")
        self.setProperty("dir", "out" if direction == "outbound" else "in")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 10)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        tag = QLabel("对方" if direction != "outbound" else "我说")
        tag.setStyleSheet(
            "color:%s; font-size:10px; font-weight:700; font-family:'Microsoft YaHei UI';"
            % ("#38d39f" if direction != "outbound" else "#5b8bff"))
        self.time_lbl = QLabel(ts)
        self.time_lbl.setObjectName("hist_time")
        head.addWidget(tag)
        head.addStretch(1)
        head.addWidget(self.time_lbl)
        lay.addLayout(head)

        self.src_lbl = QLabel(src)
        self.src_lbl.setObjectName("hist_src")
        self.src_lbl.setWordWrap(True)
        self.tgt_lbl = QLabel(tgt)
        self.tgt_lbl.setObjectName("hist_tgt")
        self.tgt_lbl.setWordWrap(True)
        lay.addWidget(self.src_lbl)
        lay.addWidget(self.tgt_lbl)
