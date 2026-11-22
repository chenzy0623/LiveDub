"""全局配置：默认值 + JSON 持久化。

配置文件位置：<项目根>/config.json
另存一份用户覆盖：%APPDATA%/LiveDub/config.json（存在则优先）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"


def _user_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LiveDub" / "config.json"


@dataclass
class Config:
    # ---------------- 音频设备 ----------------
    # "system" = 抓系统正在播放的声音（聊天/电影/游戏）
    # "mic"    = 抓麦克风（自己说话）
    capture_source: str = "system"
    loopback_device: str = ""       # 空 = 系统默认输出对应的 loopback
    mic_device: str = ""            # 空 = 系统默认输入
    playback_device: str = ""       # 译文语音播放到哪（耳机）
    virtual_mic_device: str = ""    # 译文语音送往哪个虚拟麦克风（VB-CABLE）

    # ---------------- 语言 ----------------
    source_lang: str = "auto"        # auto / en / zh / ja / ko ...
    target_lang: str = "zh"          # 译文语言（中文界面默认）
    outbound_source_lang: str = "zh"  # 我说话的语言
    outbound_target_lang: str = "en"  # 翻译给外国人听的语言

    # ---------------- 开关 ----------------
    subtitle_enabled: bool = True
    subtitle_show_src: bool = True   # 字幕里是否带原文小字（只显示译文更清爽）
    overlay_pos: str = "bottom"      # 字幕位置：bottom / top / middle
    voice_enabled: bool = True
    outbound_enabled: bool = False    # 需要虚拟麦克风
    partial_enabled: bool = True      # 说话过程中实时出字幕
    keep_voice: bool = True           # 音色保持（匹配/克隆）
    duck_original: bool = False       # 播放译文时压低原声（需虚拟声卡，暂未实现）
    duck_on_play: bool = True         # 播放译文时屏蔽环回采集，避免自我循环
    mt_context: int = 3               # 送给翻译模型的上文句子数（0 = 不用上下文）

    # ---------------- ASR ----------------
    asr_engine: str = "sensevoice"
    asr_model: str = "small"          # tiny/base/small/medium
    asr_partial_model: str = "base"   # 实时字幕用的轻量模型
    asr_threads: int = 0              # 0 = 自动
    asr_initial_prompt: str = ""

    # ---------------- 翻译 ----------------
    mt_engine: str = "bing"           # bing / deepseek / opus / nllb / none / auto
    offline_only: bool = False        # 完全离线：自动把在线引擎换成本地模型
    mt_threads: int = 4               # 本地翻译模型线程数
    opus_dir: str = ""                # 空 = models/mt（opus-mt 中英双向）
    nllb_dir: str = ""                # 空 = models/mt/nllb-600m-int8
    deepseek_api_key: str = ""
    deepseek_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    mt_extra_prompt: str = ""         # 术语表 / 风格提示

    # ---------------- TTS ----------------
    tts_engine: str = "edge"          # edge / piper / clone
    piper_dir: str = ""               # 空 = models/tts
    piper_threads: int = 2            # 本地 VITS 合成线程数（0 = 自动）
    tts_voice_zh: str = ""            # 空 = 自动按性别挑选
    tts_voice_en: str = ""
    tts_rate: str = "+0%"             # edge-tts rate
    tts_volume: str = "+0%"
    tts_pitch_follow: bool = True     # 跟随原说话人音高
    # 克隆服务（可选）
    clone_provider: str = "fish"      # fish / minimax / custom
    clone_api_key: str = ""
    clone_base_url: str = ""
    clone_voice_id: str = ""

    # ---------------- 界面 ----------------
    overlay_font_size: int = 30
    overlay_src_size: int = 15          # 原文小字字号
    overlay_tgt_size: int = 30          # 译文字号
    overlay_opacity: float = 0.88
    overlay_width: int = 1100
    overlay_y: int = 60
    overlay_show_source: bool = True
    overlay_theme: str = "dark"
    hotkey_toggle: str = "ctrl+alt+s"   # 开始/停止
    hotkey_overlay: str = "ctrl+alt+h"  # 显示/隐藏字幕
    close_to_tray: bool = True

    # ---------------- 其它 ----------------
    log_dir: str = ""

    _path: Path = field(default_factory=_user_config_path, repr=False, compare=False)

    # ---------- 读写 ----------
    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        path = _user_config_path()
        legacy = ROOT / "config.json"
        for p in (path, legacy):
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    cfg.update(data)
                    cfg._path = path
                except Exception:
                    pass
                break
        return cfg

    def update(self, data: dict[str, Any]) -> None:
        for k, v in data.items():
            if hasattr(self, k) and not k.startswith("_"):
                setattr(self, k, v)

    def save(self) -> Path:
        p = self._path
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p


CFG = Config.load()
