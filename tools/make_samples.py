"""生成测试语音（英文/中文），用 edge-tts。"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import edge_tts

EN = ("Hello there, it is really nice to meet you. "
      "I have been working on this project for about three months now, "
      "and honestly I think we are finally getting somewhere with it. "
      "What do you think about the new design?")

ZH = ("你好，很高兴认识你。"
      "这个事情我已经做了大概三个月了，"
      "说实话我觉得我们终于有点进展了。"
      "你觉得这个新设计怎么样？")


async def synth(text: str, voice: str, out: Path) -> None:
    com = edge_tts.Communicate(text, voice=voice)
    await com.save(str(out))
    print(f"OK {out.name} {out.stat().st_size/1024:.0f}KB")


async def main() -> None:
    d = ROOT / "models"
    d.mkdir(exist_ok=True)
    await synth(EN, "en-US-GuyNeural", d / "sample_en.mp3")
    await synth(EN, "en-US-AriaNeural", d / "sample_en_f.mp3")
    await synth(ZH, "zh-CN-XiaoxiaoNeural", d / "sample_zh.mp3")


asyncio.run(main())
