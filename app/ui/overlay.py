"""透明置顶字幕悬浮窗。

特性：
  * 无边框、半透明圆角、始终置顶、带柔和阴影
  * 鼠标穿透（玩游戏/看电影时点击不被挡）
  * 说话中显示灰色实时字幕，说完那句话变成高亮译文
  * 淡入淡出动画；一段时间没声音自动隐藏
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QFrame, QGraphicsDropShadowEffect)

LANG_ABBR = {"en": "EN", "zh": "中文", "ja": "日本語", "ko": "한국어",
             "ru": "RU", "fr": "FR", "de": "DE", "es": "ES", "pt": "PT",
             "it": "IT", "ar": "AR", "th": "TH", "vi": "VI", "id": "ID"}


class SubtitleOverlay(QWidget):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._drag_pos: QPoint | None = None
        self._dir = "inbound"
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.fade_out)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame(self)
        self.card.setObjectName("card")
        root.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 190))
        self.card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(22, 13, 22, 16)
        lay.setSpacing(7)

        # 顶部：方向徽章 + 语种
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.badge = QLabel("●  对方")
        self.badge.setObjectName("badge")
        self.badge.setStyleSheet(self._badge_qss("#6fd6a5"))
        self.lang_lbl = QLabel("")
        self.lang_lbl.setObjectName("lang")
        top.addWidget(self.badge)
        top.addStretch(1)
        top.addWidget(self.lang_lbl)
        lay.addLayout(top)

        self.src_lbl = QLabel("")
        self.src_lbl.setObjectName("src")
        self.src_lbl.setWordWrap(True)
        self.src_lbl.setTextInteractionFlags(Qt.NoTextInteraction)

        self.tgt_lbl = QLabel("")
        self.tgt_lbl.setObjectName("tgt")
        self.tgt_lbl.setWordWrap(True)
        self.tgt_lbl.setTextInteractionFlags(Qt.NoTextInteraction)

        lay.addWidget(self.src_lbl)
        lay.addWidget(self.tgt_lbl)

        # 淡入淡出（只连一次，用标志决定结束动作）
        self._fade_hides = False
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)

        self._apply_style()
        self.setMinimumWidth(340)
        self._reposition()

    # ------------------------------------------------------------------
    @staticmethod
    def _badge_qss(color: str) -> str:
        return (f"color:{color}; background:rgba(255,255,255,0.055);"
                "border:1px solid rgba(255,255,255,0.10); border-radius:9px;"
                "padding:2px 9px; font-size:11px; font-weight:700;"
                "font-family:'Microsoft YaHei UI';")

    def _apply_style(self) -> None:
        c = self.cfg
        fs_src = max(10, int(c.overlay_src_size))
        fs_tgt = max(14, int(c.overlay_tgt_size))
        op = float(c.overlay_opacity)
        bg = int(216 * op)
        accent = "#6fd6a5" if self._dir == "inbound" else "#66b3ff"
        self.setStyleSheet(f"""
            QFrame#card {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(18,21,29,{bg}),
                            stop:1 rgba(11,13,19,{int(bg * 0.96)}));
                border: 1px solid rgba(120,150,255,0.18);
                border-left: 3px solid {accent};
                border-radius: 16px;
            }}
            QLabel {{ background: transparent; }}
            QLabel#lang {{ color: rgba(255,255,255,0.30); font-size: 11px;
                font-family: "Consolas"; }}
            QLabel#src {{
                color: rgba(196,206,226,0.72);
                font-size: {fs_src}px;
                font-family: "Microsoft YaHei UI", "Segoe UI";
            }}
            QLabel#tgt {{
                color: #ffffff; font-size: {fs_tgt}px; font-weight: 600;
                font-family: "Microsoft YaHei UI", "Segoe UI";
            }}
        """)
        f = QFont("Microsoft YaHei UI", fs_tgt)
        f.setWeight(QFont.DemiBold)
        self.tgt_lbl.setFont(f)

    def apply_config(self) -> None:
        self._apply_style()
        self._reposition()

    # ------------------------------------------------------------------
    def _reposition(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        w = int(min(max(360, g.width() * 0.60), 1280))
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)
        self.adjustSize()
        x = g.x() + (g.width() - self.width()) // 2
        y = g.y() + g.height() - self.height() - int(g.height() * 0.09)
        self.move(max(g.x(), x), max(g.y(), y))

    def set_direction(self, direction: str) -> None:
        if direction == self._dir:
            return
        self._dir = direction
        if direction == "outbound":
            self.badge.setText("●  我说")
            self.badge.setStyleSheet(self._badge_qss("#66b3ff"))
        else:
            self.badge.setText("●  对方")
            self.badge.setStyleSheet(self._badge_qss("#6fd6a5"))
        self._apply_style()

    def _langs(self) -> None:
        s = LANG_ABBR.get(str(getattr(self.cfg, "source_lang", "")).lower(), "自动")
        t = LANG_ABBR.get(str(getattr(self.cfg, "target_lang", "")).lower(), "")
        self.lang_lbl.setText(f"{s}  →  {t}" if t else s)

    def set_partial(self, src: str, tgt: str, direction: str = "inbound") -> None:
        self.set_direction(direction)
        self._langs()
        self.src_lbl.setText(src)
        self.tgt_lbl.setText(tgt or "")
        self.tgt_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.62); font-size:%dpx; font-weight:600;"
            "font-family:'Microsoft YaHei UI','Segoe UI';"
            % int(self.cfg.overlay_tgt_size))
        self._show_and_touch(8000)

    def set_final(self, src: str, tgt: str, direction: str = "inbound",
                  keep_ms: int = 6000) -> None:
        self.set_direction(direction)
        self._langs()
        self.src_lbl.setText(src)
        self.tgt_lbl.setText(tgt or src)
        self.tgt_lbl.setStyleSheet(
            "color:#ffffff; font-size:%dpx; font-weight:600;"
            "font-family:'Microsoft YaHei UI','Segoe UI';"
            % int(self.cfg.overlay_tgt_size))
        self._show_and_touch(keep_ms)

    def show_message(self, text: str, keep_ms: int = 2500) -> None:
        self.badge.setText("●  提示")
        self.badge.setStyleSheet(self._badge_qss("#c8b06a"))
        self.src_lbl.setText("")
        self.tgt_lbl.setText(text)
        self._show_and_touch(keep_ms)

    def _show_and_touch(self, keep_ms: int) -> None:
        self._reposition()
        target = max(0.25, min(1.0, float(self.cfg.overlay_opacity)))
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(target)
            self._fade.start()
        else:
            self.setWindowOpacity(target)
        self._hide_timer.start(keep_ms)

    def _on_fade_finished(self) -> None:
        if self._fade_hides:
            self._fade_hides = False
            self.hide()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(float(self.windowOpacity()))
        self._fade.setEndValue(0.0)
        self._fade_hides = True
        self._fade.start()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_message("字幕已显示", 1200)
