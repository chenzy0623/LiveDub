"""VAD 驱动的分段器：把连续音频切成一句话一句话。

产出两种事件：
  on_partial(audio, t_start)  —— 说话过程中的实时片段（用于实时字幕）
  on_segment(audio, t_start, t_end) —— 一句话结束（用于翻译 + 配音）
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import numpy as np

from .vad import FRAME, SAMPLE_RATE


class Segmenter:
    def __init__(self, vad,
                 on_segment: Callable[[np.ndarray, float, float], None],
                 on_partial: Optional[Callable[[np.ndarray, float], None]] = None,
                 vad_threshold: float = 0.5,
                 min_silence_ms: int = 340,
                 min_speech_ms: int = 260,
                 max_segment_s: float = 12.0,
                 partial_interval_s: float = 1.1,
                 preroll_ms: int = 260,
                 on_level: Optional[Callable[[float, bool], None]] = None):
        self.vad = vad
        self.on_segment = on_segment
        self.on_partial = on_partial
        self.on_level = on_level
        self.threshold = vad_threshold
        self.min_silence_frames = max(1, int(min_silence_ms / 1000 * SAMPLE_RATE / FRAME))
        self.min_speech_frames = int(min_speech_ms / 1000 * SAMPLE_RATE / FRAME)
        self.max_frames = int(max_segment_s * SAMPLE_RATE / FRAME)
        self.partial_frames = max(4, int(partial_interval_s * SAMPLE_RATE / FRAME))
        self.preroll_frames = max(1, int(preroll_ms / 1000 * SAMPLE_RATE / FRAME))

        self._leftover = np.zeros(0, dtype=np.float32)
        self._preroll: list[np.ndarray] = []
        self._buf: list[np.ndarray] = []
        self._frames_in_buf = 0
        self._silence = 0
        self._in_speech = False
        self._t0 = 0.0            # 当前句起始时间（秒，墙钟）
        self._last_partial_frame = 0
        self._last_speech_idx = 0  # 最近一次判定为语音的帧序号
        self._sample_clock = 0    # 已处理样本数
        self._lock_ts = 0.0

    # ---------------- 对外 ----------------
    def feed(self, audio: np.ndarray) -> None:
        if audio.size == 0:
            return
        data = np.concatenate([self._leftover, np.asarray(audio, dtype=np.float32).reshape(-1)])
        n = len(data) // FRAME
        if n == 0:
            self._leftover = data
            return
        frames = data[: n * FRAME].reshape(n, FRAME)
        self._leftover = data[n * FRAME:]
        for fr in frames:
            self._step(fr)

    def flush(self) -> None:
        if self._in_speech and self._frames_in_buf >= self.min_speech_frames:
            self._emit()

    def reset(self) -> None:
        self._leftover = np.zeros(0, dtype=np.float32)
        self._preroll.clear()
        self._buf.clear()
        self._frames_in_buf = 0
        self._silence = 0
        self._in_speech = False
        self._last_partial_frame = 0
        self._last_speech_idx = 0
        try:
            self.vad.reset()
        except Exception:
            pass

    # ---------------- 内部 ----------------
    def _now(self) -> float:
        return time.monotonic()

    def _step(self, frame: np.ndarray) -> None:
        p = self.vad.prob(frame)
        self._sample_clock += FRAME
        speech = p >= self.threshold
        if self.on_level is not None:
            try:
                self.on_level(p, speech)
            except Exception:
                pass

        if not self._in_speech:
            self._preroll.append(frame)
            if len(self._preroll) > self.preroll_frames:
                self._preroll.pop(0)
            if speech:
                # 进入语音：带上预卷
                self._in_speech = True
                self._buf = list(self._preroll)
                self._frames_in_buf = len(self._buf)
                self._silence = 0
                self._last_partial_frame = self._frames_in_buf
                self._last_speech_idx = self._frames_in_buf
                self._t0 = self._now() - len(self._buf) * FRAME / SAMPLE_RATE
                self._preroll.clear()
            return

        self._buf.append(frame)
        self._frames_in_buf += 1
        if speech:
            self._silence = 0
            self._last_speech_idx = self._frames_in_buf
        else:
            self._silence += 1

        # 实时字幕：周期性吐出当前缓存
        if (self.on_partial is not None
                and self._frames_in_buf - self._last_partial_frame >= self.partial_frames
                and self._frames_in_buf >= self.min_speech_frames):
            self._last_partial_frame = self._frames_in_buf
            try:
                self.on_partial(np.concatenate(self._buf), self._t0)
            except Exception as e:
                print("[Segmenter] partial 回调异常:", e)

        # 句末
        if self._silence >= self.min_silence_frames:
            if self._frames_in_buf >= self.min_speech_frames:
                self._emit()
            else:
                self._buf.clear()
                self._frames_in_buf = 0
                self._in_speech = False
                self._silence = 0
            return

        # 超长句强制切分
        if self._frames_in_buf >= self.max_frames:
            self._emit(keep_tail=True)

    def _emit(self, keep_tail: bool = False) -> None:
        # 只保留到最后一个语音帧（+64ms 余量），避免尾部静音让 ASR 胡编
        cut = min(self._frames_in_buf, self._last_speech_idx + 5)
        buf = self._buf[:cut] if cut > 0 else self._buf
        audio = np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)
        t_end = self._t0 + len(audio) / SAMPLE_RATE
        speech_frames = self._frames_in_buf - self._silence
        if speech_frames >= self.min_speech_frames and audio.size > SAMPLE_RATE * 0.2:
            try:
                self.on_segment(audio, self._t0, t_end)
            except Exception as e:
                print("[Segmenter] segment 回调异常:", e)
        if keep_tail:
            tail = max(1, int(0.3 * SAMPLE_RATE / FRAME))
            self._buf = self._buf[-tail:]
            self._frames_in_buf = len(self._buf)
            self._t0 = t_end - len(self._buf) * FRAME / SAMPLE_RATE
            self._silence = 0
            self._last_partial_frame = self._frames_in_buf
            self._last_speech_idx = self._frames_in_buf
        else:
            self._buf.clear()
            self._frames_in_buf = 0
            self._in_speech = False
            self._silence = 0
            self._last_partial_frame = 0
            self._last_speech_idx = 0
