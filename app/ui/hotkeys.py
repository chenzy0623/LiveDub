"""全局热键（Windows RegisterHotKey），线程内跑消息循环。

用于：玩游戏/全屏看电影时不用切窗口就能开关同传、显隐字幕。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import threading

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN, "cmd": MOD_WIN}

_VK = {**{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
       **{str(d): 0x30 + d for d in range(10)}}
_VK.update({"f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
            "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
            "f11": 0x7A, "f12": 0x7B, "space": 0x20, "esc": 0x1B})


def parse(accel: str) -> tuple[int, int] | None:
    """'ctrl+alt+s' → (modifiers, vk)"""
    parts = [p.strip().lower() for p in (accel or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    vk = 0
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        else:
            vk = _VK.get(p.upper() if len(p) == 1 else p, 0)
    if not vk or not mods:
        return None
    return mods, vk


class GlobalHotkeys:
    """注册若干全局热键，命中后把名字放进 events 队列。"""

    def __init__(self, events: "queue.Queue[str]"):
        self.events = events
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ids: list[int] = []
        self._names: dict[int, str] = {}
        self.ok = False

    def start(self, mapping: dict[str, str]) -> None:
        """mapping: {'toggle': 'ctrl+alt+s', 'overlay': 'ctrl+alt+h'}"""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(dict(mapping),),
                                        name="hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, mapping: dict[str, str]) -> None:
        user32 = ctypes.windll.user32
        hid = 0xB000
        for name, acc in mapping.items():
            p = parse(acc)
            if not p:
                continue
            hid += 1
            if user32.RegisterHotKey(None, hid, p[0], p[1]):
                self._ids.append(hid)
                self._names[hid] = name
                self.ok = True
        try:
            msg = wt.MSG()
            while not self._stop.is_set():
                r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if r:
                    if msg.message == WM_HOTKEY:
                        n = self._names.get(int(msg.wParam))
                        if n:
                            try:
                                self.events.put_nowait(n)
                            except Exception:
                                pass
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    self._stop.wait(0.05)
        finally:
            for hid in self._ids:
                try:
                    user32.UnregisterHotKey(None, hid)
                except Exception:
                    pass
            self._ids.clear()
