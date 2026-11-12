# -*- coding: utf-8 -*-
"""任务栏文本条（回答展示方式之二,TrafficMonitor 同款原生窗口架构）。

- _TaskbarNative：专用线程托管的原生窗口（创建即挂接 Shell_TrayWnd 子窗口、
  独立消息泵、锚窗口 1s 自愈）
- TaskbarText：主线程侧的分页/渲染/对外接口（与 Overlay 同形）"""
import queue
import threading
import ctypes
import ctypes.wintypes

from PIL import Image, ImageDraw

from core.appconfig import config, logger
from core.i18n import t
from win32.win32util import _work_area, _find_taskbar, _taskbar_geom_for, push_layered_image
from core.imagerender import _hex_to_rgb, _load_taskbar_font, _wrap_text

# ------------------------- 任务栏文本条（回答展示方式之二） -------------------------
# settings.json 取值 -> 设置界面标签（t() 在 import 时按启动语言定格）
_TASKBAR_POSITIONS = {
    "taskbar-right": t("任务栏内（托盘区左侧）"),
    "bottom-center": t("底部居中"), "bottom-left": t("底部左侧"), "bottom-right": t("底部右侧"),
    "top-center": t("顶部居中"), "top-left": t("顶部左侧"), "top-right": t("顶部右侧"),
}

# ---- 原生窗口基础设施（TrafficMonitor 同款架构,架构说明见 _TaskbarNative） ----
wintypes = ctypes.wintypes
_TASKBAR_WNDCLASS = "ScreenAnswererTaskbarBar"
_TASKBAR_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,   # LRESULT
    ctypes.c_void_p,    # HWND
    ctypes.c_uint,      # UINT msg
    ctypes.c_size_t,    # WPARAM
    ctypes.c_ssize_t)   # LPARAM
_TB_WM_TIMER = 0x0113
_TB_WM_DESTROY = 0x0002
_TB_WS_EX = (0x00080000 | 0x00000020 | 0x00000080 | 0x08000000 | 0x00000008)  # LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE|TOPMOST
_TB_WS_POPUP = 0x80000000
_TB_HWND_MESSAGE = ctypes.c_void_p(-3)
_TB_SW_HIDE, _TB_SW_SHOWNA = 0, 8
_TB_SWP_NOACTIVATE = 0x0010
_taskbar_targets = {}   # hwnd -> _TaskbarNative 实例（WndProc 按 hwnd 路由）
_taskbar_class_registered = False
_taskbar_class_lock = threading.Lock()


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
        ("lpfnWndProc", _TASKBAR_WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.c_void_p),
    ]


def _taskbar_wndproc_impl(hwnd, msg, wparam, lparam):
    """模块级 WndProc 中转：按 hwnd 路由到实例。

    回调必须以模块级变量持有（类实例回调会在实例销毁后被 GC,导致崩窗）。"""
    target = _taskbar_targets.get(hwnd)
    if target is not None:
        try:
            return target.handle_message(hwnd, msg, wparam, lparam)
        except Exception as e:  # noqa: BLE001
            logger.warning("任务栏文本窗口消息处理异常: %s", e)
            return 0
    return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_taskbar_wndproc_ref = _TASKBAR_WNDPROC(_taskbar_wndproc_impl)  # 永久引用防 GC
# DefWindowProcW 必须显式声明 argtypes/restype：默认 c_int 会在 x64 下
# 截断 LRESULT,且 WM_NCCREATE 期 wparam 为 64 位值会触发 OverflowError,
# 回调异常返回 0 会导致窗口创建被中止（CreateWindowExW 返回 NULL）
_u32_shared = ctypes.windll.user32
_u32_shared.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t]
_u32_shared.DefWindowProcW.restype = ctypes.c_ssize_t


class _TaskbarNative:
    """专用线程托管的原生任务栏文本窗口（TrafficMonitor CTaskbarDlg 同款架构）。

    上一版把 Tk 窗口 SetParent 到 Shell_TrayWnd 导致任务栏点击无响应,根因：
    (1) Tk 周期性重写窗口扩展样式（清掉 WS_EX_TRANSPARENT）,悬在任务栏 Z
        序顶端的子窗口会吞掉任务栏点击；靠 500ms 自愈对抗形成"清样式->恢复->
        重推"风暴,每次重推都是对 explorer 线程的跨进程同步调用；
    (2) 窗口操作全在 Tk 主线程执行——SetParent 使两线程输入队列互锁
        （attach-thread-input）,Tk 主线程阻塞时任务栏输入整体停摆；
    (3) explorer 重启后无恢复。

    本类逐条对应 TrafficMonitor 的解法：
    - 原生窗口（自有 WndProc + 独立消息泵线程）,样式永不被 UI 框架重写；
    - 消息泵常开（GetMessage 阻塞时释放 GIL）,互锁后仍能即时响应；
    - 窗口仅在位置/尺寸真正变化时 SetWindowPos 一次,内容变化走 ULW；
    - 锚窗口（message-only）承载 1s 原生定时器：任务栏/explorer 重启销毁
      子窗口后自动重建并重新挂接。
    主线程经命令队列下发指令,随命令传递渲染好的每页 PIL 图像,本线程只做
    SetWindowPos 与 UpdateLayeredWindow 推送。"""

    WM_APP_WAKEUP = 0x8000 + 1
    TIMER_TICK = 1   # 轮播（挂在文本窗口上,按行间隔触发）
    TIMER_HEAL = 2   # 自愈（挂在锚点上,固定 1s）

    def __init__(self, commands):
        self._cmds = commands
        self.hwnd = None          # 文本窗口句柄（窗口线程维护,主线程只读）
        self._anchor = None       # message-only 锚窗口（承载定时器,永不随任务栏销毁）
        self._pages = []
        self._page = 0
        self._interval_ms = 2000
        self._visible = False
        self._last_geom = None    # (x, y, w, h) 上次摆放值,变化才 SetWindowPos
        self._quitting = False
        self._thread = threading.Thread(target=self._run, name="taskbar-text", daemon=True)
        self._thread.start()

    # ---- 窗口线程 ----
    def _run(self):
        u32 = self._u32()
        self._register_class()
        self._anchor = u32.CreateWindowExW(
            0, _TASKBAR_WNDCLASS, "sa-tb-anchor", 0, 0, 0, 0, 0,
            _TB_HWND_MESSAGE, None, None, None)
        if self._anchor:
            _taskbar_targets[self._anchor] = self
            u32.SetTimer(self._anchor, self.TIMER_HEAL, 1000, None)
        self._create_text_window()
        self._drain()  # 补收启动竞态期主线程已入队的命令
        msg = wintypes.MSG()
        while True:
            r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:  # 0=WM_QUIT,-1=出错
                break
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        for h in (self._anchor, self.hwnd):
            if h:
                _taskbar_targets.pop(h, None)

    @staticmethod
    def _u32():
        """独立 user32 实例：本类的 argtypes 设置不影响模块其他调用点。"""
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT]
        return u32

    def _register_class(self):
        global _taskbar_class_registered
        with _taskbar_class_lock:
            if _taskbar_class_registered:
                return
            kern = ctypes.windll.kernel32
            kern.GetModuleHandleW.restype = ctypes.c_void_p
            wc = _WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(wc)
            wc.lpfnWndProc = _taskbar_wndproc_ref
            wc.hInstance = kern.GetModuleHandleW(None)
            wc.lpszClassName = _TASKBAR_WNDCLASS
            if not ctypes.windll.user32.RegisterClassExW(ctypes.byref(wc)):
                logger.warning("任务栏文本窗口类注册失败 err=%d", ctypes.GetLastError())
            _taskbar_class_registered = True

    def _style_for_config(self):
        """按配置返回 (窗口样式, 父窗口)。

        taskbar-right：直接以 Shell_TrayWnd 为父创建 WS_CHILD 子窗口
        （TrafficMonitor 同款"创建即挂接"）。实测对 WS_POPUP 顶层窗口事后
        SetParent 跨进程会静默失败（返回非 0 但 GetParent 不变）,而
        WS_CHILD 创建时指定父窗口可靠；任务栏暂不存在时返回 (None, None)。
        浮动位置：无父顶层 popup。"""
        if config.TASKBAR_POSITION == "taskbar-right":
            tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
            if not tray:
                return None, None
            # WS_CHILD | WS_CLIPSIBLINGS
            return 0x40000000 | 0x04000000, wintypes.HWND(tray)
        return _TB_WS_POPUP, None

    def _create_text_window(self):
        u32 = self._u32()
        style, parent = self._style_for_config()
        if style is None:
            return  # 任务栏不存在（explorer 未就绪）,等自愈定时器重试
        hwnd = u32.CreateWindowExW(
            _TB_WS_EX, _TASKBAR_WNDCLASS, "sa-tb-text",
            style, 0, 0, 10, 10, parent, None, None, None)
        if not hwnd:
            logger.warning("任务栏文本窗口创建失败 err=%d", ctypes.get_last_error())
            return
        _taskbar_targets[hwnd] = self
        self.hwnd = hwnd
        self._last_geom = None

    def _sync_parent(self):
        """按当前配置对齐窗口形态：taskbar-right 为任务栏子窗口,浮动位置为
        顶层 popup。形态不符时销毁重建（SetParent 对 WS_POPUP 跨进程挂接
        不可靠——实测静默失败,故不做事后改父,直接重建）。"""
        u32 = ctypes.windll.user32
        if not self.hwnd or not u32.IsWindow(self.hwnd):
            return
        want_child = config.TASKBAR_POSITION == "taskbar-right"
        is_child = bool(u32.GetWindowLongW(self.hwnd, -16) & 0x40000000)  # WS_CHILD
        if want_child != is_child:
            _taskbar_targets.pop(self.hwnd, None)
            u32.DestroyWindow(self.hwnd)
            self.hwnd = None
            self._last_geom = None
            self._create_text_window()

    def notify(self):
        """主线程调用：命令队列有新内容,唤醒窗口线程（线程安全）。"""
        if self._anchor:
            ctypes.windll.user32.PostMessageW(self._anchor, self.WM_APP_WAKEUP, 0, 0)

    def handle_message(self, hwnd, msg, wparam, lparam):
        u32 = ctypes.windll.user32
        if hwnd == self._anchor:
            if msg == self.WM_APP_WAKEUP:
                self._drain()
                return 0
            if msg == _TB_WM_TIMER and wparam == self.TIMER_HEAL:
                self._heal()
                return 0
        elif hwnd == self.hwnd:
            if msg == _TB_WM_TIMER and wparam == self.TIMER_TICK:
                if self._visible and len(self._pages) > 1:
                    self._page = (self._page + 1) % len(self._pages)
                    self._push_page()
                return 0
            if msg == _TB_WM_DESTROY:
                # explorer 重启会连带销毁子窗口：清引用,自愈定时器稍后重建
                self.hwnd = None
                self._last_geom = None
                _taskbar_targets.pop(hwnd, None)
                return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _drain(self):
        while True:
            try:
                cmd = self._cmds.get_nowait()
            except queue.Empty:
                return
            u32 = ctypes.windll.user32
            kind = cmd[0]
            if kind == "set":
                self._pages, self._interval_ms = cmd[1], max(300, int(cmd[2]))
                self._page = 0
                if self.hwnd:
                    self._sync_parent()  # 位置模式可能在运行中切换
                    self._rearm_tick()
                    if self._visible:
                        self._push_page()
            elif kind == "show":
                self._visible = True
                if self.hwnd:
                    u32.ShowWindow(self.hwnd, _TB_SW_SHOWNA)
                    self._rearm_tick()
                    self._push_page()
            elif kind == "hide":
                self._visible = False
                if self.hwnd:
                    u32.KillTimer(self.hwnd, self.TIMER_TICK)
                    u32.ShowWindow(self.hwnd, _TB_SW_HIDE)
            elif kind == "quit":
                self._quitting = True
                u32.PostQuitMessage(0)
                return

    def _rearm_tick(self):
        u32 = ctypes.windll.user32
        if self._visible and len(self._pages) > 1:
            u32.SetTimer(self.hwnd, self.TIMER_TICK, self._interval_ms, None)
        else:
            u32.KillTimer(self.hwnd, self.TIMER_TICK)

    def _push_page(self):
        """推送当前页：位置/尺寸变化才 SetWindowPos（避免跨进程同步调用风暴）,
        内容每次都经 ULW 更新（同尺寸翻页零窗口操作）。"""
        if not self.hwnd or not self._pages:
            return
        img = self._pages[self._page % len(self._pages)]
        w, h = img.size
        geom = _taskbar_geom_for(config.TASKBAR_POSITION, w, h)
        if geom is None:
            return  # 任务栏暂时不存在（explorer 未就绪）,等自愈定时器重试
        x, y = geom
        if (x, y, w, h) != self._last_geom:
            ctypes.windll.user32.SetWindowPos(self.hwnd, 0, x, y, w, h, _TB_SWP_NOACTIVATE)
            self._last_geom = (x, y, w, h)
        push_layered_image(self.hwnd, img, None, None)

    def _heal(self):
        """锚窗口 1s 自愈：父窗口状态对齐配置；重建被销毁的文本窗口。

        可见时每秒重推一次当前页：_push_page 内部仅几何变化才 SetWindowPos,
        因此常驻开销可忽略,但能及时跟随任务栏通知区的水平变化——
        新增托盘图标会使 TrayNotifyWnd 向左扩张,盖住文本条原位置,
        必须把文本条左移让出新空间（实测踩过）。"""
        if self._quitting:
            return
        u32 = ctypes.windll.user32
        if self.hwnd and u32.IsWindow(self.hwnd):
            self._sync_parent()
            if self._visible:
                self._push_page()
            return
        self._create_text_window()  # explorer 重启销毁了子窗口 -> 重建
        if self.hwnd and self._visible:
            u32.ShowWindow(self.hwnd, _TB_SW_SHOWNA)
            self._rearm_tick()
            self._push_page()


class TaskbarText:
    """回答文本条：原生窗口挂为任务栏子窗口,TrafficMonitor 同款架构。

    主线程职责：文本归一化（换行符 -> 空格）、按「每行最大字符数」或像素
    宽度折行、按显示行数切滚动窗口（不截断,逐行轮播）、PIL 渲染每窗口图像；
    窗口的创建/挂接/显隐/轮播/自愈全部由 _TaskbarNative 专用线程处理,
    与 Tk 完全解耦。"""

    PAD_X = 10
    MAX_W = 1000  # 单窗口最大宽度（像素）,防止超长内容撑满整屏

    def __init__(self):
        self._text = t("等待监控...")
        self._font = _load_taskbar_font()
        self._pages = [[""]]
        self._all_lines = [""]  # 全部折行（渲染宽度取其最大值,逐行滚动时条宽稳定）
        self._images = []
        self._shown = False
        self._cmds = queue.Queue()
        self._native = _TaskbarNative(self._cmds)
        self._post_set()

    @property
    def text(self) -> str:
        return self._text  # 已归一化（换行符转空格）；轮播分页只影响渲染

    def _on_map(self, _event=None):  # 兼容旧测试桩
        pass

    @property
    def text(self) -> str:
        return self._text  # 原始文本（不截断；轮播分页只影响渲染）

    # ---- 分页与渲染（主线程） ----
    def _line_h(self) -> int:
        return self._font.size + 8

    def _max_text_width(self) -> int:
        L, T, R, B = _work_area()
        base = max(200, min((R - L) - 2 * self.PAD_X - 16, self.MAX_W))
        if config.TASKBAR_POSITION == "taskbar-right":
            tb = _find_taskbar()
            if tb:  # 任务栏内显示：不超过任务栏客户区宽度的一半
                base = min(base, max(160, tb["cw"] // 2))
        return base

    def _split_pages(self):
        """换行符转空格后折行、按 TASKBAR_MAX_LINES 切成滚动窗口（不截断）。

        TASKBAR_MAX_CHARS_PER_LINE > 0 时按字符数折行,否则按像素宽度折行。
        超过显示行数时切成 len(lines)-n+1 个窗口,相邻窗口滑动一行,
        由原生线程按 TASKBAR_SCROLL_INTERVAL（秒/行）逐个推进实现按行轮播。"""
        text = " ".join(str(self._text).splitlines())  # 换行符 -> 空格
        n_chars = int(config.TASKBAR_MAX_CHARS_PER_LINE)
        if n_chars > 0:
            lines = [text[i:i + n_chars] for i in range(0, len(text), n_chars)] or [""]
        else:
            lines = _wrap_text(text, self._font, self._max_text_width())
        n = max(1, int(config.TASKBAR_MAX_LINES))
        self._all_lines = lines
        if len(lines) <= n:
            self._pages = [lines]
        else:
            self._pages = [lines[i:i + n] for i in range(len(lines) - n + 1)]

    def _render_page(self, lines) -> Image.Image:
        font = self._font
        # 宽度取全部折行的最大值：逐行滚动时条宽保持稳定,
        # 避免每推进一行就 SetWindowPos 一次（跨进程同步调用）
        w = max(120, max(int(font.getlength(ln)) for ln in self._all_lines) + self.PAD_X * 2)
        w = min(w, self._max_text_width() + self.PAD_X * 2)
        line_h = self._line_h()
        # 任务栏内显示：条高与任务栏客户区一致（TrafficMonitor 同款）,
        # 文本块垂直居中；浮动模式保持内容自适应高度
        tb = _find_taskbar() if config.TASKBAR_POSITION == "taskbar-right" else None
        text_h = len(lines) * line_h
        h = tb["ch"] if tb else text_h + 6
        y0 = max(3, (h - text_h) // 2)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=6 if not tb else 0,
            fill=_hex_to_rgb(config.TASKBAR_BG_COLOR) + (int(round(config.TASKBAR_BG_ALPHA * 255)),),
        )
        y = y0
        for ln in lines:
            d.text((self.PAD_X, y), ln, font=font,
                   fill=_hex_to_rgb(config.TASKBAR_TEXT_COLOR)
                   + (int(round(config.TASKBAR_TEXT_ALPHA * 255)),))
            y += line_h
        return img

    def _post_set(self):
        """把当前各滚动窗口的渲染结果经命令队列发给窗口线程。"""
        self._images = [self._render_page(lines) for lines in self._pages]
        self._cmds.put(("set", self._images,
                        max(300, int(config.TASKBAR_SCROLL_INTERVAL * 1000))))
        self._native.notify()

    # ---- 对外接口（与 Overlay 同形） ----
    def set_answer(self, text: str):
        self._text = " ".join(str(text).splitlines())  # 换行符 -> 空格
        self._split_pages()
        self._post_set()

    def apply_config(self):
        """设置变更后实时应用：字体/行数/每行字符数/轮播速度/颜色全部重算。"""
        self._font = _load_taskbar_font()
        self._split_pages()
        self._post_set()

    def show(self):
        self._shown = True
        self._cmds.put(("show",))
        self._native.notify()

    def hide(self):
        self._shown = False
        self._cmds.put(("hide",))
        self._native.notify()

    def toggle(self):
        (self.hide if self.is_visible() else self.show)()

    def is_visible(self):
        # _shown 由主线程维护；窗口真实显隐由窗口线程 ShowWindow 执行
        return bool(self._shown and self._native.hwnd
                    and ctypes.windll.user32.IsWindow(self._native.hwnd))

    def close(self):
        """销毁原生窗口并结束其专用线程（测试收尾用；进程退出由系统清理）。"""
        self._cmds.put(("quit",))
        self._native.notify()
