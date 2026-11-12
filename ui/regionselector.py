# -*- coding: utf-8 -*-
"""区域选择浮层（全屏半透明遮罩 + 拖拽框选,ESC 取消）。"""
import ctypes

import tkinter as tk

# ------------------------- 区域选择浮层（Ctrl+Shift+F1） -------------------------
class RegionSelector:
    """全屏半透明遮罩 + 拖拽框选。ESC 取消。选区过小视为取消。"""

    def __init__(self, on_selected, on_cancelled=None):
        self.on_selected = on_selected
        self.on_cancelled = on_cancelled
        self._start = None
        user32 = ctypes.windll.user32
        x = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        y = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        w = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        h = user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.3)  # 遮罩变暗
        self.win.configure(bg="black")
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.win.bind("<Escape>", self._cancel)

    def _press(self, event):
        self._start = (event.x_root, event.y_root)

    def _drag(self, event):
        if self._start:
            self._draw(event.x_root, event.y_root)

    def _draw(self, gx, gy):
        wx, wy = self.win.winfo_rootx(), self.win.winfo_rooty()
        x0, y0 = self._start
        self.canvas.delete("sel")
        self.canvas.create_rectangle(x0 - wx, y0 - wy, gx - wx, gy - wy,
                                     outline="white", width=2, tags="sel")

    def _release(self, event):
        if not self._start:
            return
        x1, y1 = self._start
        x2, y2 = event.x_root, event.y_root
        self._start = None
        region = (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        self.win.destroy()
        if region[2] > 5 and region[3] > 5:
            self.on_selected(region)
        elif self.on_cancelled:
            self.on_cancelled()  # 选区过小视为取消,恢复被隐藏的窗口

    def _cancel(self, event=None):
        self._start = None
        self.win.destroy()
        if self.on_cancelled:
            self.on_cancelled()
