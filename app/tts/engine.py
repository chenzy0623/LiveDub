"""TTS 引擎：edge-tts（免费微软神经音色）+ 可选克隆服务。"""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

import numpy as np

# 常见音色的基准基频（Hz），用于音高贴合
VOICE_BASE_F0 = {
    "zh-CN-YunxiNeural": 128, "zh-CN-YunjianNeural": 118, "zh-CN-YunyangNeural": 122,
    "zh-CN-YunxiaNeural": 135, "zh-CN-XiaoxiaoNeural": 215, "zh-CN-XiaoyiNeural": 225,
    "en-US-GuyNeural": 118, "en-US-AndrewNeural": 120, "en-US-BrianNeural": 115,
    "en-US-ChristopherNeural": 112, "en-US-AriaNeural": 205, "en-US-JennyNeural": 210,
    "en-US-EmmaNeural": 208, "en-GB-RyanNeural": 120, "en-GB-SoniaNeural": 200,
    "ja-JP-KeitaNeural": 120, "ja-JP-NanamiNeural": 210,
    "ko-KR-InJoonNeural": 118, "ko-KR-SunHiNeural": 205,
}

# 优先使用的音色（自然度高）
PREFERRED = {
    "zh-Hans": {"male": ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural"],
                "female": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"]},
    "zh-Hant": {"male": ["zh-TW-YunJheNeural"], "female": ["zh-TW-HsiaoChenNeural"]},
    "en": {"male": ["en-US-AndrewNeural", "en-US-GuyNeural", "en-US-BrianNeural"],
           "female": ["en-US-AriaNeural", "en-US-EmmaNeural", "en-US-JennyNeural"]},
    "ja": {"male": ["ja-JP-KeitaNeural"], "female": ["ja-JP-NanamiNeural"]},
    "ko": {"male": ["ko-KR-InJoonNeural"], "female": ["ko-KR-SunHiNeural"]},
}


def locale_for(lang: str) -> str:
    l = (lang or "en").lower()
    if l.startswith("zh"):
        return "zh-Hant" if ("tw" in l or "hant" in l) else "zh-Hans"
    if l.startswith("ja"):
        return "ja"
    if l.startswith("ko"):
        return "ko"
    if l.startswith("en"):
        return "en"
    return l


def pick_voice(lang: str, gender: str) -> str:
    loc = locale_for(lang)
    table = PREFERRED.get(loc) or PREFERRED["en"]
    g = gender if gender in ("male", "female") else "female"
    return table[g][0]


class EdgeTTS:
    """edge-tts 封装；内部维护一个常驻事件循环线程。"""

    def __init__(self, rate: str = "+0%", volume: str = "+0%", pitch_hz: int = 0):
        self.rate = rate
        self.volume = volume
        self.pitch_hz = pitch_hz
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._voices: list[dict] = []
        self._ready = threading.Event()

    # ---------- 事件循环 ----------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="edge-tts-loop", daemon=True)
        self._thread.start()
        self._ready.set()
        return self._loop

    def _run(self, coro, timeout: float = 30.0):
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    # ---------- 声音列表 ----------
    def voices(self) -> list[dict]:
        if self._voices:
            return self._voices
        import edge_tts
        try:
            vs = self._run(edge_tts.list_voices(), timeout=20)
            self._voices = vs or []
        except Exception:
            self._voices = []
        return self._voices

    def voices_by_locale(self, lang: str) -> list[dict]:
        loc = locale_for(lang)
        out = []
        for v in self.voices():
            short = (v.get("ShortName") or "")
            if short.startswith(loc) or short.startswith(loc.split("-")[0]):
                out.append(v)
        return out

    # ---------- 合成 ----------
    async def _synth(self, text: str, voice: str, rate: str, volume: str, pitch: str) -> tuple[bytes, str]:
        import edge_tts
        comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
        buf = bytearray()
        fmt = "audio-24khz-48kbitrate-mono-mp3"
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf), fmt

    def synthesize(self, text: str, voice: str, pitch_hz: Optional[int] = None,
                   rate: Optional[str] = None) -> tuple[np.ndarray, int]:
        """返回 (float32 PCM, 采样率)。"""
        text = (text or "").strip()
        if not text:
            return np.zeros(0, np.float32), 24000
        p = self.pitch_hz if pitch_hz is None else pitch_hz
        pitch = f"{p:+d}Hz" if p else "+0Hz"
        data, _fmt = self._run(self._synth(text, voice, rate or self.rate,
                                           self.volume, pitch))
        if not data:
            return np.zeros(0, np.float32), 24000
        return decode_mp3(data)


def decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    """解码 mp3 字节流 → (float32 单声道, 采样率)。

    miniaudio 1.73 的 decode(bytes) 有 cffi 传参缺陷（TypeError: cdata pointer），
    因此统一走临时文件 + decode_file 的兼容路径。
    """
    import miniaudio
    import os
    import tempfile

    fmt = miniaudio.SampleFormat.SIGNED16
    try:
        dec = miniaudio.decode(data, output_format=fmt, nchannels=1, sample_rate=24000)
    except TypeError:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(data)
                tmp = f.name
            dec = miniaudio.decode_file(tmp, output_format=fmt, nchannels=1,
                                        sample_rate=24000)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    pcm = np.frombuffer(dec.samples, dtype=np.int16).astype(np.float32) / 32768.0
    if dec.nchannels > 1:
        pcm = pcm.reshape(-1, dec.nchannels).mean(axis=1)
    return pcm, int(dec.sample_rate)


class CloneTTS:
    """通用克隆 TTS：OpenAI 兼容 /audio/speech 接口（支持 Fish Audio、火山、MiniMax 等
    提供 OpenAI 兼容层服务）。voice = 克隆音色 ID。"""

    def __init__(self, base_url: str, api_key: str, model: str = "tts-1", voice_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.voice_id = voice_id

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置克隆服务 Key"
        return True, ""

    def synthesize(self, text: str, voice: str = "", pitch_hz: int = 0,
                   rate: str = "") -> tuple[np.ndarray, int]:
        import requests
        voice = voice or self.voice_id
        r = requests.post(self.base_url + "/audio/speech",
                          headers={"Authorization": f"Bearer {self.api_key}"},
                          json={"model": self.model, "input": text, "voice": voice,
                                "response_format": "mp3"}, timeout=30)
        r.raise_for_status()
        return decode_mp3(r.content)
