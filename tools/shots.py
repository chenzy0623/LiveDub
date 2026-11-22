"""离线截图工具：不打开真实窗口，直接 grab() 出 PNG 用于自测 UI。

用法:
    .venv/Scripts/python.exe tools/shots.py [outdir]

默认输出到 shots_preview/，包含 main / main_outbound / settings / about / overlay。
依赖 QT_QPA_PLATFORM=offscreen，不需要声卡和模型。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from app.config import Config  # noqa: E402
from app.ui import hotkeys as hk  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.overlay import SubtitleOverlay  # noqa: E402
from app.ui.widgets import HistoryCard  # noqa: E402
from app.ui.style import STOP  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QListWidgetItem  # noqa: E402


hk.GlobalHotkeys.start = lambda self, mapping: None  # 截图时不抢全局热键

W, H = 1020, 749
SMALL = (960, 690)   # 最小窗口尺寸，验证窄窗口不裁切

SAMPLE = [
    ("对方", "inbound", "22:10:02",
     "So, what build are you running on your rogue?",
     "所以你的游侠用的是什么流派？"),
    ("对方", "inbound", "22:10:09",
     "I'd like to run this dungeon with you. Do you have time?",
     "我想和你一起打这个副本，你有时间吗？"),
    ("我说", "outbound", "22:10:15",
     "我有时间，不过我得先换一下装备。",
     "Sure, give me a minute to swap my gear."),
]


def _fake_cfg() -> Config:
    c = Config()
    c.loopback_device = "扬声器 (USB Audio and HID) [Loopback]"
    c.playback_device = ""
    c.mt_engine = "bing"
    c.tts_engine = "edge"
    c.asr_threads = 4
    c.tts_voice_zh = "自动（按说话人性别挑选）"
    c.tts_voice_en = "自动（按说话人性别挑选）"
    return c


def _seed_live(win: MainWindow) -> None:
    win.live_src.setText("I'd like to run this dungeon with you. Do you have time?")
    win.live_tgt.setText("我想和你一起打这个副本，你有时间吗？")
    win._set_badge("on", "对方")
    win.meter.set_level(0.58, True)
    win.lvl_lbl.setText("58%")
    win.chip_asr.setText("识别 0.22s")
    win.chip_mt.setText("翻译 0.94s")
    win.chip_tts.setText("配音 1.31s")
    win.chip_e2e.setText("字幕 1.27s")
    win.chip_e2e.setProperty("hot", "true")
    win.chip_e2e.style().unpolish(win.chip_e2e)
    win.chip_e2e.style().polish(win.chip_e2e)
    win._set_stat("我想和你一起打这个副本，你有时间吗？")
    win.status_lbl.setText("运行中")
    win.dot.set_color("#3ddc97")
    win.btn_run.setText("停止同传")
    win.btn_run.setIcon(QIcon(str(STOP)))
    win.btn_run.setProperty("running", "true")
    win._repolish(win.btn_run)
    for tag, direction, ts, src, tgt in SAMPLE:
        card = HistoryCard(src, tgt, ts, direction)
        it = QListWidgetItem()
        it.setSizeHint(card.sizeHint())
        win.history.addItem(it)
        win.history.setItemWidget(it, card)
    win._sync_history()


def _load_fonts() -> None:
    """offscreen 平台不会自动加载系统字体，手动喂进去，否则中文全是方块。"""
    fdir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf",
                 "consola.ttf", "consolab.ttf"):
        p = fdir / name
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))


def _shot(widget, path: Path) -> None:
    widget.grab().save(str(path))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots_preview"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("LiveDub")
    _load_fonts()
    app.setFont(QFont("Microsoft YaHei UI", 9))

    win = MainWindow(_fake_cfg())
    win.resize(W, H)
    win.show()
    app.processEvents()

    # 空状态：没有历史记录时
    win._set_badge("off", "待机")
    win.live_src.setText("等待声音…")
    win.live_tgt.setText("")
    win.stat_lbl.setText("就绪")
    app.processEvents()
    _shot(win, out / "main_empty.png")

    _seed_live(win)
    app.processEvents()
    _shot(win, out / "main.png")

    win.chk_outbound.setChecked(True)
    win._update_vmic_hint()
    win._set_badge("on", "我说")
    app.processEvents()
    _shot(win, out / "main_outbound.png")
    win.chk_outbound.setChecked(False)

    # 最小窗口：验证窄窗口下卡片内容不被裁切
    win3 = MainWindow(_fake_cfg())
    win3.resize(*SMALL)
    win3.show()
    app.processEvents()
    _seed_live(win3)
    app.processEvents()
    _shot(win3, out / "main_min.png")
    for idx, name in ((0, "同传"), (1, "设置"), (2, "说明")):
        win3.tabs.setCurrentIndex(idx)
        app.processEvents()
        sa = win3.tabs.widget(idx).findChild(QScrollArea)
        mx = sa.verticalScrollBar().maximum() if sa else "n/a"
        print("scroll max", name, f"@{SMALL[0]}x{SMALL[1]} =", mx)
    win3.close()
    app.processEvents()

    # 目标分辨率：1366 宽（窗口 1334 可用宽）下不应出现滚动条
    win2 = MainWindow(_fake_cfg())
    win2.resize(1334, H)
    win2.show()
    app.processEvents()
    _seed_live(win2)
    app.processEvents()
    _shot(win2, out / "main_1366.png")
    for idx, name in ((0, "同传"), (1, "设置"), (2, "说明")):
        win2.tabs.setCurrentIndex(idx)
        app.processEvents()
        sa = win2.tabs.widget(idx).findChild(QScrollArea)
        print("scroll max", name, "@1334x749 =",
              sa.verticalScrollBar().maximum() if sa else "n/a")
    win2.close()
    app.processEvents()

    win.tabs.setCurrentIndex(1)
    app.processEvents()
    _shot(win, out / "settings.png")

    win.tabs.setCurrentIndex(2)
    app.processEvents()
    _shot(win, out / "about.png")

    ov = SubtitleOverlay(win.cfg)
    ov.set_final("Hello there, it is really nice to meet you.",
                 "你好，很高兴认识你。", "inbound", 60000)
    app.processEvents()
    ov.card.grab().save(str(out / "overlay.png"))
    ov.set_final("Sure, give me a minute to swap my gear.",
                 "我有时间，不过我得先换一下装备。", "outbound", 60000)
    app.processEvents()
    ov.card.grab().save(str(out / "overlay_outbound.png"))

    print("saved to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
