"""下载 LiveDub 的离线模型（国内走 hf-mirror，piper 走 GitHub Release）。

用法：
    python tools/download_offline_models.py              # 翻译 + 配音全部
    python tools/download_offline_models.py --mt         # 只下离线翻译（约 160 MB）
    python tools/download_offline_models.py --tts        # 只下离线配音（约 210 MB）
    python tools/download_offline_models.py --force      # 已存在也重下

下载内容：
    models/mt/opus-en-zh/   opus-mt 英→中 int8（CTranslate2，约 80 MB）
    models/mt/opus-zh-en/   opus-mt 中→英 int8（约 80 MB）
    tools/piper/piper/piper.exe + espeak-ng        （官方 Windows 版，22 MB）
    models/tts/zh-huayan/   中文女声 VITS（63 MB）
    models/tts/en-lessac/   英文女声（63 MB）
    models/tts/en-ryan/     英文男声（63 MB）
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

HF = "https://hf-mirror.com"

OPUS_EN_ZH = "Zoowr/opus-mt-en-zh-ct2-int8"
OPUS_ZH_EN = "jiangzhuo9357/opus-mt-zh-en-ct2"
PIPER_ZIP = ("https://github.com/rhasspy/piper/releases/download/"
             "2023.11.14-2/piper_windows_amd64.zip")
PIPER_DIR = ROOT / "tools" / "piper"

# (repo, 远端路径, 本地相对路径)
MT_FILES = [
    (OPUS_EN_ZH, "model.bin", "models/mt/opus-en-zh/model.bin"),
    (OPUS_EN_ZH, "source.spm", "models/mt/opus-en-zh/source.spm"),
    (OPUS_EN_ZH, "target.spm", "models/mt/opus-en-zh/target.spm"),
    (OPUS_EN_ZH, "shared_vocabulary.json", "models/mt/opus-en-zh/shared_vocabulary.json"),
    (OPUS_EN_ZH, "config.json", "models/mt/opus-en-zh/config.json"),
    (OPUS_ZH_EN, "model.bin", "models/mt/opus-zh-en/model.bin"),
    (OPUS_ZH_EN, "source.spm", "models/mt/opus-zh-en/source.spm"),
    (OPUS_ZH_EN, "target.spm", "models/mt/opus-zh-en/target.spm"),
    (OPUS_ZH_EN, "shared_vocabulary.json", "models/mt/opus-zh-en/shared_vocabulary.json"),
    (OPUS_ZH_EN, "config.json", "models/mt/opus-zh-en/config.json"),
]

TTS_VOICES = [
    ("csukuangfj/vits-piper-zh_CN-huayan-medium", "zh_CN-huayan-medium.onnx",
     "models/tts/zh-huayan/zh_CN-huayan-medium.onnx"),
    ("csukuangfj/vits-piper-zh_CN-huayan-medium", "zh_CN-huayan-medium.onnx.json",
     "models/tts/zh-huayan/zh_CN-huayan-medium.onnx.json"),
    ("csukuangfj/vits-piper-zh_CN-huayan-medium", "tokens.txt",
     "models/tts/zh-huayan/tokens.txt"),
    ("csukuangfj/vits-piper-en_US-lessac-medium", "en_US-lessac-medium.onnx",
     "models/tts/en-lessac/en_US-lessac-medium.onnx"),
    ("csukuangfj/vits-piper-en_US-lessac-medium", "en_US-lessac-medium.onnx.json",
     "models/tts/en-lessac/en_US-lessac-medium.onnx.json"),
    ("csukuangfj/vits-piper-en_US-lessac-medium", "tokens.txt",
     "models/tts/en-lessac/tokens.txt"),
    ("csukuangfj/vits-piper-en_US-ryan-medium", "en_US-ryan-medium.onnx",
     "models/tts/en-ryan/en_US-ryan-medium.onnx"),
    ("csukuangfj/vits-piper-en_US-ryan-medium", "en_US-ryan-medium.onnx.json",
     "models/tts/en-ryan/en_US-ryan-medium.onnx.json"),
    ("csukuangfj/vits-piper-en_US-ryan-medium", "tokens.txt",
     "models/tts/en-ryan/tokens.txt"),
]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return "?"


def download(url: str, dest: Path, force: bool = False) -> bool:
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  ✓ 已存在 {dest.relative_to(ROOT)} ({human(dest.stat().st_size)})")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                t0 = time.time()
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 // total
                        if pct % 10 == 0:
                            sys.stdout.write(
                                f"\r    {dest.name} {pct:3d}%  "
                                f"{human(got)}/{human(total)}  "
                                f"{got / max(0.01, time.time() - t0) / 1e6:.1f} MB/s")
                            sys.stdout.flush()
            if total and tmp.stat().st_size != total:
                raise IOError(f"大小不符 {tmp.stat().st_size} != {total}")
            tmp.replace(dest)
            sys.stdout.write("\r" + " " * 78 + "\r")
            print(f"  ✓ {dest.relative_to(ROOT)} ({human(dest.stat().st_size)})")
            return True
        except Exception as e:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            print(f"  重试 {attempt}/5: {e}")
            time.sleep(2 * attempt)
    print(f"  ✗ 失败 {url}")
    return False


def get_piper(force: bool = False) -> bool:
    exe = PIPER_DIR / "piper" / "piper.exe"
    if exe.exists() and not force:
        print(f"  ✓ 已存在 {exe.relative_to(ROOT)}")
        return True
    zip_path = PIPER_DIR / "piper_windows_amd64.zip"
    if not download(PIPER_ZIP, zip_path, force=True):
        return False
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(PIPER_DIR)
    zip_path.unlink(missing_ok=True)
    print(f"  ✓ 已解压到 {PIPER_DIR.relative_to(ROOT)}")
    return exe.exists()


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 LiveDub 离线模型")
    ap.add_argument("--mt", action="store_true", help="只下离线翻译")
    ap.add_argument("--tts", action="store_true", help="只下离线配音")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()
    both = not (args.mt or args.tts)

    ok = True
    if both or args.mt:
        print("== 离线翻译（opus-mt 中英双向，CTranslate2 int8）")
        for repo, remote, local in MT_FILES:
            ok &= download(f"{HF}/{repo}/resolve/main/{remote}", ROOT / local, args.force)
    if both or args.tts:
        print("== 离线配音（Piper）")
        ok &= get_piper()
        for repo, remote, local in TTS_VOICES:
            ok &= download(f"{HF}/{repo}/resolve/main/{remote}", ROOT / local, args.force)

    print()
    exe = shutil.which("piper") or (PIPER_DIR / "piper" / "piper.exe")
    print(f"piper: {exe}")
    print("完成。" if ok else "部分文件下载失败，可重试。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
