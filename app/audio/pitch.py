"""音高（F0）估计：用于判断说话人性别、以及让译文音色贴近原声。"""
from __future__ import annotations

import numpy as np


def estimate_f0(x: np.ndarray, sr: int = 16000,
                fmin: float = 70.0, fmax: float = 400.0) -> float:
    """自相关法估计基频中位数（Hz）。无声/噪声返回 0。"""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < int(0.05 * sr):
        return 0.0
    # 简单去直流 + 归一化
    x = x - x.mean()
    m = np.abs(x).max()
    if m < 1e-4:
        return 0.0
    x = x / m
    frame = int(0.04 * sr)          # 40ms 窗
    hop = int(0.02 * sr)            # 20ms
    lo = int(sr / fmax)
    hi = min(int(sr / fmin), frame - 1)
    if hi <= lo:
        return 0.0
    f0s: list[float] = []
    for i in range(0, len(x) - frame, hop):
        seg = x[i:i + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.01:
            continue
        ac = np.correlate(seg, seg, mode="full")[frame - 1:]
        ac = ac / (ac[0] + 1e-9)
        window = ac[lo:hi]
        if window.size == 0:
            continue
        k = int(np.argmax(window))
        if window[k] < 0.3:
            continue
        f0 = sr / (lo + k)
        f0s.append(f0)
    if not f0s:
        return 0.0
    return float(np.median(f0s))


def gender_of(f0: float) -> str:
    """粗略性别判断：成人男声约 85-180Hz，女声约 165-255Hz。"""
    if f0 <= 0:
        return "unknown"
    if f0 < 155:
        return "male"
    if f0 > 175:
        return "female"
    return "unknown"


def pitch_offset_for_target(src_f0: float, voice_base_f0: float) -> int:
    """计算 edge-tts 需要的 pitch 偏移（Hz）。"""
    if src_f0 <= 0 or voice_base_f0 <= 0:
        return 0
    off = int(round(src_f0 - voice_base_f0))
    return max(-60, min(60, off))
