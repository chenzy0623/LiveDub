"""轻量 DSP：降混、重采样、音量。全部用 numpy 实现，避免额外依赖。"""
from __future__ import annotations

import numpy as np


def to_mono(frames: np.ndarray, channels: int) -> np.ndarray:
    if channels <= 1:
        return frames.reshape(-1).astype(np.float32, copy=False)
    return frames.reshape(-1, channels).mean(axis=1).astype(np.float32, copy=False)


def rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def db(x: np.ndarray) -> float:
    r = rms(x)
    return 20.0 * np.log10(max(r, 1e-9))


def _lowpass_taps(cutoff: float, taps: int = 63) -> np.ndarray:
    """窗函数法低通 FIR，cutoff 为归一化频率（0~0.5）。"""
    n = np.arange(taps) - (taps - 1) / 2.0
    h = 2.0 * cutoff * np.sinc(2.0 * cutoff * n)
    h *= np.hamming(taps)
    h /= np.sum(h)
    return h.astype(np.float32)


class Resampler:
    """有状态的任意比率重采样（FIR 抗混叠 + 线性插值）。"""

    def __init__(self, sr_in: int, sr_out: int):
        self.sr_in = int(sr_in)
        self.sr_out = int(sr_out)
        self.ratio = self.sr_out / self.sr_in
        self._identity = self.sr_in == self.sr_out
        self._fir_state = np.zeros(64, dtype=np.float32)
        self._taps: np.ndarray | None = None
        if not self._identity:
            if sr_in > sr_out:
                self._taps = _lowpass_taps(0.45 * sr_out / sr_in, 63)
            self._buf = np.zeros(0, dtype=np.float32)
            self._pos = 0.0

    def _filter(self, x: np.ndarray) -> np.ndarray:
        if self._taps is None:
            return x
        n = len(self._taps)
        padded = np.concatenate([self._fir_state[: n - 1], x])
        y = np.convolve(padded, self._taps, mode="valid")
        self._fir_state = np.concatenate([self._fir_state[: n - 1], x])[-(n - 1):]
        return y.astype(np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return x
        if self._identity:
            return x
        x = self._filter(x)
        data = np.concatenate([self._buf, x])
        # 需要多一个样本做插值
        n_out = int((len(data) - 1 - self._pos) * self.ratio) + 1
        if n_out <= 0:
            self._buf = data
            return np.zeros(0, dtype=np.float32)
        idx = self._pos + np.arange(n_out) / self.ratio
        idx = idx[idx <= len(data) - 1.001]
        if idx.size == 0:
            self._buf = data
            return np.zeros(0, dtype=np.float32)
        i0 = idx.astype(np.int64)
        frac = (idx - i0).astype(np.float32)
        y = data[i0] * (1.0 - frac) + data[i0 + 1] * frac
        consumed = int(np.floor(idx[-1])) + 1
        self._pos = idx[-1] + 1.0 / self.ratio - consumed
        self._buf = data[consumed:]
        return y.astype(np.float32)


def float_to_int16(x: np.ndarray, gain: float = 1.0) -> np.ndarray:
    x = np.clip(x * gain, -1.0, 1.0)
    return (x * 32767.0).astype(np.int16)


def int16_to_float(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float32) / 32768.0
