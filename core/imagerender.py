# -*- coding: utf-8 -*-
"""回答渲染：颜色解析、字体加载、像素折行、浮窗 RGBA 图像绘制。"""
from PIL import Image, ImageDraw, ImageFont

from core.appconfig import config, logger
from core.i18n import t

def _hex_to_rgb(s: str) -> tuple:
    """'#RRGGBB' -> (r, g, b)。非法输入回退白色。"""
    try:
        s = s.strip().lstrip("#")
        if len(s) == 3:  # '#FFF' 简写展开
            s = "".join(ch * 2 for ch in s)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        logger.warning(t("颜色值非法: %r,回退为白色"), s)
        return (255, 255, 255)


_FONT_FILES = {  # 字体名 -> 字体文件（设置对话框与 settings.json 的 font_name 取值）
    "微软雅黑": "msyh.ttc",
    "黑体": "simhei.ttf",
    "宋体": "simsun.ttc",
    "楷体": "simkai.ttf",
    "Arial": "arial.ttf",
}


def _load_font(size_points, preferred: str):
    """按字体名与字号（磅 -> 像素）加载中文字体,逐级回退到雅黑/黑体/Arial。"""
    px = max(8, int(round(size_points * 4 / 3)))  # 磅 -> 像素(96dpi)
    for name in [_FONT_FILES.get(preferred, "msyh.ttc"), "msyh.ttc", "simhei.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(name, px)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _load_overlay_font():
    """按配置字体与字号加载浮窗字体。"""
    preferred = getattr(config, "OVERLAY_FONT_NAME", "微软雅黑")
    return _load_font(config.OVERLAY_FONT_SIZE, preferred)


def _load_taskbar_font():
    """按配置字体与字号加载任务栏文本条字体。"""
    preferred = getattr(config, "TASKBAR_FONT_NAME", "微软雅黑")
    return _load_font(config.TASKBAR_FONT_SIZE, preferred)


def _wrap_text(text: str, font, max_width: int) -> list:
    """按像素宽度逐字符换行（中文/中英混排安全）。保留原始换行。"""
    lines = []
    for raw in str(text).splitlines():
        if not raw:
            lines.append("")
            continue
        cur = ""
        for ch in raw:
            if cur and font.getlength(cur + ch) > max_width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


OVERLAY_PAD = 10  # 浮窗内边距（渲染与分页共用）


def _overlay_line_metrics(font=None):
    """浮窗单行几何：返回 (行高, 每页可容纳行数)。"""
    if font is None:
        font = _load_overlay_font()
    H = int(config.OVERLAY_HEIGHT)
    line_h = max(font.size + 8, 14)
    lines_per_page = max(1, int((H - OVERLAY_PAD * 2 - 8) // line_h))
    return font, line_h, lines_per_page


def overlay_pages(text: str, font=None) -> list:
    """把回答按浮窗高度切成滚动窗口：返回 [每窗口行列表, ...]。

    单屏放得下时返回单窗口（内容完整,永不截断）；放不下时切成
    len(lines)-cap+1 个窗口,相邻窗口滑动一行——调用方按
    OVERLAY_SCROLL_INTERVAL（秒/行）逐个推进即实现按行轮播。"""
    font, _, cap = _overlay_line_metrics(font)
    W = int(config.OVERLAY_WIDTH)
    lines = _wrap_text(text, font, W - OVERLAY_PAD * 2)
    if len(lines) <= cap:
        return [lines]
    return [lines[i:i + cap] for i in range(len(lines) - cap + 1)]


def render_answer_image(text: str, font=None, lines=None, selection=None) -> Image.Image:
    """把回答渲染成 RGBA 浮窗图像：背景与文字各自的不透明度独立生效。

    lines 为 None 时按单屏渲染（放不下显示截断标记,兼容旧行为）；
    调用方传入 overlay_pages() 的某个滚动窗口时按该行列表渲染（轮播用）。
    selection 为 ((行号,字符序),(行号,字符序)) 边界对（含起不含止,可乱序）,
    选中字符以文字色打底、背景色描字（反色高亮）。"""
    W, H = int(config.OVERLAY_WIDTH), int(config.OVERLAY_HEIGHT)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = OVERLAY_PAD
    # 背景（自身不透明度 OVERLAY_BG_ALPHA）
    d.rounded_rectangle(
        [0, 0, W - 1, H - 1], radius=8,
        fill=_hex_to_rgb(config.OVERLAY_BG_COLOR) + (int(round(config.OVERLAY_BG_ALPHA * 255)),),
    )
    # 文字（自身不透明度 OVERLAY_TEXT_ALPHA,自动换行）
    if font is None:
        font = _load_overlay_font()
    fg = _hex_to_rgb(config.OVERLAY_TEXT_COLOR) + (int(round(config.OVERLAY_TEXT_ALPHA * 255)),)
    line_h = max(font.size + 8, 14)
    y = pad + 4
    if lines is None:
        lines, truncated = _wrap_text(text, font, W - pad * 2), False
        for line in lines:
            if y + line_h > H - pad:
                truncated = True
                break
            d.text((pad, y), line, font=font, fill=fg)
            y += line_h
        if truncated:
            d.text((pad, H - pad - line_h), t("…(内容过长已截断)"), font=font, fill=fg)
    else:
        for line in lines:  # 轮播分页：页内行数已由 overlay_pages 保证放得下
            d.text((pad, y), line, font=font, fill=fg)
            y += line_h
    if selection is not None and lines:
        _draw_selection(d, lines, font, line_h, pad, selection)
    return img


def _draw_selection(d: ImageDraw.ImageDraw, lines: list, font, line_h: int, pad: int,
                    selection):
    """选区高亮：选中文字段落以文字色画底条,选中字符用背景色重描（反色）。"""
    (l0, c0), (l1, c1) = selection
    if (l1, c1) < (l0, c0):
        (l0, c0), (l1, c1) = (l1, c1), (l0, c0)
    fg = _hex_to_rgb(config.OVERLAY_TEXT_COLOR) + (int(round(config.OVERLAY_TEXT_ALPHA * 255)),)
    bg = _hex_to_rgb(config.OVERLAY_BG_COLOR) + (255,)
    y = pad + 4
    for li, line in enumerate(lines):
        if l0 <= li <= l1:
            s = c0 if li == l0 else 0
            e = c1 if li == l1 else len(line)
            if e > s:
                x1 = pad + font.getlength(line[:s])
                x2 = pad + font.getlength(line[:e])
                d.rectangle([x1, y, x2, y + line_h - 2], fill=fg)
                d.text((x1, y), line[s:e], font=font, fill=bg)
        y += line_h


def overlay_hit_index(x: float, y: float, lines: list, font) -> tuple:
    """浮窗坐标 -> (行号, 字符边界序号)（拖选命中测试）。

    字符边界序号 0=行首前,len(line)=行尾后；取最近边界。
    坐标越界时收敛到内容四角（行号钳制到实际行范围）。"""
    line_h = max(font.size + 8, 14)
    pad = OVERLAY_PAD
    if not lines:
        return 0, 0
    li = int((y - pad - 4) // line_h)
    li = max(0, min(len(lines) - 1, li))
    line = lines[li]
    xs = [0.0]
    for i in range(1, len(line) + 1):
        xs.append(font.getlength(line[:i]))
    rel = x - pad
    ci = min(range(len(xs)), key=lambda i: abs(xs[i] - rel))
    return li, ci
