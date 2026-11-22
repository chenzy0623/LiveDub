"""主窗口：控制台 + 设置 + 说明。"""
from __future__ import annotations

import queue
import sys
import time
import traceback
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QAction, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QTabWidget, QFrame, QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox,
    QSizePolicy, QScrollArea, QApplication, QSystemTrayIcon, QMenu,
    QStackedWidget,
)

from ..audio import devices as dv
from ..config import Config
from ..mt.translator import LANG_NAME
from ..pipeline.engine import DualPipeline, Events, SegmentResult
from .hotkeys import GlobalHotkeys
from .overlay import SubtitleOverlay
from .style import (DARK_QSS, ICON_PATH, PLAY, STOP, SWAP, REFRESH, CHECK,
                    SUCCESS, WARN, DANGER, MUTED_2)
from .widgets import (LevelMeter, Dot, HistoryCard, SectionCard, EmptyState,
                      ElidedLabel, field_row, make_font)

# 语言选项（值, 显示）
LANGS = [
    ("auto", "自动检测"), ("en", "英语"), ("zh", "中文"), ("ja", "日语"),
    ("ko", "韩语"), ("ru", "俄语"), ("fr", "法语"), ("de", "德语"),
    ("es", "西班牙语"), ("pt", "葡萄牙语"), ("it", "意大利语"),
    ("ar", "阿拉伯语"), ("th", "泰语"), ("vi", "越南语"), ("id", "印尼语"),
]
TARGET_LANGS = [x for x in LANGS if x[0] != "auto"]

MT_ENGINES = [("bing", "Bing 免费（推荐，免 Key）"),
              ("deepseek", "DeepSeek API（质量最好，需 Key）"),
              ("opus", "离线 · 本地 opus-mt（免网络，快）"),
              ("none", "不翻译（只显示原文）")]

TTS_ENGINES = [("edge", "Edge 在线音色（最自然，需网络）"),
               ("piper", "离线 · 本地 Piper（免网络，快）")]


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    return f


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.pipe: Optional[DualPipeline] = None
        self.ui_q: "queue.Queue[tuple]" = queue.Queue()
        self.hotkey_q: "queue.Queue[str]" = queue.Queue()
        self.started_at = 0.0
        self.last_final: Optional[SegmentResult] = None

        self.setWindowTitle("LiveDub · 实时同声翻译")
        self.setMinimumSize(960, 690)
        self.resize(1040, 749)
        self.setStyleSheet(DARK_QSS)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.overlay = SubtitleOverlay(cfg)
        self._build_ui()
        self._refresh_devices()
        self._load_settings_into_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

        self.hotkeys = GlobalHotkeys(self.hotkey_q)
        self.hotkeys.start({"toggle": cfg.hotkey_toggle, "overlay": cfg.hotkey_overlay})

        self._build_tray()

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 12, 18, 10)
        root.setSpacing(8)

        # ---- 顶部标题栏 ----
        head = QHBoxLayout()
        head.setSpacing(11)

        logo = QLabel("LD")
        logo.setObjectName("logo")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignCenter)
        logo.setFont(make_font(14, QFont.Black, 0.4))
        head.addWidget(logo)

        tbox = QVBoxLayout()
        tbox.setSpacing(1)
        tbox.setContentsMargins(0, 0, 0, 0)
        title = QLabel("LiveDub")
        title.setObjectName("h1")
        sub = QLabel("实时同声翻译 · 保留原说话人音色 · 本地运行")
        sub.setObjectName("sub")
        tbox.addWidget(title)
        tbox.addWidget(sub)
        head.addLayout(tbox)
        head.addStretch(1)

        self.pill = QFrame()
        self.pill.setObjectName("pill")
        pl = QHBoxLayout(self.pill)
        pl.setContentsMargins(10, 4, 12, 4)
        pl.setSpacing(7)
        self.dot = Dot("#6b7280", 9)
        self.status_lbl = QLabel("未运行")
        self.status_lbl.setObjectName("pill_txt")
        pl.addWidget(self.dot)
        pl.addWidget(self.status_lbl)
        head.addWidget(self.pill)
        head.addSpacing(2)

        self.btn_sub = QPushButton("字幕 开")
        self.btn_sub.setObjectName("ghost")
        self.btn_sub.setCheckable(True)
        self.btn_sub.setChecked(True)
        self.btn_sub.setCursor(Qt.PointingHandCursor)
        self.btn_sub.setFixedHeight(36)
        self.btn_sub.setMinimumWidth(84)
        self.btn_sub.setToolTip("显示 / 隐藏字幕悬浮窗（Ctrl+Alt+H 同效）")
        self.btn_sub.toggled.connect(self._on_subtitle_toggled)
        head.addWidget(self.btn_sub)
        head.addSpacing(2)

        self.btn_run = QPushButton("开始同传")
        self.btn_run.setObjectName("primary")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setFixedHeight(36)
        self.btn_run.setMinimumWidth(118)
        self.btn_run.setIconSize(QSize(13, 13))
        self.btn_run.setIcon(QIcon(str(PLAY)))
        self.btn_run.clicked.connect(self._toggle_run)
        head.addWidget(self.btn_run)

        root.addLayout(head)
        root.addWidget(self._hairline())

        # ---- 选项卡 ----
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._tab_main(), "同传")
        self.tabs.addTab(self._tab_settings(), "设置")
        self.tabs.addTab(self._tab_about(), "使用说明")
        root.addWidget(self.tabs, 1)

        # ---- 底部指标条 ----
        root.addWidget(self._hairline())
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 2, 0)
        bottom.setSpacing(6)
        self.chip_asr = self._chip("识别 —")
        self.chip_mt = self._chip("翻译 —")
        self.chip_tts = self._chip("配音 —")
        self.chip_e2e = self._chip("字幕 —")
        for c in (self.chip_asr, self.chip_mt, self.chip_tts, self.chip_e2e):
            bottom.addWidget(c)
        self.stat_lbl = ElidedLabel("就绪")
        self.stat_lbl.setObjectName("stat")
        bottom.addWidget(self.stat_lbl, 1)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    @staticmethod
    def _hairline() -> QFrame:
        f = QFrame()
        f.setObjectName("hline")
        f.setFixedHeight(1)
        return f

    @staticmethod
    def _repolish(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    @staticmethod
    def _chip(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("chip")
        return lb

    @staticmethod
    def _field(label: str, *widgets, width: int = 62) -> QWidget:
        return field_row(label, *widgets, width=width)

    @staticmethod
    def _step(num: str, title: str, body: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        n = QLabel(num)
        n.setObjectName("step_num")
        n.setFixedSize(20, 20)
        n.setAlignment(Qt.AlignCenter)
        n.setFont(make_font(11, QFont.Bold))
        h.addWidget(n, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("step_title")
        b = QLabel(f"<p style='margin:0; line-height:182%'>{body}</p>")
        b.setObjectName("help")
        b.setTextFormat(Qt.RichText)
        b.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(b)
        h.addLayout(col, 1)
        return row

    @staticmethod
    def _bullet(text: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(9)
        dot = QFrame()
        dot.setObjectName("bullet")
        dot.setFixedSize(5, 5)
        h.addWidget(dot, 0, Qt.AlignTop)
        lb = QLabel(f"<p style='margin:0; line-height:175%'>{text}</p>")
        lb.setObjectName("help")
        lb.setTextFormat(Qt.RichText)
        lb.setWordWrap(True)
        h.addWidget(lb, 1)
        return row

    # ------------------------------------------------------------------
    def _tab_main(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 6, 2, 0)
        lay.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)
        right = QVBoxLayout()
        right.setSpacing(8)

        # ---- 声音来源 ----
        c_src = SectionCard("声音来源", "从哪里听到声音")
        self.cmb_source = QComboBox()
        self.cmb_source.addItem("系统声音（游戏 / 电影 / 会议 / 通话）", "system")
        self.cmb_source.addItem("麦克风（面对面说话）", "mic")
        self.cmb_source.currentIndexChanged.connect(self._refresh_devices)
        c_src.body.addWidget(self._field("采集", self.cmb_source))

        self.cmb_device = QComboBox()
        self.cmb_device.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_device.setMinimumContentsLength(12)
        btn_ref = QPushButton()
        btn_ref.setObjectName("icon")
        btn_ref.setFixedSize(32, 32)
        btn_ref.setIcon(QIcon(str(REFRESH)))
        btn_ref.setIconSize(QSize(15, 15))
        btn_ref.setToolTip("重新枚举音频设备")
        btn_ref.setCursor(Qt.PointingHandCursor)
        btn_ref.clicked.connect(self._refresh_devices)
        self.cmb_device.currentIndexChanged.connect(self._sync_device_tooltip)
        c_src.body.addWidget(self._field("设备", self.cmb_device, btn_ref))

        self.cmb_playback = QComboBox()
        self.cmb_playback.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_playback.setMinimumContentsLength(12)
        c_src.body.addWidget(self._field("译文播放", self.cmb_playback))
        left.addWidget(c_src)

        # ---- 语言方向 ----
        c_lang = SectionCard("语言方向", "可一键互换")
        lang_row = QWidget()
        hl = QHBoxLayout(lang_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        col_a = QVBoxLayout()
        col_a.setSpacing(4)
        cap1 = QLabel("对方说（原声）")
        cap1.setObjectName("field_label")
        self.cmb_src = QComboBox()
        for v, t in LANGS:
            self.cmb_src.addItem(t, v)
        col_a.addWidget(cap1)
        col_a.addWidget(self.cmb_src)

        col_b = QVBoxLayout()
        col_b.setSpacing(4)
        cap2 = QLabel("翻译成（我听到的）")
        cap2.setObjectName("field_label")
        self.cmb_dst = QComboBox()
        for v, t in TARGET_LANGS:
            self.cmb_dst.addItem(t, v)
        col_b.addWidget(cap2)
        col_b.addWidget(self.cmb_dst)

        btn_swap = QPushButton()
        btn_swap.setObjectName("swap")
        btn_swap.setFixedSize(32, 32)
        btn_swap.setIcon(QIcon(str(SWAP)))
        btn_swap.setIconSize(QSize(15, 15))
        btn_swap.setCursor(Qt.PointingHandCursor)
        btn_swap.setToolTip("交换语言方向")
        btn_swap.clicked.connect(self._swap_langs)

        hl.addLayout(col_a, 1)
        hl.addWidget(btn_swap, 0, Qt.AlignBottom)
        hl.addLayout(col_b, 1)
        c_lang.body.addWidget(lang_row)
        left.addWidget(c_lang)

        # ---- 功能开关 ----
        c_feat = SectionCard("功能开关", "关掉不需要的可以降低延迟")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        self.chk_subtitle = QCheckBox("显示字幕")
        self.chk_voice = QCheckBox("译文配音（音色跟随）")
        self.chk_partial = QCheckBox("说话中实时字幕")
        self.chk_keepvoice = QCheckBox("跟随原说话人音高")
        grid.addWidget(self.chk_subtitle, 0, 0)
        grid.addWidget(self.chk_voice, 0, 1)
        grid.addWidget(self.chk_partial, 1, 0)
        grid.addWidget(self.chk_keepvoice, 1, 1)
        self.chk_subtitle.toggled.connect(self._on_subtitle_toggled)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        c_feat.body.addLayout(grid)

        self.chk_outbound = QCheckBox("双向：把我说的翻译给对方（需要虚拟声卡）")
        self.chk_outbound.toggled.connect(self._on_outbound_toggled)
        c_feat.body.addWidget(self.chk_outbound)

        self.cmb_vmic = QComboBox()
        vrow = QHBoxLayout()
        vrow.setContentsMargins(23, 0, 0, 0)
        vrow.setSpacing(8)
        cap = QLabel("虚拟麦克风")
        cap.setObjectName("field_label")
        vrow.addWidget(cap)
        vrow.addWidget(self.cmb_vmic, 1)
        self._vmic_row = QWidget()
        self._vmic_row.setLayout(vrow)
        c_feat.body.addWidget(self._vmic_row)

        self.vmic_hint = QLabel("")
        self.vmic_hint.setObjectName("stat")
        self.vmic_hint.setMinimumHeight(16)
        self.vmic_hint.setWordWrap(True)
        c_feat.body.addWidget(self.vmic_hint)
        left.addWidget(c_feat)

        c_keys = SectionCard("快捷键", "全局生效，游戏里也有效")
        self.kbd_toggle = QLabel("Ctrl+Alt+S")
        self.kbd_overlay = QLabel("Ctrl+Alt+H")
        keys = QWidget()
        kv = QVBoxLayout(keys)
        kv.setContentsMargins(0, 2, 0, 2)
        kv.setSpacing(7)
        for kbd, cap_text in ((self.kbd_toggle, "开始 / 停止同传"),
                              (self.kbd_overlay, "显示 / 隐藏字幕")):
            row = QWidget()
            kh = QHBoxLayout(row)
            kh.setContentsMargins(0, 0, 0, 0)
            kh.setSpacing(9)
            kbd.setObjectName("kbd")
            kbd.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            cap = QLabel(cap_text)
            cap.setObjectName("field_label")
            kh.addWidget(kbd, 0, Qt.AlignVCenter)
            kh.addWidget(cap, 0, Qt.AlignVCenter)
            kh.addStretch(1)
            kv.addWidget(row)
        c_keys.body.addWidget(keys)
        left.addWidget(c_keys)
        left.addStretch(1)

        # ---- 实时 ----
        c_live = SectionCard("实时")
        self.live_badge = QLabel("待机")
        self.live_badge.setObjectName("live_badge")
        self.live_badge.setProperty("state", "off")
        c_live.add_head_widget(self.live_badge)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.meter = LevelMeter()
        self.lvl_lbl = QLabel("0%")
        self.lvl_lbl.setObjectName("field_label")
        self.lvl_lbl.setFixedWidth(38)
        self.lvl_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.meter, 1)
        row.addWidget(self.lvl_lbl)
        c_live.body.addLayout(row)

        self.live_src = QLabel("等待声音…")
        self.live_src.setObjectName("live_src")
        self.live_src.setWordWrap(True)
        self.live_src.setMinimumHeight(18)
        self.live_tgt = QLabel("")
        self.live_tgt.setObjectName("live_tgt")
        self.live_tgt.setWordWrap(True)
        self.live_tgt.setMinimumHeight(56)
        self.live_tgt.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        c_live.body.addWidget(self.live_src)
        c_live.body.addWidget(self.live_tgt)

        # ---- 历史记录 ----
        c_hist = SectionCard("历史记录")
        self.hist_count = QLabel("0")
        self.hist_count.setObjectName("count_badge")
        self.hist_count.setAlignment(Qt.AlignCenter)
        c_hist.add_head_widget(self.hist_count)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("link")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_history)
        c_hist.add_head_widget(self.btn_clear)

        self.hist_stack = QStackedWidget()
        self.hist_stack.setMinimumHeight(140)
        self.history = QListWidget()
        self.history.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.history.setSpacing(6)
        self.history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.hist_empty = EmptyState(
            "还没有字幕", "点右上角「开始同传」，对话会一条条出现在这里")
        self.hist_stack.addWidget(self.hist_empty)
        self.hist_stack.addWidget(self.history)
        c_hist.body.addWidget(self.hist_stack, 1)

        right.addWidget(c_live, 0)
        right.addWidget(c_hist, 1)

        leftw = QWidget()
        leftw.setLayout(left)
        leftw.setFixedWidth(404)
        lay.addWidget(leftw, 0)
        lay.addLayout(right, 1)
        self._sync_history()
        return self._wrap_scroll(w)

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QWidget:
        """把内容包进滚动区，窗口太小时自动出现滚动条。"""
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(widget)
        ov.addWidget(sc)
        return outer

    def _swap_langs(self) -> None:
        s = self.cmb_src.currentData()
        d = self.cmb_dst.currentData()
        if not d:
            return
        i = self.cmb_src.findData(d)
        if i >= 0:
            self.cmb_src.setCurrentIndex(i)
        if s and s != "auto":
            j = self.cmb_dst.findData(s)
            if j >= 0:
                self.cmb_dst.setCurrentIndex(j)

    # ---------------- 字幕开关 ----------------
    def _on_subtitle_toggled(self, on: bool) -> None:
        """字幕总开关：立即生效，不需要重启同传。"""
        self.cfg.subtitle_enabled = bool(on)
        if self.chk_subtitle.isChecked() != bool(on):
            self.chk_subtitle.blockSignals(True)
            self.chk_subtitle.setChecked(bool(on))
            self.chk_subtitle.blockSignals(False)
        if self.btn_sub.isChecked() != bool(on):
            self.btn_sub.blockSignals(True)
            self.btn_sub.setChecked(bool(on))
            self.btn_sub.blockSignals(False)
        self.btn_sub.setText("字幕 开" if on else "字幕 关")
        if not on:
            self.overlay.hide()
        elif self.pipe is not None:
            self.overlay.show_message("字幕已打开", 1500)

    def _on_overlay_pos_changed(self, _i: int = 0) -> None:
        self.cfg.overlay_pos = self.cmb_pos.currentData() or "bottom"
        self.overlay.apply_config()

    def _on_show_src_toggled(self, on: bool) -> None:
        self.cfg.subtitle_show_src = bool(on)
        self.overlay.apply_config()
        if on and self.cfg.subtitle_enabled and self.last_final is not None:
            r = self.last_final
            self.overlay.set_final(r.src_text, r.tgt_text or r.src_text,
                                   r.direction, 2500)

    def _on_outbound_toggled(self, on: bool) -> None:
        self._vmic_row.setVisible(bool(on))
        self._update_vmic_hint()

    def _update_vmic_hint(self) -> None:
        if not self.chk_outbound.isChecked():
            self.vmic_hint.setObjectName("stat")
            self.vmic_hint.setText("勾选后你的话也会翻译成外语送给对方。")
        elif dv.has_vb_cable():
            self.vmic_hint.setObjectName("ok")
            self.vmic_hint.setText("已检测到虚拟声卡：把「虚拟麦克风」选成 CABLE Input，"
                                   "再把对方软件（Discord / 游戏 / Zoom）里的麦克风选成 "
                                   "CABLE Output 即可。")
        else:
            self.vmic_hint.setObjectName("warn")
            self.vmic_hint.setText("未检测到 VB-CABLE 虚拟声卡。要「把我说的话翻译给对方听」，"
                                   "请先安装 VB-Audio Virtual Cable（免费），装完点「刷新」。")
        self._repolish(self.vmic_hint)

    # ------------------------------------------------------------------
    def _tab_settings(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 8, 2, 0)
        v.setSpacing(8)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(0, 0, 6, 0)
        cols.setSpacing(12)
        col_a = QVBoxLayout()
        col_a.setSpacing(10)
        col_b = QVBoxLayout()
        col_b.setSpacing(10)
        cols.addLayout(col_a, 1)
        cols.addLayout(col_b, 1)
        sc.setWidget(inner)
        v.addWidget(sc, 1)

        # ---- 翻译引擎（左） ----
        g = SectionCard("翻译引擎", "决定译文质量与联网方式")
        self.cmb_mt = QComboBox()
        for val, text in MT_ENGINES:
            self.cmb_mt.addItem(text, val)
        g.body.addWidget(self._field("引擎", self.cmb_mt, width=86))

        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-…  仅 DeepSeek 引擎需要")
        g.body.addWidget(self._field("DeepSeek Key", self.ed_key, width=86))

        self.sp_ctx = QSpinBox()
        self.sp_ctx.setRange(0, 6)
        g.body.addWidget(self._field("上文句数", self.sp_ctx, width=86))

        self.chk_offline = QCheckBox("完全离线（断网也能用）")
        self.chk_offline.setToolTip("翻译走本地 opus-mt 模型，配音走本地 Piper 音色，"
                                    "全程不联网。")
        self.chk_offline.toggled.connect(self._on_offline_toggled)
        g.body.addWidget(self.chk_offline)

        self.offline_hint = QLabel("")
        self.offline_hint.setObjectName("stat")
        self.offline_hint.setWordWrap(True)
        g.body.addWidget(self.offline_hint)
        col_a.addWidget(g)

        # ---- 语音识别（左） ----
        g = SectionCard("语音识别", "CPU 即可，无需显卡")
        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(1, 16)
        g.body.addWidget(self._field("识别线程", self.sp_threads, width=86))
        model = QLabel("SenseVoiceSmall · int8 · 中英日韩粤 · 约 10 倍实时")
        model.setObjectName("tiny")
        g.body.addWidget(model)
        col_a.addWidget(g)

        # ---- 快捷键（左） ----
        g = SectionCard("快捷键", "全局生效，游戏里也能用")
        self.ed_hk1 = QLineEdit()
        g.body.addWidget(self._field("开始 / 停止", self.ed_hk1, width=86))
        self.ed_hk2 = QLineEdit()
        g.body.addWidget(self._field("显示 / 隐藏字幕", self.ed_hk2, width=86))
        col_a.addWidget(g)
        col_a.addStretch(1)

        # ---- 配音（右） ----
        g = SectionCard("配音", "译文用什么声音读出来")
        self.cmb_tts = QComboBox()
        for val, text in TTS_ENGINES:
            self.cmb_tts.addItem(text, val)
        g.body.addWidget(self._field("引擎", self.cmb_tts, width=86))

        self.cmb_voice_zh = QComboBox()
        self.cmb_voice_zh.setEditable(True)
        g.body.addWidget(self._field("中文音色", self.cmb_voice_zh, width=86))

        self.cmb_voice_en = QComboBox()
        self.cmb_voice_en.setEditable(True)
        g.body.addWidget(self._field("英语音色", self.cmb_voice_en, width=86))

        self.cmb_rate = QComboBox()
        for val in ("-20%", "-10%", "+0%", "+10%", "+20%", "+30%"):
            self.cmb_rate.addItem(val, val)
        g.body.addWidget(self._field("语速", self.cmb_rate, width=86))

        btn_voices = QPushButton("从网络刷新音色列表")
        btn_voices.setObjectName("ghost")
        btn_voices.clicked.connect(self._load_voices)
        g.body.addWidget(btn_voices, 0, Qt.AlignLeft)
        col_b.addWidget(g)

        # ---- 字幕样式（右） ----
        g = SectionCard("字幕样式", "悬浮字幕窗")
        g.body.setSpacing(6)
        self.cmb_pos = QComboBox()
        for label, val in (("底部（默认）", "bottom"), ("顶部（FPS 不挡准星）", "top"),
                           ("屏幕中间", "middle")):
            self.cmb_pos.addItem(label, val)
        self.cmb_pos.currentIndexChanged.connect(self._on_overlay_pos_changed)
        g.body.addWidget(self._field("位置", self.cmb_pos, width=86))

        self.sp_tgt_size = QSpinBox()
        self.sp_tgt_size.setRange(14, 64)
        g.body.addWidget(self._field("译文字号", self.sp_tgt_size, width=86))

        self.sp_src_size = QSpinBox()
        self.sp_src_size.setRange(9, 40)
        g.body.addWidget(self._field("原文字号", self.sp_src_size, width=86))

        self.sp_opacity = QDoubleSpinBox()
        self.sp_opacity.setRange(0.25, 1.0)
        self.sp_opacity.setSingleStep(0.05)
        g.body.addWidget(self._field("不透明度", self.sp_opacity, width=86))

        self.chk_show_src = QCheckBox("字幕里带原文小字")
        self.chk_show_src.setToolTip("关掉后悬浮窗只显示译文，FPS 视野更干净")
        self.chk_show_src.toggled.connect(self._on_show_src_toggled)
        g.body.addWidget(self.chk_show_src)

        btn_prev = QPushButton("预览字幕")
        btn_prev.setObjectName("ghost")
        btn_prev.clicked.connect(self._preview_overlay)
        g.body.addWidget(btn_prev, 0, Qt.AlignLeft)
        col_b.addWidget(g)
        col_b.addStretch(1)

        # ---- 保存条（固定底部） ----
        bar = QFrame()
        bar.setObjectName("savebar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(12, 7, 14, 7)
        hb.setSpacing(10)
        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("primary")
        btn_save.setFixedHeight(34)
        btn_save.setIcon(QIcon(str(CHECK)))
        btn_save.setIconSize(QSize(12, 12))
        btn_save.clicked.connect(self._save_settings)
        btn_open = QPushButton("打开配置目录")
        btn_open.setObjectName("ghost")
        btn_open.clicked.connect(self._open_config_dir)
        hb.addWidget(btn_save)
        hb.addWidget(btn_open)
        hb.addStretch(1)
        saved = QLabel("保存后立即写入 config.json · 热键立即生效")
        saved.setObjectName("tiny")
        hb.addWidget(saved)
        v.addWidget(bar)
        return w

    # ------------------------------------------------------------------
    def _tab_about(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(2, 10, 2, 0)
        outer.setSpacing(12)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        outer.addLayout(lay, 0)

        # 左：三种用法
        left = SectionCard("三种用法", "按场景选一项")
        left.body.setSpacing(18)
        left.body.addWidget(self._step(
            "1", "看电影 / 玩游戏 / 开会",
            "采集选「系统声音」，设备选正在放声音的那只扬声器，点右上角"
            "「开始同传」。字幕浮在屏幕下方，鼠标可以穿透，不影响操作。"))
        left.body.addWidget(self._step(
            "2", "面对面聊天",
            "采集选「麦克风」，让外国朋友对着你的麦克风说话，"
            "中文译文从耳机里播出来。"))
        left.body.addWidget(self._step(
            "3", "跟外国人语音通话（Discord / 游戏内语音 / Zoom）",
            "需要装 <span style='color:#e9edf6'>VB-Audio Virtual Cable</span>（免费）。"
            "装好后把「虚拟麦克风」选成 CABLE Input，再把对方软件里的麦克风选成 "
            "CABLE Output，勾上「双向」——对方听到的就是翻译好的外语，"
            "而你听到的是翻译好的中文。"))
        foot = QLabel("改完设置记得点「保存设置」才会生效。")
        foot.setObjectName("stat")
        left.body.addWidget(foot)
        lay.addWidget(left, 1, Qt.AlignTop)

        # 右：小提示 + 音色说明
        rw = QWidget()
        rw.setFixedWidth(380)
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        tips = SectionCard("小提示")
        tips.body.setSpacing(8)
        tips.body.addWidget(self._bullet(
            "译文配音尽量输出到<b>耳机</b>，别和采集的扬声器同一只，"
            "否则会互相干扰（程序会自动丢弃自播回声）。"))
        tips.body.addWidget(self._bullet(
            "全屏独占的游戏无法显示悬浮窗，请改成「无边框窗口 / 窗口化」。"))
        tips.body.addWidget(self._bullet(
            "字幕延迟约 1～1.5 秒（识别 0.2s + 翻译 1s），配音随后跟上；"
            "底部指标条实时显示「识别 / 翻译 / 配音 / 字幕」四段耗时。"))
        tips.body.addWidget(self._bullet(
            "快捷键：<b>Ctrl+Alt+S</b> 开始 / 停止，<b>Ctrl+Alt+H</b> 开关字幕。"))
        rl.addWidget(tips)

        voice = SectionCard("音色说明")
        vb = QLabel(
            "<p style='margin:0; line-height:165%'>"
            "本机没有 NVIDIA 显卡，跑不动「声音克隆」模型，因此采用"
            "<span style='color:#e9edf6'>音高 + 性别匹配</span>：识别原说话人是男声还是"
            "女声、音高多少，再挑最接近的配音并做音高偏移，听起来像同一个人。"
            "如需 1:1 克隆，可在设置里接云服务（如 ElevenLabs / MiniMax）。</p>")
        vb.setObjectName("help")
        vb.setTextFormat(Qt.RichText)
        vb.setWordWrap(True)
        voice.body.addWidget(vb)
        rl.addWidget(voice)
        lay.addWidget(rw, 0, Qt.AlignTop)

        outer.addWidget(self._hairline())
        note = QLabel("语音识别全程在本机完成，音频不会上传；只有选择在线翻译 / "
                      "配音引擎时，识别出的文字才会发往对应服务。")
        note.setObjectName("stat")
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch(1)
        return self._wrap_scroll(w)

    # ==================================================================
    # 设备 / 配置
    # ==================================================================
    def _refresh_devices(self) -> None:
        mode = self.cmb_source.currentData() or "system"
        self.cmb_device.clear()
        try:
            if mode == "system":
                devs = dv.list_loopbacks()
                # 默认选中"当前默认输出设备"对应的环回
                default_name = ""
                try:
                    import pyaudiowpatch as pyaudio
                    default_name = dv.get_pa().get_default_wasapi_loopback()["name"]
                except Exception:
                    default_name = ""
                for d in devs:
                    self._add_device(d.name)
                # 优先沿用已保存的设备，其次用「系统默认输出」对应的环回
                want = self._short_name(self.cfg.loopback_device or default_name or "")
                idx = 0
                if want:
                    for i in range(self.cmb_device.count()):
                        if self.cmb_device.itemText(i) == want:
                            idx = i
                            break
                    else:
                        for i in range(self.cmb_device.count()):
                            if self.cmb_device.itemText(i).startswith(want):
                                idx = i
                                break
                self.cmb_device.setCurrentIndex(idx)
            else:
                for d in dv.list_inputs():
                    self._add_device(d.name)
                i = self.cmb_device.findData(self.cfg.mic_device)
                if i >= 0:
                    self.cmb_device.setCurrentIndex(i)
        except Exception as e:
            self.cmb_device.addItem(f"枚举失败: {e}", "")

        self.cmb_playback.clear()
        self.cmb_playback.addItem("默认输出设备", "")
        try:
            for d in dv.list_outputs():
                self.cmb_playback.addItem(d.name, d.name)
            i = self.cmb_playback.findData(self.cfg.playback_device)
            if i >= 0:
                self.cmb_playback.setCurrentIndex(i)
        except Exception:
            pass

        # 虚拟麦克风（VB-CABLE 等）
        try:
            prev = self.cmb_vmic.currentData() if self.cmb_vmic.count() else None
            self.cmb_vmic.clear()
            vms = dv.list_virtual_mics()
            if not vms:
                self.cmb_vmic.addItem("（未安装虚拟声卡）", "")
            else:
                for d in vms:
                    i = self.cmb_vmic.count()
                    self.cmb_vmic.addItem(self._short_name(d.name), d.name)
                    self.cmb_vmic.setItemData(i, d.name, Qt.ToolTipRole)
                want = (self.cfg.virtual_mic_device or prev or "")
                i = self.cmb_vmic.findData(want) if want else -1
                self.cmb_vmic.setCurrentIndex(i if i >= 0 else 0)
        except Exception:
            pass

    @staticmethod
    def _short_name(name: str) -> str:
        """列表里显示短名，完整名字放 tooltip，避免窄栏里被硬切。"""
        for junk in (" [Loopback]", "[Loopback]", " (VB-Audio Virtual Cable)",
                     " (VB-Audio Point)", " Virtual Cable"):
            name = name.replace(junk, "")
        return name.strip()

    def _add_device(self, name: str) -> None:
        i = self.cmb_device.count()
        self.cmb_device.addItem(self._short_name(name), name)
        self.cmb_device.setItemData(i, name, Qt.ToolTipRole)

    def _sync_device_tooltip(self, *_) -> None:
        self.cmb_device.setToolTip(self.cmb_device.currentData() or "")

    def _load_voices(self) -> None:
        try:
            pipe = self.pipe or DualPipeline(self.cfg)
            svc = pipe.service
            zh = svc.voices_for("zh")
            en = svc.voices_for("en")
        except Exception as e:
            QMessageBox.warning(self, "音色", f"获取失败：{e}")
            return
        for cmb, vs, cur in ((self.cmb_voice_zh, zh, self.cfg.tts_voice_zh),
                             (self.cmb_voice_en, en, self.cfg.tts_voice_en)):
            cmb.clear()
            cmb.addItem("自动（按说话人性别挑选）", "")
            for v in vs:
                name = v.get("ShortName") or ""
                gender = (v.get("Gender") or "")
                cmb.addItem(f"{name}  ({gender})", name)
            i = cmb.findData(cur)
            cmb.setCurrentIndex(i if i >= 0 else 0)

    def _on_offline_toggled(self, on: bool) -> None:
        """勾上「完全离线」→ 翻译切 opus、配音切 piper。"""
        self.cfg.offline_only = bool(on)
        if on:
            i = self.cmb_mt.findData("opus")
            if i >= 0:
                self.cmb_mt.setCurrentIndex(i)
            i = self.cmb_tts.findData("piper")
            if i >= 0:
                self.cmb_tts.setCurrentIndex(i)
        self._update_offline_hint()

    def _update_offline_hint(self) -> None:
        from ..mt.translator import OpusMtTranslator
        from ..tts.offline import PiperTTS
        from ..config import MODELS_DIR

        mt_ok, mt_msg = OpusMtTranslator(MODELS_DIR / "mt").available()
        tts = PiperTTS(self.cfg.piper_dir or (MODELS_DIR / "tts"))
        tts_ok, tts_msg = tts.available()
        if self.chk_offline.isChecked():
            if mt_ok and tts_ok:
                self.offline_hint.setObjectName("ok")
                self.offline_hint.setText("离线模型齐全：本地翻译 + 本地配音，断网可用。"
                                          "（首次使用会加载约 1 秒）")
            else:
                self.offline_hint.setObjectName("warn")
                miss = []
                if not mt_ok:
                    miss.append(f"翻译模型（{mt_msg}）")
                if not tts_ok:
                    miss.append(f"配音模型（{tts_msg}）")
                self.offline_hint.setText("缺少离线" + "、".join(miss)
                                          + "。点下方按钮下载。")
        else:
            self.offline_hint.setObjectName("stat")
            self.offline_hint.setText("不勾选时用在线引擎（质量更好）。"
                                      "勾选后完全断网也能翻译和配音。")
        self.offline_hint.style().unpolish(self.offline_hint)
        self.offline_hint.style().polish(self.offline_hint)

    def _load_settings_into_ui(self) -> None:
        c = self.cfg
        self.cmb_source.setCurrentIndex(0 if c.capture_source == "system" else 1)
        self._refresh_devices()
        # 语言
        i = self.cmb_src.findData(c.source_lang)
        self.cmb_src.setCurrentIndex(max(0, i))
        i = self.cmb_dst.findData(c.target_lang)
        self.cmb_dst.setCurrentIndex(max(0, i))
        # 开关
        self.chk_subtitle.setChecked(c.subtitle_enabled)
        self.chk_show_src.setChecked(bool(getattr(c, "subtitle_show_src", True)))
        self.btn_sub.setChecked(bool(c.subtitle_enabled))
        self.btn_sub.setText("字幕 开" if c.subtitle_enabled else "字幕 关")
        self.chk_voice.setChecked(c.voice_enabled)
        self.chk_partial.setChecked(c.partial_enabled)
        self.chk_keepvoice.setChecked(c.tts_pitch_follow)
        self.chk_outbound.setChecked(c.outbound_enabled)
        # 虚拟麦克风：列表由 _refresh_devices() 填，这里只做选中
        if self.cmb_vmic.count():
            i = self.cmb_vmic.findData(c.virtual_mic_device) if c.virtual_mic_device else -1
            self.cmb_vmic.setCurrentIndex(i if i >= 0 else 0)
        self._on_outbound_toggled(bool(c.outbound_enabled))
        # 播放设备
        i = self.cmb_playback.findData(c.playback_device)
        self.cmb_playback.setCurrentIndex(i if i >= 0 else 0)
        # 设置页
        i = self.cmb_mt.findData(c.mt_engine)
        self.cmb_mt.setCurrentIndex(max(0, i))
        i = self.cmb_tts.findData(c.tts_engine)
        self.cmb_tts.setCurrentIndex(max(0, i))
        self.chk_offline.setChecked(bool(getattr(c, "offline_only", False)))
        self._update_offline_hint()
        self.ed_key.setText(c.deepseek_api_key)
        self.sp_ctx.setValue(int(getattr(c, "mt_context", 3) or 0))
        self.sp_threads.setValue(c.asr_threads or 4)
        self.sp_tgt_size.setValue(c.overlay_tgt_size)
        self.sp_src_size.setValue(c.overlay_src_size)
        self.sp_opacity.setValue(c.overlay_opacity)
        self._sync_hotkeys()
        self.ed_hk1.setText(c.hotkey_toggle)
        self.ed_hk2.setText(c.hotkey_overlay)
        i = self.cmb_rate.findData(c.tts_rate)
        self.cmb_rate.setCurrentIndex(i if i >= 0 else 2)
        self.cmb_voice_zh.addItem("自动（按说话人性别挑选）", "")
        self.cmb_voice_en.addItem("自动（按说话人性别挑选）", "")

    def _collect_settings(self) -> None:
        c = self.cfg
        c.capture_source = self.cmb_source.currentData() or "system"
        name = self.cmb_device.currentData() or ""
        if c.capture_source == "system":
            c.loopback_device = name
        else:
            c.mic_device = name
        c.playback_device = self.cmb_playback.currentData() or ""
        c.virtual_mic_device = self.cmb_vmic.currentData() or ""
        c.source_lang = self.cmb_src.currentData() or "auto"
        c.target_lang = self.cmb_dst.currentData() or "zh"
        c.subtitle_enabled = self.chk_subtitle.isChecked()
        c.subtitle_show_src = self.chk_show_src.isChecked()
        c.voice_enabled = self.chk_voice.isChecked()
        c.partial_enabled = self.chk_partial.isChecked()
        c.tts_pitch_follow = self.chk_keepvoice.isChecked()
        c.outbound_enabled = self.chk_outbound.isChecked()
        c.mt_engine = self.cmb_mt.currentData() or "bing"
        c.tts_engine = self.cmb_tts.currentData() or "edge"
        c.offline_only = self.chk_offline.isChecked()
        c.deepseek_api_key = self.ed_key.text().strip()
        c.mt_context = int(self.sp_ctx.value())
        c.asr_threads = self.sp_threads.value()
        c.overlay_pos = self.cmb_pos.currentData() or "bottom"
        c.overlay_tgt_size = self.sp_tgt_size.value()
        c.overlay_src_size = self.sp_src_size.value()
        c.overlay_opacity = float(self.sp_opacity.value())
        c.hotkey_toggle = self.ed_hk1.text().strip() or "ctrl+alt+s"
        c.hotkey_overlay = self.ed_hk2.text().strip() or "ctrl+alt+h"
        c.tts_rate = self.cmb_rate.currentData() or "+0%"
        c.tts_voice_zh = self.cmb_voice_zh.currentData() or ""
        c.tts_voice_en = self.cmb_voice_en.currentData() or ""

    def _save_settings(self) -> None:
        self._collect_settings()
        p = self.cfg.save()
        self.overlay.apply_config()
        try:
            self.hotkeys.stop()
            self.hotkeys = GlobalHotkeys(self.hotkey_q)
            self.hotkeys.start({"toggle": self.cfg.hotkey_toggle,
                                "overlay": self.cfg.hotkey_overlay})
        except Exception:
            pass
        self._sync_hotkeys()
        self._set_stat(f"设置已保存：{p.name}")

    def _open_config_dir(self) -> None:
        import subprocess
        d = self.cfg._path.parent
        try:
            subprocess.Popen(["explorer", str(d)])
        except Exception:
            pass

    def _preview_overlay(self) -> None:
        self.cfg.overlay_tgt_size = self.sp_tgt_size.value()
        self.cfg.overlay_src_size = self.sp_src_size.value()
        self.cfg.overlay_opacity = float(self.sp_opacity.value())
        self.overlay.apply_config()
        self.overlay.set_final("Hello, this is what the original sounds like.",
                               "你好，这就是原文和译文同时出现的样子。", "inbound", 5000)

    # ==================================================================
    # 运行
    # ==================================================================
    def _toggle_run(self) -> None:
        if self.pipe is not None:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        self._collect_settings()
        if self.cfg.capture_source == "system" and not self.cfg.loopback_device:
            self.cfg.loopback_device = ""
        if self.cfg.outbound_enabled and not self.cfg.virtual_mic_device:
            QMessageBox.warning(
                self, "缺少虚拟声卡",
                "双向翻译需要虚拟麦克风。\n\n请先安装 VB-Audio Virtual Cable，"
                "然后在「虚拟麦克风」里选择 CABLE Input。")
            return

        self.status_lbl.setText("正在启动…")
        self.dot.set_color(WARN)
        self._set_badge("busy", "启动中")
        self._set_stat("正在加载模型…")
        QApplication.processEvents()

        ev = Events()
        ev.on_partial = lambda s, t, d: self._push(("partial", s, t, d))
        ev.on_final = lambda r: self._push(("final", r))
        ev.on_level = lambda v, ch: self._push(("level", v))
        ev.on_error = lambda w, m: self._push(("error", w, m))
        ev.on_status = lambda s: self._push(("status", s))

        try:
            self.pipe = DualPipeline(self.cfg, ev)
            self.pipe.start()
        except Exception as e:
            self.pipe = None
            traceback.print_exc()
            QMessageBox.critical(self, "启动失败", f"{type(e).__name__}: {e}")
            self.status_lbl.setText("启动失败")
            self.dot.set_color(DANGER)
            self._set_badge("error", "启动失败")
            self._set_stat(f"启动失败：{type(e).__name__}")
            return

        self.started_at = time.time()
        self.btn_run.setText("停止同传")
        self.btn_run.setIcon(QIcon(str(STOP)))
        self.btn_run.setProperty("running", "true")
        self._repolish(self.btn_run)
        self.status_lbl.setText("运行中")
        self.dot.set_color(SUCCESS)
        self._set_badge("on", "聆听中")
        self._set_stat("正在聆听…")
        if self.cfg.subtitle_enabled:
            self.overlay.show_message("同传已开始，正在聆听…", 2000)

    def _stop(self) -> None:
        if self.pipe is not None:
            self.status_lbl.setText("正在停止…")
            QApplication.processEvents()
            try:
                self.pipe.stop()
            except Exception:
                pass
            self.pipe = None
        self.btn_run.setText("开始同传")
        self.btn_run.setIcon(QIcon(str(PLAY)))
        self.btn_run.setProperty("running", "false")
        self._repolish(self.btn_run)
        self.status_lbl.setText("未运行")
        self.dot.set_color(MUTED_2)
        self._set_badge("off", "待机")
        self._set_stat("就绪")
        self.meter.set_level(0, False)
        self.lvl_lbl.setText("0%")
        self._reset_chips()
        self.overlay.hide()

    def _set_chips(self, r: SegmentResult) -> None:
        def fmt(x: float) -> str:
            return f"{x:.2f}s" if x else "—"

        # 字幕延迟 = 识别 + 翻译（配音在后台跟上，不阻塞字幕）
        sub_s = (r.asr_s or 0.0) + (r.mt_s or 0.0)
        self.chip_asr.setText(f"识别 {fmt(r.asr_s)}")
        self.chip_mt.setText(f"翻译 {fmt(r.mt_s)}")
        self.chip_tts.setText(f"配音 {fmt(r.tts_s)}")
        self.chip_e2e.setText(f"字幕 {fmt(sub_s)}")
        for c in (self.chip_asr, self.chip_mt, self.chip_tts, self.chip_e2e):
            c.setProperty("hot", "false")
            c.style().unpolish(c)
            c.style().polish(c)
        if sub_s:
            hot = "true" if sub_s < 2.0 else "false"
            self.chip_e2e.setProperty("hot", hot)
            self.chip_e2e.style().unpolish(self.chip_e2e)
            self.chip_e2e.style().polish(self.chip_e2e)

    def _add_history(self, r: SegmentResult) -> None:
        ts = time.strftime("%H:%M:%S")
        card = HistoryCard(r.src_text, r.tgt_text or r.src_text, ts, r.direction)
        it = QListWidgetItem()
        it.setSizeHint(card.sizeHint())
        it.setToolTip(f"识别 {r.asr_s:.2f}s · 翻译 {r.mt_s:.2f}s · "
                      f"配音 {r.tts_s:.2f}s · 字幕 {(r.asr_s or 0) + (r.mt_s or 0):.2f}s")
        self.history.addItem(it)
        self.history.setItemWidget(it, card)
        while self.history.count() > 200:
            self.history.takeItem(0)
        self.history.scrollToBottom()
        self._sync_history()

    def _sync_history(self) -> None:
        """历史条数 / 空状态互换。"""
        n = self.history.count()
        self.hist_count.setText(str(n))
        self.hist_stack.setCurrentIndex(1 if n else 0)

    def _clear_history(self) -> None:
        self.history.clear()
        self._sync_history()

    @staticmethod
    def _pretty_hotkey(raw: str) -> str:
        names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
        parts = [names.get(p.strip().lower(), p.strip().upper())
                 for p in str(raw or "").split("+") if p.strip()]
        return "+".join(parts) or "—"

    def _sync_hotkeys(self) -> None:
        self.kbd_toggle.setText(self._pretty_hotkey(self.cfg.hotkey_toggle))
        self.kbd_overlay.setText(self._pretty_hotkey(self.cfg.hotkey_overlay))

    def _set_badge(self, state: str, text: str) -> None:
        self.live_badge.setText(text)
        self.live_badge.setProperty("state", state)
        self._repolish(self.live_badge)

    def _set_stat(self, text: str) -> None:
        self.stat_lbl.setText(text)

    def _reset_chips(self) -> None:
        for c, n in ((self.chip_asr, "识别"), (self.chip_mt, "翻译"),
                     (self.chip_tts, "配音"), (self.chip_e2e, "端到端")):
            c.setText(f"{n} —")
            c.setProperty("hot", "false")
            c.style().unpolish(c)
            c.style().polish(c)

    def closeEvent(self, e) -> None:
        if self.pipe is not None:
            self._stop()
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.overlay.close()
        e.accept()

    # ==================================================================
    # 事件泵
    # ==================================================================
    def _push(self, item: tuple) -> None:
        try:
            self.ui_q.put_nowait(item)
        except Exception:
            pass

    def _drain(self) -> None:
        while True:
            try:
                item = self.ui_q.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "partial":
                _, src, tgt, d = item
                self.live_src.setText(src)
                self.live_tgt.setText(tgt)
                self._set_badge("on", "我说" if d == "outbound" else "对方")
                if self.chk_subtitle.isChecked():
                    self.overlay.set_partial(src, tgt, d)
            elif kind == "final":
                r: SegmentResult = item[1]
                self.last_final = r
                self.live_src.setText(r.src_text)
                self.live_tgt.setText(r.tgt_text or r.src_text)
                self._add_history(r)
                if self.chk_subtitle.isChecked():
                    self.overlay.set_final(r.src_text, r.tgt_text or r.src_text,
                                           r.direction, 6000)
                self._set_chips(r)
                err = f" · ⚠ {r.error}" if r.error else ""
                src_tag = "我：" if r.direction == "outbound" else ""
                self._set_stat(f"{src_tag}{r.src_text}{err}")
            elif kind == "level":
                _, lv = item[0], item[1]
                self.meter.set_level(lv, lv > 0.5)
                self.lvl_lbl.setText(f"{int(lv * 100)}%")
            elif kind == "error":
                _, where, msg = item
                self._set_stat(f"⚠ {where}：{msg}")

        # 全局热键
        while True:
            try:
                name = self.hotkey_q.get_nowait()
            except queue.Empty:
                break
            if name == "toggle":
                self._toggle_run()
            elif name == "overlay":
                self._on_subtitle_toggled(not self.chk_subtitle.isChecked())

    # ==================================================================
    def _build_tray(self) -> None:
        try:
            self.tray = QSystemTrayIcon(self)
            if ICON_PATH.exists():
                self.tray.setIcon(QIcon(str(ICON_PATH)))
            self.tray.setToolTip("LiveDub 实时同声翻译")
            menu = QMenu()
            a1 = QAction("开始 / 停止", self, triggered=self._toggle_run)
            a2 = QAction("显示 / 隐藏字幕", self, triggered=self.overlay.toggle)
            a3 = QAction("显示主窗口", self, triggered=self._show_main)
            a4 = QAction("退出", self, triggered=self.close)
            for a in (a1, a2, a3):
                menu.addAction(a)
            menu.addSeparator()
            menu.addAction(a4)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(
                lambda why: self._show_main() if why == QSystemTrayIcon.Trigger else None)
            self.tray.show()
            self._tray_menu = menu
        except Exception:
            self.tray = None

    def _show_main(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
