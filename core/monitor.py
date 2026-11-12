# -*- coding: utf-8 -*-
"""监控子系统：区域截屏、dHash 变化检测、后台监控工作线程。"""
import time
import queue
import threading

import mss
from PIL import Image

from core.appconfig import config, logger
from core.i18n import t
from core.llmclient import ask_llm
from core.artifacts import save_artifacts

# ------------------------- 截屏 -------------------------
def capture_region(sct=None) -> Image.Image:
    """截取 config.REGION 区域。可传入复用的 mss 实例（同一线程内复用,
    避免每轮截屏都重新初始化）,不传则临时创建。"""
    left, top, w, h = config.REGION
    box = {"left": left, "top": top, "width": w, "height": h}
    if sct is not None:
        grab = sct.grab(box)
    else:
        with mss.MSS() as tmp:
            grab = tmp.grab(box)
    img = Image.frombytes("RGB", grab.size, grab.bgra, "raw", "BGRX")
    if config.SEND_MAX_EDGE and max(img.size) > config.SEND_MAX_EDGE:
        img.thumbnail((config.SEND_MAX_EDGE, config.SEND_MAX_EDGE))
    return img


# ------------------------- 变化检测（dHash + 亮度分层） -------------------------
def dhash(image: Image.Image, size: int = 8):
    """dHash 梯度位 + 4 位整体亮度分层。

    纯 dHash 对均匀纯色图像是盲的（全白与全黑哈希相同）,
    追加亮度分层位后,整屏反色/明暗切换也能被检测为"新图像"。
    """
    # BILINEAR 足够：9x8 缩略图上与 LANCZOS 哈希结果几乎无差,但更快
    g = image.convert("L").resize((size + 1, size), Image.Resampling.BILINEAR)
    px = list(g.getdata())
    width = size + 1
    bits = []
    # 梯度位：捕捉文字/边缘等结构变化
    for y in range(size):
        row = y * width
        for x in range(size):
            bits.append(px[row + x] > px[row + x + 1])
    # 亮度分层位：捕捉均匀图像的整体明暗变化（16 级）
    mean = sum(px) / len(px)
    level = int(mean) >> 4  # 0..15
    bits.extend(bool(level & (1 << i)) for i in range(4))
    return bits


def hamming(a, b) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


# ------------------------- 监控工作线程 -------------------------
class MonitorWorker(threading.Thread):
    def __init__(self, out_queue: queue.Queue):
        super().__init__(daemon=True)
        self._out = out_queue
        self._stop_evt = threading.Event()
        self._paused = False
        self._last_hash = None
        self._last_call = 0.0
        self._stable_logged = False  # 稳定态日志只记一次,避免每轮刷屏

    def stop(self):
        self._stop_evt.set()

    def toggle_paused(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def reset_baseline(self):
        self._last_hash = None

    def run(self):
        with mss.MSS() as sct:  # 线程内复用截屏实例,降低每轮开销
            while not self._stop_evt.is_set():
                if self._paused:
                    self._stop_evt.wait(config.CAPTURE_INTERVAL)
                    continue
                try:
                    img = capture_region(sct)
                    h = dhash(img)
                    if self._last_hash is None or hamming(self._last_hash, h) > config.CHANGE_THRESHOLD:
                        logger.info(t("检测到画面变化"))
                        self._stable_logged = False
                        self._last_hash = h
                        now = time.time()
                        if now - self._last_call >= config.COOLDOWN:
                            self._last_call = now
                            self._out.put(("answer", "..."))
                            ans = ask_llm(img)
                            try:
                                if save_artifacts(img, ans)[0] is not None:
                                    logger.info(t("已保存分析记录"))
                            except Exception as e:  # noqa: BLE001
                                logger.warning(t("保存分析记录失败: %s"), e)
                            self._out.put(("answer", ans))
                    else:
                        if not self._stable_logged:
                            logger.info(t("画面未变化"))
                            self._stable_logged = True
                except Exception as e:  # noqa: BLE001
                    self._out.put(("answer", t("[捕获错误] {err}").format(err=e)))
                self._stop_evt.wait(config.CAPTURE_INTERVAL)
