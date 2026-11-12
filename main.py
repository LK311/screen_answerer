# -*- coding: utf-8 -*-
"""
桌面智能监控回答程序 - 主程序（tkinter + pystray 轻量版,替代 PySide6 以减小打包体积）
流程：定时截屏 -> dHash 变化检测 -> 冷却后调用视觉大模型 -> 回答展示
（「桌面浮窗」半透明穿透浮窗,或「任务栏文本条」停靠屏幕底部任务栏上方,
可在设置窗口选择展示方式）。

配置：settings.json（程序同目录,首次启动自动生成默认值）。所有配置均可在托盘右键
     「设置…」窗口修改并持久生效,框选监控区域也会自动持久化。
日志：每次启动自动重置日志文件（覆盖写入）,同时输出到控制台。

快捷键（设置窗口「快捷键」页点「录入」按键自动录入,或手改 settings.json）：
  select_region    选择监控的桌面区域（拖拽框选,自动持久化）
  manual_trigger   手动触发一次区域截屏与回答
  toggle_monitor   禁用 / 启动 定时截屏 + 变化检测
  toggle_overlay   隐藏 / 显示 回答（浮窗或任务栏文本条,按展示方式）
  toggle_rect      隐藏 / 显示 监控区域矩形指示框
支持键盘组合键与鼠标按键热键（mouse_left/right/middle/x/x2,可叠加键盘
修饰键,如 ctrl+mouse_x2；鼠标点击无法拦截,会透传给当前窗口）。
「清除」可清空键位,应用后该功能不再绑定快捷键（托盘菜单仍可触发）。

依赖：pip install mss Pillow requests keyboard pystray （tkinter 为标准库自带）
运行：python main.py

目录结构（分层归组，本文件为薄入口：入口 main() + 兼容测试/外部引用的再导出）：
  core/    业务核心（appconfig 配置与日志 / monitor 截屏与变化检测 /
           llmclient 大模型调用 / imagerender 渲染 / artifacts 分析记录 /
           controller 控制器）
  ui/      展示层（overlaywin 浮窗 / taskbarwin 任务栏文本条 /
           rectindicator 指示框 / regionselector 框选 / settingsui 设置窗口 /
           trayicon 托盘）
  win32/   Windows 平台层（win32util 分层窗口与任务栏工具 /
           hotkey_capture 组合键录入）
  tests/   测试（python tests/test_main.py）
  assets/  打包资源（图标、版本信息）
"""
import ctypes
import ctypes.wintypes  # noqa: F401  测试经 main.ctypes.wintypes 使用
import queue
import threading

import tkinter as tk

import keyboard  # noqa: F401  测试经 main.keyboard 使用
import mouse  # noqa: F401  测试经 main.mouse 使用

from core import appconfig  # noqa: F401  测试打补丁入口（main.appconfig.SETTINGS_FILE）
from core import monitor  # noqa: F401  测试打补丁入口（main.monitor.ask_llm）
from core.i18n import t  # noqa: F401  再导出兼容（状态/日志文案翻译）

# ---- 兼容再导出（测试与外部引用经 main.X 使用,内部未直接引用属预期） ----
from core.appconfig import (  # noqa: F401
    config, logger, setup_logging, _DEFAULT_SETTINGS,
    save_config, load_config, save_region, APP_VERSION, GITHUB_URL)
from core.monitor import capture_region, dhash, hamming, MonitorWorker  # noqa: F401
from core.llmclient import ask_llm, _HTTP_SESSION  # noqa: F401
from core.imagerender import (  # noqa: F401
    _hex_to_rgb, _load_overlay_font, _wrap_text, render_answer_image, overlay_pages)
from core.artifacts import save_artifacts  # noqa: F401
from core.controller import Controller  # noqa: F401
from win32.hotkey_capture import _canonical_modifier, capture_hotkey_once  # noqa: F401
from win32.win32util import (  # noqa: F401
    _work_area, _find_taskbar, _get_top_hwnd, _set_layer_flags_hwnd, _premultiply)
from ui.overlaywin import Overlay  # noqa: F401
from ui.taskbarwin import _TASKBAR_POSITIONS, TaskbarText  # noqa: F401
from ui.rectindicator import RegionRectIndicator  # noqa: F401
from ui.regionselector import RegionSelector  # noqa: F401
from ui.settingsui import SettingsDialog  # noqa: F401
from ui.trayicon import build_tray  # noqa: F401

# ------------------------- 入口 -------------------------
def _enable_dpi_awareness():
    """让进程 DPI 感知：tkinter 坐标 = 物理像素,与 mss 截屏坐标体系一致。
    不设置时,在 125%/150% 缩放的屏幕上所有窗口坐标会被系统虚拟化放大,
    导致矩形框/浮窗/框选位置整体错位。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def main():
    _enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()  # 主窗口仅作事件循环载体,不显示；托盘常驻

    answers = queue.Queue()
    overlay = Overlay()
    taskbar = TaskbarText()
    if config.ANSWER_MODE == "taskbar":
        overlay.hide()
        if not config.OVERLAY_START_HIDDEN:
            taskbar.show()
    else:
        if config.OVERLAY_START_HIDDEN:
            overlay.hide()

    worker = MonitorWorker(answers)
    if config.MONITOR_START_PAUSED:
        worker.toggle_paused()
    worker.start()

    rect = RegionRectIndicator()
    if config.REGION_RECT_SHOW:
        rect.show()

    controller = Controller(root, overlay, worker, rect_indicator=rect, q=answers)
    controller.taskbar_text = taskbar
    controller.poll()

    # 键位来自 settings.json；运行时可在「设置…」窗口按键录入并实时生效（空键位不注册）
    hotkeys = {
        config.SELECT_REGION_HOTKEY: "select_region",
        config.MANUAL_TRIGGER_HOTKEY: "manual_trigger",
        config.TOGGLE_MONITOR_HOTKEY: "toggle_monitor",
        config.TOGGLE_OVERLAY_HOTKEY: "toggle_overlay",
        config.TOGGLE_RECT_HOTKEY: "toggle_rect",
    }
    err = controller.rebuild_hotkeys({c: a for c, a in hotkeys.items() if c})
    if err:
        logger.warning(t("部分热键注册失败: %s"), err)

    tray = build_tray(controller)
    controller.tray_icon = tray  # 改键后 rebuild_hotkeys 会调用 tray.update_menu()
    threading.Thread(target=tray.run, daemon=True).start()

    if config.MONITOR_START_PAUSED:
        overlay.set_answer(t("[定时监控已暂停]"))

    logger.info(
        t("已启动（托盘常驻）。键位可在托盘设置窗口修改（持久化于 settings.json）。")
    )
    try:
        root.mainloop()
    finally:
        worker.stop()
        try:
            tray.stop()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()

