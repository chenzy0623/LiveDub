"""下载 LiveDub 需要的模型（国内自动走 hf-mirror 镜像）。

用法：

    python tools/download_models.py          # 缺什么下什么
    python tools/download_models.py --force  # 全部重下

下载内容：
    models/silero_vad.onnx                   2 MB   语音活动检测（VAD）
    models/sensevoice/model.int8.onnx      229 MB   语音识别 SenseVoiceSmall int8
    models/sensevoice/tokens.txt           200 KB   词表
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

# 优先 hf-mirror.com（国内可直连），失败再试 huggingface.co
MIRRORS = [
    "https://hf-mirror.com",
    "https://huggingface.co",
]

FILES = [
    # (远端相对路径, 本地相对路径, 说明)
    ("onnx-community/silero-vad/resolve/main/onnx/model.onnx",
     "silero_vad.onnx", "语音活动检测 VAD"),
    ("csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx",
     "sensevoice/model.int8.onnx", "语音识别 SenseVoiceSmall int8"),
    ("csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt",
     "sensevoice/tokens.txt", "SenseVoice 词表"),
]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "LiveDub/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last = -1
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = int(done * 100 / total)
                if pct != last and pct % 5 == 0:
                    last = pct
                    sys.stdout.write(
                        f"\r    {human(done)} / {human(total)}  {pct:3d}%")
                    sys.stdout.flush()
    if total:
        sys.stdout.write("\r    " + " " * 40 + "\r")
    tmp.replace(dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()

    os.environ.setdefault("HF_ENDPOINT", MIRRORS[0])

    print(f"模型目录：{MODELS}\n")
    failed = []
    for rel, local, desc in FILES:
        dst = MODELS / local
        if dst.exists() and not args.force:
            print(f"[跳过] {desc}  已存在 ({human(dst.stat().st_size)})")
            continue
        ok = False
        for host in MIRRORS:
            url = f"{host}/{rel}"
            print(f"[下载] {desc}\n    {url}")
            try:
                download(url, dst)
                print(f"    完成 → {dst}  ({human(dst.stat().st_size)})")
                ok = True
                break
            except Exception as e:
                print(f"    失败：{type(e).__name__}: {e}")
                part = dst.with_suffix(dst.suffix + ".part")
                if part.exists():
                    part.unlink(missing_ok=True)
        if not ok:
            failed.append(desc)

    print()
    if failed:
        print("以下模型下载失败：\n  · " + "\n  · ".join(failed))
        print("\n可手动下载后放到对应路径，或换网络重试。")
        return 1
    print("全部就绪，可以运行：python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
