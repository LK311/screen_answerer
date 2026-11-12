# -*- coding: utf-8 -*-
"""监控区域矩形指示框（单分层窗口直绘边框）。"""
import tkinter as tk

from PIL import Image, ImageDraw

from core.appconfig import config, logger, _clamp01
from win32.win32util import set_layer_flags, push_layered_image, _get_top_hwnd
from core.imagerender import _hex_to_rgb

# ------------------------- 监控区域矩形指示框 -------------------------
class RegionRectIndicator:
    """单个分层窗口内直接绘制监控区域矩形边框（UpdateLayeredWindow 逐像素 alpha）。

    早期方案是 4 条细边小窗口拼接（规避 tkinter -transparentcolor 与 -alpha
    冲突、以及大面积键色窗口的 DWM 色键合成开销）。现复用 Overlay 已验证的
    ULW 基础设施：一个窗口覆盖整个监控区域,PIL 只把边框像素画成
    REGION_RECT_COLOR（alpha = REGION_RECT_ALPHA）,内部像素 alpha=0 全透明,
    一次推送即成矩形框。窗口数量 4 -> 1,语义直观；
    鼠标穿透 / 置顶 / 周期自愈与 Overlay 保持同一套逻辑。
    """

    THICK = 2  # 边框厚度（物理像素）

    def __init__(self):
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)   # 无边框 + 不进任务栏
        self.win.attributes("-topmost", True)
        self.win.configure(bg=config.REGION_RECT_COLOR)
        # Toplevel 默认创建即映射显示；必须先隐藏,否则在
        # REGION_RECT_SHOW=false 时不走 show(),会以默认几何错误显示
        self.win.withdraw()
        # 首次映射时顶层包装窗口才创建且样式可能被 Tk 重写,映射后立即重推
        self.win.bind("<Map>", self._on_map)
        self.win.after(500, self._self_heal)

    def _on_map(self, _event=None):
        set_layer_flags(self.win, True)
        self._push()

    @property
    def strips(self):
        # 兼容旧测试/调用点：单窗口语义下返回 [self.win]
        return [self.win]

    def _render(self) -> Image.Image:
        """渲染矩形边框 RGBA 位图：仅边框像素有 alpha,内部全透明。"""
        _, _, w, h = (int(v) for v in config.REGION)
        r, g, b = _hex_to_rgb(config.REGION_RECT_COLOR)
        a = int(round(_clamp01(config.REGION_RECT_ALPHA) * 255))
        img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)  # RGBA 图上默认替换像素（不混合）,alpha 精确可控
        d.rectangle([0, 0, w - 1, h - 1], outline=(r, g, b, a), width=self.THICK)
        return img

    def _push(self):
        """按当前 REGION 设置窗口几何并重绘边框内容。"""
        try:
            left, top, w, h = (int(v) for v in config.REGION)
            self.win.geometry(f"{w}x{h}+{left}+{top}")
            push_layered_image(_get_top_hwnd(self.win), self._render(), left, top)
        except Exception as e:  # noqa: BLE001
            logger.warning("区域框绘制失败: %s", e)

    def _self_heal(self):
        """周期性自愈：Tk 映射/几何变化时会清掉 LAYERED/TRANSPARENT 样式位
        （见 Overlay._self_heal）,仅在检测到被重写时重推内容。"""
        if self.is_visible():
            if set_layer_flags(self.win, True):
                logger.info("检测到区域框样式被外部重写,已自愈")
                self._push()
        self.win.after(500, self._self_heal)

    def update_region(self):
        """Ctrl+Shift+F1 框选新区域后调用：移动/缩放并重绘矩形框。"""
        self._push()

    def show(self):
        self.win.deiconify()
        # withdraw->deiconify 后置顶属性偶发丢失,重新断言
        self.win.attributes("-topmost", True)
        self.win.lift()
        # 显式落定分层样式 + 鼠标穿透,并重绘边框
        set_layer_flags(self.win, True)
        self._push()

    def hide(self):
        self.win.withdraw()

    def is_visible(self):
        return self.win.state() != "withdrawn"
