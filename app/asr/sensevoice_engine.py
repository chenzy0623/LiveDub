"""SenseVoice 语音识别（sherpa-onnx，CPU 极快，支持中英日韩粤）。"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np


class SenseVoiceASR:
    def __init__(self, model_dir: Path, threads: int = 4, use_itn: bool = True):
        self.model_dir = Path(model_dir)
        self.threads = threads
        self.use_itn = use_itn
        self._rec = None
        self.latency_s = 0.0

    def _model_file(self) -> Path:
        for name in ("model.int8.onnx", "model.onnx"):
            p = self.model_dir / name
            if p.exists():
                return p
        raise FileNotFoundError(f"在 {self.model_dir} 找不到 SenseVoice 模型")

    def available(self) -> tuple[bool, str]:
        try:
            self._model_file()
            (self.model_dir / "tokens.txt").exists() or (_ for _ in ()).throw(
                FileNotFoundError("缺少 tokens.txt"))
            return True, ""
        except Exception as e:
            return False, str(e)

    def ensure(self) -> None:
        if self._rec is not None:
            return
        import sherpa_onnx
        self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self._model_file()),
            tokens=str(self.model_dir / "tokens.txt"),
            num_threads=self.threads,
            use_itn=self.use_itn,
            language="auto",
            debug=False,
        )

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> "AsrResult":
        from .faster_whisper_engine import AsrResult
        self.ensure()
        a = np.asarray(audio, dtype=np.float32).reshape(-1)
        dur = len(a) / 16000.0
        if dur < 0.15:
            return AsrResult("", language or "", 0.0, dur)
        t = time.time()
        s = self._rec.create_stream()
        s.accept_waveform(16000, a)
        self._rec.decode_stream(s)
        self.latency_s = time.time() - t
        text = clean_text(s.result.text)
        lang = getattr(s.result, "lang", "") or (language or "")
        lang = lang.strip("<>|").lower() or "auto"
        return AsrResult(text, lang, 1.0, dur)


_TAG_RE = re.compile(r"<\|?.{0,24}?\|?>|<[^<>]{0,24}>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """清掉 SenseVoice 的标签残留（<|en|>、<perd>、>. 之类）。"""
    if not text:
        return ""
    t = _TAG_RE.sub(" ", text)
    # 形如 ">.", ">," 的残余
    t = re.sub(r">\s*([.,!?;:])", r"\1", t)
    t = t.replace(">", " ")
    t = _SPACE_RE.sub(" ", t).strip()
    # 标点前不应有空格
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t
