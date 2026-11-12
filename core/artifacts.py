# -*- coding: utf-8 -*-
"""问答历史：问题截图与回答按日期存放同一目录,历史永久保留（可用 SAVE_ARTIFACTS 关闭）。

目录结构：ARTIFACTS_DIR/YYYY-MM-DD/<时间戳>.png + <时间戳>.txt（同戳成对）。
不再启动清空——旧版"每次启动清空、截图与回答分 images/answers 两目录"的行为已移除。"""
import os
from datetime import datetime

from PIL import Image

from core.appconfig import config

# ------------------------- 问答历史：按日期存放,逐次保存 -------------------------


def save_artifacts(img: Image.Image, answer: str):
    """保存一次分析的问题截图与回答到**当天日期子目录**（同一目录,文件名同戳配对）。

    返回 (图片路径, 回答路径)；「通用 → 记录分析截图与回答」关闭时不落盘,
    返回 (None, None)。"""
    if not getattr(config, "SAVE_ARTIFACTS", True):
        return None, None
    now = datetime.now()
    day_dir = os.path.join(config.ARTIFACTS_DIR, now.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)  # 自建目录（含日期子目录）
    stem = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 含毫秒,避免同秒冲突
    img_path = os.path.join(day_dir, stem + ".png")
    ans_path = os.path.join(day_dir, stem + ".txt")
    img.save(img_path)
    with open(ans_path, "w", encoding="utf-8") as f:
        f.write(answer)
    return img_path, ans_path
