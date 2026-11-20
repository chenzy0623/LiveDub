"""一键设置 Windows 默认播放 / 录音设备。

用途：
  1. 装完 VB-CABLE 后，Windows 常把默认播放设备切成「CABLE Input」，
     结果系统声音全进了虚拟声卡、人什么也听不到 —— 用它改回扬声器。
  2. 有些通话软件（旧版 WhatsApp、微信、某些游戏语音）不让选麦克风，
     只能跟随系统默认录音设备 —— 用 `--input CABLE Output` 把默认录音
     设成虚拟声卡，对方就能听到 LiveDub 翻译后的语音。

用法：
    python tools/fix_default_audio.py                 # 列出所有端点
    python tools/fix_default_audio.py --name 扬声器    # 默认播放设备 → 名字含「扬声器」
    python tools/fix_default_audio.py --input "CABLE Output"
    python tools/fix_default_audio.py --input 麦克风   # 改回真实麦克风
"""
from __future__ import annotations

import argparse

from pycaw.constants import ERole
from pycaw.utils import AudioUtilities

# 三种角色都设一遍：控制台 / 多媒体 / 通信（通话软件走的就是"通信"）
ROLES = [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications]


def device_flow(dev) -> int:
    """0 = 播放（渲染端点），1 = 录音（采集端点）。"""
    from pycaw.api.mmdeviceapi import IMMEndpoint

    try:
        return int(dev._dev.QueryInterface(IMMEndpoint).GetDataFlow())
    except Exception:
        return -1


def pick(devs, keyword: str, flow: int, avoid_cable: bool):
    want = keyword.lower()
    cands = [d for d in devs
             if want in d.FriendlyName.lower() and device_flow(d) == flow]
    if avoid_cable:
        # 设播放设备时不要选到虚拟声卡，否则人听不到声音
        cands = [d for d in cands if "cable" not in d.FriendlyName.lower()]
    cands.sort(key=lambda d: "16ch" in d.FriendlyName.lower())
    return cands[0] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="", help="设为默认播放设备（名字片段）")
    ap.add_argument("--input", default="", help="设为默认录音设备（名字片段）")
    args = ap.parse_args()

    devs = [d for d in AudioUtilities.GetAllDevices() if getattr(d, "id", "")]

    if not args.name and not args.input:
        print("当前音频端点：")
        for d in devs:
            flow = {0: "播放", 1: "录音"}.get(device_flow(d), "?  ")
            print(f"  [{flow}] {d.FriendlyName}")
        return 0

    if args.name:
        target = pick(devs, args.name, flow=0, avoid_cable=True)
        if target is None:
            print(f"没找到名字包含 {args.name!r} 的播放设备")
            return 1
        AudioUtilities.SetDefaultDevice(target.id, ROLES)
        print(f"默认播放设备 → {target.FriendlyName}")

    if args.input:
        target = pick(devs, args.input, flow=1, avoid_cable=False)
        if target is None:
            print(f"没找到名字包含 {args.input!r} 的录音设备")
            return 1
        AudioUtilities.SetDefaultDevice(target.id, ROLES)
        print(f"默认录音设备 → {target.FriendlyName}")
        if "cable output" in target.FriendlyName.lower():
            print("提示：现在所有程序的默认麦克风都是虚拟声卡了。"
                  "LiveDub 的「采集=麦克风」请显式选真实麦克风，否则会抓到自己译文的回声。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
