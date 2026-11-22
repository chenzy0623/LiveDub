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

# ---------------------------------------------------------------------------
# 变调（离线配音用）：保持时长不变，只改音高
# ---------------------------------------------------------------------------
def semitones_for(src_hz: float, base_hz: float, limit: float = 6.0) -> float:
    """两个基频相差多少个半音（夹在 ±limit 内，避免过度失真）。"""
    if src_hz <= 0 or base_hz <= 0:
        return 0.0
    st = 12.0 * float(np.log2(src_hz / base_hz))
    return float(max(-limit, min(limit, st)))


def _resample_lin(x: np.ndarray, n_out: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if n_out <= 1 or x.size <= 1:
        return x.copy()
    idx = np.linspace(0.0, x.size - 1.0, n_out, dtype=np.float64)
    return np.interp(idx, np.arange(x.size, dtype=np.float64), x).astype(np.float32)


def wsola_stretch(x: np.ndarray, factor: float, sr: int) -> np.ndarray:
    """WSOLA 时间伸缩：factor > 1 变长，< 1 变短，音高不变。"""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < 256 or abs(factor - 1.0) < 1e-3:
        return x
    n = max(256, int(0.040 * sr) // 2 * 2)      # 40ms 帧
    hop = n // 2
    win = np.hanning(n).astype(np.float32)
    tol = max(1, int(0.008 * sr))               # ±8ms 搜索，找最相似的接缝
    out_len = int(round(x.size * factor))
    y = np.zeros(out_len + n, dtype=np.float32)
    acc = np.zeros(out_len + n, dtype=np.float32)
    in_pos = 0.0
    out_pos = 0
    prev: np.ndarray | None = None
    while out_pos + n <= y.size:
        ip = int(round(in_pos))
        if ip + n >= x.size:
            break
        if prev is not None:
            lo, hi = max(0, ip - tol), min(x.size - n - 1, ip + tol)
            best_pos, best_c = ip, -1e30
            seg_ref = prev
            for cand in range(lo, hi + 1, 4):
                c = float(np.dot(seg_ref, x[cand:cand + n]))
                if c > best_c:
                    best_c, best_pos = c, cand
            ip = best_pos
        seg = x[ip:ip + n]
        y[out_pos:out_pos + n] += seg * win
        acc[out_pos:out_pos + n] += win
        prev = seg
        in_pos += hop / factor
        out_pos += hop
    nz = acc > 1e-6
    y[nz] /= acc[nz]
    return y[:out_len]


def shift_pitch(x: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """变调不变速：先重采样改音高（时长跟着变），再用 WSOLA 拉回原时长。"""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < 256 or abs(semitones) < 0.15:
        return x
    r = 2.0 ** (float(semitones) / 12.0)
    res = _resample_lin(x, max(2, int(round(x.size / r))))
    return wsola_stretch(res, r, sr)
