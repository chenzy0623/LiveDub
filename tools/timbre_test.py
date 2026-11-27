"""离线音色还原自测：用男声英文样本作参考，把女声 piper 的中文配音往男声靠。"""
import sys, time, wave, pathlib
sys.path.insert(0, ".")
import numpy as np

from app.tts.engine import decode_mp3
from app.tts.offline import PiperTTS, VOICES, pick_local_voice
from app.audio.pitch import estimate_f0
from app.audio.timbre import TimbreTracker, match, ltas_distance, _ltas_db

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "shots"
TEXT = "我已经在这个项目上工作了大约三个月了，说实话我觉得我们终于有点进展了。"

def to16k(x, sr):
    if sr == 16000:
        return x
    n = int(round(len(x) * 16000 / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)

def save_wav(path, x, sr):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())

ref_pcm, ref_sr = decode_mp3((ROOT / "models/sample_en.mp3").read_bytes())
ref16 = to16k(ref_pcm, ref_sr)
tracker = TimbreTracker()
ref = tracker.update(ref16, 16000)
ref_ltas = _ltas_db(ref16, 16000)
print(f"参考: {len(ref16)/16000:.2f}s  f0={ref.f0:.1f}Hz  包络参考已取")

tts = PiperTTS()
ok, msg = tts.available()
print("piper:", ok, msg)
voice = pick_local_voice("zh", "female")
base = VOICES[voice][2]
pitch_hz = max(-50, min(50, int(round(ref.f0 - base))))
print(f"音色 {voice} 基准 {base}Hz → pitch_hz={pitch_hz}")

t0 = time.monotonic()
pcm, sr = tts.synthesize(TEXT, voice=voice, pitch_hz=pitch_hz)
t_syn = time.monotonic() - t0
print(f"合成 {len(pcm)/sr:.2f}s@{sr}Hz 用时 {t_syn:.2f}s")

f0_raw = estimate_f0(pcm, sr)
d_raw = ltas_distance(ref_ltas, _ltas_db(pcm, sr))
print(f"[未还原] f0={f0_raw:.1f}Hz  包络差={d_raw:.2f}dB  时长={len(pcm)/sr:.2f}s")
save_wav(OUT / "timbre_raw.wav", pcm, sr)

for st in (0.4, 0.7, 1.0):
    t1 = time.monotonic()
    y = match(pcm, sr, ref, strength=st)
    dt = time.monotonic() - t1
    f0 = estimate_f0(y, sr)
    d = ltas_distance(ref_ltas, _ltas_db(y, sr))
    print(f"[还原 {st:.0%}] f0={f0:.1f}Hz  包络差={d:.2f}dB  时长={len(y)/sr:.2f}s "
          f"耗时={dt*1000:.0f}ms(音频 {len(pcm)/sr:.1f}s → 开销 {dt/(len(pcm)/sr):.3f}x)")
    save_wav(OUT / f"timbre_{int(st*100)}.wav", y, sr)
