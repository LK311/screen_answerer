# -*- coding: utf-8 -*-
"""程序图标（PIL 程序化生成）与托盘（pystray,程序无任务栏图标）。"""
import pystray
from PIL import Image, ImageDraw, ImageFont

from core.controller import Controller
from core.i18n import t

# ------------------------- 程序图标（PIL 程序化生成,供托盘使用） -------------------------
def make_app_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(45, 125, 255, 255))
    try:
        f = ImageFont.truetype("arial.ttf", 34)
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
    d.text((32, 33), "A", font=f, fill="white", anchor="mm")
    return img


# ------------------------- 托盘图标（pystray,程序无任务栏图标） -------------------------
def build_tray(controller: Controller) -> pystray.Icon:
    def _quit(icon, item):
        controller.worker.stop()
        controller.submit("__quit__")
        icon.stop()

    # 全部快捷操作直留托盘（文本用 callable：pystray 每次弹出菜单时求值,改键后标签自动跟随）
    menu = pystray.Menu(
        pystray.MenuItem(
            lambda it: f"{t('显示/隐藏桌面浮窗')} ({controller.combo_of('toggle_overlay')})",
            lambda ic, it: controller.submit("toggle_overlay"), default=True),
        pystray.MenuItem(
            lambda it: f"{t('暂停/恢复定时监控')} ({controller.combo_of('toggle_monitor')})",
            lambda ic, it: controller.submit("toggle_monitor")),
        pystray.MenuItem(
            lambda it: f"{t('手动回答')} ({controller.combo_of('manual_trigger')})",
            lambda ic, it: controller.submit("manual_trigger")),
        pystray.MenuItem(
            lambda it: f"{t('框选监控区域')} ({controller.combo_of('select_region')})",
            lambda ic, it: controller.submit("select_region")),
        pystray.MenuItem(
            lambda it: f"{t('显示/隐藏区域指示框')} ({controller.combo_of('toggle_rect')})",
            lambda ic, it: controller.submit("toggle_rect")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("设置"),
                         lambda ic, it: controller.submit("open_settings")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("退出"), _quit),
    )
    icon = pystray.Icon("screen_answerer", make_app_icon_image(), t("桌面智能监控回答"), menu)
    return icon
