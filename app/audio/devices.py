"""音频设备枚举（基于 PyAudioWPatch / WASAPI）。

提供三类设备：
  - output   : 播放设备（耳机/音箱/虚拟声卡输入端点）
  - input    : 普通录音设备（麦克风）
  - loopback : WASAPI 环回设备（抓取系统正在播放的声音）
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import pyaudiowpatch as pyaudio

_audios: list["pyaudio.PyAudio"] = []
_lock = threading.Lock()


def get_pa() -> pyaudio.PyAudio:
    """复用同一个 PyAudio 实例，避免反复初始化 WASAPI。"""
    with _lock:
        if not _audios:
            pa = pyaudio.PyAudio()
            _audios.append(pa)
        return _audios[0]


@dataclass
class Device:
    index: int
    name: str
    kind: str          # output / input / loopback
    channels: int
    rate: int
    host_api: str = ""

    def label(self) -> str:
        tag = {"output": "播放", "input": "麦克风", "loopback": "系统声音"}.get(self.kind, self.kind)
        return f"[{tag}] {self.name}"


def _host_name(pa: pyaudio.PyAudio, idx: int) -> str:
    try:
        return pa.get_host_api_info_by_index(int(idx)).get("name", "")
    except Exception:
        return ""


def _wasapi_only(items: list[Device]) -> list[Device]:
    """同一个物理设备在 MME/DirectSound/WASAPI 下会出现多次。

    我们只保留 WASAPI 端点（名字完整、48k、延迟低）；若系统没有 WASAPI
    信息则原样返回。
    """
    wa = [d for d in items if "wasapi" in (d.host_api or "").lower()]
    return wa or items


def list_outputs() -> list[Device]:
    pa = get_pa()
    out: list[Device] = []
    for i in range(pa.get_device_count()):
        try:
            d = pa.get_device_info_by_index(i)
        except Exception:
            continue
        if int(d.get("maxOutputChannels", 0)) > 0:
            name = str(d.get("name", ""))
            if "loopback" in name.lower():
                continue
            out.append(Device(i, name, "output", int(d["maxOutputChannels"]),
                              int(d.get("defaultSampleRate", 48000)), _host_name(pa, d.get("hostApi", -1))))
    return _wasapi_only(out)


def list_inputs() -> list[Device]:
    pa = get_pa()
    out: list[Device] = []
    for i in range(pa.get_device_count()):
        try:
            d = pa.get_device_info_by_index(i)
        except Exception:
            continue
        if int(d.get("maxInputChannels", 0)) > 0 and not d.get("isLoopbackDevice", False):
            name = str(d.get("name", ""))
            if "loopback" in name.lower():
                continue
            out.append(Device(i, name, "input", int(d["maxInputChannels"]),
                              int(d.get("defaultSampleRate", 48000)), _host_name(pa, d.get("hostApi", -1))))
    return _wasapi_only(out)


def list_loopbacks() -> list[Device]:
    pa = get_pa()
    out: list[Device] = []
    try:
        gen = pa.get_loopback_device_info_generator()
    except Exception:
        return out
    for d in gen:
        out.append(Device(int(d["index"]), str(d.get("name", "")), "loopback",
                          int(d.get("maxInputChannels", 2)),
                          int(d.get("defaultSampleRate", 48000)),
                          _host_name(pa, d.get("hostApi", -1))))
    return _wasapi_only(out)


def find_by_index(index: int) -> Optional[Device]:
    pa = get_pa()
    try:
        d = pa.get_device_info_by_index(index)
    except Exception:
        return None
    kind = "loopback" if d.get("isLoopbackDevice") else (
        "input" if int(d.get("maxInputChannels", 0)) > 0 else "output")
    return Device(index, str(d.get("name", "")), kind,
                  int(d.get("maxInputChannels" if kind != "output" else "maxOutputChannels", 2)),
                  int(d.get("defaultSampleRate", 48000)), _host_name(pa, d.get("hostApi", -1)))


def resolve(kind: str, wanted: str) -> Device:
    """按名字片段或索引解析设备；wanted 为空则取默认。"""
    pool = {"output": list_outputs, "input": list_inputs, "loopback": list_loopbacks}[kind]()
    if not pool:
        raise RuntimeError(f"没有找到可用的{kind}设备")
    if wanted:
        w = str(wanted).lower()
        for d in pool:
            if d.name.lower() == w:
                return d
        for d in pool:
            if w in d.name.lower():
                return d
        try:
            idx = int(wanted)
            for d in pool:
                if d.index == idx:
                    return d
        except ValueError:
            pass
    # 默认：WASAPI 默认设备
    pa = get_pa()
    try:
        if kind == "loopback":
            d = pa.get_default_wasapi_loopback()
            return Device(int(d["index"]), str(d.get("name", "")), "loopback",
                          int(d.get("maxInputChannels", 2)), int(d.get("defaultSampleRate", 48000)))
        if kind == "input":
            d = pa.get_default_input_device_info()
            return Device(int(d["index"]), str(d.get("name", "")), "input",
                          int(d.get("maxInputChannels", 1)), int(d.get("defaultSampleRate", 48000)))
        d = pa.get_default_output_device_info()
        return Device(int(d["index"]), str(d.get("name", "")), "output",
                      int(d.get("maxOutputChannels", 2)), int(d.get("defaultSampleRate", 48000)))
    except Exception:
        return pool[0]


def list_virtual_mics() -> list[Device]:
    """筛选常见的虚拟声卡输入端点（VB-CABLE / VoiceMeeter / CABLE Input 等）。"""
    keys = ("cable", "vb-audio", "voicemeeter", "virtual", "虚拟")
    res = []
    for d in list_outputs():
        n = d.name.lower()
        if any(k in n for k in keys):
            res.append(d)
    # "CABLE Input" 是常用端点，"CABLE In 16ch" 排在后面
    res.sort(key=lambda d: ("16ch" in d.name.lower(), 0 if "cable input" in d.name.lower() else 1))
    return res


def has_vb_cable() -> bool:
    return bool(list_virtual_mics())


def close_all() -> None:
    with _lock:
        for pa in _audios:
            try:
                pa.terminate()
            except Exception:
                pass
        _audios.clear()
