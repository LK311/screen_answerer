# -*- coding: utf-8 -*-
"""设置对话框（托盘「设置…」入口）：展示方式/监控区域/大模型/快捷键/通用 5 页。

- _ToolTip：设置项悬停说明
- SettingsDialog：字段装载/采集/校验、「应用并保存」、展示方式联动"""
import os
import threading
import webbrowser

import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox as messagebox
import tkinter.colorchooser as colorchooser
import tkinter.simpledialog as simpledialog

from core.appconfig import (config, save_config, load_config, _clamp01,
                            _LLM_PROFILE_KEYS, BASE_DIR, APP_VERSION, GITHUB_URL)
from core.i18n import t, LANGUAGE_LABELS
from core.imagerender import _FONT_FILES, _hex_to_rgb
from core.llmclient import fetch_models
from ui.taskbarwin import _TASKBAR_POSITIONS
from win32.hotkey_capture import capture_hotkey_once, _MOUSE_BUTTONS
from ui.regionselector import RegionSelector

# ------------------------- 设置对话框（托盘「设置…」入口） -------------------------
class _ToolTip:
    """轻量悬停提示：鼠标进入控件片刻后弹出说明,离开/点击/控件销毁即消失。"""

    def __init__(self, widget, text: str, delay_ms: int = 400):
        self._widget = widget
        self._text = text
        self._delay = delay_ms
        self._tw = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tw is not None or not self._widget.winfo_exists():
            return
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        # 设置窗口为 -topmost：提示浮层必须同样置顶,否则整层被设置窗口盖住
        # （表现为"悬停说明不可见"）
        tw.attributes("-topmost", True)
        tw.lift()
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self._text, justify="left", wraplength=380,
                 background="#FFFFE1", foreground="#333333", relief="solid",
                 borderwidth=1, font=("微软雅黑", 9)).pack(ipadx=6, ipady=3)
        self._tw = tw

    def _hide(self, _e=None):
        self._cancel()
        if self._tw is not None:
            try:
                self._tw.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._tw = None


class SettingsDialog:
    """运行时设置窗口（ttk.Notebook 按类型分标签页）：

    - 展示方式：展示方式（桌面浮窗 / 任务栏文本条）下拉联动切换两组设置项。
      浮窗组=位置大小/颜色透明度/字体/置顶穿透；任务栏组=位置布局/文本折行/
      颜色透明度/字体
    - 监控区域：区域坐标、变化检测参数、区域指示框样式；含「框选区域」
      「显隐指示框」按钮（低频操作,从托盘菜单移入本页）
    - 大模型：配置方案下拉；「主接口」与「图像转文字」两个可折叠区域
      （互斥手风琴：主接口默认展开,展开/折叠一个时另一个自动折叠/展开,
      各含端点/密钥/模型下拉/提示词/参数,主接口参数含采样与截图上传项）
    - 快捷键：五个全局功能键位（keyboard 写法；先注册新键、成功才移除旧键,
      失败自动回滚）
    - 通用：启动行为、日志级别、分析记录开关与目录

    「应用并保存」即改运行时配置又写回 settings.json（原子替换）；
    框选浮窗区域后的实时预览复用内部 _apply_live（仅生效不写盘）。"""

    _HOTKEY_ACTIONS = [  # (config 属性, 动作名, 对话框标签)
        ("SELECT_REGION_HOTKEY", "select_region", t("选择监控区域")),
        ("MANUAL_TRIGGER_HOTKEY", "manual_trigger", t("手动回答")),
        ("TOGGLE_MONITOR_HOTKEY", "toggle_monitor", t("暂停/恢复监控")),
        ("TOGGLE_OVERLAY_HOTKEY", "toggle_overlay", t("显示/隐藏桌面浮窗")),
        ("TOGGLE_RECT_HOTKEY", "toggle_rect", t("显示/隐藏区域指示框")),
    ]

    _COMPARE_METHODS = ("dhash", "ahash", "phash", "pixel")
    _LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

    # 提示词场景模板（常见应用场景预设,选择后填入提示词框,可再手工修改）。
    # 场景名与正文均存中文原文键,构建下拉/匹配选中/填入文本框时才经 t() 翻译——
    # 类属性在 import 时求值,若在此处翻译会把语言定格在 import 时刻
    # （改语言重启前设置窗口语言不一致）
    SCENARIO_PRESETS = (
        ("（选择场景模板…）", None),
        ("题目解答",
         "请识别并回答图片中的题目，直接给出正确答案（选项或数值），并用一句话说明理由。"),
        ("题目解析",
         "请识别图片中的题目，给出正确答案，并分步骤讲解解题过程与涉及的知识点。"),
        ("原样转录",
         "请原样输出图片中的全部文字内容，不要回答、不要解释。"),
        ("翻译成中文",
         "请把图片中的文字翻译成中文，保持原有的标题、列表、表格结构。"),
        ("内容总结",
         "请提取图片内容的要点，用简洁的条目式列表总结。"),
        ("术语讲解",
         "请识别图片中的术语、概念或专有名词，逐条给出通俗易懂的解释。"),
        ("公式计算",
         "请识别图片中的公式或算式，给出计算过程与最终结果。"),
    )

    def __init__(self, root: tk.Tk, controller):
        self.root = root
        self.controller = controller
        # 打开窗口前重读 settings.json：程序不热加载文件,运行中手改文件后
        # 内存 config 还是旧值——若不重读,「应用并保存」会把手改内容覆盖回退
        # （框选区域/浮窗移动等交互改动本就即时写盘,重读不会丢失）
        load_config()
        self.vars = {}
        self._swatches = {}  # 颜色配置项的实时色块（key -> tk.Label）
        self._scale_click = {}  # 不透明度滑动条的点击定位处理器（key -> handler,测试用）
        self._scales = {}  # 不透明度滑动条控件（key -> ttk.Scale,测试用）
        self._model_combos = {}  # 模型下拉框（key -> ttk.Combobox,「检测模型」回填用）
        self._llm_sections = {}  # 大模型页折叠分组切换函数（key -> handler,测试用）
        self._llm_bodies = {}  # 折叠分组内容容器（key -> ttk.Frame,测试用）
        self._coll_groups = {}  # 折叠互斥手风琴组（组名 -> [section 记录]）
        self.win = tk.Toplevel(root)
        self.win.withdraw()  # 先隐藏：全部内容构建完成、几何定型后再一次性显示,
        # 否则 Toplevel 先以默认小尺寸映射,构建期间撑大,表现为"小窗闪现"
        self.win.title(t("桌面智能监控回答系统"))
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        # 居中
        self.win.update_idletasks()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"+{sw // 2 - 250}+{max(20, sh // 2 - 360)}")
        self.nb = ttk.Notebook(self.win)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_display_tab()
        self._build_region_tab()
        self._build_llm_tab()
        self._build_hotkey_tab()
        self._build_general_tab()
        bar = ttk.Frame(self.win)
        bar.pack(fill="x", padx=8, pady=(6, 8))
        ttk.Button(bar, text=t("应用并保存"), command=self._apply_persist).pack(side="left", padx=4)
        ttk.Button(bar, text=t("关闭"), command=self.win.destroy).pack(side="right", padx=4)
        self._load_current()
        # 内容与几何全部就绪后再显示（withdraw->deiconify 会丢置顶属性,重新断言）
        self.win.update_idletasks()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.lift()

    @staticmethod
    def _tip(widget, text: str):
        """给设置项挂悬停说明（鼠标悬停显示该项用途与取值范围）。"""
        _ToolTip(widget, text)

    def _new_tab(self, title: str) -> ttk.Frame:
        f = ttk.Frame(self.nb)
        self.nb.add(f, text=f" {title} ")
        return f

    # ---- 统一布局原语（各标签页共用,保证风格一致） ----
    def _row(self, parent, pady=2):
        """行容器：内部字段单元横向 pack 排列。

        统一用行容器而非整页 grid：grid 共享列宽,任一字段超宽（如长灰提示、
        长勾选文本）会把整列撑宽,把同行其他字段推远（表现为"布局太分散"）。"""
        r = ttk.Frame(parent)
        r.pack(fill="x", padx=8, pady=pady)
        return r

    def _flabel(self, row, text, tip=None):
        """行内字段标签（统一左对齐、右留 4px；悬停说明挂此处）。"""
        lbl = ttk.Label(row, text=text)
        lbl.pack(side="left", padx=(2, 4))
        if tip:
            self._tip(lbl, tip)
        return lbl

    def _collapsible_section(self, parent, title, group=None, default_open=False):
        """可折叠分组：标题行（▸/▾ + 标题,点击切换）+ 内容容器 body。

        group 给定时为**互斥手风琴组**：同组同时只有一个展开——展开一个自动
        折叠同组其他;折叠当前展开项时自动展开同组另一个（始终恰有一个展开）。
        body 仅在展开时 pack 在标题行下方（after=header）,收起时 pack_forget
        ——控件仍存在,字段装载/采集不受折叠影响。
        返回 (标题行, 内容容器, 切换函数)。"""
        header = ttk.Frame(parent)
        header.pack(fill="x", padx=8, pady=(6, 2))
        arrow = ttk.Label(header, text="▸")
        arrow.pack(side="left", padx=(0, 2))
        lbl = ttk.Label(header, text=title)
        lbl.pack(side="left")
        body = ttk.Frame(parent)
        sec = {"header": header, "arrow": arrow, "body": body, "open": False}
        members = self._coll_groups.setdefault(group, []) if group else None
        if members is not None:
            members.append(sec)  # 注册进互斥手风琴组

        def _apply(s: dict, open_: bool):
            s["open"] = open_
            s["arrow"].config(text="▾" if open_ else "▸")
            if open_:
                s["body"].pack(fill="x", padx=(16, 8), pady=(0, 6), after=s["header"])
            else:
                s["body"].pack_forget()

        def _toggle(_e=None):
            target = not sec["open"]
            if members is not None and len(members) > 1:
                _apply(sec, target)
                for other in members:  # 同组互斥：展开谁就折叠其余,折叠谁就展开其余
                    if other is not sec:
                        _apply(other, not target)
            else:
                _apply(sec, target)

        for w in (header, arrow, lbl):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", _toggle)
        if default_open:
            _apply(sec, True)
        return header, body, _toggle

    # ---- 标签页 1：展示方式（浮窗组 / 任务栏组,按展示方式联动） ----
    def _build_display_tab(self):
        pad = {"padx": 8, "pady": 4}
        f = self._new_tab(t("展示方式"))

        f0 = ttk.LabelFrame(f, text=f" {t('展示方式')} ")
        f0.pack(fill="x", **pad)
        row = self._row(f0)
        mode_var = tk.StringVar()
        mode_combo = ttk.Combobox(row, textvariable=mode_var, state="readonly", width=14,
                                  values=[t("桌面浮窗"), t("任务栏文本条")])
        mode_combo.pack(side="left")
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_changed())
        self.vars["answer_mode"] = mode_var
        self._tip(mode_combo, t("回答以哪种形式展示：\n"
                              "· 桌面浮窗：屏幕上的独立浮动窗口\n"
                              "· 任务栏文本条：嵌入任务栏或停靠屏幕边缘的文本条\n"
                              "（下方设置项随展示方式联动切换）"))

        # 两组设置容器：按展示方式整组显隐（组内 pack 顺序固定,来回切换不乱序）
        self._ov_box = ttk.Frame(f)
        self._tb_box = ttk.Frame(f)
        self._ov_box.pack(fill="x")
        self._tb_box.pack(fill="x")

        # ===== 浮窗组（展示方式=桌面浮窗时显示） =====
        f1 = ttk.LabelFrame(self._ov_box, text=f" {t('位置与大小（屏幕绝对像素坐标）')} ")
        f1.pack(fill="x", **pad)
        coord_tips = {"x": t("桌面浮窗左上角的屏幕横向绝对像素坐标"),
                      "y": t("桌面浮窗左上角的屏幕纵向绝对像素坐标"),
                      "width": t("桌面浮窗宽度（像素,最小 40）"),
                      "height": t("桌面浮窗高度（像素,最小 24）")}
        row = self._row(f1)
        for key, label in [("x", "X"), ("y", "Y"), ("width", t("宽")), ("height", t("高"))]:
            self._flabel(row, label, coord_tips[key])
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=6).pack(side="left", padx=(0, 10))
            self.vars[key] = var
        row2 = self._row(f1, pady=(0, 4))
        pick_btn = ttk.Button(row2, text=t("框选桌面浮窗区域…（拖拽框选,ESC 取消）"),
                              command=self._pick_overlay_region)
        pick_btn.pack(side="left")
        self._tip(pick_btn, t("全屏拖拽框选浮窗位置,松开后回填 X/Y/宽/高 并立即预览"))

        f2 = ttk.LabelFrame(self._ov_box, text=f" {t('颜色与透明度（背景 / 文字各自独立）')} ")
        f2.pack(fill="x", **pad)
        row = self._row(f2)
        self._flabel(row, t("背景颜色"), t("浮窗背景色,十六进制写法（如 #000000）；也可点「选色…」拾取"))
        self._color_entry(row, "bg_color")
        self._flabel(row, t("背景不透明度"), t("0%=完全透明,100%=完全不透明；点击滑动条任意位置即可定位"))
        self._alpha_scale(row, "bg_alpha")
        row = self._row(f2, pady=(0, 4))
        self._flabel(row, t("文字颜色"), t("回答文字颜色,十六进制写法（如 #FFFFFF）"))
        self._color_entry(row, "text_color")
        self._flabel(row, t("文字不透明度"), t("0%=文字完全透明,100%=完全不透明"))
        self._alpha_scale(row, "text_alpha")

        f3 = ttk.LabelFrame(self._ov_box, text=f" {t('字体')} ")
        f3.pack(fill="x", **pad)
        row = self._row(f3)
        self._flabel(row, t("字体"), t("回答文字使用的字体（内置字体文件）"))
        font_var = tk.StringVar()
        ttk.Combobox(row, textvariable=font_var, values=list(_FONT_FILES.keys()),
                     state="readonly", width=10).pack(side="left", padx=(0, 16))
        self.vars["font_name"] = font_var
        self._flabel(row, t("字号(磅)"), t("回答文字大小（8~72 磅）"))
        size_var = tk.StringVar()
        ttk.Spinbox(row, textvariable=size_var, from_=8, to=72, width=5).pack(side="left")
        self.vars["font_size"] = size_var

        f4 = ttk.LabelFrame(self._ov_box, text=f" {t('行为')} ")
        f4.pack(fill="x", **pad)
        row = self._row(f4)
        for key, label, tip in [
                ("always_on_top", t("置顶显示"), t("开启后桌面浮窗始终显示在其他窗口之上")),
                ("click_through", t("鼠标穿透（点击穿过浮窗）"),
                 t("开启后鼠标点击穿透浮窗直接作用于下方窗口；取消勾选后浮窗可正常点击"))]:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(row, text=label, variable=var)
            cb.pack(side="left", padx=(2, 12))
            self._tip(cb, tip)
            self.vars[key] = var
        self._flabel(row, t("播放速度(秒/行)"),
                     t("回答超过浮窗高度时不截断,按行轮播：每隔该秒数滚动一行（0.5~60）；\n"
                       "0=不轮播（只显示第一屏,超出部分显示「已截断」标记）。\n"
                       "另：取消鼠标穿透后,可拖动浮窗移动位置,双击/右键可复制回答全文"))
        var = tk.StringVar()
        ttk.Spinbox(row, textvariable=var, from_=0, to=60, increment=0.5, width=5).pack(side="left")
        self.vars["ov_scroll"] = var

        # ===== 任务栏组（展示方式=任务栏文本条时显示） =====
        fb = ttk.LabelFrame(self._tb_box, text=f" {t('位置与布局')} ")
        fb.pack(fill="x", **pad)
        row = self._row(fb)
        self._flabel(row, t("显示位置"),
                     t("「任务栏内」=嵌入任务栏托盘区左侧（TrafficMonitor 同款）；\n"
                       "其余为停靠屏幕边缘的浮动文本条"))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, state="readonly", width=18,
                     values=list(_TASKBAR_POSITIONS.values())).pack(side="left", padx=(0, 16))
        self.vars["tb_position"] = var
        self._flabel(row, t("显示行数"), t("文本条同时显示的行数（1~10）；超出部分按行轮播,不截断"))
        var = tk.StringVar()
        ttk.Spinbox(row, textvariable=var, from_=1, to=10, width=4).pack(side="left", padx=(0, 16))
        self.vars["tb_max_lines"] = var
        self._flabel(row, t("播放速度(秒/行)"),
                     t("内容超过显示行数时按行轮播：每隔该秒数滚动一行（0.5~60）,\n不截断"))
        var = tk.StringVar()
        ttk.Spinbox(row, textvariable=var, from_=0.5, to=60, increment=0.5, width=5).pack(side="left")
        self.vars["tb_scroll"] = var

        fw = ttk.LabelFrame(self._tb_box, text=f" {t('文本折行')} ")
        fw.pack(fill="x", **pad)
        row = self._row(fw)
        self._flabel(row, t("每行最大字符数"),
                     t("每行最多显示的字符数（0~200）。\n"
                       "0=按像素宽度自动折行；任务栏模式建议 20~40。\n"
                       "回答中的换行符按空格处理"))
        var = tk.StringVar()
        ttk.Spinbox(row, textvariable=var, from_=0, to=200, increment=1, width=6).pack(side="left")
        self.vars["tb_max_chars"] = var

        fc = ttk.LabelFrame(self._tb_box, text=f" {t('颜色与透明度')} ")
        fc.pack(fill="x", **pad)
        row = self._row(fc)
        self._flabel(row, t("文字颜色"), t("文本条文字颜色,十六进制写法（如 #FFFFFF）"))
        self._color_entry(row, "tb_text_color")
        self._flabel(row, t("文字不透明度"), t("0%=文字完全透明,100%=完全不透明；点击滑动条任意位置即可定位"))
        self._alpha_scale(row, "tb_text_alpha")
        row = self._row(fc, pady=(0, 4))
        self._flabel(row, t("背景颜色"), t("文本条背景色,十六进制写法（如 #1A1A1A）"))
        self._color_entry(row, "tb_bg_color")
        self._flabel(row, t("背景不透明度"), t("0%=完全透明,100%=完全不透明；点击滑动条任意位置即可定位"))
        self._alpha_scale(row, "tb_bg_alpha")

        ff = ttk.LabelFrame(self._tb_box, text=f" {t('字体')} ")
        ff.pack(fill="x", **pad)
        row = self._row(ff, pady=(0, 4))
        self._flabel(row, t("字体"), t("文本条文字使用的字体（内置字体文件）"))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, values=list(_FONT_FILES.keys()),
                     state="readonly", width=10).pack(side="left", padx=(0, 16))
        self.vars["tb_font_name"] = var
        self._flabel(row, t("字号(磅)"), t("文本条文字大小（8~72 磅）"))
        var = tk.StringVar()
        ttk.Spinbox(row, textvariable=var, from_=8, to=72, width=5).pack(side="left")
        self.vars["tb_font_size"] = var

    def _on_mode_changed(self):
        """展示方式联动：只显示当前模式对应的设置组。"""
        if not getattr(self, "_ov_box", None):
            return
        tb_mode = self.vars["answer_mode"].get() == t("任务栏文本条")
        if tb_mode:
            self._ov_box.pack_forget()
            self._tb_box.pack(fill="x")
        else:
            self._tb_box.pack_forget()
            self._ov_box.pack(fill="x")

    # ---- 标签页 2：监控区域 ----
    def _build_region_tab(self):
        pad = {"padx": 8, "pady": 4}
        f = self._new_tab(t("监控区域"))

        f1 = ttk.LabelFrame(f, text=f" {t('监控区域（屏幕绝对像素坐标）')} ")
        f1.pack(fill="x", **pad)
        coord_tips = {"region_left": t("监控区域左上角的屏幕横向绝对像素坐标（与桌面浮窗的 X 同义）"),
                      "region_top": t("监控区域左上角的屏幕纵向绝对像素坐标（与桌面浮窗的 Y 同义）"),
                      "region_width": t("监控区域宽度（像素,最小 16）"),
                      "region_height": t("监控区域高度（像素,最小 16）")}
        row = self._row(f1)
        for key, label in [("region_left", "X"), ("region_top", "Y"),
                           ("region_width", t("宽")), ("region_height", t("高"))]:
            self._flabel(row, label, coord_tips[key])
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=6).pack(side="left", padx=(0, 10))
            self.vars[key] = var

        f2 = ttk.LabelFrame(f, text=f" {t('变化检测')} ")
        f2.pack(fill="x", **pad)
        row = self._row(f2)
        self._flabel(row, t("监控间隔(秒)"), t("每隔多少秒截屏一次并检测画面变化（0.2~3600）"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=7).pack(side="left", padx=(0, 16))
        self.vars["capture_interval"] = var
        self._flabel(row, t("变化阈值(0~64)"), t("画面哈希距离超过该值才判定为变化；越大越不灵敏（0~64）"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=7).pack(side="left")
        self.vars["change_threshold"] = var
        row = self._row(f2, pady=(0, 4))
        self._flabel(row, t("冷却(秒)"), t("两次回答之间的最小间隔秒数（0~3600）,防止连续频繁调用大模型"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=7).pack(side="left", padx=(0, 16))
        self.vars["cooldown"] = var
        self._flabel(row, t("比较算法"), t("画面变化检测算法：dhash 默认,速度与灵敏度均衡；phash 更稳但稍慢"))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, values=list(self._COMPARE_METHODS),
                     state="readonly", width=7).pack(side="left")
        self.vars["compare_method"] = var

        f3 = ttk.LabelFrame(f, text=f" {t('区域指示框')} ")
        f3.pack(fill="x", **pad)
        row = self._row(f3)
        self._flabel(row, t("颜色"), t("监控区域指示框的边框颜色,十六进制写法（如 #00FFFF）"))
        self._color_entry(row, "rect_color")
        self._flabel(row, t("不透明度"), t("指示框边框不透明度；0%=完全透明,100%=完全不透明"))
        self._alpha_scale(row, "rect_alpha")
        row2 = self._row(f3, pady=(0, 4))
        rect_show = tk.BooleanVar()
        rect_cb = ttk.Checkbutton(row2, text=t("启动时显示指示框（下次启动生效；运行中用按钮或快捷键切换）"),
                                  variable=rect_show)
        rect_cb.pack(side="left")
        self._tip(rect_cb, t("勾选后程序每次启动自动显示指示框；运行中的显隐用下方按钮或快捷键切换"))
        self.vars["rect_show"] = rect_show

        f4 = ttk.LabelFrame(f, text=f" {t('常用操作')} ")
        f4.pack(fill="x", **pad)
        row = self._row(f4, pady=(0, 4))
        ttk.Button(row, text=t("框选监控区域…（拖拽框选,ESC 取消）"),
                   command=lambda: self.controller.select_region()).pack(side="left", padx=(2, 12))
        ttk.Button(row, text=t("显示/隐藏区域指示框"),
                   command=lambda: self.controller.toggle_rect()).pack(side="left")

    # ---- 标签页 3：大模型 ----
    def _build_llm_tab(self):
        pad = {"padx": 8, "pady": 4}
        f = self._new_tab(t("大模型"))

        f0 = ttk.LabelFrame(f, text=f" {t('配置方案')}")
        f0.pack(fill="x", **pad)
        row = self._row(f0)
        self.profile_var = tk.StringVar()
        self._profile_combo = ttk.Combobox(row, textvariable=self.profile_var,
                                           state="readonly", width=16)
        self._profile_combo.pack(side="left", padx=(0, 8))
        self._profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(row, text=t("另存为新方案"), width=18,
                   command=self._save_profile_as).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=t("删除当前方案"), width=12,
                   command=self._delete_profile).pack(side="left")

        # 主接口（可折叠,默认展开）：端点/密钥/模型/提示词/参数。
        # 与图像转文字为互斥手风琴组：展开一个自动折叠另一个
        _, main_body, main_toggle = self._collapsible_section(
            f, t("主接口（OpenAI 兼容端点）"),
            group="llm", default_open=True)
        self._llm_sections["main"] = main_toggle
        self._llm_bodies["main"] = main_body
        row = self._row(main_body)
        self._flabel(row, t("端点"), t("主模型 OpenAI 兼容接口地址（/chat/completions 的服务根地址）"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=34).pack(side="left")
        self.vars["llm_base_url"] = var
        row = self._row(main_body)
        self._flabel(row, t("密钥"), t("服务方提供的 API Key,仅保存在本机 settings.json"))
        key_var = tk.StringVar()
        key_entry = ttk.Entry(row, textvariable=key_var, width=34, show="*")
        key_entry.pack(side="left", padx=(0, 8))
        self.vars["llm_api_key"] = key_var
        self._api_key_entry = key_entry
        show_var = tk.BooleanVar()
        ttk.Checkbutton(row, text=t("显示密钥"), variable=show_var,
                        command=lambda: key_entry.config(show="" if show_var.get() else "*")).pack(side="left")
        row = self._row(main_body)
        self._flabel(row, t("模型"),
                     t("主模型名称,如 glm-4v-flash。未配置图像转文字时需为视觉模型（支持图片输入）；\n"
                       "配置图像转文字后可为纯文本大语言模型。可点「检测模型」拉取端点可用模型列表"))
        var = tk.StringVar()
        model_combo = ttk.Combobox(row, textvariable=var, width=24)
        model_combo.pack(side="left", padx=(0, 6))
        self.vars["llm_model"] = var
        self._model_combos["llm_model"] = model_combo
        btn = ttk.Button(row, text=t("检测模型"), width=8,
                         command=lambda: self._detect_models("llm_base_url", "llm_api_key", "llm_model"))
        btn.pack(side="left")
        self._tip(btn, t("向端点查询可用模型列表（GET /models）填充左侧下拉框；\n"
                       "部分服务不支持该接口,检测失败时可直接手动输入模型名"))
        # 提示词场景模板：常见应用场景预设,一键填入下方提示词框
        row = self._row(main_body)
        self._flabel(row, t("场景模板"), t("常见应用场景的提示词预设；\n"
                                    "选择后会把模板内容填入下方提示词框（覆盖现有内容,可再手工修改）"))
        self.preset_combo = ttk.Combobox(row, state="readonly", width=16,
                                         values=[t(name) for name, _ in self.SCENARIO_PRESETS])
        self.preset_combo.current(0)
        self.preset_combo.pack(side="left", padx=(0, 10))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        # 主接口提示词（发送给主模型的指令）
        row = self._row(main_body)
        self._flabel(row, t("提示词"), t("发送给主模型的指令（可留空）"))
        self.prompt_text = tk.Text(main_body, height=5, width=52, wrap="word")
        self.prompt_text.pack(fill="x", padx=10, pady=(0, 4))
        self._tip(self.prompt_text,
                  t("主模型收到的指令（图像转文字模型有单独的提示词,见下方区域）。留空=不附加指令。\n"
                    "未配置图像转文字时,截图随本提示词直发主模型（需视觉模型）；\n"
                    "配置后主模型收到纯文本：转写结果嵌入位置——\n"
                    "· 本提示词含 {{OCR_TEXT}} 动态变量：转写结果替换该变量"
                    "（不区分大小写,可放任意位置自由组织语序）\n"
                    "· 未出现时：转写结果以「【图片内容转写】」小节追加到提示词末尾"))
        # 参数（主模型采样 + 截图上传；超时/重试对两次调用均生效）
        specs = [("llm_temperature", t("温度(0~1)"),
                  t("主模型采样温度：越低回答越稳定保守,越高越发散（回答场景建议 0~0.5）；\n"
                    "图像转文字调用固定 0.1,不使用该值")),
                 ("llm_max_tokens", "max_tokens",
                  t("限制主模型回答最大 token 数；0=不限制（不下发该字段）")),
                 ("llm_timeout", t("超时(秒)"),
                  t("单次 HTTP 请求的超时秒数；主模型与图像转文字调用共用")),
                 ("llm_retry", t("重试次数 "),
                  t("请求失败后的重试次数（指数退避：1s/2s/4s…上限 8s）；\n"
                    "429 限流单独处理：遵循服务端 Retry-After 或 5s→10s→20s 长退避（上限 60s）；\n"
                    "主模型与图像转文字调用共用")),
                 ("llm_send_max_edge", t("发送长边"),
                  t("上传前把截图长边等比缩放到该像素值以减小体积；0=原图直传。\n"
                    "截图发给图像转文字模型（启用时）或主模型（未启用时）")),
                 ("llm_jpeg_quality", t("JPEG质量(1~95)"),
                  t("截图 JPEG 压缩质量：越低体积越小、上传越快,但清晰度下降。\n"
                    "截图发给图像转文字模型（启用时）或主模型（未启用时）"))]
        for i, (key, label, tip) in enumerate(specs):
            if i % 3 == 0:
                row = self._row(main_body, pady=(2, 2) if i < 3 else (2, 0))
            self._flabel(row, label, tip)
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=7).pack(side="left", padx=(0, 12))
            self.vars[key] = var

        # 图像转文字（可选,可折叠,默认折叠）：端点/密钥/模型/提示词。
        # 端点+模型两项全配才启用：截图先转文字,描述嵌入主模型提示词,
        # 主模型收到纯文本请求（借此支持纯文本大语言模型）
        _, ocr_body, ocr_toggle = self._collapsible_section(
            f, t("图像转文字（可选,端点+模型全填才启用）"),
            group="llm")
        self._llm_sections["ocr"] = ocr_toggle
        self._llm_bodies["ocr"] = ocr_body
        row = self._row(ocr_body)
        self._flabel(row, t("端点"), t("图像转文字模型的 OpenAI 兼容端点（留空=不启用,截图直发主模型）"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=34).pack(side="left")
        self.vars["llm_ocr_base_url"] = var
        row = self._row(ocr_body)
        self._flabel(row, t("密钥"), t("图像转文字模型的 API Key（本地服务可留空）"))
        key_var = tk.StringVar()
        key_entry2 = ttk.Entry(row, textvariable=key_var, width=34, show="*")
        key_entry2.pack(side="left", padx=(0, 8))
        self.vars["llm_ocr_api_key"] = key_var
        show_var2 = tk.BooleanVar()
        ttk.Checkbutton(row, text=t("显示密钥"), variable=show_var2,
                        command=lambda: key_entry2.config(show="" if show_var2.get() else "*")).pack(side="left")
        row = self._row(ocr_body)
        self._flabel(row, t("模型"),
                     t("图像转文字视觉模型名,如 glm-4v-flash（需支持图片输入）。\n"
                       "工作流程：截图→该模型转成文字→文字嵌入主模型提示词"
                       "（动态变量 {{OCR_TEXT}} 或追加末尾）\n"
                       "→主模型（可为纯文本模型）回答"))
        var = tk.StringVar()
        model_combo2 = ttk.Combobox(row, textvariable=var, width=24)
        model_combo2.pack(side="left", padx=(0, 6))
        self.vars["llm_ocr_model"] = var
        self._model_combos["llm_ocr_model"] = model_combo2
        btn2 = ttk.Button(row, text=t("检测模型"), width=8,
                          command=lambda: self._detect_models("llm_ocr_base_url", "llm_ocr_api_key",
                                                              "llm_ocr_model"))
        btn2.pack(side="left")
        self._tip(btn2, t("向图像转文字端点查询可用模型列表填充左侧下拉框；\n检测失败时可直接手动输入模型名"))
        # 图像转文字提示词（发送给转写模型的指令）
        row = self._row(ocr_body)
        self._flabel(row, t("提示词"), t("发送给图像转文字模型的指令（留空=内置默认转写指令）"))
        self.ocr_prompt_text = tk.Text(ocr_body, height=3, width=52, wrap="word")
        self.ocr_prompt_text.pack(fill="x", padx=10, pady=(0, 4))
        self._tip(self.ocr_prompt_text,
                  t("图像转文字模型收到的指令,要求它把截图转成文字（不要作答）。\n"
                    "留空使用内置默认指令：「请原样输出图片中的全部文字内容,不要回答、不要解释」。"
                    "转写结果嵌入主模型提示词的方式,见主接口提示词说明"))

    def _on_preset_selected(self, _e=None):
        """选择场景模板：把预设提示词填入主提示词框（覆盖现有内容）。

        场景名与模板正文均按当前语言翻译（正文键为中文原文,英文环境查 _EN 表,
        未收录回退中文）——下拉显示的是翻译后场景名,匹配时做同样的 t() 翻译再比对。"""
        name = self.preset_combo.get()
        for pname, ptext in self.SCENARIO_PRESETS:
            if t(pname) == name and ptext:
                self.prompt_text.delete("1.0", "end")
                self.prompt_text.insert("1.0", t(ptext))
                return

    # ---- 标签页 4：快捷键 ----
    def _build_hotkey_tab(self):
        pad = {"padx": 8, "pady": 4}
        f = self._new_tab(t("快捷键"))
        f5 = ttk.LabelFrame(f, text=f" {t('全局快捷键（点击「录入」后按下目标组合键自动录入）')} ")
        f5.pack(fill="x", **pad)
        capture_tip = t("支持键盘组合键与鼠标按键（左/右/中/侧键,可叠加 Ctrl/Shift/Alt\n"
                        "等修饰键,如 Ctrl+侧键）。键盘按下的第一个非修饰键即定型\n"
                        "（无需等待松开）,鼠标按键按下即定型；点击「录入」后 0.3 秒内\n"
                        "的鼠标点击会被忽略（保护期）。鼠标热键无法拦截点击（点击会透传）。\n"
                        "按 ESC 放弃键盘录入")
        clear_tip = t("清空该行键位；应用并保存后此功能不再绑定快捷键（仍可通过托盘菜单触发）")
        for i, (attr, action, label) in enumerate(self._HOTKEY_ACTIONS):
            row = self._row(f5, pady=3)
            self._flabel(row, label)
            var = tk.StringVar()
            entry = ttk.Entry(row, textvariable=var, width=16, state="readonly")
            entry.pack(side="left", padx=(0, 6))
            self._tip(entry, t("当前键位（只读）；点击右侧「录入」后按下新组合键即替换"))
            btn = ttk.Button(row, text=t("录入"), width=6)
            btn.config(command=lambda v=var, b=btn: self._capture_hotkey(v, b))
            btn.pack(side="left", padx=(0, 6))
            self._tip(btn, capture_tip)
            ttk.Button(row, text=t("清除"), width=6,
                       command=lambda v=var: self._clear_hotkey(v)).pack(side="left")
            self.vars[f"hk_{action}"] = var

    def _clear_hotkey(self, var: tk.StringVar):
        """清空该行键位：应用/保存后此动作不再绑定全局快捷键。"""
        if getattr(self, "_capturing", False):
            return
        var.set("")

    def _capture_hotkey(self, var: tk.StringVar, btn: ttk.Button):
        """进入按键捕获模式：首个非修饰键按下即定型（不等释放）,ESC 取消。

        录入期间临时移除已注册热键,防止按下的组合键误触发动作；结束后恢复。
        tkinter 非线程安全：读取在子线程只写结果属性,主线程用 after 轮询
        取结果并更新 UI（不能在子线程直接调用 root.after）。"""
        if getattr(self, "_capturing", False):
            return
        self._capturing = True
        self._capture_result = None
        btn.config(text=t("等待按键…"), state="disabled")
        self.controller.suspend_hotkeys()

        def _reader():
            try:
                self._capture_result = capture_hotkey_once()
            except Exception:  # noqa: BLE001
                self._capture_result = None

        threading.Thread(target=_reader, daemon=True).start()

        def _poll():
            try:
                if not self.win.winfo_exists():
                    # 窗口已销毁但录入仍在进行：必须恢复热键,否则全局键位全丢
                    if getattr(self, "_capturing", False):
                        self._capturing = False
                        self.controller.restore_hotkeys()
                    return
            except tk.TclError:
                return
            if self._capture_result is None:
                self.win.after(100, _poll)
                return
            self._capturing = False
            combo = self._capture_result
            err = self.controller.restore_hotkeys()
            try:
                btn.config(text=t("录入"), state="normal")
            except tk.TclError:
                return
            if combo and combo != "esc":
                var.set(combo)
            if err:
                messagebox.showerror(t("热键恢复失败"), str(err), parent=self.win)

        self.win.after(100, _poll)

    # ---- 大模型方案管理（多组端点/密钥/模型/提示词/参数） ----
    def _refresh_profiles(self):
        self._profile_combo.config(values=list(config.LLM_PROFILES.keys()))
        self.profile_var.set(config.LLM_ACTIVE)

    def _load_llm_profile_fields(self, name: str):
        """把指定方案的值填入当前页面字段。"""
        p = config.LLM_PROFILES.get(name, {})
        v = self.vars
        v["llm_base_url"].set(p.get("base_url", ""))
        v["llm_api_key"].set(p.get("api_key", ""))
        v["llm_model"].set(p.get("model", ""))
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", p.get("prompt", ""))
        v["llm_temperature"].set(p.get("temperature", 0.2))
        v["llm_max_tokens"].set(p.get("max_tokens", 0))
        v["llm_timeout"].set(p.get("timeout", 30))
        v["llm_retry"].set(p.get("retry", 2))
        v["llm_send_max_edge"].set(p.get("send_max_edge", 0))
        v["llm_ocr_base_url"].set(p.get("ocr_base_url", ""))
        v["llm_ocr_api_key"].set(p.get("ocr_api_key", ""))
        v["llm_ocr_model"].set(p.get("ocr_model", ""))
        self.ocr_prompt_text.delete("1.0", "end")
        self.ocr_prompt_text.insert("1.0", p.get("ocr_prompt", ""))
        v["llm_jpeg_quality"].set(p.get("jpeg_quality", 85))

    def _apply_llm_runtime(self, p: dict):
        """把大模型方案字段字典写入运行时 config.LLM_*（含可选 OCR 四项）。

        方案下拉切换、另存、删除回退与「应用并保存」共用此通道——保证
        运行时始终与当前方案完全一致（此前「应用并保存」漏写 OCR 四项,
        切到 OCR 为空的方案后运行时残留上一方案的转写端点,仍会调用图像转文字）。"""
        config.LLM_BASE_URL = str(p.get("base_url", "")).strip()
        config.LLM_API_KEY = str(p.get("api_key", "")).strip()
        config.LLM_MODEL = str(p.get("model", "")).strip()
        config.LLM_PROMPT = str(p.get("prompt", "")).strip()
        config.LLM_TEMPERATURE = _clamp01(p.get("temperature", 0.2))
        config.LLM_MAX_TOKENS = int(p.get("max_tokens", 0))
        config.LLM_TIMEOUT = int(p.get("timeout", 30))
        config.LLM_RETRY = int(p.get("retry", 2))
        config.SEND_MAX_EDGE = int(p.get("send_max_edge", 0))
        config.LLM_JPEG_QUALITY = max(1, min(95, int(p.get("jpeg_quality", 85))))
        config.LLM_OCR_BASE_URL = str(p.get("ocr_base_url", "")).strip()
        config.LLM_OCR_API_KEY = str(p.get("ocr_api_key", "")).strip()
        config.LLM_OCR_MODEL = str(p.get("ocr_model", "")).strip()
        config.LLM_OCR_PROMPT = str(p.get("ocr_prompt", "")).strip()

    def _activate_profile_runtime(self, name: str):
        """把指定方案写进运行时配置（config.LLM_*）,选择方案即生效。"""
        self._apply_llm_runtime(config.LLM_PROFILES.get(name, {}))

    def _on_profile_selected(self, _e=None):
        """下拉选择方案即生效：更新活动方案名、载入字段并切换运行时配置。"""
        name = self.profile_var.get()
        if name and name in config.LLM_PROFILES:
            config.LLM_ACTIVE = name
            self._load_llm_profile_fields(name)
            self._activate_profile_runtime(name)

    def _save_profile_as(self):
        """把当前页面的大模型字段校验后另存为新方案并立即持久化。"""
        name = simpledialog.askstring(t("另存为方案"), t("请输入方案名称："), parent=self.win)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning(t("名称无效"), t("方案名称不能为空。"), parent=self.win)
            return
        try:
            fields = self._collect_llm_fields()
        except ValueError as e:
            messagebox.showwarning(t("输入有误"), str(e), parent=self.win)
            return
        config.LLM_PROFILES[name] = {k: fields[k] for k in _LLM_PROFILE_KEYS}
        config.LLM_ACTIVE = name
        self._refresh_profiles()
        self._activate_profile_runtime(name)
        save_config()
        messagebox.showinfo(t("已保存"),
                            t("方案「{name}」已保存并生效。").format(name=name), parent=self.win)

    def _delete_profile(self):
        name = self.profile_var.get()
        if len(config.LLM_PROFILES) <= 1:
            messagebox.showinfo(t("无法删除"), t("至少保留一个方案。"), parent=self.win)
            return
        if name not in config.LLM_PROFILES:
            return
        if not messagebox.askyesno(t("删除方案"), t("确定删除方案「{name}」？").format(name=name),
                                   parent=self.win):
            return
        del config.LLM_PROFILES[name]
        nxt = next(iter(config.LLM_PROFILES))
        config.LLM_ACTIVE = nxt
        self._refresh_profiles()
        self._load_llm_profile_fields(nxt)
        self._activate_profile_runtime(nxt)
        save_config()

    def _fill_model_combo(self, model_key: str, models: list):
        """把检测到的模型列表填入下拉框（纯模型名）；
        当前手输模型名不在列表中时回落到第一项。"""
        combo = self._model_combos[model_key]
        combo.config(values=models)
        if self.vars[model_key].get().strip() not in models:
            self.vars[model_key].set(models[0])

    def _detect_models(self, url_key: str, key_key: str, model_key: str):
        """向端点查询可用模型列表（GET /models）,回填对应模型下拉框。

        网络请求在子线程执行（tkinter 非线程安全）,主线程 after 轮询取结果；
        当前文本框里手输的模型名仍会保留（在列表中不覆盖）。"""
        base = self.vars[url_key].get().strip()
        if not base:
            messagebox.showwarning(t("无法检测"), t("请先填写端点地址。"), parent=self.win)
            return
        api_key = self.vars[key_key].get().strip()
        result = {}

        def _worker():
            try:
                result["models"] = fetch_models(base, api_key)
            except Exception as e:  # noqa: BLE001
                result["error"] = e

        threading.Thread(target=_worker, daemon=True).start()

        def _poll():
            if not self.win.winfo_exists():
                return  # 设置窗口已关闭,丢弃结果
            if "models" not in result and "error" not in result:
                self.win.after(120, _poll)
                return
            if "error" in result:
                messagebox.showwarning(
                    t("检测失败"),
                    t("获取模型列表失败：{err}\n\n"
                      "请检查端点/密钥是否正确；部分服务不支持 /models 接口,\n"
                      "此时请直接手动输入模型名。").format(err=result['error']),
                    parent=self.win)
                return
            models = result["models"]
            if not models:
                messagebox.showwarning(t("检测结果"),
                                       t("端点未返回任何模型,请手动输入模型名。"),
                                       parent=self.win)
                return
            self._fill_model_combo(model_key, models)
            messagebox.showinfo(t("检测完成"),
                                t("获取到 {n} 个可用模型,已填充下拉框。").format(n=len(models)),
                                parent=self.win)

        self.win.after(120, _poll)

    def _collect_llm_fields(self) -> dict:
        """读取并校验大模型 14 项字段（含可选图像转文字 4 项,不含方案名）。非法输入抛 ValueError。"""
        v = self.vars
        prompt = self.prompt_text.get("1.0", "end-1c").strip()  # 可留空：不附加指令
        llm = {
            "base_url": v["llm_base_url"].get().strip(),
            "api_key": v["llm_api_key"].get().strip(),
            "model": v["llm_model"].get().strip(),
            "prompt": prompt,
            "temperature": self._float(v["llm_temperature"].get(), "温度", 0, 1),
            "max_tokens": self._int(v["llm_max_tokens"].get(), "max_tokens", 0),
            "timeout": self._int(v["llm_timeout"].get(), "超时", 1),
            "retry": self._int(v["llm_retry"].get(), "重试次数", 0, 10),
            "send_max_edge": self._int(v["llm_send_max_edge"].get(), "发送长边", 0),
            "jpeg_quality": self._int(v["llm_jpeg_quality"].get(), "JPEG质量", 1, 95),
            "ocr_base_url": v["llm_ocr_base_url"].get().strip(),
            "ocr_api_key": v["llm_ocr_api_key"].get().strip(),
            "ocr_model": v["llm_ocr_model"].get().strip(),
            "ocr_prompt": self.ocr_prompt_text.get("1.0", "end-1c").strip(),  # 空=内置默认指令
        }
        if not llm["base_url"] or not llm["model"]:
            raise ValueError(t("大模型端点与模型名不能为空"))
        # 图像转文字可选,但三项要么全填要么全空（半配无效且易误判）
        ocr_filled = sum(1 for k in ("ocr_base_url", "ocr_model") if llm[k])
        if ocr_filled == 1:
            raise ValueError(t("图像转文字模型需要「端点」和「模型」同时填写（密钥可留空）,或全部留空"))
        return llm

    # ---- 标签页 5：通用 ----
    def _build_general_tab(self):
        pad = {"padx": 8, "pady": 4}
        f = self._new_tab(t("通用"))

        f0 = ttk.LabelFrame(f, text=f" {t('界面')} ")
        f0.pack(fill="x", **pad)
        row = self._row(f0, pady=(2, 4))
        self._flabel(row, t("语言"), t("界面语言（中文/English）；切换并保存后重启程序生效"))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, state="readonly", width=9,
                     values=list(LANGUAGE_LABELS.values())).pack(side="left")
        self.vars["language"] = var

        f1 = ttk.LabelFrame(f, text=f" {t('启动行为（下次启动生效）')} ")
        f1.pack(fill="x", **pad)
        row = self._row(f1, pady=(2, 4))
        for key, label, tip in [
                ("monitor_paused", t("启动时暂停定时监控"),
                 t("勾选后每次启动不自动定时监控（可手动回答,或稍后通过托盘/快捷键恢复监控）")),
                ("overlay_hidden", t("启动时隐藏桌面浮窗"),
                 t("勾选后每次启动不显示回答窗口（可通过托盘菜单或快捷键再显示）"))]:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(row, text=label, variable=var)
            cb.pack(side="left", padx=(2, 12))
            self._tip(cb, tip)
            self.vars[key] = var

        f2 = ttk.LabelFrame(f, text=f" {t('日志与记录')} ")
        f2.pack(fill="x", **pad)
        row = self._row(f2)
        self._flabel(row, t("日志级别"), t("日志详细程度：DEBUG 最详细,ERROR 只记错误；排查问题选 DEBUG"))
        var = tk.StringVar()
        ttk.Combobox(row, textvariable=var, values=list(self._LOG_LEVELS),
                     state="readonly", width=9).pack(side="left", padx=(0, 16))
        self.vars["log_level"] = var
        save_art = tk.BooleanVar()
        save_cb = ttk.Checkbutton(row, text=t("记录分析截图与回答"), variable=save_art)
        save_cb.pack(side="left")
        self._tip(save_cb, t("每次回答把问题截图和回答文本成对保存到下方记录目录的"
                           "当日日期子目录；\n取消勾选后不再落盘（已有历史保留）。应用并保存后生效"))
        self.vars["save_artifacts"] = save_art
        row = self._row(f2, pady=(2, 4))
        self._flabel(row, t("记录目录"),
                     t("问题截图与回答的保存目录（相对程序目录,默认 QA_History）,\n"
                       "按日期建子目录（如 QA_History\\2026-11-12\\）,历史永久保留；\n"
                       "应用后新记录写入新目录"))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=22).pack(side="left")
        self.vars["artifacts_dir"] = var

        f3 = ttk.LabelFrame(f, text=f" {t('关于')} ")
        f3.pack(fill="x", **pad)
        row = self._row(f3, pady=(2, 4))
        self._flabel(row, t("版本"), t("程序当前版本（与 exe 文件属性/发布 tag 一致）"))
        ver_label = ttk.Label(row, text=f"v{APP_VERSION}")
        ver_label.pack(side="left", padx=(0, 24))
        self._about_ver = ver_label  # 测试断言入口
        self._flabel(row, t("项目主页"), t("点击打开项目 GitHub 仓库（查看更新/提交 Issue）"))
        link = ttk.Label(row, text=GITHUB_URL, foreground="#2d7dff", cursor="hand2")
        link.pack(side="left")
        # 点击超链接：浏览器打开项目主页（ttk.Label 无 hyperlink,手动 bind）
        link.bind("<Button-1>", lambda _e: webbrowser.open(GITHUB_URL))
        self._tip(link, t("点击在浏览器中打开项目主页"))
        self._about_link = link  # 测试断言入口
        row = self._row(f3, pady=(0, 4))
        copy_btn = ttk.Button(row, text=t("复制项目链接"), width=12,
                              command=lambda: (self.win.clipboard_clear(),
                                               self.win.clipboard_append(GITHUB_URL)))
        copy_btn.pack(side="left")
        self._tip(copy_btn, t("把项目主页地址复制到剪贴板"))

    def _color_entry(self, parent, key):
        """颜色配置项 = 输入框 + 实时色块预览 + 选色按钮（parent 为行容器）。

        色块随输入框内容实时刷新（var trace 同时覆盖「选色…」回填与
        _load_current 装载）；非法颜色串（输入过程中）保持上一次色块。"""
        var = tk.StringVar()
        ttk.Entry(parent, textvariable=var, width=10).pack(side="left", padx=(0, 4))
        swatch = tk.Label(parent, text="", width=4, relief="groove")
        swatch.pack(side="left", padx=(0, 4))

        def _apply_swatch(*_):
            try:
                swatch.config(bg=var.get().strip() or "#000000")
            except tk.TclError:
                pass  # 输入中的非法颜色值：色块保持原样

        var.trace_add("write", _apply_swatch)
        ttk.Button(parent, text=t("选色…"), width=6,
                   command=lambda: self._pick_color(var)).pack(side="left", padx=(0, 12))
        self.vars[key] = var
        self._swatches[key] = swatch

    def _alpha_scale(self, parent, key):
        """不透明度滑动条：数值标签 + 点击/拖动直接定位到点击位置（parent 为行容器）。

        部分 Windows 主题下 ttk.Scale 的默认点击行为只在两端跳变,
        这里按横向像素位置精确换算数值并屏蔽默认类绑定（return "break"）。"""
        var = tk.DoubleVar()
        scale = ttk.Scale(parent, from_=0, to=1, variable=var, length=110)
        scale.pack(side="left", padx=(0, 2))
        lbl = ttk.Label(parent, text="", width=5)
        lbl.pack(side="left", padx=(0, 12))
        var.trace_add("write", lambda *_, v=var, l=lbl: l.config(text=f"{v.get():.0%}"))

        def _locate(event, s=scale, v=var):
            width = s.winfo_width()
            if width <= 1:  # 窗口尚未完成布局时用期望宽度兜底
                width = s.winfo_reqwidth()
            frac = (event.x - 10) / max(width - 20, 1)  # 10px≈主题 trough 内边距
            v.set(round(min(1.0, max(0.0, frac)), 3))
            return "break"  # 阻断 ttk.Scale 默认类绑定,避免跳到两端

        scale.bind("<Button-1>", _locate)
        scale.bind("<B1-Motion>", _locate)
        self.vars[key] = var
        self._scale_click[key] = _locate  # 供测试直接驱动
        self._scales[key] = scale

    def _pick_color(self, var: tk.StringVar):
        try:
            picked = colorchooser.askcolor(color=var.get() or "#000000", parent=self.win)
            if picked and picked[1]:
                var.set(picked[1].upper())
        except Exception:  # noqa: BLE001
            pass

    def _pick_overlay_region(self):
        """全屏拖拽框选桌面浮窗区域：选完回填 X/Y/宽/高 并实时生效预览。"""
        self.controller.overlay.hide()  # 隐藏浮窗,便于看清下方内容

        def _on_picked(region):
            left, top, w, h = (int(v) for v in region)
            self.vars["x"].set(left); self.vars["y"].set(top)
            self.vars["width"].set(w); self.vars["height"].set(h)
            self._apply_live()  # 回填后立即生效并重新显示浮窗预览

        def _on_cancelled():
            self.controller.overlay.show()

        # 持引用防 Tk 浮层被 GC；回调在 Tk 主线程事件内执行,可直接改 var
        self._selector = RegionSelector(_on_picked, _on_cancelled)

    # ---- 数据装载 / 采集 / 应用 ----
    def refresh_overlay_vars(self):
        """桌面浮窗被拖动/缩放（非穿透模式,config 已实时更新并写盘）后,
        把新几何同步回填到本窗口输入框——否则「应用并保存」会从输入框
        读到旧值,把移动/缩放后的浮窗覆盖回退。"""
        v = self.vars
        v["x"].set(config.OVERLAY_X); v["y"].set(config.OVERLAY_Y)
        v["width"].set(config.OVERLAY_WIDTH); v["height"].set(config.OVERLAY_HEIGHT)

    def refresh_region_vars(self):
        """监控区域被外部更新（框选热键/设置页按钮走 controller 路径,选完即写盘）后,
        把 config.REGION 同步回填到本窗口输入框——否则「应用并保存」会从输入框
        读到旧值,把刚框选的区域覆盖回退。"""
        try:
            left, top, w, h = (int(x) for x in config.REGION)
        except Exception:  # noqa: BLE001
            return
        v = self.vars
        v["region_left"].set(left); v["region_top"].set(top)
        v["region_width"].set(w); v["region_height"].set(h)

    def _load_current(self):
        v, c = self.vars, config
        # 桌面浮窗
        v["x"].set(c.OVERLAY_X); v["y"].set(c.OVERLAY_Y)
        v["width"].set(c.OVERLAY_WIDTH); v["height"].set(c.OVERLAY_HEIGHT)
        v["bg_color"].set(c.OVERLAY_BG_COLOR); v["text_color"].set(c.OVERLAY_TEXT_COLOR)
        v["bg_alpha"].set(c.OVERLAY_BG_ALPHA); v["text_alpha"].set(c.OVERLAY_TEXT_ALPHA)
        v["font_name"].set(c.OVERLAY_FONT_NAME if c.OVERLAY_FONT_NAME in _FONT_FILES else "微软雅黑")
        v["font_size"].set(c.OVERLAY_FONT_SIZE)
        v["always_on_top"].set(c.OVERLAY_ALWAYS_ON_TOP)
        v["click_through"].set(c.OVERLAY_CLICK_THROUGH)
        v["ov_scroll"].set(getattr(c, "OVERLAY_SCROLL_INTERVAL", 2.0))
        # 展示方式与任务栏文本条
        v["answer_mode"].set(t("任务栏文本条") if c.ANSWER_MODE == "taskbar" else t("桌面浮窗"))
        v["tb_position"].set(_TASKBAR_POSITIONS.get(c.TASKBAR_POSITION, t("任务栏内（托盘区左侧）")))
        v["tb_max_lines"].set(c.TASKBAR_MAX_LINES)
        v["tb_max_chars"].set(c.TASKBAR_MAX_CHARS_PER_LINE)
        v["tb_scroll"].set(c.TASKBAR_SCROLL_INTERVAL)
        v["tb_font_name"].set(c.TASKBAR_FONT_NAME if c.TASKBAR_FONT_NAME in _FONT_FILES else "微软雅黑")
        v["tb_font_size"].set(c.TASKBAR_FONT_SIZE)
        v["tb_text_color"].set(c.TASKBAR_TEXT_COLOR)
        v["tb_text_alpha"].set(c.TASKBAR_TEXT_ALPHA)
        v["tb_bg_color"].set(c.TASKBAR_BG_COLOR)
        v["tb_bg_alpha"].set(c.TASKBAR_BG_ALPHA)
        # 监控区域
        left, top, w, h = (int(x) for x in c.REGION)
        v["region_left"].set(left); v["region_top"].set(top)
        v["region_width"].set(w); v["region_height"].set(h)
        v["capture_interval"].set(c.CAPTURE_INTERVAL)
        v["change_threshold"].set(c.CHANGE_THRESHOLD)
        v["cooldown"].set(c.COOLDOWN)
        v["compare_method"].set(c.COMPARE_METHOD if c.COMPARE_METHOD in self._COMPARE_METHODS else "dhash")
        v["rect_color"].set(c.REGION_RECT_COLOR)
        v["rect_alpha"].set(c.REGION_RECT_ALPHA)
        v["rect_show"].set(c.REGION_RECT_SHOW)
        # 大模型（下拉框列出全部方案,字段为活动方案的值）
        self._refresh_profiles()
        self._load_llm_profile_fields(config.LLM_ACTIVE)
        # 快捷键
        for attr, action, _ in self._HOTKEY_ACTIONS:
            v[f"hk_{action}"].set(getattr(c, attr))
        # 通用
        v["monitor_paused"].set(c.MONITOR_START_PAUSED)
        v["overlay_hidden"].set(c.OVERLAY_START_HIDDEN)
        v["save_artifacts"].set(c.SAVE_ARTIFACTS)
        v["log_level"].set(c.LOG_LEVEL if c.LOG_LEVEL in self._LOG_LEVELS else "INFO")
        v["language"].set(LANGUAGE_LABELS.get(getattr(c, "LANGUAGE", "zh"), "中文"))
        try:
            v["artifacts_dir"].set(os.path.relpath(c.ARTIFACTS_DIR, BASE_DIR))
        except ValueError:  # 跨盘符时 relpath 抛错,直接显示绝对路径
            v["artifacts_dir"].set(c.ARTIFACTS_DIR)
        # 展示方式联动：装载完成后按当前模式显隐设置组
        self._on_mode_changed()

    @staticmethod
    def _int(v, name, lo=None, hi=None):
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError(t("{name} 必须为整数").format(name=name))
        if lo is not None and n < lo or hi is not None and n > hi:
            raise ValueError(t("{name} 需在 {lo}~{hi} 之间").format(name=name, lo=lo, hi=hi))
        return n

    @staticmethod
    def _float(v, name, lo=None, hi=None):
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(t("{name} 必须为数字").format(name=name))
        if lo is not None and f < lo or hi is not None and f > hi:
            raise ValueError(t("{name} 需在 {lo}~{hi} 之间").format(name=name, lo=lo, hi=hi))
        return f

    def _collect(self) -> dict:
        """读取并校验全部字段。非法输入抛 ValueError（消息可直接展示）。"""
        v = self.vars
        # 桌面浮窗
        overlay = {}
        for key in ("x", "y", "width", "height"):
            overlay[key] = self._int(v[key].get(), t("浮窗{key}").format(key=key))
        if overlay["width"] < 40 or overlay["height"] < 24:
            raise ValueError(t("浮窗宽/高过小（至少 40x24）"))
        if overlay["x"] < -2000 or overlay["y"] < -2000:
            raise ValueError(t("坐标异常"))
        for key in ("bg_color", "text_color"):
            _hex_to_rgb(v[key].get())  # 非法会回退白,但这里要求显式合法
            if not str(v[key].get()).strip().lstrip("#"):
                raise ValueError(t("{key} 颜色不能为空").format(key=key))
            overlay[key] = v[key].get().strip().upper()
        for key in ("bg_alpha", "text_alpha"):
            overlay[key] = round(_clamp01(v[key].get()), 3)
        overlay["font_size"] = self._int(v["font_size"].get(), "字号", 8, 72)
        overlay["font_name"] = v["font_name"].get()
        overlay["always_on_top"] = bool(v["always_on_top"].get())
        overlay["click_through"] = bool(v["click_through"].get())
        overlay["scroll_interval"] = round(self._float(v["ov_scroll"].get(), "播放速度", 0, 60), 1)

        # 展示方式与任务栏文本条
        mode = "taskbar" if v["answer_mode"].get() == t("任务栏文本条") else "overlay"
        pos_label = v["tb_position"].get()
        pos_code = next((k for k, lb in _TASKBAR_POSITIONS.items() if lb == pos_label),
                        "taskbar-right")
        taskbar = {
            "mode": mode,
            "position": pos_code,
            "max_lines": self._int(v["tb_max_lines"].get(), "显示行数", 1, 10),
            "max_chars_per_line": self._int(v["tb_max_chars"].get(), "每行最大字符数", 0, 200),
            "scroll_interval": self._float(v["tb_scroll"].get(), "播放速度", 0.5, 60),
            "font_name": v["tb_font_name"].get(),
            "font_size": self._int(v["tb_font_size"].get(), "任务栏字号", 8, 72),
        }
        for key in ("tb_text_color", "tb_bg_color"):
            _hex_to_rgb(v[key].get())
            if not str(v[key].get()).strip().lstrip("#"):
                raise ValueError(t("任务栏文本条颜色不能为空"))
        taskbar["text_color"] = v["tb_text_color"].get().strip().upper()
        taskbar["text_alpha"] = round(_clamp01(v["tb_text_alpha"].get()), 3)
        taskbar["bg_color"] = v["tb_bg_color"].get().strip().upper()
        taskbar["bg_alpha"] = round(_clamp01(v["tb_bg_alpha"].get()), 3)

        # 监控区域
        region = {
            "left": self._int(v["region_left"].get(), "区域左坐标", -5000),
            "top": self._int(v["region_top"].get(), "区域上坐标", -5000),
            "width": self._int(v["region_width"].get(), "区域宽", 16),
            "height": self._int(v["region_height"].get(), "区域高", 16),
        }
        capture = {
            "capture_interval": self._float(v["capture_interval"].get(), "监控间隔", 0.2, 3600),
            "compare_method": v["compare_method"].get(),
            "change_threshold": self._int(v["change_threshold"].get(), "变化阈值", 0, 64),
            "cooldown": self._float(v["cooldown"].get(), "冷却时间", 0, 3600),
        }
        _hex_to_rgb(v["rect_color"].get())
        if not str(v["rect_color"].get()).strip().lstrip("#"):
            raise ValueError(t("指示框颜色不能为空"))
        rect = {
            "color": v["rect_color"].get().strip().upper(),
            "alpha": round(_clamp01(v["rect_alpha"].get()), 3),
            "show": bool(v["rect_show"].get()),
        }

        # 大模型
        llm = self._collect_llm_fields()
        llm["profile"] = config.LLM_ACTIVE

        # 快捷键（空键位 = 不绑定；重复检查仅针对已绑定的键位）
        hotkeys = {}
        seen = set()
        for attr, action, label in self._HOTKEY_ACTIONS:
            combo = v[f"hk_{action}"].get().strip().lower()
            if not combo:
                continue
            # 鼠标段校验：至多一个鼠标按键,且必须是已知按钮
            mouse_parts = [p for p in combo.split("+") if p.startswith("mouse_")]
            if len(mouse_parts) > 1 or (mouse_parts and mouse_parts[0][len("mouse_"):] not in _MOUSE_BUTTONS):
                raise ValueError(t("快捷键「{combo}」含未知鼠标按键（可选 left/right/middle/x/x2）").format(combo=combo))
            if combo in seen:
                raise ValueError(t("快捷键「{combo}」被重复使用").format(combo=combo))
            seen.add(combo)
            hotkeys[combo] = action

        # 通用
        general = {
            "monitor_paused": bool(v["monitor_paused"].get()),
            "overlay_hidden": bool(v["overlay_hidden"].get()),
            "save_artifacts": bool(v["save_artifacts"].get()),
            "log_level": v["log_level"].get(),
            "artifacts_dir": v["artifacts_dir"].get().strip(),
            "language": next((code for code, lb in LANGUAGE_LABELS.items()
                              if lb == v["language"].get()), "zh"),
        }
        if not general["artifacts_dir"]:
            raise ValueError(t("记录目录不能为空"))

        return {"overlay": overlay, "taskbar": taskbar, "region": region, "capture": capture,
                "rect": rect, "llm": llm, "hotkeys": hotkeys, "general": general}

    def _apply_common(self, vals: dict):
        """把全部页面落到 config 命名空间并实时应用；热键重建（失败返回错误）。

        常规项（浮窗/区域/检测/大模型/通用中的运行时可变项）全部即时生效；
        启动行为与指示框启动显隐仅影响下次启动。"""
        o = vals["overlay"]
        config.OVERLAY_X = o["x"]; config.OVERLAY_Y = o["y"]
        config.OVERLAY_WIDTH = o["width"]; config.OVERLAY_HEIGHT = o["height"]
        config.OVERLAY_BG_COLOR = o["bg_color"]; config.OVERLAY_BG_ALPHA = o["bg_alpha"]
        config.OVERLAY_TEXT_COLOR = o["text_color"]; config.OVERLAY_TEXT_ALPHA = o["text_alpha"]
        config.OVERLAY_FONT_NAME = o["font_name"]; config.OVERLAY_FONT_SIZE = o["font_size"]
        config.OVERLAY_ALWAYS_ON_TOP = o["always_on_top"]
        config.OVERLAY_CLICK_THROUGH = o["click_through"]
        config.OVERLAY_SCROLL_INTERVAL = o["scroll_interval"]
        self.controller.overlay.apply_config()

        # 展示方式与任务栏文本条：配置落定后,仅保留当前模式的窗口可见
        tb = vals["taskbar"]
        config.ANSWER_MODE = tb["mode"]
        config.TASKBAR_POSITION = tb["position"]
        config.TASKBAR_MAX_LINES = tb["max_lines"]
        config.TASKBAR_MAX_CHARS_PER_LINE = tb["max_chars_per_line"]
        config.TASKBAR_SCROLL_INTERVAL = tb["scroll_interval"]
        config.TASKBAR_FONT_NAME = tb["font_name"]
        config.TASKBAR_FONT_SIZE = tb["font_size"]
        config.TASKBAR_TEXT_COLOR = tb["text_color"]
        config.TASKBAR_TEXT_ALPHA = tb["text_alpha"]
        config.TASKBAR_BG_COLOR = tb["bg_color"]
        config.TASKBAR_BG_ALPHA = tb["bg_alpha"]
        if self.controller.taskbar_text is not None:
            self.controller.taskbar_text.apply_config()
        if config.ANSWER_MODE == "taskbar":
            self.controller.overlay.hide()
            if self.controller.taskbar_text is not None:
                self.controller.taskbar_text.show()  # 调参场景下让用户立刻看到效果
        else:
            if self.controller.taskbar_text is not None:
                self.controller.taskbar_text.hide()
            self.controller.overlay.show()  # 调参场景下让用户立刻看到效果

        rg = vals["region"]
        config.REGION = (rg["left"], rg["top"], rg["width"], rg["height"])
        self.controller.worker.reset_baseline()
        if self.controller.rect_indicator is not None:
            self.controller.rect_indicator.update_region()  # 重定位/重绘（隐藏态为无害推送）

        cp = vals["capture"]
        config.CAPTURE_INTERVAL = cp["capture_interval"]
        config.COMPARE_METHOD = cp["compare_method"]
        config.CHANGE_THRESHOLD = cp["change_threshold"]
        config.COOLDOWN = cp["cooldown"]

        rc = vals["rect"]
        config.REGION_RECT_COLOR = rc["color"]
        config.REGION_RECT_ALPHA = rc["alpha"]
        config.REGION_RECT_SHOW = rc["show"]

        lm = vals["llm"]
        self._apply_llm_runtime(lm)  # 与方案切换共用通道（含 OCR 四项,避免残留旧端点）
        # 应用即写入活动方案（页面字段就是该方案的新值）
        config.LLM_ACTIVE = lm["profile"]
        config.LLM_PROFILES[lm["profile"]] = {k: lm[k] for k in _LLM_PROFILE_KEYS}

        g = vals["general"]
        config.MONITOR_START_PAUSED = g["monitor_paused"]
        config.OVERLAY_START_HIDDEN = g["overlay_hidden"]
        config.SAVE_ARTIFACTS = g["save_artifacts"]
        if g["log_level"] != config.LOG_LEVEL:
            config.LOG_LEVEL = g["log_level"]
            logging.getLogger().setLevel(g["log_level"])
        config.ARTIFACTS_DIR = os.path.join(BASE_DIR, g["artifacts_dir"])
        # 界面语言：仅写配置,UI 文案在构建时已按启动语言定格——重启后生效
        if g["language"] != getattr(config, "LANGUAGE", "zh"):
            config.LANGUAGE = g["language"]
            messagebox.showinfo(t("语言设置"), t("界面语言将在重启程序后生效。"),
                                parent=self.win)

        err = self.controller.rebuild_hotkeys(vals["hotkeys"])
        if err is None:
            for attr, action, _ in self._HOTKEY_ACTIONS:
                # 空键位 = 该动作不绑定快捷键
                combo = next((c for c, a in vals["hotkeys"].items() if a == action), "")
                setattr(config, attr, combo)
        return err

    def _apply_live(self):
        """仅实时生效不写盘（不再有独立按钮；框选浮窗区域后的预览复用此通道）。"""
        try:
            vals = self._collect()
        except ValueError as e:
            messagebox.showwarning(t("输入有误"), str(e), parent=self.win)
            return
        err = self._apply_common(vals)
        if err:
            messagebox.showerror(t("热键注册失败"),
                                 t("{err}\n\n其他设置已生效；快捷键保留原键位。").format(err=err),
                                 parent=self.win)

    def _apply_persist(self):
        """「应用并保存」：实时生效 + 写回 settings.json（原子替换）。"""
        try:
            vals = self._collect()
        except ValueError as e:
            messagebox.showwarning(t("输入有误"), str(e), parent=self.win)
            return
        err = self._apply_common(vals)
        if err:
            messagebox.showerror(t("热键注册失败"),
                                 t("{err}\n\n其他设置已生效；快捷键保留原键位,未写入配置。").format(err=err),
                                 parent=self.win)
            return
        if not save_config():
            # 仅失败时提示；成功不打断（无二次弹窗）
            messagebox.showwarning(t("保存失败"),
                                   t("设置已实时生效,但写回 settings.json 失败（详见日志）,\n"
                                     "重启后将恢复为原配置。"), parent=self.win)
