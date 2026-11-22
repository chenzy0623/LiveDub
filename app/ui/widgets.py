"""小部件：分段卡片、字段行、音量电平条、状态圆点、历史卡片、空状态。"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QSize
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QFont, QFontMetrics
from PySide6.QtWidgets import (QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
                               QSizePolicy, QComboBox, QLineEdit)

FONT_FAMILY = "Microsoft YaHei UI"


# ---------------------------------------------------------------- 字体助手
def make_font(px: int, weight: QFont.Weight = QFont.Normal,
              spacing: float = 0.0, family: str = FONT_FAMILY) -> QFont:
    """按像素给字号（与 QSS 的 px 对齐），可选字间距。"""
    f = QFont(family)
    f.setPixelSize(px)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def field_row(label: str, *widgets, width: int = 64, spacing: int = 8) -> QWidget:
    """一行「标签 + 控件」，标签定宽保证多行对齐。"""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    cap = QLabel(label)
    cap.setObjectName("field_label")
    cap.setFixedWidth(width)
    h.addWidget(cap, 0, Qt.AlignVCenter)
    for w in widgets:
        h.addWidget(w, 1 if isinstance(w, (QComboBox, QLineEdit)) else 0)
    return row


# ---------------------------------------------------------------- 卡片
class SectionCard(QFrame):
    """统一的分段卡片：左侧渐变竖条 + 标题 + 右侧可选控件 + 内容区。"""

    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 11, 16, 11)
        outer.setSpacing(7)

        self.head = QHBoxLayout()
        self.head.setContentsMargins(0, 0, 0, 0)
        self.head.setSpacing(8)

        bar = QFrame()
        bar.setObjectName("bar")
        bar.setFixedSize(3, 12)
        self.head.addWidget(bar, 0, Qt.AlignVCenter)

        cap = QLabel(title)
        cap.setObjectName("card_title")
        cap.setFont(make_font(12, QFont.DemiBold, 0.6))
        self.head.addWidget(cap, 0, Qt.AlignVCenter)

        if hint:
            h = QLabel(hint)
            h.setObjectName("card_hint")
            self.head.addWidget(h, 0, Qt.AlignVCenter)

        self.head.addStretch(1)
        outer.addLayout(self.head)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(7)
        outer.addLayout(self.body, 1)

    def add_head_widget(self, w: QWidget) -> QWidget:
        """右侧小控件（状态徽章 / 计数 / 链接按钮）。"""
        self.head.addWidget(w, 0, Qt.AlignVCenter)
        return w


class EmptyState(QFrame):
    """列表空状态：波形图标 + 主标题 + 一句引导。"""

    def __init__(self, title: str, sub: str, parent=None):
        super().__init__(parent)
        self.setObjectName("empty")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(6)
        v.addStretch(1)

        art = _WaveArt()
        v.addWidget(art, 0, Qt.AlignHCenter)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("empty_title")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(self.title_lbl)

        self.sub_lbl = QLabel(sub)
        self.sub_lbl.setObjectName("empty_sub")
        self.sub_lbl.setAlignment(Qt.AlignCenter)
        self.sub_lbl.setWordWrap(True)
        v.addWidget(self.sub_lbl)
        v.addStretch(1)


class _WaveArt(QWidget):
    """空状态用的小波形图形（纯绘制，不依赖字体 / 图片）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        heights = (6, 13, 20, 11, 5)
        w = 3.0
        gap = 4.0
        total = len(heights) * w + (len(heights) - 1) * gap
        x = (self.width() - total) / 2.0
        for i, h in enumerate(heights):
            c = QColor(120, 134, 160)
            c.setAlpha(90 if i not in (1, 3) else 150)
            p.setBrush(c)
            y = (self.height() - h) / 2.0
            p.drawRoundedRect(QRectF(x, y, w, h), 1.5, 1.5)
            x += w + gap


# ---------------------------------------------------------------- 电平条
class LevelMeter(QWidget):
    """VAD 概率 / 音量电平条（渐变 + 头部光点）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = 0.0
        self._speech = False
        self._peak = 0.0
        self.setFixedHeight(8)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(r, radius, radius)
        # 四分刻度，让静止时也有结构感
        p.setBrush(QColor(255, 255, 255, 14))
        for frac in (0.25, 0.5, 0.75):
            x = r.width() * frac
            p.drawRect(QRectF(x, 2, 1, r.height() - 4))

        w = r.width() * self._v
        if w > 2:
            g = QLinearGradient(0, 0, r.width(), 0)
            if self._speech:
                g.setColorAt(0.0, QColor(61, 220, 151))
                g.setColorAt(0.55, QColor(90, 162, 255))
                g.setColorAt(1.0, QColor(139, 92, 246))
            else:
                g.setColorAt(0.0, QColor(58, 70, 92))
                g.setColorAt(1.0, QColor(92, 110, 140))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, max(w, r.height()), r.height()),
                              radius, radius)

            if self._speech and w > r.height():
                head = QPointF(w - radius, r.center().y())
                p.setBrush(QColor(190, 210, 255, 80))
                p.drawEllipse(head, radius * 1.6, radius * 1.6)
                p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(head, radius * 0.55, radius * 0.55)


# ---------------------------------------------------------------- 状态点
class Dot(QWidget):
    """状态圆点；pulse=True 时呼吸发光（运行中）。"""

    def __init__(self, color="#6b7280", size=10, parent=None, pulse=False):
        super().__init__(parent)
        self._c = QColor(color)
        self._pulse = bool(pulse)
        self._phase = 0.0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        if self._pulse:
            self._timer.start()

    def set_color(self, color: str, pulse: bool | None = None) -> None:
        self._c = QColor(color)
        if pulse is not None and pulse != self._pulse:
            self._pulse = pulse
            if pulse:
                self._timer.start()
            else:
                self._timer.stop()
                self._phase = 0.0
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.14) % (2 * math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        halo = QColor(self._c)
        halo.setAlpha(int(46 + 34 * (0.5 + 0.5 * math.sin(self._phase))))
        p.setBrush(halo)
        p.drawEllipse(0, 0, self.width(), self.height())
        p.setBrush(self._c)
        m = self.width() * 0.28
        p.drawEllipse(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m))


# ---------------------------------------------------------------- 历史项
class HistoryCard(QFrame):
    """一条历史字幕：方向标签 + 时间 / 原文 / 译文。"""

    def __init__(self, src: str, tgt: str, ts: str, direction: str = "inbound",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("hist")
        d = "out" if direction == "outbound" else "in"
        self.setProperty("dir", d)
        self.setAttribute(Qt.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 8, 12, 9)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        tag = QLabel("我说" if d == "out" else "对方")
        tag.setObjectName("hist_tag")
        tag.setProperty("dir", d)
        tag.setFont(make_font(10, QFont.Bold))
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


# ---------------------------------------------------------------- 省略号文本
class ElidedLabel(QLabel):
    """按可用宽度自动省略的 QLabel（底部状态条用，避免长句把布局撑开）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(90)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def setText(self, text: str) -> None:
        self._full = text or ""
        self._apply()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply()

    def _apply(self) -> None:
        fm: QFontMetrics = self.fontMetrics()
        w = max(0, self.width() - 2)
        super().setText(fm.elidedText(self._full, Qt.ElideRight, w))

    def sizeHint(self) -> QSize:
        return QSize(160, super().sizeHint().height())
