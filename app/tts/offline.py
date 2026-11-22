"""离线配音：piper.exe 常驻进程 + VITS/Piper 模型（纯 CPU，不联网）。

为什么用 piper.exe 而不是 sherpa-onnx 的 OfflineTts：
    sherpa-onnx >= 2.0 已废弃 `vits-data-dir`（espeak 音素词典），Piper 模型没法直接喂
    给它；而 piper.exe 自带 espeak-ng + onnxruntime，单进程常驻后每句只需
    推理时间（RTF ≈ 0.12，1.8 秒语音约 0.2 秒合成），完全离线。

模型目录（models/tts/）：
    zh-huayan/zh_CN-huayan-medium.onnx   中文女声
    en-lessac/en_US-lessac-medium.onnx   英文女声
    en-ryan/en_US-ryan-medium.onnx       英文男声

对外接口与 EdgeTTS 一致：synthesize(text, voice=..., pitch_hz=...) -> (float32 mono, sr)
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent

# 音色 id → (子目录, 模型文件名, 基础基频 Hz)
VOICES: dict[str, tuple[str, str, int]] = {
    "piper-zh-f": ("zh-huayan", "zh_CN-huayan-medium.onnx", 208),
    "piper-en-f": ("en-lessac", "en_US-lessac-medium.onnx", 190),
    "piper-en-m": ("en-ryan", "en_US-ryan-medium.onnx", 118),
}

# 常驻进程（进程退出时统一关掉）
_PROCS: dict[str, "PiperProc"] = {}
_PROCS_LOCK = threading.Lock()


def pick_local_voice(lang: str, gender: str) -> str:
    lang = (lang or "en").lower()
    if lang.startswith("zh"):
        return "piper-zh-f"
    return "piper-en-m" if (gender or "").startswith("m") else "piper-en-f"


def _rate_to_speed(rate: str | int | float) -> float:
    """'+20%' / '-10%' / 0 → 语速倍数。"""
    if isinstance(rate, (int, float)):
        return max(0.5, min(2.0, 1.0 + float(rate) / 100.0))
    s = str(rate or "").strip().rstrip("%")
    try:
        return max(0.5, min(2.0, 1.0 + float(s) / 100.0))
    except ValueError:
        return 1.0


def _wav_sr(model_path: Path) -> int:
    """从 .onnx.json 里读采样率（读不到就按 22050）。"""
    try:
        cfg = json.loads(Path(str(model_path) + ".json").read_text(encoding="utf-8"))
        return int(cfg["audio"]["sample_rate"])
    except Exception:
        return 22050


class PiperProc:
    """一个常驻的 piper.exe：写一行文本 → 从 stdout 读回原始 PCM。"""

    def __init__(self, exe: str, model: Path, sr: int, speed: float = 1.0):
        self.exe = exe
        self.model = Path(model)
        self.sr = int(sr)
        self.speed = float(speed)
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.proc: subprocess.Popen | None = None
        self._alive = True

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        args = [self.exe, "-m", str(self.model), "--output_raw", "-q",
                "--sentence_silence", "0.12"]
        if abs(self.speed - 1.0) > 0.01:
            # piper 的 length_scale 是「音素时长倍数」，语速越快越小
            args += ["--length_scale", f"{1.0 / self.speed:.3f}"]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0,
                                     creationflags=flags)
        threading.Thread(target=self._reader, name="piper-reader", daemon=True).start()
        with _PROCS_LOCK:
            _PROCS[str(self.model)] = self
        self._ready.set()

    def _reader(self) -> None:
        fd = self.proc.stdout.fileno() if self.proc and self.proc.stdout else -1
        while fd >= 0:
            try:
                chunk = os.read(fd, 16384)
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                self._buf.extend(chunk)
        self._alive = False

    @property
    def alive(self) -> bool:
        return self._alive and self.proc is not None and self.proc.poll() is None

    def close(self) -> None:
        self._alive = False
        try:
            if self.proc and self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            if self.proc:
                self.proc.terminate()
        except Exception:
            pass

    # ---------------- 合成 ----------------
    def speak(self, text: str, timeout: float = 20.0) -> np.ndarray:
        if not self.alive:
            self.close()
            self.start()
        with self._lock:
            self._buf.clear()
        self.proc.stdin.write((text.replace("\n", " ") + "\n").encode("utf-8", "ignore"))
        self.proc.stdin.flush()

        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.02)
            with self._lock:
                raw = bytes(self._buf)
            if len(raw) < 8000:          # 至少 0.18 秒才判断
                continue
            x = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16)
            tail = x[::-1]
            voiced = np.nonzero(np.abs(tail) > 250)[0]
            if voiced.size == 0:
                continue
            silence = int(voiced[0])     # 末尾连续静音样本数
            if silence / self.sr >= 0.09 and len(x) / self.sr >= 0.3:
                with self._lock:
                    self._buf.clear()
                body = x[: len(x) - silence] if silence < len(x) else x
                return body.astype(np.float32) / 32768.0 * 0.92
        return np.zeros(0, np.float32)


@atexit.register
def _shutdown() -> None:
    with _PROCS_LOCK:
        for p in list(_PROCS.values()):
            p.close()
        _PROCS.clear()


class PiperTTS:
    """离线配音（piper.exe 常驻）。"""

    name = "piper"

    def __init__(self, models_dir: Path | None = None, threads: int = 2, rate: str = "+0%",
                 exe: str | Path | None = None):
        self.dir = Path(models_dir or (ROOT / "models" / "tts"))
        self.threads = max(1, int(threads))
        self.rate = rate
        self.speed = _rate_to_speed(rate)
        cand = [Path(exe)] if exe else []
        cand += [ROOT / "tools" / "piper" / "piper" / "piper.exe",
                 ROOT / "tools" / "piper" / "piper.exe"]
        self.exe = next((str(c) for c in cand if c.exists()), "")
        self._procs: dict[str, PiperProc] = {}
        self._lock = threading.Lock()

    # ---------------- 可用性 ----------------
    def available(self) -> tuple[bool, str]:
        if not self.exe:
            return False, ("缺少 piper.exe（离线配音需要它）。"
                           "可运行 tools/download_offline_models.py 自动下载。")
        if not self.voices():
            return False, f"缺少离线音色模型：{self.dir}"
        return True, ""

    def _path(self, voice: str) -> Path:
        sub, fname, _ = VOICES[voice]
        return self.dir / sub / fname

    def voices(self) -> list[str]:
        return [v for v in VOICES if self._path(v).exists()]

    def voices_by_locale(self, lang: str) -> list[str]:
        lang = (lang or "").lower()
        if lang.startswith("zh"):
            return [v for v in self.voices() if v.startswith("piper-zh")]
        return [v for v in self.voices() if v.startswith("piper-en")]

    # ---------------- 进程 ----------------
    def _proc(self, voice: str) -> PiperProc:
        with self._lock:
            p = self._procs.get(voice)
            if p is not None and p.alive:
                return p
            path = self._path(voice)
            p = PiperProc(self.exe, path, _wav_sr(path), self.speed)
            p.start()
            self._procs[voice] = p
            return p

    def ensure(self, voice: str | None = None) -> None:
        for v in ([voice] if voice else self.voices()):
            try:
                self._proc(v)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            for p in self._procs.values():
                p.close()
            self._procs.clear()

    # ---------------- 合成 ----------------
    def synthesize(self, text: str, voice: str | None = None,
                   pitch_hz: int = 0) -> tuple[np.ndarray, int]:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, np.float32), 22050
        if voice not in VOICES or not self._path(voice).exists():
            lang = "zh" if str(voice or "").startswith("zh") else "en"
            voice = pick_local_voice(lang, "female")

        proc = self._proc(voice)
        pcm = proc.speak(text)
        sr = proc.sr
        if pcm.size and pitch_hz and sr > 0:
            from ..audio.pitch import shift_pitch, semitones_for
            base = VOICES[voice][2]
            st = semitones_for(base + int(pitch_hz), base)
            pcm = shift_pitch(pcm, sr, st)
        return pcm, sr
