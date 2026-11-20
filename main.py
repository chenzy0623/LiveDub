"""LiveDub 入口。

    python main.py

首次启动会自动检查模型；缺少时给出提示。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 中国大陆镜像（模型下载 / HuggingFace）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.config import Config, MODELS_DIR
    from app.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("LiveDub")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    cfg = Config.load()

    missing = []
    if not (MODELS_DIR / "sensevoice" / "model.int8.onnx").exists():
        missing.append("语音识别模型 models/sensevoice/model.int8.onnx")
    if not (MODELS_DIR / "silero_vad.onnx").exists():
        missing.append("语音活动检测模型 models/silero_vad.onnx")
    if missing:
        QMessageBox.critical(
            None, "缺少模型",
            "以下文件不存在：\n\n" + "\n".join(missing) +
            "\n\n请运行 tools/download_models.py 自动下载（国内走 hf-mirror 镜像）。")
        return 2

    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
