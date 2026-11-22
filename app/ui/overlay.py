"""透明置顶字幕悬浮窗。

特性：
  * 无边框、半透明圆角、始终置顶、带柔和阴影
  * 鼠标穿透（玩游戏/看电影时点击不被挡）
  * 说话中显示灰色实时字幕，说完那句话变成高亮译文
  * 淡入淡出动画；一段时间没声音自动隐藏
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation,
                            QEasingCurve, Signal)
from PySide6.QtGui import QFont, QColor, QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QFrame, QGraphicsDropShadowEffect)

from .style import SUCCESS, INFO, WARN, TEXT

LANG_ABBR = {"en": "EN", "zh": "中文", "ja": "日本語", "ko": "한국어",
             "ru": "RU", "fr": "FR", "de": "DE", "es": "ES", "pt": "PT",
             "it": "IT", "ar": "AR", "th": "TH", "vi": "VI", "id": "ID"}


_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020


class SubtitleOverlay(QWidget):
    """置顶字幕窗。

    平时鼠标穿透（点击落到下面的窗口/游戏里）；`set_drag_mode(True)` 时临时
    取消穿透，可以直接用鼠标把它拖到任意位置，坐标存进配置，下次启动自动还原。
    """

    moved_by_user = Signal(int, int)   # 拖动结束 → (x, y)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._drag_pos: QPoint | None = None
        self.drag_mode = False
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
        lay.setContentsMargins(24, 13, 24, 17)
        lay.setSpacing(6)

        # 顶部：方向徽章 + 语种
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.badge = QLabel("对方")
        self.badge.setObjectName("badge")
        self.badge.setStyleSheet(self._badge_qss(SUCCESS))
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
    # 鼠标穿透的开关：Qt 的 WindowTransparentForInput 会在 HWND 上置
    # WS_EX_TRANSPARENT，要动态关掉它才能收到鼠标消息
    def _set_click_through(self, on: bool) -> None:
        self.setAttribute(Qt.WA_TransparentForMouseEvents, on)
        try:
            hwnd = int(self.winId())
            u = ctypes.windll.user32
            ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ex = (ex | _WS_EX_TRANSPARENT) if on else (ex & ~_WS_EX_TRANSPARENT)
            u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex)
        except Exception:
            pass

    def set_drag_mode(self, on: bool) -> None:
        """进入 / 退出拖动模式。"""
        on = bool(on)
        if on == self.drag_mode:
            return
        self.drag_mode = on
        if on:
            self._hide_timer.stop()
            self._set_click_through(False)
            self.setCursor(Qt.SizeAllCursor)
            self.card.setStyleSheet(self._drag_hint_qss())
            self.show_message("拖动我，放好后按 Ctrl+Alt+M 完成", 600000)
            self.setWindowOpacity(max(0.6, float(self.cfg.overlay_opacity)))
            self.raise_()
        else:
            pos = self.pos()          # 退出时兜底再存一次坐标
            self.cfg.overlay_x, self.cfg.overlay_y = pos.x(), pos.y()
            self._set_click_through(True)
            self.unsetCursor()
            self._apply_style()
            self.show_message("字幕位置已保存", 1200)

    def _drag_hint_qss(self) -> str:
        bg = int(216 * float(self.cfg.overlay_opacity))
        return (f"QFrame#card {{ background: rgba(19,23,32,{bg});"
                " border: 2px dashed rgba(139,165,255,0.95); border-radius: 14px; }")

    # ------------------------------------------------------------------
    # 拖动：只在拖动模式下生效，其它时候窗口是穿透的，收不到事件
    def mousePressEvent(self, e) -> None:
        if not self.drag_mode or e.button() != Qt.LeftButton:
            return
        self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if not self.drag_mode or self._drag_pos is None:
            return
        self.move(e.globalPosition().toPoint() - self._drag_pos)
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if not self.drag_mode or self._drag_pos is None:
            return
        self._drag_pos = None
        g = self.screen().availableGeometry() if self.screen() else None
        pos = self.pos()
        if g is not None:   # 夹到屏幕内，避免拖出可视区域后再也找不回来
            x = min(max(pos.x(), g.x()), g.x() + g.width() - self.width())
            y = min(max(pos.y(), g.y()), g.y() + g.height() - self.height())
            if (x, y) != (pos.x(), pos.y()):
                self.move(x, y)
        self.cfg.overlay_x = self.pos().x()
        self.cfg.overlay_y = self.pos().y()
        self.moved_by_user.emit(self.pos().x(), self.pos().y())
        e.accept()

    @staticmethod
    def _badge_qss(color: str) -> str:
        """方向徽章：半透明同色底 + 同色描边 + 左侧圆点。"""
        return (f"color:{color};"
                f"background:rgba({int(color[1:3], 16)},{int(color[3:5], 16)},"
                f"{int(color[5:7], 16)},0.13);"
                f"border:1px solid rgba({int(color[1:3], 16)},{int(color[3:5], 16)},"
                f"{int(color[5:7], 16)},0.34);"
                "border-radius:10px; padding:2px 10px;"
                "font-size:11px; font-weight:700;"
                "font-family:'Microsoft YaHei UI';")

    def _apply_style(self) -> None:
        c = self.cfg
        fs_src = max(10, int(c.overlay_src_size))
        fs_tgt = max(14, int(c.overlay_tgt_size))
        op = float(c.overlay_opacity)
        bg = int(216 * op)
        accent = SUCCESS if self._dir == "inbound" else INFO
        self.setStyleSheet(f"""
            QFrame#card {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(19,23,32,{bg}),
                            stop:1 rgba(9,11,16,{int(bg * 0.97)}));
                border: 1px solid rgba(126,146,190,0.16);
                border-left: 4px solid {accent};
                border-radius: 14px;
            }}
            QLabel {{ background: transparent; }}
            QLabel#lang {{ color: rgba(233,237,246,0.44); font-size: 10px;
                letter-spacing: 1px; font-family: "Consolas", "Cascadia Mono"; }}
            QLabel#src {{
                color: rgba(196,206,226,0.66);
                font-size: {fs_src}px;
                font-family: "Microsoft YaHei UI", "Segoe UI";
            }}
            QLabel#tgt {{
                color: {TEXT}; font-size: {fs_tgt}px; font-weight: 600;
                font-family: "Microsoft YaHei UI", "Segoe UI";
            }}
        """)
        f = QFont("Microsoft YaHei UI", fs_tgt)
        f.setWeight(QFont.DemiBold)
        self.tgt_lbl.setFont(f)

    def apply_config(self) -> None:
        self._apply_style()
        self._sync_src()
        self._reposition()

    def _sync_src(self) -> None:
        """只显示译文时把原文行收起来（FPS 用更清爽）。"""
        show = bool(getattr(self.cfg, "subtitle_show_src", True))
        self.src_lbl.setVisible(show and bool(self.src_lbl.text()))

    # ------------------------------------------------------------------
    def _reposition(self, force_auto: bool = False) -> None:
        """摆放位置：优先用用户拖出来的坐标，否则按 overlay_pos 预设。"""
        if self.drag_mode and not force_auto:
            return                      # 拖动过程中别被自动摆放打断
        scr = self.screen() or QGuiApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        w = int(min(max(360, g.width() * 0.60), 1280))
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)
        self.adjustSize()

        cx = int(getattr(self.cfg, "overlay_x", -1) or -1)
        cy = int(getattr(self.cfg, "overlay_y", -1) or -1)
        if cx >= 0 and cy >= 0 and not force_auto:
            # 手动拖过的位置：宽度仍然自适应，坐标夹在屏幕内
            x = min(max(cx, g.x()), g.x() + g.width() - self.width())
            y = min(max(cy, g.y()), g.y() + g.height() - self.height())
            self.move(x, y)
            return

        x = g.x() + (g.width() - self.width()) // 2
        pos = str(getattr(self.cfg, "overlay_pos", "bottom") or "bottom").lower()
        if pos == "top":
            y = g.y() + int(g.height() * 0.06)
        elif pos == "middle":
            y = g.y() + (g.height() - self.height()) // 2
        else:
            y = g.y() + g.height() - self.height() - int(g.height() * 0.09)
        self.move(max(g.x(), x), max(g.y(), y))

    def reset_position(self) -> None:
        """清掉手动坐标，回到预设位置。"""
        self.cfg.overlay_x = -1
        self.cfg.overlay_y = -1
        self._reposition(force_auto=True)

    def set_direction(self, direction: str) -> None:
        if direction == self._dir:
            return
        self._dir = direction
        if direction == "outbound":
            self.badge.setText("我说")
            self.badge.setStyleSheet(self._badge_qss(INFO))
        else:
            self.badge.setText("对方")
            self.badge.setStyleSheet(self._badge_qss(SUCCESS))
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
        self._sync_src()
        self.tgt_lbl.setStyleSheet(
            "color: rgba(233,237,246,0.60); font-size:%dpx; font-weight:600;"
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
            f"color:{TEXT}; font-size:%dpx; font-weight:600;"
            "font-family:'Microsoft YaHei UI','Segoe UI';"
            % int(self.cfg.overlay_tgt_size))
        self._sync_src()
        self._show_and_touch(keep_ms)

    def show_message(self, text: str, keep_ms: int = 2500) -> None:
        self.badge.setText("提示")
        self.badge.setStyleSheet(self._badge_qss(WARN))
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
