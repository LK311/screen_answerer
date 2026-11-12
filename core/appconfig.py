# -*- coding: utf-8 -*-
"""配置模块：settings.json <-> config 命名空间、日志初始化。

- _Config：简单命名空间,业务代码以 config.XXX 访问（模块级单例 config）
- load_config/save_config：settings.json 读写（原子替换、损坏容错）
- setup_logging：启动即重置日志文件（覆盖写入）并输出到控制台

import 本模块即完成配置解析与日志初始化（测试亦复用此实例）。"""
import os
import sys
import json
import logging

import core.i18n as i18n
from core.i18n import t

# 程序所在目录（配置/日志/记录均相对此目录,兼容 PyInstaller 打包后运行）
# 注意：onefile 模式下 __file__ 指向临时解压目录,必须改用 exe 所在目录,
# 否则启动时读不到同目录的 settings.json、日志与记录会写进临时目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    # 开发态：本文件在 core/ 子包内,上跳一级才是项目根（settings.json/app.log 所在）
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# 版本与项目主页（设置窗口「通用」页「关于」块展示;发布新版本时同步更新此处
# 与 assets/version_info.txt 的 filevers/FileVersion）
APP_VERSION = "1.0.0"
GITHUB_URL = "https://github.com/LK311/screen_answerer"

# ------------------------- 配置（settings.json <-> config 命名空间） -------------------------
class _Config:
    """简单命名空间：加载 settings.json 后把所有配置项挂成属性,
    业务代码以 config.XXX 访问。"""


def _to_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _as_bool(v) -> bool:
    """手改 JSON 兼容：bool("false") 是 True,字符串布尔必须显式转换。"""
    if isinstance(v, str):
        return _to_bool(v)
    return bool(v)


def _to_region(v: str):
    parts = [p.strip() for p in str(v).replace("(", "").replace(")", "").split(",")]
    vals = [int(float(p)) for p in parts if p]
    if len(vals) != 4:
        raise ValueError(f"region 应为 4 个数字 (left, top, width, height),实际: {v!r}")
    return tuple(vals)


# 默认配置：settings.json 缺失时使用；加载时逐键回退（新增键自动取默认值）
_DEFAULT_SETTINGS = {
    "capture": {
        "capture_interval": 3.0,
        "monitor_index": 1,
        "region": [292, 368, 1052, 364],
        "compare_method": "dhash",
        "change_threshold": 10,
        "ignore_cursor": True,
        "cooldown": 5.0,
    },
    "llm": {
        "active": "默认",
        "profiles": {
            "默认": {
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key": "",
                "model": "glm-4v-flash",
                "prompt": "",         # 主模型指令（留空=不附加指令,截图/转写直发）
                "temperature": 0.2,
                "max_tokens": 0,
                "timeout": 30,
                "retry": 2,
                "send_max_edge": 0,
                "jpeg_quality": 85,
                "ocr_base_url": "",   # 可选：图像转文字模型端点（留空=不启用,截图直发主模型）
                "ocr_api_key": "",
                "ocr_model": "",
                "ocr_prompt": "请原样输出图片中的全部文字内容，不要回答、不要解释。",
                                      # 图像转文字指令（留空=使用内置默认转写指令）
            }
        },
    },
    "overlay": {
        "answer_mode": "overlay",  # 回答展示方式：overlay=桌面浮窗 / taskbar=任务栏文本条
        "x": 1400, "y": 150, "width": 500, "height": 300,
        "bg_color": "#000000", "bg_alpha": 0.3,
        "text_color": "#FFFFFF", "text_alpha": 1.0,
        "font_size": 10, "font_name": "微软雅黑",
        "always_on_top": True, "click_through": True,
        "scroll_interval": 2.0,       # 轮播速度：每行滚动间隔秒数（0=不轮播,超出截断）
    },
    "taskbar": {
        "position": "taskbar-right",  # taskbar-right=嵌入任务栏；bottom/top × left/center/right=浮动停靠
        "max_lines": 1,               # 显示行数（1~10）,超出按行轮播
        "max_chars_per_line": 0,      # 每行最大字符数（0=按像素宽度自动折行）
        "scroll_interval": 2.0,       # 轮播速度：每行滚动间隔秒数（0.5~60）
        "font_size": 12, "font_name": "微软雅黑",
        "text_color": "#FFFFFF", "text_alpha": 1.0,
        "bg_color": "#1A1A1A", "bg_alpha": 0.3,
    },
    "region_rect": {"show": False, "color": "#00FFFF", "alpha": 1},
    "startup": {"monitor_paused": True, "overlay_hidden": False},
    "general": {"language": "zh"},  # 界面语言：zh=中文 / en=English（重启后生效）
    "hotkeys": {
        "select_region": "ctrl+shift+f1",
        "manual_trigger": "ctrl+shift+f2",
        "toggle_monitor": "ctrl+shift+f3",
        "toggle_overlay": "ctrl+shift+f4",
        "toggle_rect": "ctrl+shift+f5",
    },
    "storage": {"artifacts_dir": "QA_History", "save_artifacts": True},
    "log": {"level": "INFO", "file": "app.log"},
}

_LLM_PROFILE_KEYS = ("base_url", "api_key", "model", "prompt", "temperature",
                     "max_tokens", "timeout", "retry", "send_max_edge", "jpeg_quality",
                     "ocr_base_url", "ocr_api_key", "ocr_model", "ocr_prompt")


def _deep_update(base: dict, over: dict) -> dict:
    """递归合并：over 覆盖 base 的同名标量键,子 dict 深合并（新增键自动补默认）。"""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def _config_to_dict(c: _Config) -> dict:
    def _rel(p: str) -> str:
        try:
            return os.path.relpath(p, BASE_DIR)
        except ValueError:  # 跨盘符
            return p

    return {
        "capture": {
            "capture_interval": c.CAPTURE_INTERVAL, "monitor_index": c.MONITOR_INDEX,
            "region": list(c.REGION), "compare_method": c.COMPARE_METHOD,
            "change_threshold": c.CHANGE_THRESHOLD, "ignore_cursor": c.IGNORE_CURSOR,
            "cooldown": c.COOLDOWN,
        },
        "llm": {"active": c.LLM_ACTIVE, "profiles": c.LLM_PROFILES},
        "overlay": {
            "answer_mode": c.ANSWER_MODE,
            "x": c.OVERLAY_X, "y": c.OVERLAY_Y, "width": c.OVERLAY_WIDTH, "height": c.OVERLAY_HEIGHT,
            "bg_color": c.OVERLAY_BG_COLOR, "bg_alpha": c.OVERLAY_BG_ALPHA,
            "text_color": c.OVERLAY_TEXT_COLOR, "text_alpha": c.OVERLAY_TEXT_ALPHA,
            "font_size": c.OVERLAY_FONT_SIZE, "font_name": c.OVERLAY_FONT_NAME,
            "always_on_top": c.OVERLAY_ALWAYS_ON_TOP, "click_through": c.OVERLAY_CLICK_THROUGH,
            "scroll_interval": c.OVERLAY_SCROLL_INTERVAL,
        },
        "taskbar": {
            "position": c.TASKBAR_POSITION, "max_lines": c.TASKBAR_MAX_LINES,
            "max_chars_per_line": c.TASKBAR_MAX_CHARS_PER_LINE,
            "scroll_interval": c.TASKBAR_SCROLL_INTERVAL,
            "font_size": c.TASKBAR_FONT_SIZE, "font_name": c.TASKBAR_FONT_NAME,
            "text_color": c.TASKBAR_TEXT_COLOR, "text_alpha": c.TASKBAR_TEXT_ALPHA,
            "bg_color": c.TASKBAR_BG_COLOR, "bg_alpha": c.TASKBAR_BG_ALPHA,
        },
        "region_rect": {"show": c.REGION_RECT_SHOW, "color": c.REGION_RECT_COLOR,
                        "alpha": c.REGION_RECT_ALPHA},
        "startup": {"monitor_paused": c.MONITOR_START_PAUSED, "overlay_hidden": c.OVERLAY_START_HIDDEN},
        "general": {"language": c.LANGUAGE},
        "hotkeys": {
            "select_region": c.SELECT_REGION_HOTKEY, "manual_trigger": c.MANUAL_TRIGGER_HOTKEY,
            "toggle_monitor": c.TOGGLE_MONITOR_HOTKEY, "toggle_overlay": c.TOGGLE_OVERLAY_HOTKEY,
            "toggle_rect": c.TOGGLE_RECT_HOTKEY,
        },
        "storage": {"artifacts_dir": _rel(c.ARTIFACTS_DIR), "save_artifacts": c.SAVE_ARTIFACTS},
        "log": {"level": c.LOG_LEVEL, "file": _rel(c.LOG_FILE)},
    }


def save_config(c: _Config = None) -> bool:
    """把当前配置写回 settings.json（临时文件 + 原子替换,失败不破坏原文件）。"""
    try:
        if c is None:
            c = config
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_config_to_dict(c), f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(t("写回 settings.json 失败（仅本次运行生效）: %s"), e)
        return False


def load_config(path: str = SETTINGS_FILE) -> _Config:
    """加载 settings.json（缺失/非法键回退默认值）。"""
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("settings.json 顶层应为对象")
        except Exception as e:  # noqa: BLE001
            logging.getLogger().warning("settings.json 解析失败（%s）,改用默认配置；原文件备份为 .corrupt", e)
            try:
                os.replace(path, path + ".corrupt")
            except OSError:
                pass
            data = {}

    merged = _deep_update(json.loads(json.dumps(_DEFAULT_SETTINGS)), data)
    if isinstance(data.get("llm"), dict) and isinstance(data["llm"].get("profiles"), dict):
        # 大模型方案列表整体替换（不做深合并）：用户删除的方案不应被默认值复活
        merged["llm"]["profiles"] = data["llm"]["profiles"]
    c = _Config()

    # ---- capture ----
    cap = merged["capture"]
    c.CAPTURE_INTERVAL = float(cap["capture_interval"])
    c.MONITOR_INDEX = int(cap["monitor_index"])
    region = cap["region"]
    if isinstance(region, str):  # 手改 JSON：可能是 "l, t, w, h" 字符串
        c.REGION = _to_region(region)
    else:
        c.REGION = tuple(int(v) for v in region)
    c.COMPARE_METHOD = str(cap["compare_method"]).strip()
    c.CHANGE_THRESHOLD = int(cap["change_threshold"])
    c.IGNORE_CURSOR = _as_bool(cap["ignore_cursor"])
    c.COOLDOWN = float(cap["cooldown"])

    # ---- llm（多方案） ----
    llm = merged["llm"]
    c.LLM_PROFILES = llm.get("profiles") or {}
    if not isinstance(c.LLM_PROFILES, dict) or not c.LLM_PROFILES:
        c.LLM_PROFILES = dict(_DEFAULT_SETTINGS["llm"]["profiles"])
    active = llm.get("active")
    if active not in c.LLM_PROFILES:
        active = next(iter(c.LLM_PROFILES))
    c.LLM_ACTIVE = active
    prof = c.LLM_PROFILES[active]
    c.LLM_BASE_URL = str(prof.get("base_url", "")).strip()
    c.LLM_API_KEY = str(prof.get("api_key", "")).strip()
    c.LLM_MODEL = str(prof.get("model", "")).strip()
    c.LLM_PROMPT = str(prof.get("prompt", "")).strip()
    c.LLM_TEMPERATURE = _clamp01(prof.get("temperature", 0.2))
    c.LLM_MAX_TOKENS = int(prof.get("max_tokens", 0))
    c.LLM_TIMEOUT = int(prof.get("timeout", 30))
    c.LLM_RETRY = int(prof.get("retry", 2))
    c.SEND_MAX_EDGE = int(prof.get("send_max_edge", 0))
    c.LLM_JPEG_QUALITY = max(1, min(95, int(prof.get("jpeg_quality", 85))))
    # 可选图像转文字模型（三项全配才启用）：先把截图转成文字嵌入提示词,再交主模型回答
    c.LLM_OCR_BASE_URL = str(prof.get("ocr_base_url", "")).strip()
    c.LLM_OCR_API_KEY = str(prof.get("ocr_api_key", "")).strip()
    c.LLM_OCR_MODEL = str(prof.get("ocr_model", "")).strip()
    # 图像转文字指令：留空时 describe_image 回退为内置固定转写指令 OCR_PROMPT
    c.LLM_OCR_PROMPT = str(prof.get("ocr_prompt", "")).strip()

    # ---- overlay ----
    ov = merged["overlay"]
    mode = str(ov.get("answer_mode", "overlay")).strip().lower()
    c.ANSWER_MODE = mode if mode in ("overlay", "taskbar") else "overlay"
    c.OVERLAY_X = int(ov["x"]); c.OVERLAY_Y = int(ov["y"])
    c.OVERLAY_WIDTH = int(ov["width"]); c.OVERLAY_HEIGHT = int(ov["height"])
    c.OVERLAY_BG_COLOR = str(ov["bg_color"]).strip()
    c.OVERLAY_BG_ALPHA = _clamp01(ov["bg_alpha"])
    c.OVERLAY_TEXT_COLOR = str(ov["text_color"]).strip()
    c.OVERLAY_TEXT_ALPHA = _clamp01(ov["text_alpha"])
    c.OVERLAY_FONT_SIZE = int(ov["font_size"])
    c.OVERLAY_FONT_NAME = str(ov.get("font_name", "微软雅黑")).strip()
    c.OVERLAY_ALWAYS_ON_TOP = _as_bool(ov["always_on_top"])
    c.OVERLAY_CLICK_THROUGH = _as_bool(ov["click_through"])
    c.OVERLAY_SCROLL_INTERVAL = max(0.0, min(60.0, float(ov.get("scroll_interval", 2.0))))

    # ---- taskbar（任务栏文本条） ----
    tb = merged["taskbar"]
    c.TASKBAR_POSITION = str(tb.get("position", "taskbar-right")).strip().lower()
    if c.TASKBAR_POSITION not in ("taskbar-right",
                                  "bottom-left", "bottom-center", "bottom-right",
                                  "top-left", "top-center", "top-right"):
        c.TASKBAR_POSITION = "taskbar-right"
    c.TASKBAR_MAX_LINES = max(1, min(10, int(tb["max_lines"])))
    c.TASKBAR_MAX_CHARS_PER_LINE = max(0, min(200, int(tb.get("max_chars_per_line", 0))))
    c.TASKBAR_SCROLL_INTERVAL = max(0.5, min(60.0, float(tb["scroll_interval"])))
    c.TASKBAR_FONT_SIZE = int(tb["font_size"])
    c.TASKBAR_FONT_NAME = str(tb.get("font_name", "微软雅黑")).strip()
    c.TASKBAR_TEXT_COLOR = str(tb["text_color"]).strip()
    c.TASKBAR_TEXT_ALPHA = _clamp01(tb.get("text_alpha", 1.0))
    c.TASKBAR_BG_COLOR = str(tb["bg_color"]).strip()
    c.TASKBAR_BG_ALPHA = _clamp01(tb["bg_alpha"])

    # ---- region_rect ----
    rr = merged["region_rect"]
    c.REGION_RECT_SHOW = _as_bool(rr["show"])
    c.REGION_RECT_COLOR = str(rr["color"]).strip()
    c.REGION_RECT_ALPHA = _clamp01(rr["alpha"])

    # ---- startup ----
    su = merged["startup"]
    c.MONITOR_START_PAUSED = _as_bool(su["monitor_paused"])
    c.OVERLAY_START_HIDDEN = _as_bool(su["overlay_hidden"])

    # ---- general ----
    c.LANGUAGE = str(merged["general"].get("language", "zh")).strip().lower()
    if c.LANGUAGE not in i18n.LANGUAGES:
        c.LANGUAGE = "zh"

    # ---- hotkeys ----
    hk = merged["hotkeys"]
    c.SELECT_REGION_HOTKEY = str(hk["select_region"]).strip()
    c.MANUAL_TRIGGER_HOTKEY = str(hk["manual_trigger"]).strip()
    c.TOGGLE_MONITOR_HOTKEY = str(hk["toggle_monitor"]).strip()
    c.TOGGLE_OVERLAY_HOTKEY = str(hk["toggle_overlay"]).strip()
    c.TOGGLE_RECT_HOTKEY = str(hk["toggle_rect"]).strip()

    # ---- storage / log ----
    c.ARTIFACTS_DIR = os.path.join(BASE_DIR, str(merged["storage"]["artifacts_dir"]).strip())
    c.SAVE_ARTIFACTS = _as_bool(merged["storage"].get("save_artifacts", True))
    c.LOG_LEVEL = str(merged["log"]["level"]).strip().upper()
    c.LOG_FILE = os.path.join(BASE_DIR, str(merged["log"]["file"]).strip())

    if not os.path.exists(path):
        if save_config(c):
            # 此时模块级 logger 尚未建立,记录到函数属性,setup_logging 后补记
            load_config.init_note = "已生成默认配置 settings.json"
    return c


load_config.init_note = None


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def setup_logging(level: str = "INFO", logfile: str = None) -> logging.Logger:
    """启动即重置日志文件（mode='w' 覆盖写入）,同时输出到控制台。

    PyInstaller --noconsole 模式下 sys.stdout/stderr 为 None,
    控制台 handler 自动跳过,仅写文件。"""
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()
    if sys.stdout is not None or sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    if logfile:
        try:
            fh = logging.FileHandler(logfile, mode="w", encoding="utf-8")  # 每次启动重置
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception as e:  # noqa: BLE001
            root.warning(t("日志文件创建失败（仅控制台输出）: {err}").format(err=e))
    return logging.getLogger("screen_answerer")


# 模块级加载：import main 即完成配置解析（测试亦复用此实例）
config = load_config()
logger = setup_logging(config.LOG_LEVEL, config.LOG_FILE)
if load_config.init_note:
    logger.info(load_config.init_note)
    load_config.init_note = None
# 界面语言一次性设定（进程启动时）：设置窗口切换仅写盘,重启后此处生效
i18n.set_language(config.LANGUAGE)

# ------------------------- 将区域持久化（settings.json） -------------------------
def save_region(region):
    config.REGION = tuple(region)
    if save_config():
        logger.info(t("监控区域已更新并持久化: {region}").format(region=region))
    else:
        logger.warning(t("监控区域仅本次运行生效（settings.json 写盘失败）"))
