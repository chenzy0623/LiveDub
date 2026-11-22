"""GUI 冒烟：启动真实管线 → 播放样例音频 → 检查历史/实时/指标 → 出图到 shots/live.png。

用法：
  python tools/gui_smoke.py            # 播放 models/sample_en.mp3
  python tools/gui_smoke.py --zh       # 播放中文样例（验证中→英方向）
"""
from __future__ import annotations

import sys
import time
import threading

sys.path.insert(0, ".")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import Config
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    cfg = Config.load()
    if "--zh" in sys.argv:
        cfg.source_lang, cfg.target_lang = "zh", "en"
    cfg.capture_source = "system"
    cfg.voice_enabled = True
    cfg.asr_partial = True
    win = MainWindow(cfg)
    win.resize(1020, 749)
    win.show()

    def play() -> None:
        from tools.run_cli import play_file
        from pathlib import Path
        name = "sample_zh.mp3" if "--zh" in sys.argv else "sample_en.mp3"
        play_file(Path("models") / name)
        print("play done", flush=True)

    def start() -> None:
        win._toggle_run()
        threading.Thread(target=play, daemon=True).start()

    def check() -> None:
        c = win.cfg
        print("cfg:", c.capture_source, "|", c.loopback_device, "|",
              c.mt_engine, c.tts_engine, flush=True)
        print("history items:", win.history.count(), flush=True)
        for i in range(win.history.count()):
            w = win.history.itemWidget(win.history.item(i))
            if w is None:
                continue
            from PySide6.QtWidgets import QLabel
            kids = w.findChildren(QLabel)
            print("  ", i, " | ".join(k.text()[:70] for k in kids), flush=True)
        print("live src:", (win.live_src.text() or "")[:60])
        print("live tgt:", (win.live_tgt.text() or "")[:60])
        print("badge:", win.status_lbl.text())
        print("chips:", [c.text() for c in (win.chip_asr, win.chip_mt, win.chip_tts, win.chip_e2e)])
        win.grab().save("shots/live.png")
        win._toggle_run()
        QTimer.singleShot(2500, finish)

    def finish() -> None:
        win.close()
        app.quit()

    QTimer.singleShot(1200, start)
    QTimer.singleShot(26000, check)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
