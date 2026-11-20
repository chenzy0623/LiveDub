"""验证「我方说话 → 翻译英文 → 送进 VB-CABLE」这条出站链路。

没有真人麦克风，用「扬声器环回」冒充麦克风：
    播放中文样本 → 扬声器环回(假麦克风) → 出站通道(识别→翻译→配音)
        → 写入 CABLE Input → 再从 CABLE Input 环回录音，检查是否真有英文语音。

用法： python tools/vb_test.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pyaudiowpatch as pyaudio

from app.audio import devices as dv
from app.audio.stream import CaptureStream
from app.config import Config
from app.pipeline.engine import Channel, Events, Service


def play_to(path: Path, dev: dv.Device) -> None:
    import miniaudio
    from app.audio.dsp import Resampler

    dec = miniaudio.decode_file(str(path), output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=24000)
    pcm = np.frombuffer(dec.samples, dtype=np.int16).astype(np.float32) / 32768.0
    pa = dv.get_pa()
    ch = 2 if dev.channels >= 2 else 1
    st = pa.open(format=pyaudio.paFloat32, channels=ch, rate=int(dev.rate),
                 frames_per_buffer=1024, output=True, output_device_index=dev.index)
    rs = Resampler(dec.sample_rate, int(dev.rate))
    y = rs.process(pcm)
    out = np.column_stack([y, y]).reshape(-1) if ch == 2 else y
    st.write(out.astype(np.float32).tobytes())
    st.stop_stream()
    st.close()


def main() -> int:
    fake_mic = dv.resolve("loopback", "扬声器 (USB Audio and HID)")           # 冒充麦克风
    cable_in = dv.resolve("output", "CABLE Input (VB-Audio Virtual Cable)")   # 送给对方
    cable_mon = dv.resolve("input", "CABLE Output (VB-Audio Virtual Cable)")  # 旁听（对方看到的那路）
    speaker = dv.resolve("output", "扬声器 (USB Audio and HID)")              # 播中文样本
    print(f"假麦克风  : {fake_mic.name} @ {fake_mic.rate}")
    print(f"虚拟麦克风: {cable_in.name} @ {cable_in.rate}")
    print(f"旁听      : {cable_mon.name} @ {cable_mon.rate}")
    print(flush=True)

    cfg = Config()
    cfg.voice_enabled = True
    cfg.keep_voice = True
    cfg.outbound_source_lang = "zh"
    cfg.outbound_target_lang = "en"
    cfg.mt_engine = "bing"
    cfg.asr_engine = "sensevoice"

    finals = []
    events = Events()
    events.on_final = lambda r: (finals.append(r),
                                 print(f"[字幕] {r.src_text}  →  {r.tgt_text}  "
                                       f"[{r.voice}] 延迟 {r.latency:.2f}s", flush=True),
                                 None)[-1]
    events.on_error = lambda ch, msg: print(f"[错误][{ch}] {msg}", flush=True)

    svc = Service(cfg)
    svc.preload()

    heard: list[np.ndarray] = []
    lock = threading.Lock()

    def on_mon(audio: np.ndarray) -> None:
        with lock:
            heard.append(audio.copy())

    mon = CaptureStream(cable_mon, on_mon)
    mon.start()

    ch = Channel("outbound", fake_mic, "outbound", cable_in, svc, events, cfg)
    ch.start()

    threading.Thread(target=play_to, args=(Path("models/sample_zh.mp3"), speaker),
                     daemon=True).start()

    time.sleep(16)
    print("… 停止通道", flush=True)
    ch.stop()
    time.sleep(0.6)
    mon.stop()

    with lock:
        data = np.concatenate(heard) if heard else np.zeros(0, np.float32)
    dur = len(data) / 16000.0
    peak = float(np.abs(data).max()) if data.size else 0.0
    rms = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
    speech = float(np.mean(np.abs(data) > 0.01)) if data.size else 0.0
    print(f"=== 虚拟麦克风上收到的音频：{dur:.1f}s  峰值 {peak:.3f}  "
          f"RMS {rms:.4f}  有声比例 {speech * 100:.0f}%", flush=True)

    if data.size:
        np.save("shots/vb_out.npy", data)
        from app.asr.sensevoice_engine import SenseVoiceASR
        asr = SenseVoiceASR(Path("models/sensevoice"))
        asr.ensure()
        idx = np.where(np.abs(data) > 0.01)[0]
        seg = data[idx[0]:idx[-1]] if idx.size else data
        r = asr.transcribe(seg, 16000)
        print(f"=== 对方听到的内容（识别）：{r.text!r}  语言={r.lang}", flush=True)

    ok = peak > 0.02 and dur > 1.0 and bool(finals)
    print("=== 结论:", "出站链路 OK" if ok else "出站链路异常", flush=True)
    sys.stdout.flush()
    os._exit(0 if ok else 1)   # 跳过 pyaudio/onnxruntime 的退出清理，避免 0xC0000005


if __name__ == "__main__":
    raise SystemExit(main())
