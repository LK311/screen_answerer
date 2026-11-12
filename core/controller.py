# -*- coding: utf-8 -*-
"""控制器（单队列分发,跨线程安全）：热键/托盘线程入队,主线程 root.after 轮询执行。"""
import queue
import threading

import tkinter as tk

import keyboard
import mouse

from core.appconfig import config, logger, save_region
from core.i18n import t
from win32.hotkey_capture import _MOUSE_BUTTONS
from core.monitor import capture_region, MonitorWorker
from core.llmclient import ask_llm
from core.artifacts import save_artifacts
from ui.overlaywin import Overlay
from ui.regionselector import RegionSelector
from ui.settingsui import SettingsDialog

# ------------------------- 控制器（单队列分发,跨线程安全） -------------------------
class Controller:
    """keyboard 钩子线程与 pystray 托盘线程只往队列投递请求,
    主线程 root.after 轮询队列执行所有界面动作。"""

    def __init__(self, root: tk.Tk, overlay: Overlay, worker: MonitorWorker,
                 rect_indicator=None, q: queue.Queue = None):
        self.root = root
        self.overlay = overlay
        self.worker = worker
        self.rect_indicator = rect_indicator
        # 浮窗被拖动/缩放后同步设置窗口输入框（防「应用并保存」用旧值覆盖回退）
        overlay.on_geometry_changed = self._sync_overlay_geometry
        self.taskbar_text = None  # 任务栏文本条（main() 装配后回填；回答展示方式之二）
        # 矩形框运行时显隐状态（REGION_RECT_SHOW 仅作为启动默认值）
        self._rect_visible = bool(config.REGION_RECT_SHOW)
        self.q = q if q is not None else queue.Queue()
        self._stopping = False
        # 运行时热键管理（设置窗口可改键）
        self._hotkey_handles = []   # [(combo, handle)]
        self._hotkey_map = {}       # {combo: action}
        self.settings_win = None    # SettingsDialog 引用（防重复打开）
        self.tray_icon = None       # pystray.Icon（main() 装配后回填；改键后需 update_menu）

    # ---- 线程入口（仅入队） ----
    def submit(self, name: str):
        self.q.put(("action", name))

    def push_answer(self, text: str):
        self.q.put(("answer", text))

    def _set_answer_ui(self, text: str):
        """把回答送到当前展示模式对应的窗口（主线程调用）。"""
        if config.ANSWER_MODE == "taskbar" and self.taskbar_text is not None:
            self.taskbar_text.set_answer(text)
        else:
            self.overlay.set_answer(text)

    # ---- 主线程轮询 ----
    def poll(self):
        self._drain()
        if not self._stopping:
            self.root.after(100, self.poll)  # 100ms 轮询足够灵敏且降低空转开销

    def _drain(self):
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                return
            if kind == "answer":
                self._set_answer_ui(payload)
            elif payload == "__quit__":
                self._stopping = True
                self.root.after(0, self.root.destroy)
                return
            else:
                fn = {
                    "select_region": self.select_region,
                    "manual_trigger": self.manual_trigger,
                    "toggle_monitor": self.toggle_monitor,
                    "toggle_overlay": self.toggle_overlay,
                    "toggle_rect": self.toggle_rect,
                    "open_settings": self.open_settings,
                }.get(payload)
                if fn:
                    fn()

    # ---- Ctrl+Shift+F1：选择区域 ----
    def _sync_overlay_geometry(self):
        """浮窗拖动/缩放后,把新几何回填到开着的设置窗口（不存在则无操作）。"""
        sw = self.settings_win
        if sw is not None and sw.win.winfo_exists():
            sw.refresh_overlay_vars()

    def select_region(self):
        logger.info(t("开始框选监控区域"))
        self.overlay.hide()
        if self.rect_indicator is not None:
            self.rect_indicator.hide()
        self._selector = RegionSelector(self._on_region_selected, self._on_region_cancelled)

    def _on_region_selected(self, region):
        save_region(region)
        self.worker.reset_baseline()
        if self.rect_indicator is not None:
            self.rect_indicator.update_region()
            if self._rect_visible:
                self.rect_indicator.show()
        # 设置窗口开着时同步回填其区域输入框——否则窗口里的旧值会在
        # 「应用并保存」时把刚框选的区域覆盖回退
        sw = self.settings_win
        if sw is not None and sw.win.winfo_exists():
            sw.refresh_region_vars()
        self.overlay.show()
        self.overlay.set_answer(t("[区域已更新] {region}").format(region=region))

    def _on_region_cancelled(self):
        if self.rect_indicator is not None and self._rect_visible:
            self.rect_indicator.show()
        self.overlay.show()

    # ---- Ctrl+Shift+F2：手动触发一次截图+回答 ----
    def manual_trigger(self):
        logger.info(t("手动触发回答"))
        self._set_answer_ui("...")
        threading.Thread(target=self._do_manual, daemon=True).start()

    def _do_manual(self):
        try:
            img = capture_region()
            ans = ask_llm(img)
            try:
                save_artifacts(img, ans)
            except Exception as e:  # noqa: BLE001
                logger.warning(t("保存分析记录失败: %s"), e)
        except Exception as e:  # noqa: BLE001
            ans = t("[手动捕获错误] {err}").format(err=e)
        self.push_answer(ans)

    # ---- Ctrl+Shift+F3：暂停/恢复定时监控 ----
    def toggle_monitor(self):
        paused = self.worker.toggle_paused()
        logger.info(t("定时监控 %s"), t("暂停") if paused else t("恢复"))
        self._set_answer_ui(t("[定时监控已暂停]") if paused else t("[定时监控已恢复]"))

    # ---- Ctrl+Shift+F4：隐藏/显示回答 ----
    def toggle_overlay(self):
        if config.ANSWER_MODE == "taskbar" and self.taskbar_text is not None:
            self.taskbar_text.toggle()
            logger.info(t("回答展示（任务栏文本条） %s"),
                        t("显示") if self.taskbar_text.is_visible() else t("隐藏"))
        else:
            self.overlay.toggle()
            logger.info(t("桌面浮窗 %s"),
                        t("显示") if self.overlay.is_visible() else t("隐藏"))

    # ---- Ctrl+Shift+F5：隐藏/显示监控区域矩形指示框 ----
    def toggle_rect(self):
        if self.rect_indicator is None:
            return
        self._rect_visible = not self._rect_visible
        logger.info(t("区域指示框 %s"), t("显示") if self._rect_visible else t("隐藏"))
        if self._rect_visible:
            self.rect_indicator.update_region()  # 显示前对齐当前 REGION,防止期间区域已改
            self.rect_indicator.show()
            self._set_answer_ui(t("[区域指示框已显示]"))
        else:
            self.rect_indicator.hide()
            self._set_answer_ui(t("[区域指示框已隐藏]"))

    # ---- 运行时热键管理（设置窗口改键用） ----
    @staticmethod
    def _remove_hotkey_handle(kind: str, handle, combo: str = ""):
        try:
            if kind == "mouse":
                mouse.unhook(handle)
            else:
                keyboard.remove_hotkey(handle)
        except Exception as e:  # noqa: BLE001
            logger.warning(t("移除热键 %s 失败: %s"), combo, e)

    def _register_hotkey_handle(self, combo: str, action: str):
        """注册单个热键,返回 (kind, handle)。

        纯键盘组合走 keyboard.add_hotkey；含鼠标段（mouse_*）的组合走
        mouse 全局钩子：匹配到目标按键按下且全部键盘修饰键处于按下状态时
        触发动作（鼠标事件无法抑制,点击会透传给当前窗口）。"""
        parts = [p for p in combo.split("+") if p]
        mouse_btn = next((p[len("mouse_"):] for p in parts if p.startswith("mouse_")), None)
        if mouse_btn is None:
            return "keyboard", keyboard.add_hotkey(combo, lambda a=action: self.submit(a))
        if mouse_btn not in _MOUSE_BUTTONS:
            raise ValueError(t("未知鼠标按键: {combo}").format(combo=combo))
        kb_mods = tuple(p for p in parts if not p.startswith("mouse_"))

        def _on_mouse(event, btn=mouse_btn, mods=kb_mods, a=action):
            # mouse.hook 会推送全部鼠标事件（MoveEvent/WheelEvent/ButtonEvent）,
            # 必须先按类型过滤——MoveEvent/WheelEvent 没有 event_type 属性
            if (not isinstance(event, mouse.ButtonEvent)
                    or event.event_type != mouse.DOWN or event.button != btn):
                return
            try:
                if all(keyboard.is_pressed(m) for m in mods):
                    self.submit(a)
            except Exception:  # noqa: BLE001
                pass

        mouse.hook(_on_mouse)
        return "mouse", _on_mouse

    def rebuild_hotkeys(self, combo_map) -> str | None:
        """重建全部全局热键。combo_map: {combo: action}（可含鼠标组合键）。

        先注册新键,全部成功才移除旧键；任一新键注册失败则回滚并保留旧键位。
        键位映射与当前完全一致时直接跳过（不重建、不刷日志、不重建托盘菜单）。
        成功返回 None,失败返回错误信息。"""
        combo_map = dict(combo_map)
        # suspend_hotkeys 会同时清空 _hotkey_map 与 _hotkey_handles,
        # 因此"映射一致且句柄非空"才视为未变化；录入恢复路径不受影响
        if combo_map == self._hotkey_map and self._hotkey_handles:
            return None
        new_handles = []  # [(combo, kind, handle)]
        try:
            for combo, action in combo_map.items():
                if not combo:  # 清除后的空键位：不注册
                    continue
                kind, handle = self._register_hotkey_handle(combo, action)
                new_handles.append((combo, kind, handle))
        except Exception as e:  # noqa: BLE001
            for combo, kind, handle in new_handles:
                self._remove_hotkey_handle(kind, handle, combo)
            return str(e)
        for combo, kind, handle in self._hotkey_handles:
            self._remove_hotkey_handle(kind, handle, combo)
        self._hotkey_handles = new_handles
        self._hotkey_map = dict(combo_map)
        logger.info(t("热键已更新: %s"),
                    " / ".join(c for c, _, _ in new_handles) or t("（全部未绑定）"))
        # pystray Win32 缓存菜单句柄,callable 标签只在创建时求值；
        # 键位变了必须显式重建菜单,否则托盘右键仍显示旧键位
        if self.tray_icon is not None:
            try:
                self.tray_icon.update_menu()
            except Exception as e:  # noqa: BLE001
                logger.warning(t("托盘菜单刷新失败: %s"), e)
        return None

    def combo_of(self, action: str) -> str:
        """托盘菜单标签用：返回动作当前绑定的键位（未绑定为「未设置」）。"""
        return next((c for c, a in self._hotkey_map.items() if a == action), t("未设置"))

    def suspend_hotkeys(self):
        """录入期间临时移除全部已注册热键,防止按下的组合键误触发动作。"""
        for combo, kind, handle in self._hotkey_handles:
            self._remove_hotkey_handle(kind, handle, combo)
        self._hotkey_handles = []
        self._hotkey_map = {}

    def restore_hotkeys(self):
        """按当前 config 键位重新注册（录入结束/取消后恢复）。"""
        combo_map = {}
        for attr, action, _ in SettingsDialog._HOTKEY_ACTIONS:
            combo = str(getattr(config, attr, "") or "").strip().lower()
            if combo:
                combo_map[combo] = action
        return self.rebuild_hotkeys(combo_map)

    # ---- 托盘「设置…」入口 ----
    def open_settings(self):
        logger.info(t("打开设置窗口"))
        # 单实例：已存在则置顶显示（SettingsDialog 非 Tk 控件,其 winfo_exists/
        # deiconify 在 .win 子窗口上——此前误调在对话框自身上,AttributeError
        # 被 except 吞掉,导致每次点击都新建出多个设置窗口）
        sw = self.settings_win
        if sw is not None:
            try:
                if sw.win.winfo_exists():
                    sw.win.deiconify()
                    sw.win.lift()
                    sw.win.focus_force()
                    return
            except tk.TclError:  # 窗口已销毁等异常状态：走重建
                pass
        self.settings_win = SettingsDialog(self.root, self)
