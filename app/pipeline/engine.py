"""双通道同传管线。

入站（foreigner → me）：
   系统声音 / 麦克风 → VAD 分段 → ASR → 翻译 → ①悬浮字幕 ②译文语音(耳机)

出站（me → foreigner）：
   麦克风 → VAD 分段 → ASR → 翻译 → 译文语音 → 虚拟麦克风(VB-CABLE)

设计要点：
  * 采集回调只做入队，重活都在工作线程
  * 语音优先于字幕：一句话说完立即翻译并配音，同时说话期间出实时字幕
  * 所有阶段都带超时/异常保护，单句失败不影响整体
"""
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from ..audio import devices as dv
from ..audio.pitch import estimate_f0, gender_of
from ..audio.stream import CaptureStream, PlaybackStream
from ..config import MODELS_DIR, Config
from ..segmenter import Segmenter
from ..vad import load_vad


# ----------------------------------------------------------------------------
@dataclass
class Utterance:
    seq: int
    audio: np.ndarray
    t0: float
    t1: float
    direction: str = "inbound"


@dataclass
class SegmentResult:
    seq: int
    src_text: str = ""
    tgt_text: str = ""
    src_lang: str = ""
    tgt_lang: str = ""
    direction: str = "inbound"
    asr_s: float = 0.0
    mt_s: float = 0.0
    tts_s: float = 0.0
    total_s: float = 0.0
    t_audio_end: float = 0.0
    t_done: float = 0.0
    error: str = ""
    voice: str = ""

    @property
    def latency(self) -> float:
        return max(0.0, self.t_done - self.t_audio_end) if self.t_done else 0.0


class Events:
    """UI 回调集合（全部在工作线程触发，UI 层需自行转到主线程）。"""

    def __init__(self):
        self.on_partial: Callable[[str, str, str], None] = lambda *a: None   # src, tgt, dir
        self.on_final: Callable[[SegmentResult], None] = lambda r: None
        self.on_level: Callable[[float, str], None] = lambda v, d: None
        self.on_status: Callable[[str], None] = lambda s: None
        self.on_error: Callable[[str, str], None] = lambda where, msg: None


class Service:
    """负责构建并持有 ASR / MT / TTS 实例。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._asr = None
        self._asr_partial = None
        self._asr_kind = ""
        self._mt = None
        self._tts = None
        self._lock = threading.Lock()

    # ---------------- ASR ----------------
    def asr(self, partial: bool = False):
        with self._lock:
            size = self.cfg.asr_partial_model if partial else self.cfg.asr_model
            attr = "_asr_partial" if partial else "_asr"
            inst = getattr(self, attr)
            if inst is not None and getattr(inst, "_cfg_size", None) == size:
                return inst
            inst = self._build_asr(size, partial)
            setattr(self, attr, inst)
            return inst

    def _build_asr(self, size: str, partial: bool):
        # 1) SenseVoice（CPU 上快 10 倍以上）
        sv_dir = MODELS_DIR / "sensevoice"
        try:
            from ..asr.sensevoice_engine import SenseVoiceASR
            sv = SenseVoiceASR(sv_dir, threads=4, use_itn=True)
            ok, _ = sv.available()
            if ok:
                sv._cfg_size = size
                return sv
        except Exception:
            pass
        # 2) faster-whisper 回退
        from ..asr.faster_whisper_engine import FasterWhisperASR
        fw = FasterWhisperASR(size, MODELS_DIR, threads=self.cfg.asr_threads)
        fw._cfg_size = size
        return fw

    # ---------------- MT ----------------
    def mt(self):
        with self._lock:
            if self._mt is None:
                from ..mt.translator import build_translator
                self._mt = build_translator(self.cfg)
            return self._mt

    def reset_mt(self):
        with self._lock:
            self._mt = None

    # ---------------- TTS ----------------
    def tts(self):
        with self._lock:
            if self._tts is None:
                from ..tts.engine import CloneTTS, EdgeTTS, pick_voice
                if self.cfg.tts_engine == "clone" and self.cfg.clone_api_key:
                    self._tts = CloneTTS(self.cfg.clone_base_url or "https://api.fish.audio/v1",
                                         self.cfg.clone_api_key,
                                         voice_id=self.cfg.clone_voice_id)
                else:
                    self._tts = EdgeTTS(rate=self.cfg.tts_rate, volume=self.cfg.tts_volume)
            return self._tts

    def voices_for(self, lang: str):
        t = self.tts()
        if hasattr(t, "voices_by_locale"):
            return t.voices_by_locale(lang)
        return []

    def preload(self) -> None:
        """后台预热：加载 ASR 模型、刷新翻译 token，避免首句延迟。"""
        try:
            a = self.asr()
            if hasattr(a, "ensure"):
                a.ensure()
        except Exception:
            pass
        try:
            mt = self.mt()
            if hasattr(mt, "warmup"):
                mt.warmup()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
_HALLUC = {"period", "comma", "question", "exclamation", "you", "thank you.",
           "thank you", "thanks", "bye.", "bye"}
_PUNCT_MAP = {"period": ".", "comma": ",", "question": "?", "exclamation": "!"}
_PUNCT_HALLUC_RE = re.compile(
    r"([,.!?;:，。！？；：])\s*(period|comma|question|exclamation)\b", re.I)


def _clean_hallucination(text: str) -> str:
    """清掉 SenseVoice 在静音/边界处常见的幻觉词与标点误标。"""
    t = (text or "").strip()
    if not t:
        return ""
    t = _PUNCT_HALLUC_RE.sub(lambda m: _PUNCT_MAP[m.group(2).lower()], t)
    t = re.sub(r"\b(period|comma|question|exclamation)$", "", t, flags=re.I).strip()
    if t.lower().strip(" .!?,") in _HALLUC and len(t) <= 16:
        return ""
    return t


class Channel:
    """一条采集→翻译→播放的通道。"""

    def __init__(self, name: str, capture: dv.Device, direction: str,
                 play: Optional[dv.Device], service: Service, events: Events,
                 cfg: Config):
        self.name = name
        self.cfg = cfg
        self.service = service
        self.events = events
        self.direction = direction
        self.capture_dev = capture
        self.play_dev = play
        self._seq = 0
        self._seg_q: "queue.Queue[Utterance]" = queue.Queue(maxsize=8)
        self._part_q: "queue.Queue[tuple[int, np.ndarray]]" = queue.Queue(maxsize=2)
        self._play_q: "queue.Queue[Optional[tuple[int, np.ndarray, int, str]]]" = queue.Queue(maxsize=16)
        self._running = False
        self._threads: list[threading.Thread] = []
        self._capture: Optional[CaptureStream] = None
        self._player: Optional[PlaybackStream] = None
        self._history: list[str] = []
        self._history_lock = threading.Lock()
        self._last_partial: tuple[str, str] = ("", "")
        self._last_partial_ts = 0.0
        self._last_partial_mt = 0.0
        self._final_busy = False
        self._self_speaking = threading.Event()
        self._duck_until = 0.0
        self._last_tts: tuple[float, float, str] = (0.0, 0.0, "")  # 自播音时间窗 + 文本
        self.segments_done = 0
        self.last_error = ""

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        vad = load_vad(MODELS_DIR, threads=2)
        self._segmenter = Segmenter(
            vad,
            on_segment=self._on_segment,
            on_partial=self._on_partial if self.cfg.partial_enabled else None,
            on_level=lambda p, s: self.events.on_level(p, self.name),
        )
        self._capture = CaptureStream(self.capture_dev, self._on_audio)
        self._capture.start()
        if self.play_dev is not None:
            self._player = PlaybackStream(self.play_dev)
        t = threading.Thread(target=self._seg_worker, name=f"{self.name}-asr", daemon=True)
        t.start(); self._threads.append(t)
        if self.cfg.partial_enabled:
            t = threading.Thread(target=self._part_worker, name=f"{self.name}-partial", daemon=True)
            t.start(); self._threads.append(t)
        if self.play_dev is not None:
            t = threading.Thread(target=self._play_worker, name=f"{self.name}-play", daemon=True)
            t.start(); self._threads.append(t)

    def stop(self) -> None:
        self._running = False
        if self._capture:
            self._capture.stop()
        try:
            self._segmenter.flush()
        except Exception:
            pass
        for q in (self._seg_q, self._part_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
        try:
            self._play_q.put_nowait(None)
        except Exception:
            pass
        if self._player:
            self._player.close()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()

    # ---------------- 采集回调（采集线程） ----------------
    def _on_audio(self, audio: np.ndarray) -> None:
        try:
            # 播放自己译文时，环回会把译文一起录进来。这里不再屏蔽采集
            # （那会连对方正在说的话也一起丢掉），改为在文本层做回声判定。
            self._segmenter.feed(audio)
        except Exception as e:
            self.last_error = str(e)

    def _on_segment(self, audio: np.ndarray, t0: float, t1: float) -> None:
        self._seq += 1
        utt = Utterance(self._seq, audio, t0, t1, self.direction)
        try:
            self._seg_q.put_nowait(utt)
        except queue.Full:
            try:
                self._seg_q.get_nowait()
                self._seg_q.put_nowait(utt)
            except Exception:
                pass

    def _on_partial(self, audio: np.ndarray, t0: float) -> None:
        try:
            while True:
                self._part_q.get_nowait()
        except queue.Empty:
            pass
        try:
            self._part_q.put_nowait((self._seq + 1, audio))
        except Exception:
            pass

    # ---------------- ASR→MT→TTS ----------------
    def _seg_worker(self) -> None:
        while self._running:
            try:
                utt = self._seg_q.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                self._final_busy = True
                res = self._process(utt)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.events.on_error(self.name, self.last_error)
                continue
            finally:
                self._final_busy = False
            if res and (res.src_text or res.tgt_text):
                self.segments_done += 1
                self.events.on_final(res)

    def _process(self, utt: Utterance) -> Optional[SegmentResult]:
        cfg = self.cfg
        t_start = time.time()
        res = SegmentResult(seq=utt.seq, direction=self.direction, t_audio_end=utt.t1)
        src_lang = cfg.source_lang if self.direction == "inbound" else cfg.outbound_source_lang
        tgt_lang = cfg.target_lang if self.direction == "inbound" else cfg.outbound_target_lang

        # 1) ASR
        try:
            asr = self.service.asr(partial=False)
            ar = asr.transcribe(utt.audio)
            res.asr_s = time.time() - t_start
            res.src_text = ar.text
            res.src_lang = ar.lang or src_lang
        except Exception as e:
            res.error = f"ASR: {e}"
            return res
        res.src_text = _clean_hallucination(res.src_text)
        if not res.src_text:
            return None

        # 1.5) 自播回声：这段音频与我们刚播的译文时间重叠、文字又高度相似 → 丢掉
        if self._is_self_echo(res.src_text, utt.t0, utt.t1):
            return None

        # 2) 翻译（如果识别的语言已经是目标语言则跳过）
        detected = (res.src_lang or "").lower()
        if self._same_lang(detected, tgt_lang):
            res.tgt_text = res.src_text
        else:
            try:
                n_ctx = int(getattr(cfg, "mt_context", 3) or 0)
                with self._history_lock:
                    ctx = list(self._history[-n_ctx:]) if n_ctx > 0 else []
                mt = self.service.mt()
                t = time.time()
                res.tgt_text = mt.translate(res.src_text, res.src_lang or src_lang, tgt_lang, ctx)
                res.mt_s = time.time() - t
            except Exception as e:
                res.error = f"MT: {e}"
                res.tgt_text = ""
        res.tgt_lang = tgt_lang
        with self._history_lock:
            self._history.append(res.src_text)
            if len(self._history) > 12:
                del self._history[:-12]

        # 3) 配音
        if cfg.voice_enabled and res.tgt_text and self.play_dev is not None:
            try:
                t = time.time()
                pcm, sr = self._speak(res, utt.audio, tgt_lang)
                res.tts_s = time.time() - t
                if pcm.size:
                    self._play_q.put_nowait((utt.seq, pcm, sr, res.tgt_text))
            except Exception as e:
                res.error = (res.error + f" | TTS: {e}").strip(" |")
        res.t_done = time.monotonic()
        res.total_s = time.time() - t_start
        return res

    def _speak(self, res: SegmentResult, src_audio: np.ndarray, tgt_lang: str):
        cfg = self.cfg
        tts = self.service.tts()
        gender = "female"
        pitch_hz = 0
        if cfg.keep_voice:
            f0 = estimate_f0(src_audio, 16000)
            gender = gender_of(f0)
            if cfg.tts_pitch_follow and f0 > 0:
                from ..tts.engine import VOICE_BASE_F0, pick_voice
                voice_try = pick_voice(tgt_lang, gender)
                base = VOICE_BASE_F0.get(voice_try, 0)
                if base:
                    pitch_hz = max(-50, min(50, int(f0 - base)))
        from ..tts.engine import pick_voice
        voice = cfg.tts_voice_zh if tgt_lang.startswith("zh") else cfg.tts_voice_en
        if not voice:
            voice = pick_voice(tgt_lang, gender)
        res.voice = voice
        if hasattr(tts, "synthesize"):
            try:
                return tts.synthesize(res.tgt_text, voice=voice, pitch_hz=pitch_hz)
            except TypeError:
                return tts.synthesize(res.tgt_text, voice)
        return np.zeros(0, np.float32), 24000

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"[\s，。、！？；：,.!?;:'\"（）()\-—…]+", "", text or "").lower()

    def _is_self_echo(self, text: str, t0: float, t1: float) -> bool:
        """判断识别结果是不是我们自己刚播放的译文被环回重采。"""
        p0, p1, spoken = self._last_tts
        if not spoken or t1 <= p0 or t0 >= p1:
            return False
        overlap = min(t1, p1) - max(t0, p0)
        span = max(1e-3, t1 - t0)
        if overlap / span < 0.35:
            return False
        a, b = self._norm(text), self._norm(spoken)
        if not a or not b:
            return False
        if a == b or a in b or b in a:
            return True
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio() > 0.62

    @staticmethod
    def _same_lang(detected: str, target: str) -> bool:
        d, t = (detected or "").lower(), (target or "").lower()
        if not d or not t:
            return False
        if d.startswith("zh") and t.startswith("zh"):
            return True
        return d.split("-")[0] == t.split("-")[0]

    # ---------------- 播放 ----------------
    def _play_worker(self) -> None:
        while self._running:
            try:
                item = self._play_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if item is None:
                break
            seq, pcm, sr, tts_text = item
            try:
                assert self._player is not None
                # 记录自播时间窗与文本，供回声判定（PyAudio 写入可能提前返回）
                dur = len(pcm) / float(sr or 24000)
                self._self_speaking.set()
                now = time.monotonic()
                self._duck_until = now + dur + 0.35
                self._last_tts = (now - 0.15, now + dur + 0.15, tts_text)
                self._player.write(pcm, sr)
            except Exception as e:
                self.events.on_error(self.name, f"播放失败: {e}")
            finally:
                self._duck_until = max(self._duck_until, time.monotonic() + 0.3)
                self._self_speaking.clear()

    # ---------------- 实时字幕 ----------------
    def _part_worker(self) -> None:
        while self._running:
            try:
                seq, audio = self._part_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # 整句任务优先：有积压时不出字幕，避免抢 CPU/网络
            if self._final_busy or not self._seg_q.empty():
                continue
            if len(audio) < 16000 * 0.5:
                continue
            now = time.monotonic()
            if now - self._last_partial_ts < 0.4:
                continue
            self._last_partial_ts = now
            try:
                asr = self.service.asr(partial=True)
                ar = asr.transcribe(audio)
            except Exception:
                continue
            text = (ar.text or "").strip()
            if not text or text == self._last_partial[0]:
                continue
            # 实时字幕同样过滤自播回声（否则会看到自己译文的回读）
            if self._is_self_echo(text, now - len(audio) / 16000.0, now):
                continue
            src_lang = self.cfg.source_lang if self.direction == "inbound" else self.cfg.outbound_source_lang
            tgt_lang = self.cfg.target_lang if self.direction == "inbound" else self.cfg.outbound_target_lang
            tgt = self._last_partial[1]
            need = (not self._same_lang(ar.lang or src_lang, tgt_lang))
            if need and now - self._last_partial_mt >= 1.4 and len(text) > 6:
                self._last_partial_mt = now
                try:
                    tgt = self.service.mt().translate(text, ar.lang or src_lang, tgt_lang, [])
                except Exception:
                    tgt = ""
            elif not need:
                tgt = text
            self._last_partial = (text, tgt)
            self.events.on_partial(text, tgt, self.direction)


# ----------------------------------------------------------------------------
class DualPipeline:
    """同时管理入站与出站两条通道。"""

    def __init__(self, cfg: Config, events: Optional[Events] = None):
        self.cfg = cfg
        self.events = events or Events()
        self.service = Service(cfg)
        self.inbound: Optional[Channel] = None
        self.outbound: Optional[Channel] = None

    def start(self) -> None:
        cfg = self.cfg
        threading.Thread(target=self.service.preload, name="preload", daemon=True).start()
        if cfg.capture_source == "mic":
            cap = dv.resolve("input", cfg.mic_device)
        else:
            cap = dv.resolve("loopback", cfg.loopback_device)
        play = None
        if cfg.voice_enabled:
            play = dv.resolve("output", cfg.playback_device)
        self.inbound = Channel("inbound", cap, "inbound", play, self.service, self.events, cfg)
        self.inbound.start()

        if cfg.outbound_enabled:
            mic = dv.resolve("input", cfg.mic_device)
            vm = dv.resolve("output", cfg.virtual_mic_device)
            self.outbound = Channel("outbound", mic, "outbound", vm, self.service, self.events, cfg)
            self.outbound.start()

    def stop(self) -> None:
        for ch in (self.inbound, self.outbound):
            if ch:
                try:
                    ch.stop()
                except Exception:
                    pass
        self.inbound = None
        self.outbound = None

    @property
    def running(self) -> bool:
        return self.inbound is not None
