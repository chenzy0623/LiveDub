"""语音识别（faster-whisper，CPU int8）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

# 必须在导入 huggingface_hub 前设置镜像
if os.environ.get("HF_ENDPOINT", "") == "":
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


class AsrResult:
    __slots__ = ("text", "lang", "confidence", "audio_s")

    def __init__(self, text: str, lang: str, confidence: float, audio_s: float):
        self.text = text
        self.lang = lang
        self.confidence = confidence
        self.audio_s = audio_s

    def __repr__(self) -> str:
        return f"AsrResult({self.text!r}, lang={self.lang}, conf={self.confidence:.2f})"


class FasterWhisperASR:
    def __init__(self, model_size: str = "small", models_dir: Optional[Path] = None,
                 threads: int = 0, compute_type: str = "int8"):
        self.model_size = model_size
        self.models_dir = Path(models_dir) if models_dir else None
        self.threads = threads or max(2, (os.cpu_count() or 4) // 2)
        self.compute_type = compute_type
        self._model = None
        self._loaded_size = None

    def ensure(self, size: Optional[str] = None) -> None:
        size = size or self.model_size
        if self._model is not None and self._loaded_size == size:
            return
        from faster_whisper import WhisperModel

        name = size
        if size.endswith(".en"):
            name = size
        self._model = WhisperModel(
            name,
            device="cpu",
            compute_type=self.compute_type,
            cpu_threads=self.threads,
            download_root=str(self.models_dir) if self.models_dir else None,
        )
        self._loaded_size = size

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None,
                   beam_size: int = 1, initial_prompt: Optional[str] = None,
                   size: Optional[str] = None) -> AsrResult:
        self.ensure(size)
        a = np.asarray(audio, dtype=np.float32).reshape(-1)
        duration = a.size / 16000.0
        if duration < 0.15:
            return AsrResult("", language or "", 0.0, duration)

        segments, info = self._model.transcribe(
            a,
            language=None if not language or language == "auto" else language,
            beam_size=beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
            initial_prompt=initial_prompt or None,
            no_speech_threshold=0.9,
        )
        parts: list[str] = []
        confs: list[float] = []
        for s in segments:
            txt = (s.text or "").strip()
            if not txt:
                continue
            # 过滤音乐/噪声幻觉：no_speech 高且 avg_logprob 低
            if (s.no_speech_prob or 0) > 0.75 and (s.avg_logprob or -9) < -0.9:
                continue
            parts.append(txt)
            confs.append(float(s.avg_logprob or -2.0))
        text = " ".join(parts).strip()
        lang = (info.language if info else language) or (language or "")
        conf = float(np.mean(confs)) if confs else 0.0
        return AsrResult(text, lang, conf, duration)
