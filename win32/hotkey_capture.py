# -*- coding: utf-8 -*-
"""组合键录入（替代 keyboard.read_hotkey 的缺陷实现）。"""
import time
import threading

import keyboard
import mouse

from core.appconfig import logger

# ------------------------- 组合键录入（替代 keyboard.read_hotkey） -------------------------
def _canonical_modifier(name: str) -> str | None:
    """把 keyboard 库的修饰键名归一化：left shift/right shift -> shift 等。
    非修饰键返回 None。"""
    n = str(name or "").strip().lower()
    if not n:
        return None
    for base in ("shift", "ctrl", "alt", "windows"):
        if n in (base, f"left {base}", f"right {base}"):
            return base
    return None


# 鼠标热键：组合键里的鼠标按键段（mouse_x = 侧键1,mouse_x2 = 侧键2）
_MOUSE_BUTTONS = ("left", "right", "middle", "x", "x2")


def capture_hotkey_once() -> str:
    """阻塞式捕获一个组合键（键盘或鼠标）,返回如 "shift+w" / "mouse_right" /
    "ctrl+mouse_x2" 的字符串；按 ESC 返回 "esc"。

    键盘部分不用 keyboard.read_hotkey：它在首个 KEY_UP 才返回,并用当时全部
    处于按下状态的键拼串（_pressed_events）,按住期间多按的任何键都会被并进
    结果（如按 shift+w 期间误触 z、f1,会得到 shift+w+z+f1）。本实现改为：
    捕获期间记录已按下的修饰键,第一个非修饰键 KEY_DOWN 到来即定型返回
    （不等释放）。

    鼠标部分用 mouse 库全局钩子：任意按键（左/右/中/侧键）按下即定型,
    叠加已按住的键盘修饰键。捕获开始后 0.3 秒内的鼠标事件被忽略,
    避免把点击「录入」按钮本身录进去。滚轮不作为热键录入。

    键盘事件捕获期间被抑制（不透传）；鼠标事件无法抑制（mouse 库不支持）,
    点击会同时透传给当前焦点窗口。注意 keyboard 库 blocking hook 的返回值
    语义：False = 抑制该事件（keyboard.KeyboardListener.direct_callback:
    `if not all(hook(event) for hook in self.blocking_hooks): return False`）,
    True 反而放行。"""
    mods = []
    result = {}
    done = threading.Event()
    start_t = time.time()

    def _key_handler(event):
        # 捕获期间键盘事件一律抑制（返回 False）,按键不透传给当前焦点窗口
        if event.event_type != keyboard.KEY_DOWN:
            return False
        name = str(event.name or "").strip().lower()
        if not name:
            return False
        mod = _canonical_modifier(name)
        if mod:
            if not done.is_set() and mod not in mods:
                mods.append(mod)
            return False
        if done.is_set():
            return False
        done.set()
        result["combo"] = "+".join(mods + [name])
        return False

    def _mouse_handler(event):
        if done.is_set():
            return
        if not isinstance(event, mouse.ButtonEvent) or event.event_type != mouse.DOWN:
            return  # 忽略移动/滚轮/抬起
        if time.time() - start_t < 0.3:
            return  # 保护期：忽略点击「录入」按钮本身的按下
        if event.button not in _MOUSE_BUTTONS:
            return
        done.set()
        result["combo"] = "+".join(mods + [f"mouse_{event.button}"])

    hooked = keyboard.hook(_key_handler, suppress=True)
    try:
        mouse.hook(_mouse_handler)
    except Exception as e:  # noqa: BLE001  鼠标钩子初始化失败则仅支持键盘录入
        logger.warning("鼠标钩子不可用,本次录入仅支持键盘: %s", e)
        _mouse_handler = None
    try:
        done.wait()  # 无超时：daemon 线程,退出随主进程
    finally:
        try:
            keyboard.unhook(hooked)
        except Exception:  # noqa: BLE001
            pass
        if _mouse_handler is not None:
            try:
                mouse.unhook(_mouse_handler)
            except Exception:  # noqa: BLE001
                pass
    return result.get("combo", "esc")
