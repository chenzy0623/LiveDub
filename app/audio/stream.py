"""采集 / 播放音频流（WASAPI loopback + 普通输入 + 输出）。"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np
import pyaudiowpatch as pyaudio

from . import dsp
from .devices import Device, get_pa

TARGET_SR = 16000          # 交给 VAD / ASR 的采样率
FRAME_MS = 32              # 每次回调的块长（毫秒）


class CaptureStream:
    """从 loopback / 麦克风采集，降混为单声道 16k float32 并回调。

    回调在采集线程内执行，必须非常快（只做入队）。
    """

    def __init__(self, device: Device, on_audio: Callable[[np.ndarray], None],
                 target_sr: int = TARGET_SR):
        self.device = device
        self.on_audio = on_audio
        self.target_sr = target_sr
        self._pa = get_pa()
        self._stream: Optional[pyaudio.Stream] = None
        self._resampler: Optional[dsp.Resampler] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[str] = None

    @property
    def error(self) -> Optional[str]:
        return self._error

    def start(self) -> None:
        if self._running:
            return
        ch = max(1, self.device.channels)
        self._rate = int(self.device.rate) or 48000
        self._resampler = dsp.Resampler(self._rate, self.target_sr)
        frames = max(256, int(self._rate * FRAME_MS / 1000))
        try:
            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=ch,
                rate=self._rate,
                frames_per_buffer=frames,
                input=True,
                input_device_index=self.device.index,
            )
        except Exception as e:  # 尝试 int16 或单声道退路
            self._stream = None
            for fmt, c in ((pyaudio.paInt16, ch), (pyaudio.paFloat32, 1), (pyaudio.paInt16, 1)):
                try:
                    self._stream = self._pa.open(
                        format=fmt, channels=c, rate=self._rate,
                        frames_per_buffer=frames, input=True,
                        input_device_index=self.device.index)
                    self._fmt16 = fmt == pyaudio.paInt16
                    ch = c
                    break
                except Exception:
                    continue
            if self._stream is None:
                self._error = f"打开采集设备失败：{e}"
                raise RuntimeError(self._error)
        self._ch = ch
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="capture", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        assert self._stream is not None
        while self._running:
            try:
                data = self._stream.read(int(self._stream.get_read_available() or 1),
                                         exception_on_overflow=False)
            except Exception as e:
                self._error = f"读取音频失败：{e}"
                break
            if not data:
                continue
            fmt16 = getattr(self, "_fmt16", False)
            if fmt16:
                x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            else:
                x = np.frombuffer(data, dtype=np.float32)
            mono = dsp.to_mono(x, self._ch)
            y = self._resampler.process(mono) if self._resampler else mono
            if y.size:
                try:
                    self.on_audio(y)
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


class PlaybackStream:
    """播放 TTS 音频（任意采样率 float32 → 设备原生采样率）。"""

    def __init__(self, device: Device, volume: float = 1.0):
        self.device = device
        self.volume = volume
        self._pa = get_pa()
        self._stream: Optional[pyaudio.Stream] = None
        self._rate = int(device.rate) or 48000
        self._ch = 2 if device.channels >= 2 else 1
        self._lock = threading.Lock()
        self._resampler: Optional[dsp.Resampler] = None
        self._src_sr = 0

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = self._pa.open(
            format=pyaudio.paFloat32, channels=self._ch, rate=self._rate,
            frames_per_buffer=1024, output=True,
            output_device_index=self.device.index)

    def write(self, samples: np.ndarray, sr: int) -> None:
        if samples.size == 0:
            return
        with self._lock:
            self.open()
            if sr != self._src_sr:
                self._resampler = dsp.Resampler(sr, self._rate)
                self._src_sr = sr
            y = self._resampler.process(samples) if self._resampler else samples
            if y.size == 0:
                return
            y = np.clip(y * self.volume, -1.0, 1.0).astype(np.float32)
            if self._ch == 2:
                y = np.column_stack([y, y]).reshape(-1)
            self._stream.write(y.tobytes(), exception_on_underflow=False)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None


class FilePlayer:
    """把音频块写入 WAV 文件（测试/录制用）。"""

    def __init__(self, path: str, sr: int = 24000):
        import wave
        self.wf = wave.open(path, "wb")
        self.wf.setnchannels(1)
        self.wf.setsampwidth(2)
        self.wf.setframerate(sr)

    def write(self, samples: np.ndarray, sr: int = 24000) -> None:
        self.wf.writeframes(dsp.float_to_int16(samples).tobytes())

    def close(self) -> None:
        self.wf.close()
