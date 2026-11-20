"""ASR 速度基准：用本地音频测得实时率 (RTF)。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np


def load_any(path: Path) -> tuple[np.ndarray, int]:
    if path.suffix.lower() == ".wav":
        import wave
        w = wave.open(str(path), "rb")
        n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
        d = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        w.close()
        if ch > 1:
            d = d.reshape(-1, ch).mean(axis=1)
        return d, sr
    import miniaudio
    dec = miniaudio.decode(path.read_bytes(), output_format=miniaudio.SampleFormat.SIGNED16)
    d = np.frombuffer(dec.samples, dtype=np.int16).reshape(-1, dec.nchannels).mean(axis=1)
    return d.astype(np.float32) / 32768.0, dec.sample_rate


def main():
    from app.audio.dsp import Resampler
    from app.asr.faster_whisper_engine import FasterWhisperASR
    from app.config import MODELS_DIR

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "models" / "tts_test.mp3"
    sizes = sys.argv[2:] or ["base", "small"]
    audio, sr = load_any(src)
    if sr != 16000:
        audio = Resampler(sr, 16000).process(audio)
    print(f"音频: {src.name}  {len(audio)/16000:.2f}s")

    for size in sizes:
        print(f"\n=== whisper-{size} ===")
        asr = FasterWhisperASR(size, MODELS_DIR)
        t = time.time()
        try:
            asr.ensure()
        except Exception as e:
            print("  加载失败:", e)
            continue
        print(f"  加载/下载 {time.time()-t:.1f}s, threads={asr.threads}")
        for dur in (2.0, 4.0, 8.0):
            if dur * 16000 > len(audio):
                continue
            clip = audio[: int(dur * 16000)]
            asr.transcribe(clip[: 16000], language="en")  # 预热
            t = time.time()
            r = asr.transcribe(clip, language="en")
            dt = time.time() - t
            print(f"  {dur:.0f}s 音频 -> {dt:.2f}s  RTF={dt/dur:.2f}  [{r.lang}] {r.text[:100]}")


if __name__ == "__main__":
    main()
