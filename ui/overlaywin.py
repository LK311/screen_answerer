# -*- coding: utf-8 -*-
"""桌面浮窗（逐像素透明分层窗口,无任务栏图标）。"""
import tkinter as tk

from core.appconfig import config, logger, save_config
from core.i18n import t
from win32.win32util import set_layer_flags, push_layered_image, _get_top_hwnd
from core.imagerender import (_load_overlay_font, render_answer_image, overlay_pages,
                              overlay_hit_index)

# ------------------------- 桌面浮窗（逐像素透明分层窗口,无任务栏图标） -------------------------
_OVER_GRIP = 18      # 右下角缩放热区边长（像素）
_OVER_MIN_W = 160    # 浮窗最小宽度
_OVER_MIN_H = 60     # 浮窗最小高度


class Overlay:
    """Win32 UpdateLayeredWindow 逐像素透明浮窗：背景与文字的颜色、透明度完全独立。

    背景：tkinter 的 -alpha 是整窗统一透明度,无法"背景透明度"与"文字透明度"
    分开；-transparentcolor 键色方案又与 alpha 组合不稳定。故用 PIL 把
    背景+文字画成 RGBA 位图（各自 alpha 通道）经 UpdateLayeredWindow 直推
    屏幕,绕开 Tk 自绘——透明度任意可控,且对"窗口已映射但内容从未落盘"
    的渲染竞态免疫（内容不经过 Tk 画布）。

    自动轮播仅在鼠标穿透模式下生效（OVERLAY_SCROLL_INTERVAL 秒/行）；
    非穿透模式下鼠标事件被浮窗接收,改由滚轮上下逐行滚动,不再自动轮播。

    交互（仅非穿透模式生效;穿透状态下鼠标事件直接穿过窗口,无法响应）：
    - 左键拖选文本：渲染反色高亮,右键菜单「复制所选」/ Ctrl+C 复制所选
    - Alt+左键拖动移动浮窗位置（松开后持久化到 settings.json）
    - 右下角拖拽缩放浮窗尺寸（实时同步设置,松开后持久化）
    - 右键菜单「复制回答全文」/ 左键双击复制回答全文
    """

    def __init__(self):
        self.win = tk.Toplevel()
        self.win.overrideredirect(True)  # 无边框 + 不进任务栏
        self.win.attributes("-topmost", True)
        self.win.configure(bg=config.OVERLAY_BG_COLOR)
        self.win.geometry(
            f"{config.OVERLAY_WIDTH}x{config.OVERLAY_HEIGHT}+{config.OVERLAY_X}+{config.OVERLAY_Y}"
        )
        self._text = t("等待监控...")
        self._font = _load_overlay_font()
        self._pages = overlay_pages(self._text, self._font)
        self._page = 0
        self._lines = []     # 当前滚动窗口的行列表（拖选命中测试用）
        self._sel = None     # 选区 ((行号,字符边界),(行号,字符边界))；None=无选区
        self._mode = None    # 当前手势: None / "move" / "select" / "resize"
        self._drag_off = None  # (按下点相对窗口左上角的偏移)
        self._tick_id = None
        self.on_geometry_changed = None  # 几何（拖动/缩放）变化后的回调（controller 注入,同步设置窗口）
        self._push()
        # 首次映射时顶层包装窗口才创建且样式可能被 Tk 重写,映射后立即重推
        self.win.bind("<Map>", self._on_map)
        self._bind_interactions()
        self._arm_tick()
        self.win.after(500, self._self_heal)

    def _on_map(self, _event=None):
        set_layer_flags(self.win, config.OVERLAY_CLICK_THROUGH)
        self._push()

    @property
    def text(self) -> str:
        return self._text

    @property
    def pages(self) -> list:
        return self._pages

    def _push(self):
        try:
            lines = self._pages[self._page] if self._pages else None
            self._lines = list(lines) if lines else []
            push_layered_image(
                _get_top_hwnd(self.win),
                render_answer_image(self._text, self._font, lines=lines, selection=self._sel),
                int(config.OVERLAY_X), int(config.OVERLAY_Y),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("浮窗内容推送失败: %s", e)

    def _self_heal(self):
        """周期性自愈：Tk 映射/几何变化时会用自己记录的样式重写窗口,
        清掉 LAYERED/TRANSPARENT 位导致内容消失、穿透失效。
        每次检查仅在实际发生变化时才重推内容,常态开销可忽略。"""
        if self.is_visible():
            changed = set_layer_flags(self.win, config.OVERLAY_CLICK_THROUGH)
            if changed:
                logger.info("检测到浮窗样式被外部重写,已自愈")
                self._push()
        self.win.after(500, self._self_heal)

    # ---- 逐行轮播 ----
    def _arm_tick(self):
        """轮播定时器：取配置的每行滚动间隔,无轮播时低频空转（开销可忽略）。"""
        if self._tick_id is not None:
            try:
                self.win.after_cancel(self._tick_id)
            except Exception:  # noqa: BLE001
                pass
        interval = float(getattr(config, "OVERLAY_SCROLL_INTERVAL", 0) or 0)
        delay = int(max(interval, 0.2) * 1000)
        self._tick_id = self.win.after(delay, self._tick)

    def _tick(self):
        """自动轮播：仅穿透模式生效——非穿透模式下浮窗接收鼠标事件,
        由用户滚轮手动逐行滚动（_on_wheel）,不自动打扰。"""
        self._tick_id = None
        interval = float(getattr(config, "OVERLAY_SCROLL_INTERVAL", 0) or 0)
        if (self.is_visible() and config.OVERLAY_CLICK_THROUGH
                and interval > 0 and len(self._pages) > 1):
            self._page = (self._page + 1) % len(self._pages)
            self._sel = None  # 页面变了,选区失效
            self._push()
        self._arm_tick()

    def _on_wheel(self, event):
        """滚轮逐行滚动（仅非穿透模式收到事件）：上滚回退一行窗口,下滚前进一行。
        到首/尾窗口后停住（不回绕,与阅读习惯一致）。"""
        if config.OVERLAY_CLICK_THROUGH or len(self._pages) <= 1:
            return
        step = -1 if getattr(event, "delta", 0) > 0 else 1  # Windows delta=±120
        np = max(0, min(len(self._pages) - 1, self._page + step))
        if np != self._page:
            self._page = np
            self._sel = None  # 页面变了,选区失效
            self._push()

    def set_answer(self, text: str):
        self._text = str(text)
        self._page = 0
        self._sel = None
        self._pages = overlay_pages(self._text, self._font)
        self._push()

    # ---- 鼠标交互（Alt+拖动移动 / 左键拖选复制 / 右下角缩放） ----
    def _bind_interactions(self):
        # 左键：拖选文本（ULW 渲染像素无法原生选中,自绘反色高亮 + 命中测试）
        self.win.bind("<ButtonPress-1>", self._on_select_start)
        self.win.bind("<B1-Motion>", self._on_select_motion)
        self.win.bind("<ButtonRelease-1>", self._on_select_end)
        # Alt+左键：移动浮窗（左键拖动让给文本选择）
        self.win.bind("<Alt-ButtonPress-1>", self._on_move_start)
        self.win.bind("<Alt-B1-Motion>", self._on_drag_motion)
        self.win.bind("<Alt-ButtonRelease-1>", self._on_drag_end)
        # 滚轮：非穿透模式下逐行滚动回答内容
        self.win.bind("<MouseWheel>", self._on_wheel)
        # 悬停：右下角缩放热区显示缩放光标
        self.win.bind("<Motion>", self._on_hover)
        # 复制：双击全文;Ctrl+C 复制所选（有选区）否则全文;右键菜单两项齐全
        self.win.bind("<Double-Button-1>", lambda _e: self._copy_answer())
        self.win.bind("<Control-c>", lambda _e: (self._copy_selection() or self._copy_answer()))
        self.win.bind("<Button-3>", self._on_context_menu)

    def _in_grip(self, x, y) -> bool:
        """是否落在右下角缩放热区。"""
        return (x >= int(config.OVERLAY_WIDTH) - _OVER_GRIP
                and y >= int(config.OVERLAY_HEIGHT) - _OVER_GRIP)

    def _on_hover(self, event):
        """悬停光标反馈：右下角热区显示 NW-SE 缩放光标。"""
        try:
            cur = "size_nw_se" if self._in_grip(event.x, event.y) else "arrow"
            if str(self.win.cget("cursor")) != cur:
                self.win.configure(cursor=cur)
        except tk.TclError:
            pass  # 窗口已销毁（退出中）

    # ---- 缩放 ----
    def _do_resize(self, event):
        """拖拽右下角缩放：实时更新 config 与几何,折行窗口即时重算。"""
        try:
            nw = max(_OVER_MIN_W, int(event.x))
            nh = max(_OVER_MIN_H, int(event.y))
            if (nw, nh) == (int(config.OVERLAY_WIDTH), int(config.OVERLAY_HEIGHT)):
                return
            config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT = nw, nh
            self.win.geometry(f"{nw}x{nh}+{int(config.OVERLAY_X)}+{int(config.OVERLAY_Y)}")
            self._sel = None  # 宽高变化折行重排,选区失效
            self._pages = overlay_pages(self._text, self._font)
            self._page = min(self._page, len(self._pages) - 1)
            self._push()
        except tk.TclError:
            pass  # 窗口已销毁（退出中）

    # ---- 文本拖选 ----
    def _on_select_start(self, event):
        if config.OVERLAY_CLICK_THROUGH:
            return  # 穿透状态下不会收到事件,防御性处理
        if self._in_grip(event.x, event.y):
            self._mode = "resize"
            self._sel = None
            return
        self._mode = "select"
        self._sel = None
        li, ci = overlay_hit_index(event.x, event.y, self._lines, self._font)
        self._sel = ((li, ci), (li, ci))  # 锚点
        self._push()

    def _on_select_motion(self, event):
        if self._mode == "resize":
            self._do_resize(event)
            return
        if self._mode != "select" or self._sel is None:
            return
        try:
            li, ci = overlay_hit_index(event.x, event.y, self._lines, self._font)
            self._sel = (self._sel[0], (li, ci))
            self._push()
        except tk.TclError:
            pass  # 窗口已销毁（退出中）

    def _on_select_end(self, _event):
        if self._mode == "resize":
            self._mode = None
            logger.info("浮窗尺寸已调整至 %sx%s",
                        config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT)
            self._save_geometry()
            return
        self._mode = None
        # 零宽度选区（单击）视为取消选择
        if self._sel is not None and self._sel[0] == self._sel[1]:
            self._sel = None

    def _selected_text(self) -> str:
        """当前选区覆盖的文本（跨行以换行拼接；行文本来自当前滚动窗口的折行）。"""
        if not self._sel:
            return ""
        (l0, c0), (l1, c1) = self._sel
        if (l1, c1) < (l0, c0):
            (l0, c0), (l1, c1) = (l1, c1), (l0, c0)
        parts = []
        for li in range(l0, l1 + 1):
            if li >= len(self._lines):
                break
            line = self._lines[li]
            s = c0 if li == l0 else 0
            e = c1 if li == l1 else len(line)
            parts.append(line[s:e])
        return "\n".join(parts)

    def _copy_selection(self):
        """复制拖选的文本片段到剪贴板（无选区时静默返回 False）。"""
        txt = self._selected_text()
        if not txt:
            return False
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(txt)
            logger.info("所选文本已复制到剪贴板（%d 字）", len(txt))
            return True
        except tk.TclError as e:
            logger.warning("复制所选失败: %s", e)
            return False

    # ---- 移动（Alt+拖动） ----
    def _on_move_start(self, event):
        if config.OVERLAY_CLICK_THROUGH:
            return
        self._mode = "move"
        self._drag_off = (event.x, event.y)

    def _on_drag_motion(self, event):
        if self._drag_off is None:
            return
        try:
            nx, ny = event.x_root - self._drag_off[0], event.y_root - self._drag_off[1]
            self.win.geometry(f"+{nx}+{ny}")
            # 同步 config：轮播定时器/自愈在此期间推送时使用新坐标,不会被拉回旧位置
            config.OVERLAY_X, config.OVERLAY_Y = nx, ny
        except tk.TclError:
            pass  # 窗口已销毁（退出中）

    def _on_drag_end(self, _event):
        if self._drag_off is None:
            return
        self._drag_off = None
        self._mode = None
        logger.info("浮窗位置已移动至 (%s, %s)", config.OVERLAY_X, config.OVERLAY_Y)
        self._save_geometry()

    def _save_geometry(self):
        """几何（位置/尺寸）持久化到 settings.json：写盘失败仅记日志,不影响本次显示。

        同时通知 controller（回调在 __init__ 后注入）——设置窗口开着时把
        新几何同步回填其输入框,否则「应用并保存」会用旧值把移动/缩放覆盖回退。"""
        try:
            save_config()  # 原子替换,写盘失败返回 False 仅记日志
        except Exception as e:  # noqa: BLE001
            logger.warning("浮窗几何持久化失败: %s", e)
        if self.on_geometry_changed is not None:
            try:
                self.on_geometry_changed()
            except Exception as e:  # noqa: BLE001
                logger.warning("浮窗几何变化通知失败: %s", e)

    def _on_context_menu(self, event):
        if config.OVERLAY_CLICK_THROUGH:
            return
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label=t("复制所选"), command=self._copy_selection,
                         state="normal" if self._selected_text() else "disabled")
        menu.add_command(label=t("复制回答全文"), command=self._copy_answer)
        menu.add_separator()
        menu.add_command(label=t("移动浮窗:按住 Alt 拖动 / 缩放:拖右下角"),
                         state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_answer(self):
        """回答全文复制到剪贴板（逐像素分层窗口的文本是渲染像素,
        整段复制走右键菜单/双击;片段复制用左键拖选+「复制所选」）。"""
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self._text)
            logger.info("回答已复制到剪贴板（%d 字）", len(self._text))
        except tk.TclError as e:
            logger.warning("复制回答失败: %s", e)

    def apply_config(self):
        """设置变更后实时应用：几何/字体/分层样式全部按当前 config 重新落定。

        若浮窗当前可见则立即重推内容（含置顶/穿透断言）；隐藏时仅准备,
        下次 show() 自然生效。"""
        try:
            self.win.geometry(
                f"{config.OVERLAY_WIDTH}x{config.OVERLAY_HEIGHT}+{config.OVERLAY_X}+{config.OVERLAY_Y}"
            )
        except tk.TclError:
            return  # 窗口已销毁（退出中）
        self._font = _load_overlay_font()
        self._page = 0  # 几何变化后重置到首窗口
        self._sel = None
        self._pages = overlay_pages(self._text, self._font)
        self._arm_tick()
        if self.is_visible():
            self.show()

    def show(self):
        self.win.deiconify()
        # withdraw->deiconify 后置顶属性偶发丢失,重新断言
        self.win.attributes("-topmost", True)
        self.win.lift()
        # 重新断言分层样式 + 鼠标穿透,并重推内容
        set_layer_flags(self.win, config.OVERLAY_CLICK_THROUGH)
        self._push()

    def hide(self):
        self.win.withdraw()

    def toggle(self):
        (self.hide if self.is_visible() else self.show)()

    def is_visible(self):
        return self.win.state() != "withdrawn"
