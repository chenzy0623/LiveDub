"""冒烟测试：设备枚举 / 环回采集 / VAD / ASR / TTS 全链路。

用法：
  .venv\\Scripts\\python.exe tools\\smoke.py devices
  .venv\\Scripts\\python.exe tools\\smoke.py loopback 5      # 录 5 秒系统声音
  .venv\\Scripts\\python.exe tools\\smoke.py vad            # 对录好的 wav 跑 VAD
  .venv\\Scripts\\python.exe tools\\smoke.py asr base small  # 下载模型 + 测速
  .venv\\Scripts\\python.exe tools\\smoke.py tts            # edge-tts 合成
"""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np


def cmd_devices():
    from app.audio import devices as dv
    for kind, fn in (("播放", dv.list_outputs), ("麦克风", dv.list_inputs), ("系统声音", dv.list_loopbacks)):
        print(f"\n=== {kind} ===")
        for d in fn():
            print(f"  #{d.index:<3} {d.name}  ch={d.channels} sr={d.rate} {d.host_api}")


def cmd_loopback(secs: float = 5.0):
    from app.audio import devices as dv
    from app.audio.stream import CaptureStream
    dev = dv.resolve("loopback", "")
    print("采集设备:", dev.label(), "sr=", dev.rate)
    chunks: list[np.ndarray] = []
    st = CaptureStream(dev, lambda a: chunks.append(a.copy()))
    st.start()
    t0 = time.time()
    while time.time() - t0 < secs:
        time.sleep(0.1)
        n = sum(c.size for c in chunks)
        print(f"\r采集 {n/16000:.1f}s", end="", flush=True)
    st.stop()
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    print(f"\n共 {audio.size/16000:.2f}s, 峰值 {np.abs(audio).max():.3f}, RMS {np.sqrt((audio**2).mean()):.4f}")
    out = ROOT / "models" / "capture_test.wav"
    w = wave.open(str(out), "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
    print("已保存:", out)


def _read_wav(path: Path) -> np.ndarray:
    w = wave.open(str(path), "rb")
    n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
    data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        from app.audio.dsp import Resampler
        data = Resampler(sr, 16000).process(data)
    return data.astype(np.float32)


def cmd_vad(path: str = ""):
    from app.vad import load_vad, FRAME
    from app.segmenter import Segmenter
    from app.config import MODELS_DIR
    p = Path(path) if path else ROOT / "models" / "capture_test.wav"
    audio = _read_wav(p)
    vad = load_vad(MODELS_DIR, threads=2)
    print("VAD 类型:", type(vad).__name__)
    segs = []

    def on_seg(a, t0, t1):
        segs.append((t0, t1, len(a) / 16000))
        print(f"  段落 {len(segs)}: {t0:.2f}-{t1:.2f}s ({len(a)/16000:.2f}s 音频)")

    sg = Segmenter(vad, on_seg)
    t = time.time()
    sg.feed(audio)
    sg.flush()
    print(f"共 {len(segs)} 段, 处理耗时 {time.time()-t:.2f}s (音频 {len(audio)/16000:.1f}s)")


def cmd_asr(sizes: list[str]):
    from app.config import MODELS_DIR
    from app.asr.faster_whisper_engine import FasterWhisperASR
    audio = _read_wav(ROOT / "models" / "capture_test.wav")
    for size in sizes:
        print(f"\n=== {size} ===")
        asr = FasterWhisperASR(size, MODELS_DIR)
        t = time.time()
        asr.ensure()
        print(f"模型加载 {time.time()-t:.1f}s")
        for dur in (2.0, 4.0):
            clip = audio[: int(dur * 16000)]
            t = time.time()
            r = asr.transcribe(clip, language="en")
            dt = time.time() - t
            print(f"  {dur}s 音频 -> {dt:.2f}s (RTF {dt/dur:.2f}x)  [{r.lang}] {r.text[:90]}")


def cmd_tts(text: str = "Hello, this is a real time translation test."):
    import asyncio
    import edge_tts
    from app.audio.dsp import Resampler

    async def run():
        t = time.time()
        comm = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        chunks = []
        async for c in comm.stream():
            if c["type"] == "audio":
                chunks.append(c["data"])
        data = b"".join(chunks)
        print(f"合成 {len(data)} bytes, 耗时 {time.time()-t:.2f}s")
        return data

    data = asyncio.run(run())
    out = ROOT / "models" / "tts_test.mp3"
    out.write_bytes(data)
    print("已保存:", out)
    # 解码
    try:
        import miniaudio
        dec = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16)
        print(f"解码: {dec.sample_rate}Hz {dec.nchannels}ch {dec.num_frames} frames = {dec.num_frames/dec.sample_rate:.2f}s")
    except Exception as e:
        print("miniaudio 未安装（可选）:", e)


def cmd_mt():
    import requests
    tests = [
        ("mymemory", "https://api.mymemory.translated.net/get?q=Hello%20world&langpair=en|zh-CN"),
        ("libretranslate", "https://libretranslate.com/translate"),
    ]
    for name, url in tests:
        try:
            if name == "libretranslate":
                r = requests.post(url, json={"q": "Hello world", "source": "en", "target": "zh"}, timeout=8)
            else:
                r = requests.get(url, timeout=8)
            print(f"{name}: {r.status_code} {r.text[:150]}")
        except Exception as e:
            print(f"{name}: FAIL {type(e).__name__} {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "devices"
    if cmd == "devices":
        cmd_devices()
    elif cmd == "loopback":
        cmd_loopback(float(sys.argv[2]) if len(sys.argv) > 2 else 5.0)
    elif cmd == "vad":
        cmd_vad(sys.argv[2] if len(sys.argv) > 2 else "")
    elif cmd == "asr":
        cmd_asr(sys.argv[2:] or ["base", "small"])
    elif cmd == "tts":
        cmd_tts(*sys.argv[2:])
    elif cmd == "mt":
        cmd_mt()
    else:
        print(__doc__)
