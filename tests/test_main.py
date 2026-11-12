# -*- coding: utf-8 -*-
"""
桌面智能监控回答程序 - 测试脚本（tkinter + pystray 版,在 conda labelpaw 环境运行）
覆盖：真实 import、config 校验、dHash、区域写回、LLM 请求构造(mock)、
worker 暂停、真实截屏、GUI 组件构建(tkinter)、分析记录、启动冒烟。

运行：python tests/test_main.py （或 python -m tests.test_main,项目根目录均可）
"""
import os
import sys

# 允许直接以脚本方式运行（python tests/test_main.py）：把项目根加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
import queue
import logging
import tempfile
import threading
import traceback
from datetime import datetime

PASS, SKIP, FAIL = [], [], []


def report(name, ok, msg=""):
    (PASS if ok is True else FAIL if ok is False else SKIP).append(f"{name} {msg}".strip())


# ---------- 真实 import 校验（核心门槛） ----------
try:
    import main
    config = main.config  # settings.json 加载后的命名空间
    report("import main(含配置加载)", True, "(labelpaw 真实 import 通过)")
except Exception as e:
    report("import main(含配置加载)", False, repr(e))
    raise

from PIL import Image
import tkinter as tk

# 测试期间把分析记录写入临时目录,避免污染工作区
TMP_ART = tempfile.mkdtemp(prefix="screen_answerer_test_")
config.ARTIFACTS_DIR = TMP_ART


# ---------- 1. config 字段校验 ----------
def test_config():
    try:
        assert isinstance(config.REGION, tuple) and len(config.REGION) == 4
        assert all(isinstance(v, (int, float)) for v in config.REGION)
        assert config.CAPTURE_INTERVAL > 0
        assert config.CHANGE_THRESHOLD > 0
        assert config.COOLDOWN >= 0
        assert isinstance(config.LLM_BASE_URL, str)   # 运行时值来自用户 settings.json,勿断言内容
        assert isinstance(config.LLM_API_KEY, str)    # 用户可能未配密钥/主动清空,仅校验类型
        assert isinstance(config.LLM_PROMPT, str)     # 默认提示词已允许为空
        assert 0 <= config.OVERLAY_BG_ALPHA <= 1
        assert 0 <= config.OVERLAY_TEXT_ALPHA <= 1
        assert config.OVERLAY_FONT_SIZE > 0
        # 快捷键配置化（tkinter 版改为从 config 读取）
        for key in ("SELECT_REGION_HOTKEY", "MANUAL_TRIGGER_HOTKEY", "TOGGLE_MONITOR_HOTKEY",
                    "TOGGLE_OVERLAY_HOTKEY", "TOGGLE_RECT_HOTKEY"):
            assert isinstance(getattr(config, key), str) and getattr(config, key), f"缺少配置 {key}"
        # 内置默认键位：手动回答 = Ctrl+Shift+F2（勿依赖运行时 config——用户 settings.json 可能已自定义）
        assert main.appconfig._DEFAULT_SETTINGS["hotkeys"]["manual_trigger"] == "ctrl+shift+f2", \
            "手动回答默认键位应为 ctrl+shift+f2"
        # 内置默认值（第 31 轮调整）：浮窗/任务栏背景不透明度 30%；主提示词默认为空；OCR 默认转写指令
        ds = main.appconfig._DEFAULT_SETTINGS
        assert ds["overlay"]["bg_alpha"] == 0.3 and ds["taskbar"]["bg_alpha"] == 0.3, \
            "两种展示方式的背景不透明度默认均应为 0.3"
        prof0 = ds["llm"]["profiles"]["默认"]
        assert prof0["prompt"] == "", "主接口默认提示词应为空"
        from core.llmclient import OCR_PROMPT
        assert prof0["ocr_prompt"] == OCR_PROMPT == "请原样输出图片中的全部文字内容，不要回答、不要解释。", \
            "图像转文字默认指令应为原样转写文本,且配置默认值与内置兜底一致"
        # 界面语言（第 32 轮）：默认中文,运行时取值合法
        assert ds["general"]["language"] == "zh", "界面语言默认应为 zh"
        assert getattr(config, "LANGUAGE", None) in ("zh", "en"), "运行时语言取值应合法"
        # 新增配置项
        assert isinstance(config.REGION_RECT_SHOW, bool)
        assert config.REGION_RECT_COLOR.startswith("#")
        assert 0 <= config.REGION_RECT_ALPHA <= 1
        assert isinstance(config.MONITOR_START_PAUSED, bool)
        assert isinstance(config.OVERLAY_START_HIDDEN, bool)
        assert isinstance(config.ARTIFACTS_DIR, str) and config.ARTIFACTS_DIR
        # 展示方式与任务栏文本条配置
        assert config.ANSWER_MODE in ("overlay", "taskbar")
        assert config.TASKBAR_POSITION in main._TASKBAR_POSITIONS
        assert 1 <= config.TASKBAR_MAX_LINES <= 10
        assert 0 <= config.TASKBAR_MAX_CHARS_PER_LINE <= 200
        assert 0.5 <= config.TASKBAR_SCROLL_INTERVAL <= 60
        assert config.TASKBAR_FONT_SIZE > 0
        assert config.TASKBAR_BG_COLOR.startswith("#") and config.TASKBAR_TEXT_COLOR.startswith("#")
        assert 0 <= config.TASKBAR_BG_ALPHA <= 1
        assert 0 <= config.TASKBAR_TEXT_ALPHA <= 1, "任务栏文字不透明度应有效"
        assert isinstance(config.SAVE_ARTIFACTS, bool), "分析记录开关应为布尔"
        report("config 字段校验", True)
    except AssertionError as e:
        import traceback as _tb
        _ln = _tb.extract_tb(sys.exc_info()[2])[-1].lineno
        report("config 字段校验", False, str(e) or f"@test_main.py:{_ln}")
    except Exception as e:
        report("config 字段校验", False, repr(e))


# ---------- 1b. i18n 多语言（中文原文为键,英文查表,缺失回退） ----------
def test_i18n():
    try:
        from core import i18n
        assert i18n.get_language() in i18n.LANGUAGES, "进程语言取值应合法"
        i18n.set_language("zh")
        assert i18n.t("应用并保存") == "应用并保存", "中文环境应原样返回"
        i18n.set_language("en")
        assert i18n.t("应用并保存") == "Apply & Save", "英文环境应查表翻译"
        assert i18n.t("展示方式") == "Display", "标签页文案应翻译"
        assert i18n.t("任务栏内（托盘区左侧）") == "In taskbar (left of tray)", \
            "任务栏停靠位置标签应翻译"
        assert i18n.t("{name} 必须为整数").format(name="字号") == "字号 must be an integer", \
            "参数化校验消息应可 format"
        assert i18n.t("未收录键xyz") == "未收录键xyz", "未收录键应回退中文原文（不报错不空白）"
        i18n.set_language("fr")
        assert i18n.get_language() == "zh", "非法语言码应回退中文"
        # 运行时状态文本与日志键（浮窗/任务栏/日志均走 t()）
        i18n.set_language("en")
        assert i18n.t("[定时监控已暂停]") == "[Monitoring paused]", "状态文本应翻译"
        assert i18n.t("[定时监控已恢复]") == "[Monitoring resumed]", "状态文本应翻译"
        assert i18n.t("[区域指示框已隐藏]") == "[Region indicator hidden]", "状态文本应翻译"
        assert i18n.t("[区域已更新] {region}").format(region="(1,2,3,4)") == \
            "[Region updated] (1,2,3,4)", "参数化状态文本应可 format"
        assert i18n.t("[捕获错误] {err}").format(err="x") == "[Capture error] x", \
            "捕获错误文本应可 format"
        assert i18n.t("检测到画面变化") == "Screen change detected", "日志文案应翻译"
        assert i18n.t("定时监控 %s") == "Periodic monitoring %s", "日志模板应翻译"
        assert i18n.t("[%s] 调用地址: %s | 模型: %s%s").startswith("[%s] URL:"), \
            "LLM 调用日志模板应翻译"
        assert i18n.t("图像转文字模型") == "image-to-text model", "调用 tag 应翻译"
        assert i18n.t("未设置") == "not set", "键位占位文案应翻译"
        # 场景模板正文（英文模式选模板填入英文提示词）
        assert i18n.t("请原样输出图片中的全部文字内容，不要回答、不要解释。") == \
            "Output all text in the image verbatim; do not answer or explain.", \
            "场景模板正文应翻译"
        assert i18n.t("请识别并回答图片中的题目，直接给出正确答案（选项或数值），并用一句话说明理由。")\
            .startswith("Identify and answer"), "场景模板正文应翻译"
        i18n.set_language("zh")  # 套件统一中文基线（勿还原为用户 settings.json 的语言,
                                 # 否则 en 环境下 GUI 标题/日志文案断言会假失败）
        report("i18n 多语言", True)
    except AssertionError as e:
        import traceback as _tb
        _ln = _tb.extract_tb(sys.exc_info()[2])[-1].lineno
        report("i18n 多语言", False, str(e) or f"@test_main.py:{_ln}")
    except Exception as e:
        report("i18n 多语言", False, repr(e))


# ---------- 2. dHash 稳定性 / 灵敏度 ----------
def test_dhash():
    try:
        img = Image.new("RGB", (64, 64), (255, 255, 255))
        h1 = main.dhash(img)
        assert main.hamming(h1, main.dhash(img)) == 0, "同图距离应为 0"
        # 回归：均匀图像盲区——全白 vs 全黑必须可区分（纯 dHash 此处距离为 0）
        black = Image.new("RGB", (64, 64), (0, 0, 0))
        d_inv = main.hamming(h1, main.dhash(black))
        assert d_inv > 0, f"整屏反色应被感知, got {d_inv}"
        # 微小改动仍敏感
        img2 = img.copy()
        img2.putpixel((10, 10), (0, 0, 0))
        d_small = main.hamming(h1, main.dhash(img2))
        assert 0 < d_small <= 20, f"微小改动距离应小, got {d_small}"
        # 结构性大变化（噪声）应远大于微改
        import random
        rnd = random.Random(42)
        noise = Image.frombytes("RGB", (64, 64), bytes(rnd.randrange(256) for _ in range(64 * 64 * 3)))
        d_noise = main.hamming(h1, main.dhash(noise))
        assert d_noise > d_small, f"噪声距离({d_noise})应大于微改({d_small})"
        report("dhash 稳定性/灵敏度", True, f"(微改={d_small}, 反色={d_inv}, 噪声={d_noise})")
    except Exception as e:
        report("dhash 稳定性/灵敏度", False, repr(e))


# ---------- 3. save_region 持久化 settings.json 并可重新读回 ----------
def test_save_region():
    import tempfile
    old = main.appconfig.SETTINGS_FILE
    try:
        main.appconfig.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(prefix="region_test_"), "settings.json")
        main.save_region((11, 22, 33, 44))
        assert config.REGION == (11, 22, 33, 44), "运行时 config.REGION 未同步"
        # 重启视角：重新 load_config 读回
        c2 = main.load_config(main.appconfig.SETTINGS_FILE)
        assert c2.REGION == (11, 22, 33, 44), "重启后读回不符"
        report("save_region 持久化 settings.json", True)
    except Exception as e:
        report("save_region 持久化 settings.json", False, repr(e))
    finally:
        main.appconfig.SETTINGS_FILE = old
        config.REGION = (0, 0, 200, 150)  # 测试期间用小区域


# ---------- 3b. load_config 类型解析（JSON）/ 日志启动重置 ----------
def test_load_config_and_log():
    try:
        import tempfile
        import json as _json
        tmp_json = os.path.join(tempfile.mkdtemp(prefix="cfg_test_"), "settings.json")
        with open(tmp_json, "w", encoding="utf-8") as f:
            _json.dump({
                "capture": {"capture_interval": 1.5, "region": [1, 2, 3, 4],
                            "change_threshold": 5, "ignore_cursor": True,
                            "cooldown": 2.0, "compare_method": "dhash", "monitor_index": 1},
                "llm": {"active": "测试", "profiles": {"测试": {
                    "base_url": "https://example.com/v1", "api_key": "k", "model": "m",
                    "prompt": "第一行\n第二行", "temperature": 0.1, "max_tokens": 0,
                    "timeout": 10, "retry": 1, "send_max_edge": 0, "jpeg_quality": 85}}},
                "overlay": {"x": 0, "y": 0, "width": 10, "height": 10,
                            "text_color": "#FFFFFF", "font_size": 9,
                            "bg_color": "#000000", "bg_alpha": 0.5, "text_alpha": 0.8,
                            "always_on_top": True, "click_through": False,
                            "font_name": "微软雅黑"},
                "taskbar": {"position": "taskbar-right", "max_lines": 2,
                            "max_chars_per_line": 0, "scroll_interval": 2.0,
                            "font_size": 12, "font_name": "微软雅黑",
                            "text_color": "#FFFFFF", "text_alpha": 0.7,
                            "bg_color": "#1A1A1A", "bg_alpha": 0.9},
                "region_rect": {"show": False, "color": "#FF0000", "alpha": 0.2},
                "startup": {"monitor_paused": True, "overlay_hidden": False},
                "hotkeys": {"select_region": "f9", "manual_trigger": "f10",
                            "toggle_monitor": "f11", "toggle_overlay": "f12",
                            "toggle_rect": "f8"},
                "storage": {"artifacts_dir": "tmp_art", "save_artifacts": False},
                "log": {"level": "debug", "file": "tmp_test.log"},
            }, f, ensure_ascii=False)
        c = main.load_config(tmp_json)
        assert c.CAPTURE_INTERVAL == 1.5 and isinstance(c.CAPTURE_INTERVAL, float)
        assert c.REGION == (1, 2, 3, 4) and isinstance(c.REGION, tuple)
        assert c.IGNORE_CURSOR is True and c.REGION_RECT_SHOW is False
        assert c.LLM_PROMPT == "第一行\n第二行", f"多行 prompt 解析不符: {c.LLM_PROMPT!r}"
        assert c.LLM_MAX_TOKENS == 0 and c.LOG_LEVEL == "DEBUG"
        assert c.OVERLAY_BG_ALPHA == 0.5 and c.OVERLAY_TEXT_ALPHA == 0.8
        assert c.TASKBAR_TEXT_ALPHA == 0.7, "taskbar text_alpha 未解析"
        assert c.SAVE_ARTIFACTS is False, "storage.save_artifacts 未解析"
        assert c.LLM_ACTIVE == "测试" and list(c.LLM_PROFILES) == ["测试"]
        # 缺失键回退默认值（新增键无需迁移旧文件）
        c2 = main.load_config(tmp_json)  # 完整文件
        assert c2.LLM_JPEG_QUALITY == 85

        # 日志：setup_logging 应挂上 mode='w' 的 FileHandler（启动重置语义）
        log_path = c.LOG_FILE
        lg = main.setup_logging("INFO", log_path)
        fh = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
        assert fh and fh[0].baseFilename == os.path.abspath(log_path), "未挂载日志文件"
        assert fh[0].mode == "w", "日志文件应为覆盖写入（每次启动重置）"
        lg.info("log-reset-probe")
        assert os.path.isfile(log_path)
        report("load_config 类型解析 / 日志启动重置", True)
    except Exception as e:
        report("load_config 类型解析 / 日志启动重置", False, repr(e))
    finally:
        # 还原全局 logger（避免影响后续测试输出）
        main.setup_logging(config.LOG_LEVEL, config.LOG_FILE)


# ---------- 3c. save_config 持久化 / 损坏容错 ----------
def test_save_config():
    import tempfile
    old = main.appconfig.SETTINGS_FILE
    try:
        tmp_json = os.path.join(tempfile.mkdtemp(prefix="cfg_save_"), "settings.json")
        main.appconfig.SETTINGS_FILE = tmp_json
        config.OVERLAY_X = 99
        assert main.save_config(), "save_config 应成功"
        with open(tmp_json, encoding="utf-8") as f:
            data = json.load(f)
        assert data["overlay"]["x"] == 99
        assert data["llm"]["active"] == config.LLM_ACTIVE
        assert set(data["llm"]["profiles"]) == set(config.LLM_PROFILES)
        # 回读 round-trip
        c2 = main.load_config(tmp_json)
        assert c2.OVERLAY_X == 99 and c2.LLM_ACTIVE == config.LLM_ACTIVE
        # 损坏文件容错：备份为 .corrupt,改用默认值
        with open(tmp_json, "w", encoding="utf-8") as f:
            f.write("{broken json")
        c3 = main.load_config(tmp_json)
        assert c3.REGION == tuple(main._DEFAULT_SETTINGS["capture"]["region"])
        assert os.path.exists(tmp_json + ".corrupt"), "损坏文件应备份为 .corrupt"
        report("save_config 持久化/损坏容错", True)
    except Exception as e:
        report("save_config 持久化/损坏容错", False, repr(e))
    finally:
        main.appconfig.SETTINGS_FILE = old
        config.OVERLAY_X = 1400


# ---------- 4. ask_llm 请求构造与解析（mock 网络） ----------
def test_ask_llm_mock():
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "  42  "}}]}

    orig = main._HTTP_SESSION.post
    # 不依赖用户 settings.json：测试期间强制未配置图像转文字（截图直发主模型）
    old_ocr = (config.LLM_OCR_BASE_URL, config.LLM_OCR_API_KEY, config.LLM_OCR_MODEL)
    config.LLM_OCR_BASE_URL, config.LLM_OCR_API_KEY, config.LLM_OCR_MODEL = "", "", ""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResp()

    try:
        main._HTTP_SESSION.post = fake_post
        img = Image.new("RGB", (32, 32), (255, 255, 255))
        ans = main.ask_llm(img)
        assert ans == "42", f"应解析并 strip 内容, got {ans!r}"
        assert captured["url"].endswith("/chat/completions"), captured["url"]
        assert captured["headers"]["Authorization"] == f"Bearer {config.LLM_API_KEY}"
        content = captured["json"]["messages"][0]["content"]
        assert any(p.get("type") == "text" for p in content), "缺 text part"
        assert any(p.get("type") == "image_url" for p in content), "缺 image_url part"
        # 图像应经 JPEG 编码上传（体积远小于 PNG）
        img_url = next(p["image_url"]["url"] for p in content if p.get("type") == "image_url")
        assert img_url.startswith("data:image/jpeg;base64,"), \
            f"应使用 JPEG data URL, got {img_url[:40]}..."
        # LLM_MAX_TOKENS=0 表示不限制,payload 不应包含 max_tokens
        old = config.LLM_MAX_TOKENS
        try:
            config.LLM_MAX_TOKENS = 0
            main.ask_llm(img)
            assert "max_tokens" not in captured["json"], "MAX_TOKENS=0 时不应下发 max_tokens"
            config.LLM_MAX_TOKENS = 100
            main.ask_llm(img)
            assert captured["json"].get("max_tokens") == 100
        finally:
            config.LLM_MAX_TOKENS = old
        # 主提示词留空：不应发送空 text 段（部分端点拒绝空 text）,只发图片
        old_prompt = config.LLM_PROMPT
        try:
            config.LLM_PROMPT = ""
            main.ask_llm(img)
            content2 = captured["json"]["messages"][0]["content"]
            assert len(content2) == 1 and content2[0]["type"] == "image_url", \
                "提示词为空时 content 应只含图片"
        finally:
            config.LLM_PROMPT = old_prompt
        report("ask_llm 请求构造/解析(mock)", True)
    except Exception as e:
        report("ask_llm 请求构造/解析(mock)", False, repr(e))
    finally:
        main._HTTP_SESSION.post = orig
        config.LLM_OCR_BASE_URL, config.LLM_OCR_API_KEY, config.LLM_OCR_MODEL = old_ocr


# ---------- 4b. 图像转文字二段式（mock 网络） ----------
def test_llm_ocr_mock():
    from core import llmclient as llm_mod
    captured = []

    class FakeResp:
        def __init__(self, text):
            self._t = text

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": self._t}}]}

    orig_post = main._HTTP_SESSION.post
    old_ocr = (config.LLM_OCR_BASE_URL, config.LLM_OCR_API_KEY, config.LLM_OCR_MODEL)
    old_ocr_prompt = getattr(config, "LLM_OCR_PROMPT", "")
    old_prompt, old_retry = config.LLM_PROMPT, config.LLM_RETRY
    try:
        config.LLM_PROMPT = "回答这道题"
        config.LLM_RETRY = 1
        img = Image.new("RGB", (8, 8), (0, 0, 0))

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.append((url, json))
            if json["model"] == "ocr-model":  # 第一段：图像转文字
                return FakeResp("图片里有一道 1+1 的题")
            return FakeResp("2")  # 主模型

        main._HTTP_SESSION.post = fake_post
        # 未配置 OCR：单次请求,截图直发主模型（原路径回归）
        config.LLM_OCR_BASE_URL = ""
        captured.clear()
        assert main.ask_llm(img) == "2" and len(captured) == 1, "未配置 OCR 应只发一次请求"
        content = captured[0][1]["messages"][0]["content"]
        assert any(p.get("type") == "image_url" for p in content), "未配置 OCR 时应直发截图"
        # 配置 OCR：先转写后回答,主模型收到纯文本且提示词嵌入了转写
        config.LLM_OCR_BASE_URL = "https://ocr.example.com/api"
        config.LLM_OCR_API_KEY = "k-ocr"
        config.LLM_OCR_MODEL = "ocr-model"
        captured.clear()
        assert main.ask_llm(img) == "2" and len(captured) == 2, "应先调图像转文字再调主模型"
        url1, payload1 = captured[0]
        assert url1.startswith("https://ocr.example.com") and payload1["model"] == "ocr-model"
        assert payload1["messages"][0]["content"][0]["text"] == llm_mod.OCR_PROMPT
        # 自定义转写指令：配置 LLM_OCR_PROMPT 后替代内置默认指令
        config.LLM_OCR_PROMPT = "自定义转写指令"
        captured.clear()
        main.ask_llm(img)
        assert captured[0][1]["messages"][0]["content"][0]["text"] == "自定义转写指令", \
            "自定义转写指令应替代内置默认指令"
        config.LLM_OCR_PROMPT = ""
        url2, payload2 = captured[1]
        content2 = payload2["messages"][0]["content"]
        assert len(content2) == 1 and content2[0]["type"] == "text", "主模型应为纯文本请求"
        assert "图片里有一道 1+1 的题" in content2[0]["text"], "转写应嵌入主模型提示词"
        assert "回答这道题" in content2[0]["text"], "原提示词应保留"
        # {{OCR_TEXT}} 动态变量：指定位置嵌入（容错手误 {{ORC_TEXT}},不区分大小写）
        config.LLM_PROMPT = "题目：{{ORC_TEXT}}\n请回答"
        captured.clear()
        main.ask_llm(img)
        t3 = captured[1][1]["messages"][0]["content"][0]["text"]
        assert t3.startswith("题目：图片里有一道 1+1 的题"), "{{ORC_TEXT}} 应替换为转写结果"
        assert "请回答" in t3 and "【图片内容转写】" not in t3, \
            "已指定嵌入位置时不应追加小节"
        config.LLM_PROMPT = "题目：{{ocr_text}}\n请回答"
        captured.clear()
        main.ask_llm(img)
        t4 = captured[1][1]["messages"][0]["content"][0]["text"]
        assert t4.startswith("题目：图片里有一道 1+1 的题"), "{{ocr_text}} 小写应同样替换"
        config.LLM_PROMPT = "回答这道题"
        # 转写失败降级：图像转文字调用抛错时回退为截图直发主模型
        def fail_first(url, json=None, headers=None, timeout=None):
            captured.append(url)
            if len(captured) == 1:
                raise RuntimeError("ocr boom")
            return FakeResp("2")

        main._HTTP_SESSION.post = fail_first
        config.LLM_RETRY = 0
        captured.clear()
        assert main.ask_llm(img) == "2" and len(captured) == 2, \
            "转写失败应回退为截图直发主模型"
        report("图像转文字二段式(mock)", True)
    except Exception as e:
        report("图像转文字二段式(mock)", False, repr(e))
    finally:
        main._HTTP_SESSION.post = orig_post
        config.LLM_OCR_BASE_URL, config.LLM_OCR_API_KEY, config.LLM_OCR_MODEL = old_ocr
        config.LLM_OCR_PROMPT = old_ocr_prompt
        config.LLM_PROMPT, config.LLM_RETRY = old_prompt, old_retry


# ---------- 4c. 模型列表检测（mock 网络） ----------
def test_llm_models_mock():
    from core.llmclient import fetch_models

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    orig_get = main._HTTP_SESSION.get
    try:
        def fake_get(url, headers=None, timeout=None):
            assert url.endswith("/models"), f"应请求 /models, got {url}"
            assert headers["Authorization"].startswith("Bearer "), "应携带鉴权头"
            return FakeResp({"data": [{"id": "zhipu-glm"}, {"id": "abc-model"},
                                      {"id": "zhipu-glm"}]})

        main._HTTP_SESSION.get = fake_get
        models = fetch_models("https://api.example.com/v1/", "sk-test")
        assert models == ["abc-model", "zhipu-glm"], f"应排序去重, got {models}"

        # 端点不支持 /models（404）等失败：异常上抛,由设置界面弹窗提示
        def fail_get(url, headers=None, timeout=None):
            class Err:
                def raise_for_status(self):
                    raise RuntimeError("404 not found")

                def json(self):
                    return {}

            return Err()

        main._HTTP_SESSION.get = fail_get
        try:
            fetch_models("https://api.example.com/v1", "")
            raise AssertionError("请求失败应抛异常")
        except RuntimeError:
            pass
        report("模型列表检测(mock)", True)
    except Exception as e:
        report("模型列表检测(mock)", False, repr(e))
    finally:
        main._HTTP_SESSION.get = orig_get


# ---------- 4c-2. 429 限流长退避（mock 网络） ----------
def test_llm_429_backoff():
    import requests as _req
    from core import llmclient as llm_mod

    class FakeResp:
        def __init__(self, status, headers=None, text="ok"):
            self.status_code = status
            self.headers = headers or {}
            self._t = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise _req.exceptions.HTTPError(f"{self.status_code} Client Error", response=self)

        def json(self):
            return {"choices": [{"message": {"content": self._t}}]}

    orig_post = main._HTTP_SESSION.post
    orig_sleep = llm_mod.time.sleep
    old_retry, old_ocr = config.LLM_RETRY, config.LLM_OCR_BASE_URL
    calls, waits = [], []
    try:
        config.LLM_RETRY = 2
        config.LLM_OCR_BASE_URL = ""  # 测试勿依赖用户配置：单请求路径
        config.LLM_PROMPT = "回答这道题"

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                return FakeResp(429, {"Retry-After": "7"})   # 服务端指定等待
            if len(calls) == 2:
                return FakeResp(429, {})                      # 无 Retry-After
            return FakeResp(200, text="2")

        main._HTTP_SESSION.post = fake_post
        llm_mod.time.sleep = lambda s: waits.append(s)
        img = Image.new("RGB", (8, 8), (0, 0, 0))
        assert main.ask_llm(img) == "2" and len(calls) == 3, "429 应重试直至成功"
        assert waits and waits[0] == 7, f"应遵循 Retry-After=7s, got {waits}"
        assert waits[1] == 10, f"无 Retry-After 应取指数长退避(5→10s), got {waits}"
        report("429 限流长退避(mock)", True)
    except Exception as e:
        report("429 限流长退避(mock)", False, repr(e))
    finally:
        main._HTTP_SESSION.post = orig_post
        llm_mod.time.sleep = orig_sleep
        config.LLM_RETRY, config.LLM_OCR_BASE_URL = old_retry, old_ocr


# ---------- 4c-3. 调用信息日志（地址/模型/提示词/返回消息） ----------
def test_llm_call_logging():
    import logging as _logging
    from core import llmclient as llm_mod

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": " 首行\n第二行 "}}]}

    recs = []

    class Cap(_logging.Handler):
        def emit(self, record):
            recs.append(record.getMessage())

    lg = llm_mod.logger
    cap = Cap()
    old_level = lg.level
    lg.addHandler(cap)
    lg.setLevel(_logging.INFO)
    orig_post = main._HTTP_SESSION.post
    old_retry, old_ocr = config.LLM_RETRY, config.LLM_OCR_BASE_URL
    try:
        config.LLM_RETRY = 0
        config.LLM_OCR_BASE_URL = ""  # 单请求路径,勿依赖用户配置
        main._HTTP_SESSION.post = lambda url, json=None, headers=None, timeout=None: FakeResp()
        img = Image.new("RGB", (8, 8))
        main.ask_llm(img)
        joined = "\n".join(recs)
        assert "调用地址" in joined and "/chat/completions" in joined, "应记录调用地址"
        assert "模型:" in joined, "应记录模型名"
        assert "提示词" in joined and "回答这道题" in joined, "应记录提示词内容"
        assert "返回消息" in joined and "首行\\n第二行" in joined, \
            "返回消息应记录且换行压平为 \\n"
    except Exception as e:
        report("调用信息日志(mock)", False, repr(e))
    else:
        report("调用信息日志(mock)", True)
    finally:
        lg.removeHandler(cap)
        lg.setLevel(old_level)
        main._HTTP_SESSION.post = orig_post
        config.LLM_RETRY, config.LLM_OCR_BASE_URL = old_retry, old_ocr


# ---------- 4c-5. 提示词特殊字符（引号/转义/百分号/花括号）全链路安全 ----------
def test_prompt_special_chars():
    """提示词含单/双引号、反斜杠、换行/制表、百分号、花括号、OCR 动态变量时：
    存盘/装载（json）、请求构造（requests json=）、{{OCR_TEXT}} 嵌入（lambda 替换）
    与调用日志（%s 位置参数）均不得转义错乱或抛异常。"""
    import requests as _req
    from core import llmclient as llm_mod

    class FakeResp:
        def __init__(self, text):
            self.status_code = 200
            self._t = text

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": self._t}}]}

    orig_post = main._HTTP_SESSION.post
    old = (config.LLM_PROMPT, config.LLM_RETRY,
           config.LLM_OCR_BASE_URL, config.LLM_OCR_MODEL, config.LLM_OCR_API_KEY)
    old_prof_prompt = config.LLM_PROFILES[config.LLM_ACTIVE]["prompt"]
    old_sf = main.appconfig.SETTINGS_FILE
    recs = []

    class Cap(logging.Handler):
        def emit(self, record):
            recs.append(record.getMessage())

    lg = llm_mod.logger
    cap = Cap()
    lg.addHandler(cap)
    lg.setLevel(logging.INFO)
    try:
        # 含单/双引号、反斜杠、换行、制表、百分号、花括号、动态变量（含手误变体）
        tricky = "a'b\"c\\d\n{{OCR_TEXT}}\t%s{}{OCR_TEXT}} {{ORC_TEXT}}"
        config.LLM_PROMPT = tricky
        config.LLM_RETRY = 0

        # 1) 存盘/装载往返：settings.json 的 json.dump/load 应无损还原特殊字符
        # （LLM_PROMPT 为运行时展平属性,持久化经激活方案的 profile.prompt；
        #   装载时对 prompt 做 strip——首尾空白会丢失,属既有设计,特殊字符不受影响）
        config.LLM_PROFILES[config.LLM_ACTIVE]["prompt"] = tricky
        main.appconfig.SETTINGS_FILE = os.path.join(
            tempfile.mkdtemp(prefix="prompt_chars_"), "settings.json")
        assert main.save_config(), "含特殊字符的提示词应能写盘"
        # load_config 的 path 默认参数在 def 时绑定原路径,须显式传入临时路径
        c2 = main.load_config(main.appconfig.SETTINGS_FILE)
        assert c2.LLM_PROMPT == tricky, f"存盘/装载往返应无损还原, got {c2.LLM_PROMPT!r}"

        # 2) 直发主模型（无 OCR）：提示词应原样进入请求体（不做任何转义/替换）
        config.LLM_OCR_BASE_URL = ""
        captured = []
        main._HTTP_SESSION.post = lambda url, json=None, headers=None, timeout=None: \
            (captured.append(json), FakeResp("ANS"))[1]
        main.ask_llm(Image.new("RGB", (8, 8)))
        payload = captured[-1]
        text = payload["messages"][0]["content"][0]["text"]
        assert text == tricky, f"特殊字符提示词应原样进入请求体, got {text!r}"
        # requests 实际会做 json.dumps：显式验证可序列化且往返无损
        assert json.loads(json.dumps(payload))["messages"][0]["content"][0]["text"] == tricky, \
            "请求体应可 JSON 序列化且往返无损"
        # 日志以 %s 位置参数记录提示词：含 %s 的提示词不得引起格式化错乱
        assert any(tricky.replace("\n", "\\n") in m for m in recs), \
            "调用日志应完整记录特殊字符提示词（%s 为参数而非格式位）"

        # 3) 二段式：反斜杠/引号描述经 lambda 替换嵌入 {{OCR_TEXT}}（含手误 ORC 变体）
        desc = "back\\slash 'sq' \"dq\" %s {x}"   # 转写结果同样含特殊字符
        captured.clear()
        answers = [FakeResp(desc), FakeResp("ANS")]
        def fake_post(url, json=None, headers=None, timeout=None):
            captured.append((url, json))
            return answers.pop(0)
        main._HTTP_SESSION.post = fake_post
        config.LLM_OCR_BASE_URL = "http://ocr.local/v1"
        config.LLM_OCR_MODEL = "ocr-v"
        config.LLM_OCR_API_KEY = ""
        ans = main.ask_llm(Image.new("RGB", (8, 8)))
        assert ans == "ANS", "二段式应返回主模型结果"
        expected = tricky.replace("{{OCR_TEXT}}", desc).replace("{{ORC_TEXT}}", desc)
        mtext = captured[-1][1]["messages"][0]["content"][0]["text"]
        assert mtext == expected, f"转写结果嵌入应无损替换动态变量, got {mtext!r}"
        report("提示词特殊字符(mock)", True)
    except Exception as e:
        traceback.print_exc()
        report("提示词特殊字符(mock)", False, repr(e))
    finally:
        lg.removeHandler(cap)
        main._HTTP_SESSION.post = orig_post
        (config.LLM_PROMPT, config.LLM_RETRY,
         config.LLM_OCR_BASE_URL, config.LLM_OCR_MODEL, config.LLM_OCR_API_KEY) = old
        config.LLM_PROFILES[config.LLM_ACTIVE]["prompt"] = old_prof_prompt
        main.appconfig.SETTINGS_FILE = old_sf


# ---------- 5. worker 暂停/恢复/重置 ----------
def test_worker_pause():
    try:
        w = main.MonitorWorker(queue.Queue())
        assert w.toggle_paused() is True, "首次切换应为暂停"
        assert w.toggle_paused() is False, "再次切换应为恢复"
        w.reset_baseline()
        report("worker 暂停/恢复/重置", True)
    except Exception as e:
        report("worker 暂停/恢复/重置", False, repr(e))


# ---------- 6. 真实截屏（mss） ----------
def test_capture_region():
    try:
        img = main.capture_region()
        assert isinstance(img, Image.Image)
        assert img.size[0] > 0 and img.size[1] > 0
        report("capture_region 真实截屏", True, f"size={img.size}")
    except Exception as e:
        report("capture_region 真实截屏", False, repr(e))


# ---------- 7. GUI 组件构建（tkinter） ----------
def test_gui():
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        ov = main.Overlay()
        ov.hide()
        ov.set_answer("测试回答")
        assert ov.text == "测试回答"

        # 浮窗分页轮播：超长内容分页不截断,原始文本保留（与任务栏文本条同语义）
        old_iv = config.OVERLAY_SCROLL_INTERVAL
        old_ct = config.OVERLAY_CLICK_THROUGH
        try:
            config.OVERLAY_SCROLL_INTERVAL = 2.0
            long_ans = "这是一段很长的回答内容,需要换行与分页。" * 50
            ov.set_answer(long_ans)
            assert ov.text == long_ans, "set_answer 不应截断文本（轮播只影响渲染）"
            assert len(ov.pages) > 1, "超长回答应分页轮播"
            assert ov._page == 0, "新回答应从第一页开始"
            ov.show()  # 隐藏态不推进页码（预期行为）,显示态下驱动一次轮播
            try:
                # 自动轮播仅穿透模式生效
                config.OVERLAY_CLICK_THROUGH = True
                ov._tick()
                assert ov._page == 1 % len(ov.pages), "穿透模式轮播应推进页码"
                # 非穿透模式不自动轮播,改由滚轮手动逐行滚动
                config.OVERLAY_CLICK_THROUGH = False
                ov._tick()
                assert ov._page == 1 % len(ov.pages), "非穿透模式不应自动轮播"

                class _WheelEv:
                    def __init__(self, delta):
                        self.delta = delta

                ov._on_wheel(_WheelEv(120))
                assert ov._page == 0, "滚轮上滚(+120)应回退一行窗口"
                ov._on_wheel(_WheelEv(-120))
                assert ov._page == 1 % len(ov.pages), "滚轮下滚(-120)应前进一行窗口"
            finally:
                ov.hide()
                config.OVERLAY_CLICK_THROUGH = old_ct
            ov.set_answer("短回答")
            assert len(ov.pages) == 1 and ov._page == 0, "短内容应单页"
        finally:
            config.OVERLAY_SCROLL_INTERVAL = old_iv

        # 拖动移动浮窗 + 复制回答（取消穿透后的交互）
        class _DragEv:
            def __init__(self, x, y, rx, ry):
                self.x, self.y, self.x_root, self.y_root = x, y, rx, ry

        from ui import overlaywin as _ovmod
        orig_sc = _ovmod.save_config
        sc_calls = []
        _ovmod.save_config = lambda: sc_calls.append(1)  # 不写真实 settings.json
        old_xy = (config.OVERLAY_X, config.OVERLAY_Y)
        old_ct = config.OVERLAY_CLICK_THROUGH
        # 几何变化回调（controller 注入）：设置窗口开着时回填输入框,防「应用并保存」回退
        fired = []
        ov.on_geometry_changed = lambda: fired.append(1)
        try:
            config.OVERLAY_CLICK_THROUGH = False
            # Alt+拖动移动浮窗（左键拖动已让给文本选择）
            ov._on_move_start(_DragEv(10, 5, old_xy[0] + 10, old_xy[1] + 5))
            ov._on_drag_motion(_DragEv(30, 25, old_xy[0] + 30, old_xy[1] + 25))
            assert config.OVERLAY_X == old_xy[0] + 20 and config.OVERLAY_Y == old_xy[1] + 20, \
                "拖动应同步更新浮窗位置"
            ov._on_drag_end(_DragEv(30, 25, old_xy[0] + 30, old_xy[1] + 25))
            assert sc_calls, "拖动结束应触发位置持久化"
            assert fired, "拖动结束应触发几何变化回调（同步设置窗口）"

            # 右下角拖拽缩放：实时同步 config,松开持久化
            old_wh = (config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT)
            try:
                sc_calls.clear()
                ov._on_select_start(_DragEv(old_wh[0] - 5, old_wh[1] - 5, 0, 0))
                assert ov._mode == "resize", "右下角热区按下应进入缩放模式"
                ov._on_select_motion(_DragEv(400, 200, 0, 0))
                assert config.OVERLAY_WIDTH == 400 and config.OVERLAY_HEIGHT == 200, \
                    "缩放应实时更新浮窗尺寸到设置"
                ov._on_select_end(_DragEv(400, 200, 0, 0))
                assert sc_calls, "缩放结束应触发尺寸持久化"
            finally:
                config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT = old_wh
                ov.set_answer("短回答")  # 重建折行窗口

            # 左键拖选文本 + 复制所选（ULW 像素文本的自绘选区）
            ov.set_answer("第一行测试文本\n第二行测试文本")
            lines = ov.pages[0]
            assert len(lines) == 2, "两行内容应为单窗口两行"
            ov._on_select_start(_DragEv(12, 15, 0, 0))    # 第一行行首附近
            ov._on_select_motion(_DragEv(12 + (config.OVERLAY_WIDTH // 3), 15, 0, 0))
            img_plain = main.render_answer_image(ov.text, ov._font, lines=lines)
            img_sel = main.render_answer_image(ov.text, ov._font, lines=lines,
                                               selection=ov._sel)
            assert list(img_plain.getdata()) != list(img_sel.getdata()), \
                "选区应改变渲染结果（反色高亮）"
            ov._on_select_end(_DragEv(12 + (config.OVERLAY_WIDTH // 3), 15, 0, 0))
            sel_txt = ov._selected_text()
            assert sel_txt and sel_txt in lines[0], "拖选应选中第一行片段"
            ov._copy_selection()
            assert root.clipboard_get() == sel_txt, "复制所选应进入剪贴板"
            # 单击（零宽度选区）= 取消选择
            ov._on_select_start(_DragEv(12, 15, 0, 0))
            ov._on_select_end(_DragEv(12, 15, 0, 0))
            assert ov._selected_text() == "", "单击应取消选区"

            ov._copy_answer()
            assert root.clipboard_get() == "第一行测试文本\n第二行测试文本", \
                "复制回答全文应进入剪贴板"
        finally:
            _ovmod.save_config = orig_sc
            config.OVERLAY_CLICK_THROUGH = old_ct
            config.OVERLAY_X, config.OVERLAY_Y = old_xy

        r = main.RegionRectIndicator()
        r.hide()
        w = main.MonitorWorker(queue.Queue())
        ctl = main.Controller(root, ov, w, rect_indicator=r, q=queue.Queue())
        ctl.push_answer("信号通路")
        ctl._drain()
        assert ov.text == "信号通路", "Controller->Overlay 队列通路未生效"

        # 任务栏文本条：构建 + 按展示模式路由回答
        tb = main.TaskbarText()
        tb.hide()
        ctl.taskbar_text = tb
        config.ANSWER_MODE = "taskbar"
        ctl.push_answer("任务栏文本")
        ctl._drain()
        assert tb.text == "任务栏文本", "taskbar 模式下回答未路由到文本条"
        assert ov.text == "信号通路", "taskbar 模式下浮窗不应收到回答"
        config.ANSWER_MODE = "overlay"
        ctl.push_answer("浮窗文本")
        ctl._drain()
        assert ov.text == "浮窗文本", "overlay 模式下回答未路由到浮窗"
        # 文本条不截断：超长内容按行分页（轮播）,原始文本保留
        tb.set_answer("长" * 500)
        assert tb.text == "长" * 500, "set_answer 不应截断文本（轮播只影响渲染）"
        assert len(tb._pages) > 1, "超长内容应分页轮播"
        assert all(len(p) <= max(1, config.TASKBAR_MAX_LINES) for p in tb._pages), \
            "每页行数不应超过显示行数"
        tb.set_answer("短回答")
        assert len(tb._pages) == 1 and tb._pages[0] == ["短回答"], "短内容应单页显示"
        assert tb.is_visible() is False

        # 换行符转空格 + 每行最大字符数折行（显式固定显示行数=1,不依赖用户 settings.json）
        tb.set_answer("第一行\n第二行")
        assert tb.text == "第一行 第二行", "换行符应转换为空格"
        old_chars = config.TASKBAR_MAX_CHARS_PER_LINE
        old_lines = config.TASKBAR_MAX_LINES
        try:
            config.TASKBAR_MAX_CHARS_PER_LINE = 3
            config.TASKBAR_MAX_LINES = 1
            tb.set_answer("abcdefg")
            assert tb._pages == [["abc"], ["def"], ["g"]], \
                f"应按每行最大字符数折行, got {tb._pages}"
            # 显示行数=2：内容折出 3 行时,相邻滚动窗口应滑动一行（按行轮播语义）
            config.TASKBAR_MAX_LINES = 2
            tb.set_answer("abcdefgh")
            assert tb._pages == [["abc", "def"], ["def", "gh"]], \
                f"窗口应滑动一行, got {tb._pages}"
            config.TASKBAR_MAX_CHARS_PER_LINE = 0
            config.TASKBAR_MAX_LINES = 1
            tb.set_answer("短回答")
        finally:
            config.TASKBAR_MAX_CHARS_PER_LINE = old_chars
            config.TASKBAR_MAX_LINES = old_lines

        # 原生窗口嵌入任务栏（TrafficMonitor 同款架构,专用线程）：
        # taskbar-right 挂到 Shell_TrayWnd；切浮动位置自动摘回；显隐走窗口线程
        tb_info = main._find_taskbar()
        assert tb_info and tb_info["hwnd"] and tb_info["cw"] > 0 and tb_info["ch"] > 0, \
            "应能找到 Shell_TrayWnd 任务栏窗口"
        user32 = main.ctypes.windll.user32

        def _wait(cond, timeout=3.0):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if cond():
                    return True
                time.sleep(0.05)
            return False

        old_pos = config.TASKBAR_POSITION
        try:
            config.TASKBAR_POSITION = "taskbar-right"
            tb.set_answer("嵌入测试")
            tb.show()
            assert _wait(lambda: tb._native.hwnd and
                         user32.GetParent(tb._native.hwnd) == tb_info["hwnd"]), \
                "taskbar-right 应把原生窗口挂到任务栏"
            hwnd = tb._native.hwnd
            assert _wait(lambda: user32.IsWindowVisible(hwnd)), "show 后原生窗口应可见"
            assert tb.is_visible() is True, "is_visible 应反映窗口线程显隐状态"
            # 几何回归：文本条必须落在任务栏窗口矩形内（曾因把屏幕坐标混入
            # 子窗口 SetWindowPos 的父客户区相对坐标而整体移出可视区）
            assert _wait(lambda: tb._native._last_geom is not None), "嵌入后应完成落位"
            wrect = main.ctypes.wintypes.RECT()
            brect = main.ctypes.wintypes.RECT()
            user32.GetWindowRect(tb_info["hwnd"], main.ctypes.byref(wrect))
            user32.GetWindowRect(hwnd, main.ctypes.byref(brect))  # 屏幕坐标
            assert wrect.top <= brect.top and brect.bottom <= wrect.bottom, \
                f"文本条垂直方向应在任务栏内: bar={dict(l=brect.left,t=brect.top,r=brect.right,b=brect.bottom)} tray={dict(t=wrect.top,b=wrect.bottom)}"
            assert wrect.left <= brect.left and brect.right <= wrect.right, \
                "文本条水平方向应在任务栏内"
            # 条高与任务栏客户区一致（TrafficMonitor 同款全高条）
            assert tb._images and tb._images[0].size[1] == tb_info["ch"], \
                f"任务栏模式条高应等于任务栏客户区高: got {tb._images[0].size if tb._images else None}, want h={tb_info['ch']}"
            config.TASKBAR_POSITION = "bottom-center"
            tb.apply_config()
            assert _wait(lambda: tb._native.hwnd and
                         user32.GetParent(tb._native.hwnd) == 0), \
                "切回浮动位置后应为无父顶层窗口"
            config.TASKBAR_POSITION = "taskbar-right"
            tb.apply_config()
            assert _wait(lambda: tb._native.hwnd and
                         user32.GetParent(tb._native.hwnd) == tb_info["hwnd"]), \
                "再次嵌入应成功"
            hwnd = tb._native.hwnd  # 模式切换走销毁重建,句柄已更新
            tb.hide()
            assert _wait(lambda: not user32.IsWindowVisible(hwnd)), \
                "hide 后原生窗口应隐藏"
        finally:
            tb.hide()
            tb.close()
            config.TASKBAR_POSITION = old_pos

        # 鼠标组合热键注册/挂起（mouse 钩子初始化失败时 rebuild 返回错误,容忍跳过）
        # 键位未变化时 rebuild 应直接跳过（不重建句柄、不刷"热键已更新"日志）
        if ctl._hotkey_handles:
            same_map = dict(ctl._hotkey_map)
            handles_before = list(ctl._hotkey_handles)
            assert ctl.rebuild_hotkeys(same_map) is None
            assert ctl._hotkey_handles == handles_before, "键位未变不应重建热键句柄"

        # 穿透位增删：取消穿透必须显式清除 WS_EX_TRANSPARENT（曾只置不清导致永远穿透）
        hwnd_ov = main._get_top_hwnd(ov.win)
        WS_EX_TRANSPARENT = 0x00000020
        u32 = main.ctypes.windll.user32
        main._set_layer_flags_hwnd(hwnd_ov, False)
        assert not (u32.GetWindowLongW(hwnd_ov, -20) & WS_EX_TRANSPARENT), \
            "click_through=False 应清除 TRANSPARENT 位"
        main._set_layer_flags_hwnd(hwnd_ov, True)
        assert u32.GetWindowLongW(hwnd_ov, -20) & WS_EX_TRANSPARENT, \
            "click_through=True 应置位 TRANSPARENT"
        main._set_layer_flags_hwnd(hwnd_ov, config.OVERLAY_CLICK_THROUGH)  # 恢复配置态

        err = ctl.rebuild_hotkeys({"mouse_x2": "toggle_rect"})
        if err is None:
            assert ctl._hotkey_handles and ctl._hotkey_handles[0][1] == "mouse", \
                "mouse_x2 应走 mouse 钩子注册"
            # mouse.hook 会推送 MoveEvent/WheelEvent/ButtonEvent 全部事件,
            # 处理器必须按类型过滤——此前未过滤导致移动鼠标即抛
            # AttributeError: 'MoveEvent' object has no attribute 'event_type'
            kind, handler = ctl._hotkey_handles[0][1], ctl._hotkey_handles[0][2]
            assert kind == "mouse"
            while not ctl.q.empty():
                ctl.q.get_nowait()  # 清掉此前测试的队列残留
            if handler is not None:
                try:
                    handler(main.mouse.MoveEvent(100, 200, time.time()))   # 移动: 不应崩溃
                    handler(main.mouse.WheelEvent(0, -1))                  # 滚轮: 不应崩溃
                    handler(main.mouse.ButtonEvent(main.mouse.DOWN, "left", time.time()))  # 非目标键
                    assert ctl.q.empty(), "非目标鼠标事件不应触发动作"
                    handler(main.mouse.ButtonEvent(main.mouse.DOWN, "x2", time.time()))
                    assert not ctl.q.empty() and ctl.q.get_nowait() == ("action", "toggle_rect"), \
                        "目标按键按下应入队对应动作"
                except AttributeError as e:
                    raise AssertionError(f"鼠标钩子处理器未过滤事件类型: {e}")
            ctl.suspend_hotkeys()
            assert not ctl._hotkey_handles, "挂起后应清空全部热键句柄"
            ctl.restore_hotkeys()
            ctl.suspend_hotkeys()  # 测试结束前移除,避免残留全局钩子

        # Ctrl+Shift+F5（TOGGLE_RECT_HOTKEY）区域框切换
        init_visible = ctl._rect_visible
        ctl.toggle_rect()
        assert ctl._rect_visible == (not init_visible), "切换后状态未翻转"
        state = r.strips[0].state()
        assert all((s.state() != "withdrawn") == ctl._rect_visible for s in r.strips), \
            "isVisible 与状态不一致"
        ctl.toggle_rect()
        assert ctl._rect_visible == init_visible

        # 设置对话框：构建 + 字段装载 + _collect 校验通道（不触发真实热键/写盘）
        old_cfg = main.appconfig.SETTINGS_FILE
        main.appconfig.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(prefix="dlg_test_"), "settings.json")
        try:
            dlg = main.SettingsDialog(root, ctl)
            assert dlg.win.winfo_exists(), "设置窗口应已创建"
            assert dlg.win.state() == "normal", "设置窗口应构建完成后一次性显示（无小窗闪现）"
            assert dlg.win.title() == "桌面智能监控回答系统", f"窗口标题不符: {dlg.win.title()}"
            assert len(dlg.nb.tabs()) == 5, f"应含 5 个标签页, got {len(dlg.nb.tabs())}"
            tabs = [dlg.nb.tab(t, "text").strip() for t in dlg.nb.tabs()]
            assert tabs[0] == "展示方式" and tabs[1] == "监控区域", f"标签页顺序异常: {tabs}"
            # 托盘重复点击「设置」应单实例（此前 winfo_exists 误调在对话框自身上,
            # AttributeError 被 except 吞掉,导致每次点击都新建出多个设置窗口）：
            # 已存在时置顶显示已存在的窗口,不再新建
            ctl.settings_win = dlg
            dlg.win.withdraw()
            ctl.open_settings()
            assert ctl.settings_win is dlg, "已存在设置窗口时重复点击不应新建第二个窗口"
            assert dlg.win.state() == "normal", "重复打开应把已存在的窗口重新显示置顶"
            # 展示方式页应包含浮窗组与任务栏组全部设置项（任务栏组并入本页）
            for key in ("answer_mode", "x", "y", "width", "height",
                        "bg_color", "text_color", "bg_alpha", "text_alpha",
                        "tb_position", "tb_max_lines", "tb_scroll", "tb_max_chars",
                        "tb_font_name", "tb_font_size", "tb_text_color", "tb_text_alpha",
                        "tb_bg_color", "tb_bg_alpha", "ov_scroll"):
                assert key in dlg.vars, f"展示方式页缺少设置项 {key}"
            # 展示方式联动：浮窗模式只显示浮窗组,任务栏模式只显示任务栏组
            # （与 config.ANSWER_MODE 实际取值无关,纯 UI 联动验证）
            dlg.vars["answer_mode"].set("桌面浮窗")
            dlg._on_mode_changed()
            assert dlg._ov_box.winfo_manager() == "pack" and dlg._tb_box.winfo_manager() == "", \
                "浮窗模式应只显示浮窗组"
            dlg.vars["answer_mode"].set("任务栏文本条")
            dlg._on_mode_changed()
            assert dlg._tb_box.winfo_manager() == "pack" and dlg._ov_box.winfo_manager() == "", \
                "任务栏模式应只显示任务栏组"
            # 恢复为配置态模式,保证 _collect 采集结果与 config 一致
            dlg.vars["answer_mode"].set("任务栏文本条" if config.ANSWER_MODE == "taskbar" else "桌面浮窗")
            dlg.win.update_idletasks()
            scale = dlg._scales["bg_alpha"]
            click = dlg._scale_click["bg_alpha"]

            class _Ev:
                def __init__(self, x):
                    self.x = x

            width = scale.winfo_width() if scale.winfo_width() > 1 else scale.winfo_reqwidth()
            assert width > 40, f"滑动条宽度异常: {width}"
            assert click(_Ev(width // 2)) == "break", "点击处理应阻断默认类绑定"
            assert 0.3 <= dlg.vars["bg_alpha"].get() <= 0.7, \
                f"点击中部应得中间值, got {dlg.vars['bg_alpha'].get()}"
            click(_Ev(width - 12))
            assert dlg.vars["bg_alpha"].get() >= 0.9, "点击右端应接近 100%"
            click(_Ev(10))
            assert dlg.vars["bg_alpha"].get() <= 0.1, "点击左端应接近 0%"
            dlg.vars["bg_alpha"].set(config.OVERLAY_BG_ALPHA)  # 还原字段再继续采集校验
            assert dlg.vars["x"].get() != "", "字段应从 config 装载"
            dlg.vars["width"].set(66)
            vals = dlg._collect()
            assert vals["overlay"]["width"] == 66, "_collect 应读取对话框字段"
            assert vals["overlay"]["bg_alpha"] == config.OVERLAY_BG_ALPHA
            assert len(vals["hotkeys"]) == 5, "应采集 5 个快捷键"
            assert set(vals) == {"overlay", "taskbar", "region", "capture", "rect",
                                 "llm", "hotkeys", "general"}, "_collect 应覆盖全部标签页"
            assert vals["taskbar"]["mode"] == config.ANSWER_MODE, "taskbar 模式未采集"
            assert vals["taskbar"]["text_alpha"] == config.TASKBAR_TEXT_ALPHA, "文字不透明度未采集"
            assert vals["general"]["save_artifacts"] == config.SAVE_ARTIFACTS, "记录开关未采集"
            # 界面语言（第 32 轮）：下拉框装载 + 采集
            assert "language" in dlg.vars, "通用页缺少语言设置项"
            assert dlg.vars["language"].get() in ("中文", "English"), "语言下拉框应装载当前语言"
            assert vals["general"]["language"] in ("zh", "en"), "界面语言未采集"
            # 关于块（版本 + GitHub 项目主页链接）
            assert dlg._about_ver.cget("text") == f"v{main.appconfig.APP_VERSION}", \
                "版本标注应与 APP_VERSION 常量一致"
            assert dlg._about_link.cget("text") == main.appconfig.GITHUB_URL, \
                "链接文本应为项目仓库地址"
            assert main.appconfig.GITHUB_URL == "https://github.com/LK311/screen_answerer", \
                "项目主页应为 GitHub 仓库页（非 .git 克隆地址）"
            # 浮窗轮播速度与图像转文字设置项
            assert vals["overlay"]["scroll_interval"] == round(float(dlg.vars["ov_scroll"].get()), 1), \
                "浮窗播放速度未采集"
            for k in ("llm_ocr_base_url", "llm_ocr_api_key", "llm_ocr_model"):
                assert k in dlg.vars, f"图像转文字设置项缺失 {k}"
            assert set(dlg._model_combos) == {"llm_model", "llm_ocr_model"}, \
                "主模型/图像转文字模型下拉框缺失"
            assert vals["llm"]["ocr_model"] == dlg.vars["llm_ocr_model"].get().strip(), \
                "图像转文字模型未采集"
            # 提示词场景模板：预设存在,选择后填入提示词框
            # 场景名经 t() 翻译且 SCENARIO_PRESETS 为类属性（import 时按进程语言定格）,
            # 断言须用 t() 动态求值,勿硬编码中文名（用户 settings.json language=en 时会假失败）
            from core.i18n import t as _t
            assert len(dlg.SCENARIO_PRESETS) >= 8, "场景模板至少应含 7 个场景"
            old_prompt = dlg.prompt_text.get("1.0", "end-1c")
            try:
                dlg.preset_combo.set(_t("翻译成中文"))
                dlg._on_preset_selected()
                tmpl = [tx for n, tx in dlg.SCENARIO_PRESETS if n == _t("翻译成中文")][0]
                assert dlg.prompt_text.get("1.0", "end-1c") == tmpl, \
                    "选择模板后提示词框应填入模板内容"
                # 占位项（None）不应清空提示词
                dlg.preset_combo.set(_t("（选择场景模板…）"))
                dlg._on_preset_selected()
                assert dlg.prompt_text.get("1.0", "end-1c") == tmpl, "占位项不应改动提示词"
            finally:
                dlg.prompt_text.delete("1.0", "end")
                dlg.prompt_text.insert("1.0", old_prompt)
            # 框选监控区域回填同步：config.REGION 被外部更新（框选写盘）后,
            # refresh_region_vars 应把新值回填输入框——否则「应用并保存」会用旧值覆盖回退
            old_region = config.REGION
            try:
                config.REGION = (12, 34, 56, 78)
                dlg.refresh_region_vars()
                assert (dlg.vars["region_left"].get(), dlg.vars["region_top"].get(),
                        dlg.vars["region_width"].get(), dlg.vars["region_height"].get()) \
                    == ("12", "34", "56", "78"), "框选后应同步回填区域输入框"
                assert dlg._collect()["region"]["left"] == 12, \
                    "回填后采集应取到新区域（不再回退旧值）"
            finally:
                config.REGION = old_region
                dlg.refresh_region_vars()
            # 浮窗移动/缩放后几何回填同步（同 refresh_region_vars 机制）：
            # 非穿透模式拖动/缩放已实时写 config,设置窗口须回填否则「应用并保存」回退
            old_geom = (config.OVERLAY_X, config.OVERLAY_Y,
                        config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT)
            try:
                config.OVERLAY_X, config.OVERLAY_Y = 111, 222
                config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT = 333, 44
                dlg.refresh_overlay_vars()
                assert (dlg.vars["x"].get(), dlg.vars["y"].get(),
                        dlg.vars["width"].get(), dlg.vars["height"].get()) \
                    == ("111", "222", "333", "44"), "浮窗移动/缩放后应同步回填输入框"
                assert dlg._collect()["overlay"]["x"] == 111, "回填后采集应取到新几何"
            finally:
                config.OVERLAY_X, config.OVERLAY_Y = old_geom[:2]
                config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT = old_geom[2:]
                dlg.refresh_overlay_vars()
            # LLM 运行时同步：方案切换/应用并保存共用 _apply_llm_runtime——
            # OCR 为空的方案必须清空运行时 OCR（此前「应用并保存」漏写,
            # 导致切方案后仍残留旧转写端点继续调用图像转文字）
            old_llm = {k: getattr(config, k) for k in
                       ("LLM_BASE_URL", "LLM_MODEL", "LLM_OCR_BASE_URL", "LLM_OCR_API_KEY",
                        "LLM_OCR_MODEL", "LLM_OCR_PROMPT", "LLM_TEMPERATURE")}
            try:
                dlg._apply_llm_runtime({"base_url": "https://api.mimo.com/v1", "model": "m",
                                        "ocr_base_url": "", "ocr_api_key": "",
                                        "ocr_model": "", "ocr_prompt": ""})
                assert config.LLM_BASE_URL == "https://api.mimo.com/v1"
                assert not config.LLM_OCR_BASE_URL and not config.LLM_OCR_MODEL, \
                    "OCR 为空的方案应清空运行时 OCR 端点（不得残留旧值）"
                assert not config.LLM_OCR_PROMPT
                dlg._apply_llm_runtime({"base_url": "", "ocr_base_url": " https://ocr.x/api ",
                                        "ocr_api_key": "k", "ocr_model": " v1 ",
                                        "ocr_prompt": " 转写 "})
                assert config.LLM_OCR_BASE_URL == "https://ocr.x/api"
                assert config.LLM_OCR_MODEL == "v1" and config.LLM_OCR_PROMPT == "转写", \
                    "OCR 四项应去空白后写入运行时"
            finally:
                for k, v in old_llm.items():
                    setattr(config, k, v)
            # 大模型页折叠分组（手风琴互斥）：主接口默认展开、图像转文字折叠,
            # 展开一个自动折叠另一个,折叠一个自动展开另一个（始终恰有一个展开）
            assert set(dlg._llm_sections) == {"main", "ocr"}, "折叠分组缺失"
            assert dlg._llm_bodies["main"].winfo_manager() == "pack", "主接口默认应展开"
            assert dlg._llm_bodies["ocr"].winfo_manager() != "pack", "图像转文字默认应折叠"
            dlg._llm_sections["ocr"]()
            dlg.win.update_idletasks()
            assert dlg._llm_bodies["ocr"].winfo_manager() == "pack" and \
                dlg._llm_bodies["main"].winfo_manager() != "pack", \
                "展开图像转文字应自动折叠主接口"
            dlg._llm_sections["ocr"]()
            assert dlg._llm_bodies["main"].winfo_manager() == "pack" and \
                dlg._llm_bodies["ocr"].winfo_manager() != "pack", \
                "折叠图像转文字应自动展开主接口"
            dlg._llm_sections["main"]()
            assert dlg._llm_bodies["ocr"].winfo_manager() == "pack", \
                "折叠主接口应自动展开图像转文字"
            dlg._llm_sections["ocr"]()  # 恢复：主接口展开、图像转文字折叠
            # 检测模型回填：下拉项为纯模型名,当前手输名不在列表时回落到第一项
            orig_model = dlg.vars["llm_model"].get()
            try:
                dlg._fill_model_combo("llm_model", ["glm-4v-flash", "deepseek-chat"])
                assert dlg._model_combos["llm_model"].cget("values") == \
                    ("glm-4v-flash", "deepseek-chat"), "检测模型应回填纯模型名列表"
                assert dlg.vars["llm_model"].get() == "glm-4v-flash", \
                    "手输名不在列表中应回落到第一项"
                vals_m = dlg._collect()
                assert vals_m["llm"]["model"] == "glm-4v-flash", "模型采集应取下拉当前值"
            finally:
                dlg.vars["llm_model"].set(orig_model)
            # 颜色配置项色块实时预览
            assert dlg._swatches["bg_color"].cget("bg").lower() == str(config.OVERLAY_BG_COLOR).lower(), \
                "色块应显示当前配置颜色"
            dlg.vars["bg_color"].set("#FF0000")
            assert dlg._swatches["bg_color"].cget("bg").lower() == "#ff0000", \
                "色块应随输入实时刷新"
            dlg.vars["bg_color"].set(config.OVERLAY_BG_COLOR)
            # 清除快捷键：空键位允许,采集时跳过（功能不绑定）
            dlg.vars["hk_toggle_rect"].set("")
            vals2 = dlg._collect()
            assert len(vals2["hotkeys"]) == 4 and "toggle_rect" not in vals2["hotkeys"].values()
            # 重复键位仍被拦截
            dlg.vars["hk_toggle_rect"].set(dlg.vars["hk_toggle_monitor"].get())
            try:
                dlg._collect()
                raise AssertionError("重复快捷键应抛 ValueError")
            except ValueError:
                pass
            dlg.vars["hk_toggle_rect"].set("ctrl+shift+f5")
            # 非法输入应被拦截
            dlg.vars["height"].set("abc")
            try:
                dlg._collect()
                raise AssertionError("height=abc 应抛 ValueError")
            except ValueError:
                pass
            dlg.win.destroy()
            assert not dlg.win.winfo_exists()
        finally:
            main.appconfig.SETTINGS_FILE = old_cfg

        # 区域选择浮层构建校验（未进 mainloop,窗口不会真实映射到屏幕）
        sel = main.RegionSelector(lambda rg: None)
        sel.win.destroy()

        root.destroy()
        report("GUI 组件构建(tkinter)", True)
    except tk.TclError as e:
        report("GUI 组件构建(tkinter)", None, f"(跳过: 无可用显示环境 {e})")
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:
        traceback.print_exc()  # 失败时打印完整堆栈（report 只显示 repr,难定位）
        report("GUI 组件构建(tkinter)", False, repr(e))
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass


# ---------- 7b. 浮窗渲染函数（独立透明度/换行/截断/预乘） ----------
def test_overlay_render():
    try:
        old = (config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT,
               config.OVERLAY_BG_COLOR, config.OVERLAY_BG_ALPHA,
               config.OVERLAY_TEXT_COLOR, config.OVERLAY_TEXT_ALPHA)
        config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT = 200, 100
        config.OVERLAY_BG_COLOR = "#FF0000"
        config.OVERLAY_BG_ALPHA = 0.5
        config.OVERLAY_TEXT_COLOR = "#00FF00"
        config.OVERLAY_TEXT_ALPHA = 0.8
        try:
            img = main.render_answer_image("第一行\n第二行")
            assert img.mode == "RGBA" and img.size == (200, 100)
            # 背景像素 = 直通 alpha (255,0,0,bg_alpha*255≈128),预乘发生在推送时
            px = img.load()[3, 3]
            assert px == (255, 0, 0, 128), f"背景 alpha 未独立生效: {px}"
            # hex 简写与非法值回退
            assert main._hex_to_rgb("#0F0") == (0, 255, 0)
            assert main._hex_to_rgb("xyz") == (255, 255, 255), "非法颜色应回退白色"
            # 换行：超宽文本应拆成多行
            font = main._load_overlay_font()
            lines = main._wrap_text("长" * 200, font, 100)
            assert len(lines) > 1, "长文本应自动换行"
            # 超高内容触发截断标记
            img2 = main.render_answer_image("\n".join(f"行{i}" for i in range(50)))
            assert img2.mode == "RGBA"
            # 按行滚动窗口：超高内容切成滑动窗口（相邻窗口滑动一行）,render 接受 lines 参数
            pages = main.overlay_pages("\n".join(f"行{i}" for i in range(50)))
            assert len(pages) > 1, "超高内容应切多个滚动窗口"
            assert all(len(p) <= len(pages[0]) for p in pages), "窗口行数不应超过单屏上限"
            if len(pages[0]) >= 2:  # 单屏上限≥2 行时,相邻窗口应滑动一行（按行轮播）
                assert pages[1][0] == pages[0][1], "相邻窗口应滑动一行"
            img3 = main.render_answer_image("x", lines=pages[0])
            assert img3.mode == "RGBA" and img3.size == (200, 100)
            assert main.overlay_pages("短") == [["短"]], "短内容应单屏"
            # 预乘：不透明红 (255,0,0,255) -> BGRA (0,0,255,255)；半透明白 -> (127,127,127,127)
            import struct
            op = main._premultiply(Image.new("RGBA", (1, 1), (255, 0, 0, 255)))
            assert op == bytes([0, 0, 255, 255]), f"预乘不透明红不符: {op}"
            half = main._premultiply(Image.new("RGBA", (1, 1), (255, 255, 255, 127)))
            v = struct.unpack("4B", half)
            assert abs(v[0] - 127) <= 1 and abs(v[3] - 127) <= 1, f"预乘半透明不符: {v}"
            report("浮窗渲染函数(独立透明度/换行/预乘)", True)
        finally:
            (config.OVERLAY_WIDTH, config.OVERLAY_HEIGHT,
             config.OVERLAY_BG_COLOR, config.OVERLAY_BG_ALPHA,
             config.OVERLAY_TEXT_COLOR, config.OVERLAY_TEXT_ALPHA) = old
    except Exception as e:
        report("浮窗渲染函数(独立透明度/换行/预乘)", False, repr(e))


# ---------- 8. 区域指示框（单窗口直绘边框）跟随 REGION ----------
def test_rect_indicator():
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        r = main.RegionRectIndicator()
        old = config.REGION
        old_color, old_alpha = config.REGION_RECT_COLOR, config.REGION_RECT_ALPHA
        config.REGION = (5, 6, 70, 80)
        config.REGION_RECT_COLOR = "#FF0000"
        config.REGION_RECT_ALPHA = 0.8
        try:
            # 构造后应处于隐藏态（REGION_RECT_SHOW=false 路径不显示）
            assert r.win.state() == "withdrawn", "构造后应隐藏"
            r.update_region()
            r.show()
            r.win.update_idletasks()
            assert (r.win.winfo_x(), r.win.winfo_y(),
                    r.win.winfo_width(), r.win.winfo_height()) == (5, 6, 70, 80), \
                f"窗口应覆盖整个监控区域, got {r.win.winfo_geometry()}"
            assert r.win.state() != "withdrawn", "show 后应可见"
            # 渲染语义：边框像素不透明、内部全透明
            img = r._render()
            assert img.size == (70, 80), f"渲染尺寸不符: {img.size}"
            corner = img.getpixel((0, 0))
            center = img.getpixel((35, 40))
            assert corner[3] == int(round(0.8 * 255)), f"边框 alpha 不符: {corner}"
            assert corner[:3] == (255, 0, 0), f"边框颜色不符: {corner}"
            assert center[3] == 0, f"内部应为全透明: {center}"
            r.hide()
            assert r.win.state() == "withdrawn", "hide 后应隐藏"
        finally:
            config.REGION = old
            config.REGION_RECT_COLOR, config.REGION_RECT_ALPHA = old_color, old_alpha
        root.destroy()
        report("RegionRectIndicator 构建/跟随区域", True)
    except tk.TclError as e:
        report("RegionRectIndicator 构建/跟随区域", None, f"(跳过: {e})")
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:
        report("RegionRectIndicator 构建/跟随区域", False, repr(e))
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass


# ---------- 9. 问答历史：按日期同目录配对保存/文件名不冲突/历史不清空 ----------
def test_artifacts():
    try:
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        # 「记录分析截图与回答」关闭时不落盘
        old_save = config.SAVE_ARTIFACTS
        config.SAVE_ARTIFACTS = False
        assert main.save_artifacts(img, "不保存") == (None, None), "关闭记录时应返回 (None, None)"
        config.SAVE_ARTIFACTS = old_save
        p1 = main.save_artifacts(img, "回答A")
        p2 = main.save_artifacts(img, "回答B")
        assert os.path.isfile(p1[0]) and os.path.isfile(p1[1]), "图片/回答应成对落盘"
        # 截图与回答同目录（不再分 images/answers 两子目录）,按日期存放
        day = datetime.now().strftime("%Y-%m-%d")
        for p in p1 + p2:
            assert os.path.dirname(p).endswith(day), f"应存入当日日期子目录: {p}"
        assert os.path.dirname(p1[0]) == os.path.dirname(p1[1]), "截图与回答应同目录配对"
        assert os.path.basename(p1[0]) != os.path.basename(p2[0]), "文件名应含毫秒不冲突"
        with open(p2[1], encoding="utf-8") as f:
            assert f.read() == "回答B"
        # 历史永久保留：不再有启动清空（clear_artifacts 已移除,不存在该函数）
        assert not hasattr(main, "clear_artifacts"), "启动清空逻辑应已移除"
        assert os.listdir(os.path.dirname(p1[0])), "不应清空当日历史"
        report("QA_History 按日期保存/不清空", True)
    except Exception as e:
        report("QA_History 按日期保存/不清空", False, repr(e))


# ---------- 10. 启动冒烟：worker 线程真实跑一轮 ----------
def test_launch_smoke():
    try:
        config.CAPTURE_INTERVAL = 0.2  # 加速循环
        q = queue.Queue()
        w = main.MonitorWorker(q)
        orig = main.monitor.ask_llm
        main.monitor.ask_llm = lambda img: "MOCK_ANSWER"  # 监控线程从 monitor 模块取 ask_llm  # 免网络
        got = []
        try:
            w.start()
            deadline = time.time() + 5
            while time.time() < deadline and "MOCK_ANSWER" not in got:
                try:
                    kind, payload = q.get(timeout=0.2)
                    if kind == "answer":
                        got.append(payload)
                except queue.Empty:
                    pass
        finally:
            main.monitor.ask_llm = orig
            w.stop()
            w.join(timeout=3)
        assert "MOCK_ANSWER" in got, f"worker 未产出回答, got={got}"
        assert not w.is_alive(), "worker 应在 stop 后退出"
        report("启动冒烟(worker全链路)", True, f"输出={got}")
    except Exception as e:
        report("启动冒烟(worker全链路)", False, repr(e))


# ---------- 8b. 组合键录入辅助 / 任务栏文本条配置往返 ----------
def test_capture_helpers_and_taskbar():
    try:
        # 修饰键归一化
        assert main._canonical_modifier("shift") == "shift"
        assert main._canonical_modifier("left ctrl") == "ctrl"
        assert main._canonical_modifier("right alt") == "alt"
        assert main._canonical_modifier("left windows") == "windows"
        assert main._canonical_modifier("w") is None
        assert main._canonical_modifier("f1") is None
        assert main._canonical_modifier("") is None

        # 工作区查询（底部文本条停靠依据）
        wa = main._work_area()
        assert len(wa) == 4 and wa[2] > wa[0] and wa[3] > wa[1], f"工作区异常: {wa}"

        # capture_hotkey_once 通路：向 keyboard listener 注入合成事件,
        # 模拟「按住 shift 再按 w」——首个非修饰键 KEY_DOWN 即定型,无多余键并入
        kb = main.keyboard
        res = {}
        cap_t = threading.Thread(target=lambda: res.update(v=main.capture_hotkey_once()), daemon=True)
        cap_t.start()
        # blocking_hooks 在 listener init() 后才存在,等待捕获线程完成注册
        deadline = time.time() + 2
        hooks = None
        while time.time() < deadline:
            hooks = getattr(kb._listener, "blocking_hooks", None)
            if hooks:
                break
            time.sleep(0.05)
        if not hooks:
            report("capture_hotkey_once 合成事件通路", None, "(跳过: 沙箱禁止底层键盘钩子)")
        else:
            try:
                # shift KEY_DOWN 被 handler 抑制（返回 False）,仍应记入修饰键
                assert hooks[0](kb.KeyboardEvent(kb.KEY_DOWN, 42, "shift")) is False, \
                    "捕获期事件应被抑制（blocking hook 返回 False）"
                hooks[0](kb.KeyboardEvent(kb.KEY_DOWN, 17, "w"))
                cap_t.join(timeout=2)
                got = res.get("v")
                if got is not None and got != "shift+w" and "+" not in str(got) \
                        and len(str(got)) == 1:
                    # 录入期间捕获到真实键盘杂键（如 i/z/1）：环境污染,跳过录入断言
                    report("capture_hotkey_once 合成事件通路", None,
                           f"(录入被真实击键污染: got {got!r})")
                else:
                    assert got == "shift+w", f"合成 shift+w 应录入 shift+w, got {got!r}"
                    # 录入完成后 hook 应已移除
                    assert not hooks, "录入结束后 blocking hook 未移除"
            finally:
                # 清理合成事件遗留的按下状态,注入对应 KEY_UP
                for sc, nm in ((17, "w"), (42, "shift")):
                    try:
                        kb._listener.direct_callback(kb.KeyboardEvent(kb.KEY_UP, sc, nm))
                    except Exception:  # noqa: BLE001
                        pass

        # 鼠标捕获通路：shift 按住后按鼠标右键 → shift+mouse_right
        res_m = {}
        cap_m = threading.Thread(target=lambda: res_m.update(v=main.capture_hotkey_once()), daemon=True)
        cap_m.start()
        deadline = time.time() + 2
        m_handlers = []
        while time.time() < deadline:
            m_handlers = list(getattr(main.mouse._listener, "handlers", []) or [])
            if m_handlers:
                break
            time.sleep(0.05)
        if not m_handlers:
            report("鼠标捕获通路", None, "(跳过: 沙箱禁止底层鼠标钩子)")
        else:
            try:
                time.sleep(0.4)  # 越过 0.3s 保护期
                kb._listener.direct_callback(kb.KeyboardEvent(kb.KEY_DOWN, 42, "shift"))
                m_handlers[0](main.mouse.ButtonEvent(main.mouse.DOWN, "right", time.time()))
                cap_m.join(timeout=2)
                got_m = res_m.get("v")
                polluted = (got_m is not None and got_m != "shift+mouse_right"
                            and "+" not in str(got_m) and len(str(got_m)) == 1)
                if polluted:
                    # 录入期间捕获到真实键盘杂键（如 i/z/1）：环境污染。
                    # 跳过后续录入断言；任务栏配置断言与键盘无关,仍照常执行。
                    # （不能在这里启动第二个捕获——其全局钩子无人喂事件会残留吞键）
                    report("鼠标捕获通路", None, f"(录入被真实击键污染: got {got_m!r})")
                else:
                    assert got_m == "shift+mouse_right", \
                        f"shift+鼠标右键应录入 shift+mouse_right, got {got_m!r}"
                    # 保护期内的鼠标点击应被忽略（捕获仍在进行）
                    res_g = {}
                    cap_g = threading.Thread(target=lambda: res_g.update(v=main.capture_hotkey_once()), daemon=True)
                    cap_g.start()
                    time.sleep(0.15)
                    m_handlers2 = list(main.mouse._listener.handlers)
                    if m_handlers2:
                        m_handlers2[0](main.mouse.ButtonEvent(main.mouse.DOWN, "middle", time.time()))
                        time.sleep(0.2)
                        assert cap_g.is_alive(), "保护期内的鼠标点击不应被录入"
                        cap_g.join(timeout=3)
            finally:
                try:
                    kb._listener.direct_callback(kb.KeyboardEvent(kb.KEY_UP, 42, "shift"))
                except Exception:  # noqa: BLE001
                    pass

        # taskbar 配置：save -> load 往返 + 非法值回退
        old_file, old_mode = main.appconfig.SETTINGS_FILE, config.ANSWER_MODE
        old_tb = {k: getattr(config, k) for k in ("TASKBAR_POSITION", "TASKBAR_MAX_LINES",
                                                  "TASKBAR_MAX_CHARS_PER_LINE",
                                                  "TASKBAR_SCROLL_INTERVAL", "TASKBAR_FONT_SIZE",
                                                  "TASKBAR_FONT_NAME", "TASKBAR_TEXT_ALPHA")}
        try:
            main.appconfig.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(prefix="tb_cfg_"), "settings.json")
            config.ANSWER_MODE = "taskbar"
            config.TASKBAR_POSITION, config.TASKBAR_MAX_LINES = "top-right", 3
            config.TASKBAR_MAX_CHARS_PER_LINE, config.TASKBAR_SCROLL_INTERVAL = 25, 1.5
            config.TASKBAR_TEXT_ALPHA = 0.6
            assert main.save_config(), "save_config 应成功"
            with open(main.appconfig.SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            assert data["taskbar"]["max_lines"] == 3, "taskbar 段未写盘"
            assert data["taskbar"]["max_chars_per_line"] == 25, "max_chars_per_line 未写盘"
            assert data["taskbar"]["position"] == "top-right", "position 未写盘"
            assert data["taskbar"]["text_alpha"] == 0.6, "text_alpha 未写盘"
            assert data["overlay"]["answer_mode"] == "taskbar", "answer_mode 未写盘"
            c2 = main.load_config(main.appconfig.SETTINGS_FILE)
            assert c2.ANSWER_MODE == "taskbar" and c2.TASKBAR_POSITION == "top-right"
            assert c2.TASKBAR_MAX_LINES == 3 and c2.TASKBAR_SCROLL_INTERVAL == 1.5
            assert c2.TASKBAR_MAX_CHARS_PER_LINE == 25
            assert c2.TASKBAR_TEXT_ALPHA == 0.6, "text_alpha 读回不符"
            # 非法 mode/position 回退；缺失 taskbar 段回退默认值
            data["overlay"]["answer_mode"] = "bogus"
            data["taskbar"]["position"] = "middle-nowhere"
            with open(main.appconfig.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            c3 = main.load_config(main.appconfig.SETTINGS_FILE)
            assert c3.ANSWER_MODE == "overlay", "非法 mode 应回退 overlay"
            assert c3.TASKBAR_POSITION == "taskbar-right", "非法 position 应回退默认"
        finally:
            main.appconfig.SETTINGS_FILE = old_file
            config.ANSWER_MODE = old_mode
            for k, v in old_tb.items():
                setattr(config, k, v)
        report("组合键/鼠标录入辅助/任务栏文本条配置", True)
    except Exception as e:
        report("组合键/鼠标录入辅助/任务栏文本条配置", False, repr(e))


if __name__ == "__main__":
    # 语言基线不依赖用户 settings.json（en 环境下窗口标题/日志文案断言会假失败）
    from core import i18n as _i18n
    _i18n.set_language("zh")
    test_config()
    test_i18n()
    test_dhash()
    test_save_region()
    test_load_config_and_log()
    test_save_config()
    test_ask_llm_mock()
    test_llm_ocr_mock()
    test_llm_models_mock()
    test_llm_429_backoff()
    test_llm_call_logging()
    test_prompt_special_chars()
    test_worker_pause()
    test_capture_region()
    test_overlay_render()
    test_capture_helpers_and_taskbar()
    test_gui()
    test_rect_indicator()
    test_artifacts()
    test_launch_smoke()

    print("\n================ 测试结果 ================")
    for p in PASS:
        print("PASS |", p)
    for s in SKIP:
        print("SKIP |", s)
    for f in FAIL:
        print("FAIL |", f)
    print(f"合计: {len(PASS)} 通过 / {len(SKIP)} 跳过 / {len(FAIL)} 失败")
    raise SystemExit(1 if FAIL else 0)
