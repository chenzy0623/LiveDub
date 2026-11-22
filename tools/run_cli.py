"""无界面端到端测试：播放一段音频 → 环回采集 → 同传。

用法：
  python tools/run_cli.py                 # 播放 models/sample_en.mp3 并同传
  python tools/run_cli.py --file xxx.mp3 --target zh
  python tools/run_cli.py --mic 8         # 直接听麦克风 8 秒
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # Windows 控制台中文输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np


def play_file(path: Path, device_name: str = "") -> None:
    """后台播放音频文件（用于喂给环回采集）。"""
    import miniaudio
    import pyaudiowpatch as pyaudio
    from app.audio import devices as dv
    from app.audio.dsp import Resampler

    dec = miniaudio.decode(path.read_bytes(), output_format=miniaudio.SampleFormat.SIGNED16)
    pcm = np.frombuffer(dec.samples, dtype=np.int16).reshape(-1, dec.nchannels).mean(axis=1)
    pcm = pcm.astype(np.float32) / 32768.0
    dev = dv.resolve("output", device_name)
    pa = dv.get_pa()
    ch = 2 if dev.channels >= 2 else 1
    st = pa.open(format=pyaudio.paFloat32, channels=ch, rate=int(dev.rate),
                 frames_per_buffer=1024, output=True, output_device_index=dev.index)
    rs = Resampler(dec.sample_rate, int(dev.rate))
    y = rs.process(pcm)
    out = np.column_stack([y, y]).reshape(-1) if ch == 2 else y
    st.write(out.astype(np.float32).tobytes())
    st.stop_stream(); st.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "models" / "sample_en.mp3"))
    ap.add_argument("--target", default="zh")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--mic", type=float, default=0, help="直接采集麦克风 N 秒（不播放文件）")
    ap.add_argument("--voice", action="store_true", help="开启配音")
    ap.add_argument("--mt", default="bing", help="bing / deepseek / opus / none")
    ap.add_argument("--tts", default="edge", help="edge / piper")
    ap.add_argument("--offline", action="store_true", help="完全离线：翻译 opus + 配音 piper")
    ap.add_argument("--loopback", default="")
    args = ap.parse_args()

    from app.config import Config
    from app.pipeline.engine import DualPipeline, Events

    cfg = Config.load()
    cfg.capture_source = "mic" if args.mic else "system"
    cfg.loopback_device = args.loopback
    cfg.target_lang = args.target
    cfg.source_lang = args.source
    cfg.voice_enabled = bool(args.voice)
    cfg.mt_engine = "opus" if args.offline else args.mt
    cfg.tts_engine = "piper" if args.offline else args.tts
    cfg.offline_only = bool(args.offline)
    cfg.partial_enabled = True

    ev = Events()
    t_start = time.time()

    def on_partial(src, tgt, d):
        print(f"\r[字幕] {src}  →  {tgt}" + " " * 20, end="", flush=True)

    def on_final(r):
        print(f"\n[完成] 识别({r.asr_s:.2f}s) 翻译({r.mt_s:.2f}s) 配音({r.tts_s:.2f}s) "
              f"总延迟 {r.latency:.2f}s")
        print(f"       原文: {r.src_text}")
        print(f"       译文: {r.tgt_text}" + (f"   [{r.voice}]" if r.voice else ""))
        if r.error:
            print(f"       ! {r.error}")

    def on_error(where, msg):
        print(f"\n[错误/{where}] {msg}")

    ev.on_partial = on_partial
    ev.on_final = on_final
    ev.on_error = on_error

    pipe = DualPipeline(cfg, ev)
    print(f"启动：采集={'麦克风' if args.mic else '系统声音'} 目标语言={args.target} "
          f"MT={cfg.mt_engine} TTS={cfg.tts_engine} 配音={args.voice}")

    play_thread = None
    if args.mic:
        seconds = args.mic
    else:
        f = Path(args.file)
        if not f.exists():
            print("找不到音频文件:", f)
            return
        import miniaudio
        dec = miniaudio.decode(f.read_bytes())
        seconds = dec.num_frames / dec.sample_rate + 4.0
        play_thread = threading.Thread(target=play_file, args=(f,), daemon=True)
        play_thread.start()

    pipe.start()
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    print("\n停止中…")
    pipe.stop()
    if play_thread:
        play_thread.join(timeout=5)
    print(f"总耗时 {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
