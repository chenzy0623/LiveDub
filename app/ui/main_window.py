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
    QPushButton, QComboBox, QCheckBox, QGroupBox, QListWidget, QListWidgetItem,
    QTabWidget, QFrame, QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox,
    QSizePolicy, QScrollArea, QApplication, QSystemTrayIcon, QMenu,
)

from ..audio import devices as dv
from ..config import Config
from ..mt.translator import LANG_NAME
from ..pipeline.engine import DualPipeline, Events, SegmentResult
from .hotkeys import GlobalHotkeys
from .overlay import SubtitleOverlay
from .style import DARK_QSS, ICON_PATH
from .widgets import LevelMeter, Dot, HistoryCard

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
              ("none", "不翻译（只显示原文）")]


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
        self.setMinimumSize(920, 740)
        self.resize(1020, 850)
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
        root.setContentsMargins(22, 16, 22, 12)
        root.setSpacing(8)

        # ---- 顶部标题栏 ----
        head = QHBoxLayout()
        head.setSpacing(12)

        logo = QLabel("LD")
        logo.setObjectName("logo")
        logo.setFixedSize(38, 38)
        logo.setAlignment(Qt.AlignCenter)
        head.addWidget(logo)

        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        title = QLabel("LiveDub")
        title.setObjectName("h1")
        sub = QLabel("实时同声翻译 · 保持原说话人音色")
        sub.setObjectName("sub")
        tbox.addWidget(title)
        tbox.addWidget(sub)
        head.addLayout(tbox)
        head.addStretch(1)

        pill = QFrame()
        pill.setObjectName("pill")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(12, 5, 14, 5)
        pl.setSpacing(8)
        self.dot = Dot("#6b7280", 12)
        self.status_lbl = QLabel("未运行")
        self.status_lbl.setObjectName("pill_txt")
        pl.addWidget(self.dot)
        pl.addWidget(self.status_lbl)
        head.addWidget(pill)
        head.addSpacing(6)

        self.btn_run = QPushButton("开始同传")
        self.btn_run.setObjectName("primary")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self._toggle_run)
        head.addWidget(self.btn_run)
        root.addLayout(head)

        root.addSpacing(6)

        # ---- 选项卡 ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_main(), "  同传  ")
        self.tabs.addTab(self._tab_settings(), "  设置  ")
        self.tabs.addTab(self._tab_about(), "  使用说明  ")
        root.addWidget(self.tabs, 1)

        # ---- 底部状态条 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.stat_lbl = QLabel("就绪")
        self.stat_lbl.setObjectName("stat")
        self.chip_asr = self._chip("识别 —")
        self.chip_mt = self._chip("翻译 —")
        self.chip_tts = self._chip("配音 —")
        self.chip_e2e = self._chip("端到端 —")
        for c in (self.chip_asr, self.chip_mt, self.chip_tts, self.chip_e2e):
            bottom.addWidget(c)
        bottom.addStretch(1)
        bottom.addWidget(self.stat_lbl)
        root.addLayout(bottom)

    @staticmethod
    def _chip(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("chip")
        return lb

    @staticmethod
    def _cap(text: str, width: int = 96) -> QLabel:
        lb = QLabel(text)
        lb.setMinimumWidth(width)
        return lb

    # ------------------------------------------------------------------
    def _tab_main(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 16, 2, 0)
        lay.setSpacing(6)

        # ---- 采集 ----
        g1 = QGroupBox("声音来源")
        gl = QGridLayout(g1)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(10)
        gl.setContentsMargins(2, 2, 2, 0)

        gl.addWidget(QLabel("采集"), 0, 0)
        self.cmb_source = QComboBox()
        self.cmb_source.addItem("系统声音（游戏 / 电影 / 会议 / 通话）", "system")
        self.cmb_source.addItem("麦克风（面对面说话）", "mic")
        self.cmb_source.currentIndexChanged.connect(self._refresh_devices)
        gl.addWidget(self.cmb_source, 0, 1, 1, 2)

        gl.addWidget(QLabel("设备"), 1, 0)
        self.cmb_device = QComboBox()
        gl.addWidget(self.cmb_device, 1, 1)
        btn_ref = QPushButton("刷新")
        btn_ref.setObjectName("ghost")
        btn_ref.setMinimumHeight(34)
        btn_ref.setCursor(Qt.PointingHandCursor)
        btn_ref.clicked.connect(self._refresh_devices)
        gl.addWidget(btn_ref, 1, 2)

        gl.addWidget(QLabel("译文播放"), 2, 0)
        self.cmb_playback = QComboBox()
        gl.addWidget(self.cmb_playback, 2, 1, 1, 2)

        gl.setColumnStretch(1, 1)
        lay.addWidget(g1)

        # ---- 语言 ----
        g2 = QGroupBox("语言方向")
        hl = QHBoxLayout(g2)
        hl.setSpacing(12)
        hl.setContentsMargins(2, 2, 2, 0)

        left = QVBoxLayout()
        left.setSpacing(3)
        cap1 = QLabel("对方说（原声）")
        cap1.setObjectName("field_cap")
        self.cmb_src = QComboBox()
        for v, t in LANGS:
            self.cmb_src.addItem(t, v)
        left.addWidget(cap1)
        left.addWidget(self.cmb_src)

        right = QVBoxLayout()
        right.setSpacing(3)
        cap2 = QLabel("翻译成（我听到的）")
        cap2.setObjectName("field_cap")
        self.cmb_dst = QComboBox()
        for v, t in TARGET_LANGS:
            self.cmb_dst.addItem(t, v)
        right.addWidget(cap2)
        right.addWidget(self.cmb_dst)

        btn_swap = QPushButton("⇄")
        btn_swap.setObjectName("swap")
        btn_swap.setFixedSize(34, 34)
        btn_swap.setCursor(Qt.PointingHandCursor)
        btn_swap.setToolTip("交换语言方向")
        btn_swap.clicked.connect(self._swap_langs)

        hl.addLayout(left, 1)
        hl.addWidget(btn_swap, 0, Qt.AlignBottom)
        hl.addLayout(right, 1)
        lay.addWidget(g2)

        # ---- 功能开关 ----
        g3 = QGroupBox("功能")
        fl = QGridLayout(g3)
        fl.setHorizontalSpacing(16)
        fl.setVerticalSpacing(6)
        fl.setContentsMargins(2, 2, 2, 0)
        self.chk_subtitle = QCheckBox("显示字幕")
        self.chk_voice = QCheckBox("译文配音（说话人音色）")
        self.chk_partial = QCheckBox("说话中实时字幕")
        self.chk_keepvoice = QCheckBox("跟随原说话人音高")
        fl.addWidget(self.chk_subtitle, 0, 0)
        fl.addWidget(self.chk_voice, 0, 1)
        fl.addWidget(self.chk_partial, 1, 0)
        fl.addWidget(self.chk_keepvoice, 1, 1)

        self.chk_outbound = QCheckBox("双向：把我说的翻译给对方（需要虚拟声卡）")
        self.chk_outbound.toggled.connect(self._on_outbound_toggled)
        fl.addWidget(self.chk_outbound, 2, 0, 1, 2)

        self.cmb_vmic = QComboBox()
        vrow = QHBoxLayout()
        vrow.setContentsMargins(26, 0, 0, 0)
        vrow.setSpacing(8)
        cap = QLabel("虚拟麦克风")
        cap.setObjectName("field_cap")
        vrow.addWidget(cap)
        vrow.addWidget(self.cmb_vmic, 1)
        self._vmic_row = QWidget()
        self._vmic_row.setLayout(vrow)
        fl.addWidget(self._vmic_row, 3, 0, 1, 2)

        self.vmic_hint = QLabel("")
        self.vmic_hint.setObjectName("warn")
        self.vmic_hint.setWordWrap(True)
        fl.addWidget(self.vmic_hint, 4, 0, 1, 2)
        lay.addWidget(g3)

        # ---- 实时区 ----
        g4 = QGroupBox("实时")
        rl = QVBoxLayout(g4)
        rl.setSpacing(5)
        rl.setContentsMargins(2, 2, 2, 0)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.meter = LevelMeter()
        self.lvl_lbl = QLabel("静音")
        self.lvl_lbl.setObjectName("field_cap")
        self.lvl_lbl.setFixedWidth(52)
        row.addWidget(self.meter, 1)
        row.addWidget(self.lvl_lbl)
        rl.addLayout(row)

        self.live_src = QLabel("等待声音…")
        self.live_src.setObjectName("live_src")
        self.live_src.setWordWrap(True)
        self.live_tgt = QLabel("")
        self.live_tgt.setObjectName("live_tgt")
        self.live_tgt.setWordWrap(True)
        rl.addWidget(self.live_src)
        rl.addWidget(self.live_tgt)

        self.history = QListWidget()
        self.history.setMinimumHeight(64)
        self.history.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.history.setSpacing(6)
        self.history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        rl.addWidget(self.history, 1)
        lay.addWidget(g4, 1)
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

    def _on_outbound_toggled(self, on: bool) -> None:
        self._vmic_row.setVisible(bool(on))
        self._update_vmic_hint()
        self._vmic_row.parentWidget().updateGeometry()

    def _update_vmic_hint(self) -> None:
        if not self.chk_outbound.isChecked():
            self.vmic_hint.setObjectName("stat")
            self.vmic_hint.setText("提示：勾选上面的「双向」后，可把你说的话翻译成外语，"
                                   "送进虚拟麦克风给对方听。")
        elif dv.has_vb_cable():
            self.vmic_hint.setObjectName("ok")
            self.vmic_hint.setText("已检测到虚拟声卡：把「虚拟麦克风」选成 CABLE Input，"
                                   "再把对方软件（Discord / 游戏 / Zoom）里的麦克风选成 "
                                   "CABLE Output 即可。")
        else:
            self.vmic_hint.setObjectName("warn")
            self.vmic_hint.setText("未检测到 VB-CABLE 虚拟声卡。要「把我说的话翻译给对方听」，"
                                   "请先安装 VB-Audio Virtual Cable（免费），装完点「刷新」。")
        self.vmic_hint.style().unpolish(self.vmic_hint)
        self.vmic_hint.style().polish(self.vmic_hint)

    # ------------------------------------------------------------------
    def _tab_settings(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 12, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)

        # 翻译
        g = QGroupBox("翻译引擎")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(9)
        gl.addWidget(self._cap("引擎"), 0, 0)
        self.cmb_mt = QComboBox()
        for v, t in MT_ENGINES:
            self.cmb_mt.addItem(t, v)
        gl.addWidget(self.cmb_mt, 0, 1, 1, 2)
        gl.addWidget(self._cap("DeepSeek Key"), 1, 0)
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...  （用 DeepSeek 引擎时填写）")
        gl.addWidget(self.ed_key, 1, 1, 1, 2)
        gl.addWidget(self._cap("上文参考条数"), 2, 0)
        self.sp_ctx = QSpinBox()
        self.sp_ctx.setRange(0, 6)
        gl.addWidget(self.sp_ctx, 2, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # 识别
        g = QGroupBox("语音识别（CPU，无需显卡）")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(9)
        gl.addWidget(self._cap("当前模型"), 0, 0)
        asr_name = QLabel("SenseVoiceSmall int8（中英日韩粤，约 10 倍实时）")
        asr_name.setObjectName("hint")
        gl.addWidget(asr_name, 0, 1, 1, 2)
        gl.addWidget(self._cap("识别线程"), 1, 0)
        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(1, 16)
        gl.addWidget(self.sp_threads, 1, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # 配音
        g = QGroupBox("配音（TTS）")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(9)
        gl.addWidget(self._cap("中文音色"), 0, 0)
        self.cmb_voice_zh = QComboBox()
        self.cmb_voice_zh.setEditable(True)
        gl.addWidget(self.cmb_voice_zh, 0, 1)
        gl.addWidget(self._cap("英语音色"), 1, 0)
        self.cmb_voice_en = QComboBox()
        self.cmb_voice_en.setEditable(True)
        gl.addWidget(self.cmb_voice_en, 1, 1)
        gl.addWidget(self._cap("语速"), 2, 0)
        self.cmb_rate = QComboBox()
        for v in ("-20%", "-10%", "+0%", "+10%", "+20%", "+30%"):
            self.cmb_rate.addItem(v, v)
        gl.addWidget(self.cmb_rate, 2, 1)
        btn_voices = QPushButton("从网络刷新音色列表")
        btn_voices.clicked.connect(self._load_voices)
        gl.addWidget(btn_voices, 3, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # 字幕
        g = QGroupBox("字幕样式")
        gl = QGridLayout(g)
        gl.setVerticalSpacing(9)
        gl.addWidget(self._cap("译文字号"), 0, 0)
        self.sp_tgt_size = QSpinBox()
        self.sp_tgt_size.setRange(14, 64)
        gl.addWidget(self.sp_tgt_size, 0, 1)
        gl.addWidget(self._cap("原文字号"), 1, 0)
        self.sp_src_size = QSpinBox()
        self.sp_src_size.setRange(9, 40)
        gl.addWidget(self.sp_src_size, 1, 1)
        gl.addWidget(self._cap("不透明度"), 2, 0)
        self.sp_opacity = QDoubleSpinBox()
        self.sp_opacity.setRange(0.25, 1.0)
        self.sp_opacity.setSingleStep(0.05)
        gl.addWidget(self.sp_opacity, 2, 1)
        btn_prev = QPushButton("预览字幕")
        btn_prev.clicked.connect(self._preview_overlay)
        gl.addWidget(btn_prev, 3, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # 热键
        g = QGroupBox("快捷键（全局，游戏里也生效）")
        gl = QGridLayout(g)
        gl.addWidget(self._cap("开始 / 停止"), 0, 0)
        self.ed_hk1 = QLineEdit()
        gl.addWidget(self.ed_hk1, 0, 1)
        gl.addWidget(self._cap("显示 / 隐藏字幕"), 1, 0)
        self.ed_hk2 = QLineEdit()
        gl.addWidget(self.ed_hk2, 1, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        row = QHBoxLayout()
        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save_settings)
        btn_open = QPushButton("打开配置目录")
        btn_open.clicked.connect(self._open_config_dir)
        row.addWidget(btn_save)
        row.addWidget(btn_open)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

        sc.setWidget(inner)
        outer.addWidget(sc)
        return w

    # ------------------------------------------------------------------
    def _card(self, title: str, html: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(9)
        t = QLabel(title)
        t.setStyleSheet("color:#8b95ab; font-size:11px; font-weight:700;"
                        "letter-spacing:2px;")
        body = QLabel(html)
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setObjectName("help")
        cl.addWidget(t)
        cl.addWidget(body)
        return card

    def _tab_about(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 12, 8, 0)
        lay.setSpacing(9)

        step = ("<p style='margin:0 0 10px 0; line-height:165%'>"
                "<span style='color:#6f8cff; font-weight:700;'>{n}.</span> "
                "<b style='color:#ffffff'>{h}</b><br/>{b}</p>")

        lay.addWidget(self._card("三种用法 · 按场景选一项", "".join([
            step.format(n="1", h="看电影 / 玩游戏 / 开会",
                        b="采集选「系统声音」，设备选正在放声音的那只扬声器，"
                          "点右上角「开始同传」。字幕浮在屏幕下方，鼠标可以穿透，不影响操作。"),
            step.format(n="2", h="面对面聊天",
                        b="采集选「麦克风」，让外国朋友对着你的麦克风说话，"
                          "中文译文从耳机里播出来。"),
            step.format(n="3", h="跟外国人语音通话（Discord / 游戏内语音 / Zoom）",
                        b="需要装 <b>VB-Audio Virtual Cable</b>（免费）。装好后把「虚拟麦克风」"
                          "选成 CABLE Input，再把对方软件里的麦克风选成 CABLE Output，"
                          "勾上「双向」——这样对方听到的就是翻译好的英语，"
                          "而你听到的是翻译好的中文。"),
        ])))

        lay.addWidget(self._card("小提示", "".join([
            "<p style='margin:0 0 8px 0; line-height:160%'>"
            "· 译文配音尽量输出到<b>耳机</b>，别和采集的扬声器同一只，"
            "否则会互相干扰（程序已自动屏蔽自播声音）。</p>",
            "<p style='margin:0 0 8px 0; line-height:160%'>"
            "· 全屏独占的游戏无法显示悬浮窗，请改成「无边框窗口 / 窗口化」。</p>",
            "<p style='margin:0 0 8px 0; line-height:160%'>"
            "· 端到端延迟约 2～3 秒：语音识别 0.2s + 翻译 1s + 合成 1.3s。</p>",
            "<p style='margin:0; line-height:160%'>"
            "· 快捷键：<b>Ctrl+Alt+S</b> 开始 / 停止，<b>Ctrl+Alt+H</b> 显示 / 隐藏字幕。</p>",
        ])))

        lay.addWidget(self._card("音色说明", "".join([
            "<p style='margin:0; line-height:160%'>"
            "本机没有 NVIDIA 显卡，跑不动「声音克隆」模型，因此采用"
            "<b>音高 + 性别匹配</b>方案：识别原说话人是男声还是女声、音高多少，"
            "再挑最接近的配音并做音高偏移，听起来像同一个人。"
            "如需 1:1 克隆，可在设置里接云服务（如 ElevenLabs / MiniMax）。</p>",
        ])))
        lay.addStretch(1)
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
                    self.cmb_device.addItem(d.name, d.name)
                idx = 0
                if default_name:
                    for i in range(self.cmb_device.count()):
                        if self.cmb_device.itemText(i).startswith(default_name):
                            idx = i
                            break
                self.cmb_device.setCurrentIndex(idx)
            else:
                for d in dv.list_inputs():
                    self.cmb_device.addItem(d.name, d.name)
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
                    self.cmb_vmic.addItem(d.name, d.name)
                want = (self.cfg.virtual_mic_device or prev or "")
                i = self.cmb_vmic.findData(want) if want else -1
                self.cmb_vmic.setCurrentIndex(i if i >= 0 else 0)
        except Exception:
            pass

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
        self.ed_key.setText(c.deepseek_api_key)
        self.sp_ctx.setValue(int(getattr(c, "mt_context", 3) or 0))
        self.sp_threads.setValue(c.asr_threads or 4)
        self.sp_tgt_size.setValue(c.overlay_tgt_size)
        self.sp_src_size.setValue(c.overlay_src_size)
        self.sp_opacity.setValue(c.overlay_opacity)
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
        c.voice_enabled = self.chk_voice.isChecked()
        c.partial_enabled = self.chk_partial.isChecked()
        c.tts_pitch_follow = self.chk_keepvoice.isChecked()
        c.outbound_enabled = self.chk_outbound.isChecked()
        c.mt_engine = self.cmb_mt.currentData() or "bing"
        c.deepseek_api_key = self.ed_key.text().strip()
        c.mt_context = int(self.sp_ctx.value())
        c.asr_threads = self.sp_threads.value()
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
        self.stat_lbl.setText(f"设置已保存 → {p}")

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
        self.dot.set_color("#e0a44a")
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
            self.dot.set_color("#c23b3b")
            return

        self.started_at = time.time()
        self.btn_run.setText("停止")
        self.btn_run.setProperty("running", "true")
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.status_lbl.setText("运行中")
        self.dot.set_color("#4ade80")
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
        self.btn_run.setProperty("running", "false")
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.status_lbl.setText("未运行")
        self.dot.set_color("#6b7280")
        self.meter.set_level(0)
        self.lvl_lbl.setText("静音")
        self._reset_chips()
        self.overlay.hide()

    def _set_chips(self, r: SegmentResult) -> None:
        def fmt(x: float) -> str:
            return f"{x:.2f}s" if x else "—"

        self.chip_asr.setText(f"识别 {fmt(r.asr_s)}")
        self.chip_mt.setText(f"翻译 {fmt(r.mt_s)}")
        self.chip_tts.setText(f"配音 {fmt(r.tts_s)}")
        self.chip_e2e.setText(f"端到端 {fmt(r.latency)}")
        for c in (self.chip_asr, self.chip_mt, self.chip_tts, self.chip_e2e):
            c.setProperty("hot", "false")
            c.style().unpolish(c)
            c.style().polish(c)
        if r.latency:
            hot = "true" if r.latency < 3.0 else "false"
            self.chip_e2e.setProperty("hot", hot)
            self.chip_e2e.style().unpolish(self.chip_e2e)
            self.chip_e2e.style().polish(self.chip_e2e)

    def _add_history(self, r: SegmentResult) -> None:
        ts = time.strftime("%H:%M:%S")
        card = HistoryCard(r.src_text, r.tgt_text or r.src_text, ts, r.direction)
        it = QListWidgetItem()
        it.setSizeHint(card.sizeHint())
        it.setToolTip(f"识别 {r.asr_s:.2f}s · 翻译 {r.mt_s:.2f}s · "
                      f"配音 {r.tts_s:.2f}s · 端到端 {r.latency:.2f}s")
        self.history.addItem(it)
        self.history.setItemWidget(it, card)
        while self.history.count() > 200:
            self.history.takeItem(0)
        self.history.scrollToBottom()

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
                if self.cfg.subtitle_enabled:
                    self.overlay.set_partial(src, tgt, d)
            elif kind == "final":
                r: SegmentResult = item[1]
                self.last_final = r
                self.live_src.setText(r.src_text)
                self.live_tgt.setText(r.tgt_text or r.src_text)
                self._add_history(r)
                if self.cfg.subtitle_enabled:
                    self.overlay.set_final(r.src_text, r.tgt_text or r.src_text,
                                           r.direction, 6000)
                self._set_chips(r)
                err = f"  ⚠ {r.error}" if r.error else ""
                src_tag = "" if r.direction == "inbound" else "（我）"
                self.stat_lbl.setText(f"{src_tag}{r.src_text[:38]}{err}")
            elif kind == "level":
                _, lv = item[0], item[1]
                self.meter.set_level(lv, lv > 0.5)
                self.lvl_lbl.setText(f"{int(lv * 100)}%")
            elif kind == "error":
                _, where, msg = item
                self.stat_lbl.setText(f"⚠ {where}: {msg}")

        # 全局热键
        while True:
            try:
                name = self.hotkey_q.get_nowait()
            except queue.Empty:
                break
            if name == "toggle":
                self._toggle_run()
            elif name == "overlay":
                self.overlay.toggle()

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
