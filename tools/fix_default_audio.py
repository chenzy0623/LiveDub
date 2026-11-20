"""把 Windows 默认播放设备改回真实扬声器/耳机。

装完 VB-CABLE 后，Windows 常把默认播放设备切成「CABLE Input」，
结果就是系统声音全进了虚拟声卡、用户什么也听不到。这个小工具就是用来一键改回去的。

用法：
    python tools/fix_default_audio.py                 # 列出所有播放设备
    python tools/fix_default_audio.py --name 扬声器    # 按名字片段设为默认
"""
from __future__ import annotations

import argparse
import sys

from pycaw.utils import AudioUtilities


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="", help="设备名片段；留空则只列出")
    args = ap.parse_args()

    devs = [d for d in AudioUtilities.GetAllDevices() if getattr(d, "id", "")]
    print("当前播放/录音端点：")
    for d in devs:
        print(f"  {d.FriendlyName}")

    if not args.name:
        return 0

    want = args.name.lower()
    target = next((d for d in devs if want in d.FriendlyName.lower()
                   and "cable" not in d.FriendlyName.lower()), None)
    if target is None:
        print(f"没找到名字包含 {args.name!r} 的设备")
        return 1

    from pycaw.constants import ERole
    AudioUtilities.SetDefaultDevice(
        target.id, [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])
    print(f"已把默认播放设备设为：{target.FriendlyName}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
