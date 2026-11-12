# -*- coding: utf-8 -*-
"""大模型调用（OpenAI 兼容 /chat/completions,JPEG 上传,指数退避重试）。

支持可选的"图像转文字"二段式：先调用视觉模型把截图转成文字描述,
把描述嵌入主模型提示词后以**纯文本**请求主模型——借此支持纯文本
大语言模型（主模型无需图片输入能力）。未配置图像转文字模型时,
截图直接发给主模型（原视觉模型路径）。

转写结果嵌入提示词（指定位置）：主模型提示词含动态变量 {{OCR_TEXT}}
（不区分大小写,容错手误 {{ORC_TEXT}}）时替换为转写结果;均未出现时
以「【图片内容转写】」小节追加到提示词末尾。"""
import io
import re
import time
import threading
import base64

import requests
from PIL import Image

from core.appconfig import config, logger
from core.i18n import t

# ------------------------- 大模型调用（OpenAI 兼容） -------------------------
_HTTP_SESSION = requests.Session()   # 模块级复用 TCP/TLS 连接（keep-alive）,省去每次握手
_HTTP_LOCK = threading.Lock()        # 定时线程与手动触发线程串行化,规避 Session 并发边界

# 图像转文字阶段的内置默认指令：只做忠实转写,不回答问题（回答由主模型完成）。
# 可在设置中配置自定义指令（config.LLM_OCR_PROMPT）,留空即使用本指令。
OCR_PROMPT = "请原样输出图片中的全部文字内容，不要回答、不要解释。"


def _jpeg_data_url(image: Image.Image) -> str:
    """截图 -> base64 data URL（JPEG 有损编码：体积比 PNG 小 60-80%,缩短上传耗时）。"""
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=config.LLM_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _retry_after_seconds(response) -> float | None:
    """解析 429 响应的 Retry-After 头（秒数或 HTTP 日期）,无/非法返回 None。"""
    if response is None:
        return None
    val = response.headers.get("Retry-After")
    if not val:
        return None
    try:
        return max(0.0, float(val))
    except ValueError:
        pass
    try:  # HTTP 日期格式（如 "Wed, 21 Oct 2026 07:28:00 GMT"）
        from email.utils import parsedate_to_datetime
        delta = parsedate_to_datetime(val) - __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)
        return max(0.0, delta.total_seconds())
    except Exception:  # noqa: BLE001
        return None


def _flat(s: str) -> str:
    """压平多行文本为单行日志（换行转义为 \\n,保留内容原样）。"""
    return str(s).replace("\r", "").replace("\n", "\\n")


def _log_request_info(tag: str, url: str, payload: dict):
    """记录一次模型调用的请求信息：调用地址 / 模型名 / 提示词（含附图标注）。"""
    msg = payload["messages"][0]
    content = msg.get("content", "")
    if isinstance(content, str):
        text, has_img = content, False
    else:
        text = "".join(p.get("text", "") for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
        has_img = any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)
    logger.info(t("[%s] 调用地址: %s | 模型: %s%s"), tag, url, payload.get("model", ""),
                t(" | 附图: 是") if has_img else "")
    logger.info(t("[%s] 提示词: %s"), tag, _flat(text))


def _chat_with_retry(url: str, headers: dict, payload: dict, tag: str) -> str:
    """统一的请求+重试；最终失败抛异常（由调用方决定降级方式）。

    每次调用在日志记录请求信息（地址/模型/提示词）与返回消息；
    重试不重复记请求信息（内容不变,失败行已含次数）。
    429（限流）单独处理：优先遵循服务端 Retry-After 头,否则用更长的
    退避间隔（5s 起步指数增长,上限 60s）——限流窗口通常持续数秒以上,
    普通错误的短退避（1s/2s/4s）对限流基本无效,只会连续撞墙。
    """
    _log_request_info(tag, url, payload)
    for attempt in range(config.LLM_RETRY + 1):
        try:
            with _HTTP_LOCK:  # Session 非线程安全保证：串行化所有 LLM 请求
                r = _HTTP_SESSION.post(url, json=payload, headers=headers, timeout=config.LLM_TIMEOUT)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            logger.info(t("[%s] 返回消息: %s"), tag, _flat(content))
            return content
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", 0) or 0
            if status == 429:
                wait = _retry_after_seconds(e.response)
                src = t("（服务端指定）") if wait is not None else ""
                if wait is None:
                    wait = min(5 * (2 ** attempt), 60)  # 5s -> 10s -> 20s -> 40s -> 60s
                logger.warning(t("%s 调用失败(第%d次): %s；已限流,%g 秒后重试%s"),
                               tag, attempt + 1, e, wait, src)
                if attempt == config.LLM_RETRY:
                    raise
                time.sleep(wait)
            else:
                logger.warning(t("%s 调用失败(第%d次): %s"), tag, attempt + 1, e)
                if attempt == config.LLM_RETRY:
                    raise
                # 指数退避：1s -> 2s -> 4s...（上限 8s）
                time.sleep(min(2 ** attempt, 8))


def _ocr_enabled() -> bool:
    """图像转文字模型是否已配置（端点+模型必填;密钥可为空以支持本地服务）。"""
    return bool(getattr(config, "LLM_OCR_BASE_URL", "") and getattr(config, "LLM_OCR_MODEL", ""))


def fetch_models(base_url: str, api_key: str, timeout: int | None = None) -> list:
    """查询 OpenAI 兼容端点的可用模型列表（GET /models）。

    返回模型 id 列表（排序去重）；请求失败抛异常,由调用方提示。
    兼容两种返回格式：{"data": [{"id": ...}, ...]} 与纯列表。"""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with _HTTP_LOCK:  # 与对话请求共用 Session,同样串行化
        r = _HTTP_SESSION.get(url, headers=headers, timeout=timeout or config.LLM_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    ids = []
    for it in items or []:
        mid = it.get("id") if isinstance(it, dict) else str(it)
        if mid:
            ids.append(str(mid))
    return sorted(set(ids))


def describe_image(data_url: str) -> str | None:
    """二段式第一步：把截图交给图像转文字模型,返回内容转写文本。

    未配置返回 None；调用失败记日志并返回 None（回退为截图直发主模型）。"""
    if not _ocr_enabled():
        return None
    # 转写指令：设置里配置了自定义指令则用之,否则用内置默认指令
    ocr_prompt = str(getattr(config, "LLM_OCR_PROMPT", "")).strip() or OCR_PROMPT
    payload = {
        "model": config.LLM_OCR_MODEL,
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": ocr_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}
        ],
        "temperature": 0.1,  # 转写任务求稳,温度取低
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_OCR_API_KEY}",
        "Content-Type": "application/json",
    }
    url = config.LLM_OCR_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        return _chat_with_retry(url, headers, payload, t("图像转文字模型"))
    except Exception as e:  # noqa: BLE001
        logger.warning(t("图像转文字失败,回退为截图直发主模型: %s"), e)
        return None


def ask_llm(image: Image.Image) -> str:
    data_url = _jpeg_data_url(image)

    # 二段式：截图先转文字,描述嵌入提示词后以纯文本请求主模型（支持纯文本大语言模型）
    # 嵌入位置：动态变量 {{OCR_TEXT}}（不区分大小写,容错手误 {{ORC_TEXT}}）时
    # 替换为转写结果;未出现时以「【图片内容转写】」小节追加到提示词末尾
    desc = describe_image(data_url)
    if desc:
        prompt = config.LLM_PROMPT
        if re.search(r"\{\{\s*(?:OCR|ORC)_TEXT\s*\}\}", prompt, re.IGNORECASE):
            prompt = re.sub(r"\{\{\s*(?:OCR|ORC)_TEXT\s*\}\}", lambda _m: desc, prompt,
                            flags=re.IGNORECASE)  # lambda 替换,避免转写结果含反斜杠被转义
        elif prompt:
            prompt = (f"{prompt}\n\n【图片内容转写（由图像转文字模型生成）】\n"
                      f"{desc}")
        else:  # 主提示词留空：仅发送转写内容本身
            prompt = f"【图片内容转写（由图像转文字模型生成）】\n{desc}"
        content = [{"type": "text", "text": prompt}]
    else:
        content = []
        if config.LLM_PROMPT:  # 主提示词留空时不发送空文本段（部分端点会拒绝空 text）
            content.append({"type": "text", "text": config.LLM_PROMPT})
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": config.LLM_TEMPERATURE,
    }
    if config.LLM_MAX_TOKENS and config.LLM_MAX_TOKENS > 0:
        payload["max_tokens"] = config.LLM_MAX_TOKENS  # 0/负数 = 不限制,不下发该字段
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        return _chat_with_retry(url, headers, payload, "LLM")
    except Exception as e:  # noqa: BLE001
        return t("[错误] {err}").format(err=e)
