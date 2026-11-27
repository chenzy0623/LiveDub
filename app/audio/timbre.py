"""离线「音色还原」：把译文配音的嗓音往原说话人靠。

纯 numpy 信号处理，不需要额外模型、不需要联网，CPU 开销约 1% 实时。

做两件事：
1. **音高 / 声道长度**：按原说话人的 F0 均值做变调。变调走「重采样 + WSOLA
   拉回时长」的路子，音高和共振峰一起按比例变化，等价于换成一个「声道更长 /
   更短」的人说话 —— 男声配女声的配音用它能明显压下来，接近原声的厚度。
2. **频谱包络（音色亮度 / 共鸣）**：用长时平均谱（LTAS）对比译文与参考语音，
   在 40 个对数频带上算出一条增益曲线，平滑、限幅后叠加到译文上，让共鸣位置
   更接近原说话人。

局限（诚实说明）：这是**信号层面的音色近似**，不是神经网络语音转换。
真正的 1:1 音色克隆（RVC / OpenVoice / GPT-SoVITS 一类）在本机这种没有
NVIDIA 显卡的 CPU 上跑不到实时（RTF 普遍 1~5），所以离线模式用这个方案兜底；
想要 1:1 克隆仍然建议接在线克隆服务。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pitch import estimate_f0, semitones_for, shift_pitch

# 对数频带数（频谱包络的分辨率）
N_BANDS = 40
F_LO = 70.0
F_HI = 7600.0


def _band_edges(sr: int) -> np.ndarray:
    hi = min(F_HI, sr / 2.0 * 0.95)
    return np.geomspace(F_LO, hi, N_BANDS + 1)


def _frames(x: np.ndarray, sr: int, win_s: float = 0.032,
            hop_s: float = 0.016):
    n = max(256, int(win_s * sr))
    hop = max(64, int(hop_s * sr))
    if x.size < n:
        return np.zeros((0, n), np.float32)
    count = 1 + (x.size - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(count)[:, None]
    return x[idx]


def _ltas_db(x: np.ndarray, sr: int) -> np.ndarray:
    """长时平均谱 → 每频带 dB（已按总能量归一化，只留「形状」）。"""
    fr = _frames(x, sr)
    if fr.size == 0:
        return np.zeros(N_BANDS, np.float32)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    fr = fr[rms > max(1e-4, float(rms.mean()) * 0.12)]      # 丢掉静音帧
    if fr.size == 0:
        return np.zeros(N_BANDS, np.float32)
    win = np.hanning(fr.shape[1]).astype(np.float32)
    spec = np.abs(np.fft.rfft(fr * win, axis=1)) ** 2
    freqs = np.fft.rfftfreq(fr.shape[1], 1.0 / sr)
    edges = _band_edges(sr)
    out = np.zeros(N_BANDS, np.float32)
    for i in range(N_BANDS):
        m = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if m.any():
            out[i] = float(spec[:, m].mean())
    out = 10.0 * np.log10(out + 1e-12)
    out -= out.mean()                                        # 只保留形状
    return out.astype(np.float32)


def _smooth(v: np.ndarray, k: int = 3) -> np.ndarray:
    if v.size < k:
        return v
    ker = np.ones(k, np.float32) / k
    pad = k // 2
    return np.convolve(np.pad(v, pad, mode="edge"), ker, mode="valid").astype(np.float32)


@dataclass
class TimbreProfile:
    f0: float = 0.0
    ltas: np.ndarray = None            # type: ignore[assignment]

    def ok(self) -> bool:
        return self.ltas is not None and self.ltas.size == N_BANDS


def analyze(x: np.ndarray, sr: int = 16000) -> TimbreProfile | None:
    """从原说话人这段语音里提取音色参考（F0 + 频谱包络）。"""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < int(0.25 * sr):
        return None
    f0 = estimate_f0(x, sr)
    if f0 <= 0:
        return None
    m = float(np.abs(x).max())
    if m < 1e-4:
        return None
    return TimbreProfile(f0=f0, ltas=_smooth(_ltas_db(x / m, sr)))


class TimbreTracker:
    """跨句子平滑的音色参考，避免每句话音色跳来跳去。"""

    def __init__(self, alpha: float = 0.45):
        self.alpha = float(alpha)
        self.profile: TimbreProfile | None = None

    def update(self, x: np.ndarray, sr: int = 16000) -> TimbreProfile | None:
        p = analyze(x, sr)
        if p is None:
            return self.profile
        if self.profile is None or not self.profile.ok():
            self.profile = p
            return p
        a = self.alpha
        self.profile.f0 = (1 - a) * self.profile.f0 + a * p.f0
        self.profile.ltas = ((1 - a) * self.profile.ltas + a * p.ltas).astype(np.float32)
        return self.profile


def _apply_band_gain(x: np.ndarray, sr: int, gain_db: np.ndarray) -> np.ndarray:
    """按频带增益曲线做帧级 EQ（Hann 窗 + 重叠相加）。"""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    n = max(256, int(0.032 * sr))
    hop = n // 4
    win = np.hanning(n).astype(np.float32)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    centers = (np.asarray(_band_edges(sr))[:-1] + np.asarray(_band_edges(sr))[1:]) / 2.0
    curve = np.interp(freqs, centers, gain_db, left=gain_db[0], right=gain_db[-1])
    g = (10.0 ** (curve / 20.0)).astype(np.float32)

    pad = n
    y = np.zeros(x.size + 2 * pad, np.float32)
    acc = np.zeros_like(y)
    xp = np.pad(x, (pad, pad))
    for start in range(0, xp.size - n, hop):
        seg = xp[start:start + n]
        if not seg.any():
            continue
        spec = np.fft.rfft(seg * win)
        seg2 = np.fft.irfft(spec * g, n).astype(np.float32) * win
        y[start:start + n] += seg2
        acc[start:start + n] += win ** 2
    nz = acc > 1e-6
    y[nz] /= acc[nz]
    return y[pad:pad + x.size]


def match(pcm: np.ndarray, sr: int, ref: TimbreProfile | None,
          strength: float = 0.8, max_semitone: float = 7.0,
          max_gain_db: float = 9.0) -> np.ndarray:
    """把译文配音往参考音色靠：变调（含共振峰）+ 频谱包络匹配。

    strength: 0 = 不变（原样返回），1 = 完全按参考来（可能过头）。
    """
    pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
    s = float(max(0.0, min(1.0, strength)))
    if pcm.size < 256 or s <= 0.0 or ref is None or not ref.ok() or sr <= 0:
        return pcm

    y = pcm
    # 1) 音高 / 声道长度
    cur = estimate_f0(y, sr)
    if cur > 0 and ref.f0 > 0:
        st = semitones_for(ref.f0, cur, max_semitone) * s
        if abs(st) >= 0.15:
            y = shift_pitch(y, sr, st)

    # 2) 频谱包络
    cur_ltas = _smooth(_ltas_db(y, sr))
    gain = np.clip(ref.ltas - cur_ltas, -max_gain_db, max_gain_db) * s
    if float(np.abs(gain).max()) >= 0.5:
        y = _apply_band_gain(y, sr, _smooth(gain, 5))

    peak = float(np.abs(y).max())
    if peak > 0.98:
        y = y * (0.98 / peak)
    return y.astype(np.float32)


def ltas_distance(a: np.ndarray, b: np.ndarray) -> float:
    """两条频谱包络的平均绝对差（dB），用来量化「贴近了多少」。"""
    if a is None or b is None or a.size != b.size:
        return float("nan")
    return float(np.mean(np.abs(a - b)))
