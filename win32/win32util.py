# -*- coding: utf-8 -*-
"""Win32 工具集：工作区/任务栏查询、分层窗口样式、UpdateLayeredWindow 逐像素推送。"""
import ctypes
import ctypes.wintypes

from PIL import Image

from core.appconfig import logger, _clamp01

def _work_area() -> tuple:
    """主显示器工作区（不含任务栏）,返回 (left, top, right, bottom)。"""
    rect = ctypes.wintypes.RECT()
    SPI_GETWORKAREA = 0x0048
    try:
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:  # noqa: BLE001
        pass
    user32 = ctypes.windll.user32
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _find_taskbar() -> dict | None:
    """查找系统任务栏窗口信息（TrafficMonitor 同款做法）。

    返回 {"hwnd": Shell_TrayWnd 句柄, "cw": 客户区宽, "ch": 客户区高,
          "notify_left": 通知区(TrayNotifyWnd)左缘在客户区中的 x 坐标}；
    找不到（异常桌面环境/explorer 未就绪）返回 None。"""
    try:
        user32 = ctypes.windll.user32
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return None
        wrect = ctypes.wintypes.RECT()
        crect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(tray, ctypes.byref(wrect)) or \
                not user32.GetClientRect(tray, ctypes.byref(crect)):
            return None
        # 客户区原点（屏幕坐标）,任务栏通常无边框,一般为 0
        ox = wrect.left + crect.left
        oy = wrect.top + crect.top
        notify = user32.FindWindowExW(tray, None, "TrayNotifyWnd", None)
        if notify:
            nrect = ctypes.wintypes.RECT()
            if not user32.GetWindowRect(notify, ctypes.byref(nrect)):
                notify = None
            else:
                notify_left = nrect.left - ox
        if not notify:
            notify_left = crect.right - 16  # 兜底：贴任务栏右缘
        return {"hwnd": tray, "cw": crect.right, "ch": crect.bottom,
                "notify_left": max(0, notify_left), "left": ox, "top": oy}
    except Exception:  # noqa: BLE001
        return None


def _taskbar_geom_for(pos: str, w: int, h: int):
    """计算文本条窗口目标位置。

    taskbar-right：返回**父窗口客户区相对坐标**（子窗口 SetWindowPos 语义）——
    贴托盘通知区左缘右侧、任务栏内垂直居中。注意绝不能混入任务栏的屏幕
    坐标 top/left：子窗口坐标以 Shell_TrayWnd 客户区 (0,0) 为起点,混入
    屏幕坐标会把窗口推到可视区外被裁剪（此坑实测发生过）。
    任务栏暂时不可用时返回 None（等待自愈定时器重试）。
    bottom-*/top-*：窗口为无父顶层窗口,返回屏幕坐标,停靠工作区边缘。"""
    if pos == "taskbar-right":
        tb = _find_taskbar()
        if not tb:
            return None
        x = max(8, tb["notify_left"] - w - 4)
        y = max(0, (tb["ch"] - h) // 2)
        return x, y
    L, T, R, B = _work_area()
    y = T if pos.startswith("top") else B - h
    if pos.endswith("left"):
        x = L + 8
    elif pos.endswith("right"):
        x = R - w - 8
    else:
        x = L + ((R - L) - w) // 2
    return x, y


# ------------------------- 共用：窗口渲染样式（分层透明 + 鼠标穿透） -------------------------
def apply_window_render_style(widget, alpha: float, click_through: bool):
    """在 Win32 层显式统一设置顶层窗口的「分层样式 + 透明度属性 +（可选）鼠标穿透」。

    背景：本机实测发现,仅依赖 tkinter 的 -alpha/-transparentcolor 时,启动线程
    较多（键盘钩子/托盘/截屏线程并存）存在渲染竞态——窗口已映射（IsWindowVisible=
    True、命中测试可命中）但 GDI 内容从未落盘,表现为"完全透明/不可见"。
    此函数在窗口映射后直接调 SetLayeredWindowAttributes 落定分层属性,
    并在每次 show 后重复调用以自愈状态漂移。

    注意：tkinter 的 winfo_id 是内部子窗口 HWND,真正的顶层 HWND 需取 GetParent。
    """
    try:
        hwnd = widget.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        LWA_ALPHA = 0x00000002
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        new_style = style | WS_EX_LAYERED
        if click_through:
            new_style |= WS_EX_TRANSPARENT
        else:
            new_style &= ~WS_EX_TRANSPARENT  # 取消穿透须显式清位
        if new_style != style:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        # 每次都显式落定透明度：保证"分层样式"与"分层属性"永远成对生效
        user32.SetLayeredWindowAttributes(hwnd, 0, int(round(_clamp01(alpha) * 255)), LWA_ALPHA)
    except Exception as e:  # noqa: BLE001
        logger.warning("窗口渲染样式设置失败（将尝试保持默认行为）: %s", e)


# ------------------------- 分层窗口逐像素内容推送（UpdateLayeredWindow） -------------------------
class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def _get_top_hwnd(widget) -> int:
    """tkinter 的 winfo_id 是内部子窗口 HWND,真正的顶层 HWND 需取 GetParent。"""
    hwnd = widget.winfo_id()
    parent = ctypes.windll.user32.GetParent(hwnd)
    return parent if parent else hwnd


def _set_layer_flags_hwnd(hwnd: int, click_through: bool) -> bool:
    """对指定 HWND 设置 WS_EX_LAYERED,并按 click_through 增删
    WS_EX_TRANSPARENT（鼠标穿透）位。

    返回样式位是否因此发生了变化。Tk 在窗口映射/几何变化时会用自己记录的
    exstyle 重写窗口样式（实测会清掉我们设置的 LAYERED/TRANSPARENT 位）,
    因此需要周期性重新断言（见 Overlay._self_heal）。

    注意：click_through=False 时必须显式**清除** TRANSPARENT 位——只置位
    不清位会导致勾选过一次穿透后永远穿透、取消勾选无效（实测踩过）。"""
    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        new_style = style | WS_EX_LAYERED
        if click_through:
            new_style |= WS_EX_TRANSPARENT
        else:
            new_style &= ~WS_EX_TRANSPARENT
        if new_style != style:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("分层样式设置失败（穿透/透明可能不生效）: %s", e)
        return False


def set_layer_flags(widget, click_through: bool) -> bool:
    """为顶层窗口设置 WS_EX_LAYERED（+可选 WS_EX_TRANSPARENT 鼠标穿透）。"""
    try:
        return _set_layer_flags_hwnd(_get_top_hwnd(widget), click_through)
    except Exception as e:  # noqa: BLE001
        logger.warning("分层样式设置失败（穿透/透明可能不生效）: %s", e)
        return False


def _premultiply(img: Image.Image) -> bytes:
    """RGBA 图像 -> 预乘 alpha 的 BGRA 字节流（UpdateLayeredWindow 的要求）。"""
    img = img.convert("RGBA")
    from PIL import ImageChops
    r, g, b, a = img.split()
    # 逐通道乘以 alpha（ImageChops.multiply = a*b/255）,得到预乘结果
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    # 合并为 B,G,R,A 通道序（DIB 32bpp 为 BGRA 内存布局）
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


def push_layered_image(hwnd: int, img: Image.Image, x: int = None, y: int = None):
    """把 RGBA 图像作为分层窗口的逐像素内容推送到屏幕。

    x/y 为窗口目标位置（屏幕坐标）；传 None 则保持当前位置不动
    （嵌入任务栏的子窗口模式：位置先经 SetWindowPos 以父窗口客户区
    坐标设置,此处不再由 ULW 指定坐标）。

    背景/文字各自的不透明度已在图像 alpha 通道中体现；相比 tkinter 的
    整窗 -alpha,此法可实现任意像素级透明度,且内容不依赖 Tk 自绘,
    对"窗口已映射但内容从未落盘"的渲染竞态天然免疫。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    w, h = img.size
    raw = _premultiply(img)

    # ULW 硬性要求目标窗口带 WS_EX_LAYERED,否则返回 FALSE 且 GetLastError()=87。
    # Tk 在映射/几何变化时会重写窗口样式（可能清掉该位）,且映射前后真正生效的
    # HWND 会变（顶层包装窗口在首次映射时才创建）,因此必须在推送前对目标
    # hwnd 现场断言一次（幂等,已带该位则零开销）。
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if not ex_style & WS_EX_LAYERED:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)

    hdc_screen = user32.GetDC(0)
    mem_dc = None
    hbmp = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(hdc_screen)
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # 负值 = 自上而下的行序
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        ppbits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(ppbits), None, 0
        )
        if not hbmp or not ppbits:
            raise OSError(f"CreateDIBSection 失败 err={ctypes.GetLastError()}")
        ctypes.memmove(ppbits, raw, len(raw))
        old_bmp = gdi32.SelectObject(mem_dc, hbmp)

        pt_dst = ctypes.wintypes.POINT(x, y) if x is not None and y is not None else None
        pt_src = ctypes.wintypes.POINT(0, 0)
        size = _SIZE(w, h)
        blend = _BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER + AC_SRC_ALPHA（用图像自带 alpha）
        ok = user32.UpdateLayeredWindow(
            hwnd, hdc_screen, ctypes.byref(pt_dst) if pt_dst is not None else None,
            ctypes.byref(size),
            mem_dc, ctypes.byref(pt_src), 0, ctypes.byref(blend), 2,  # ULW_ALPHA
        )
        gdi32.SelectObject(mem_dc, old_bmp)
        if not ok:
            raise OSError(f"UpdateLayeredWindow 失败 err={ctypes.GetLastError()}")
    finally:
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, hdc_screen)
