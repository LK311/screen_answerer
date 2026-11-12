# -*- coding: utf-8 -*-
"""界面多语言支持（中文 / 英文）。

设计（gettext 风格,中文原文为键）：
- 语言存 settings.json 的 ``general.language``（"zh"/"en",默认 zh）
- ``t(中文原文)``：中文环境原样返回；英文环境查 _EN 表翻译,
  未收录的键自动回退中文原文（新增界面漏配不会报错、不会空白）
- 带参数的文案用模板键（如 ``"{name} 必须为整数"``）+ ``.format()`` 填充
- 语言在进程启动时由 appconfig 装载配置后调用 ``set_language`` 一次性设定,
  设置窗口切换语言仅写盘,重启程序后生效（UI 文案在构建时定格）

UI 文案翻译清单（按模块）：
- settingsui 设置窗口全部标签/分组/提示/按钮/弹窗/校验消息
- trayicon 托盘菜单
- overlaywin 浮窗初始文本与右键菜单
- taskbarwin 任务栏停靠位置标签
- imagerender 截断标记
- controller/monitor/main 浮窗与任务栏的运行时状态文本（如「[定时监控已暂停]」）
- controller/monitor/llmclient/appconfig/imagerender/main 日志文案"""

# 语言取值（settings.json 存码,界面下拉项固定双语显示便于切换回来）
LANGUAGES = ("zh", "en")
LANGUAGE_LABELS = {"zh": "中文", "en": "English"}

_LANG = "zh"

# ------------------------- 英文翻译表（键 = 中文原文/模板） -------------------------
_EN = {
    # ---- 窗口 / 标签页 / 按钮 ----
    "桌面智能监控回答系统": "Desktop Screen QA Monitor",
    "展示方式": "Display",
    "监控区域": "Monitor Region",
    "大模型": "LLM",
    "快捷键": "Hotkeys",
    "通用": "General",
    "界面": "Interface",
    "应用并保存": "Apply & Save",
    "关闭": "Close",
    "选色…": "Pick color…",
    "录入": "Capture",
    "清除": "Clear",
    "等待按键…": "Press keys…",
    "检测模型": "Detect models",
    "另存为新方案": "Save as new profile",
    "删除当前方案": "Delete profile",
    "框选监控区域…（拖拽框选,ESC 取消）":
        "Select monitor region… (drag to select, ESC to cancel)",
    "显示/隐藏区域指示框": "Show/Hide region indicator",
    "框选桌面浮窗区域…（拖拽框选,ESC 取消）":
        "Select overlay region… (drag to select, ESC to cancel)",

    # ---- 展示方式页：分组与字段 ----
    "位置与大小（屏幕绝对像素坐标）": "Position & Size (absolute screen pixels)",
    "颜色与透明度（背景 / 文字各自独立）":
        "Colors & Transparency (background / text independent)",
    "行为": "Behavior",
    "桌面浮窗": "Desktop overlay",
    "任务栏文本条": "Taskbar text bar",
    "背景颜色": "Background color",
    "背景不透明度": "Background opacity",
    "文字颜色": "Text color",
    "文字不透明度": "Text opacity",
    "字体": "Font",
    "字号(磅)": "Size (pt)",
    "置顶显示": "Always on top",
    "鼠标穿透（点击穿过浮窗）": "Click-through (clicks pass through overlay)",
    "播放速度(秒/行)": "Scroll speed (s/line)",
    "位置与布局": "Position & Layout",
    "显示位置": "Position",
    "显示行数": "Visible lines",
    "文本折行": "Text Wrapping",
    "每行最大字符数": "Max chars per line",
    "颜色与透明度": "Colors & Transparency",
    "宽": "W",
    "高": "H",

    # ---- 展示方式页：提示 ----
    "回答以哪种形式展示：\n"
    "· 桌面浮窗：屏幕上的独立浮动窗口\n"
    "· 任务栏文本条：嵌入任务栏或停靠屏幕边缘的文本条\n"
    "（下方设置项随展示方式联动切换）":
        "How the answer is displayed:\n"
        "· Desktop overlay: an independent floating window on screen\n"
        "· Taskbar text bar: embedded in the taskbar or docked to screen edges\n"
        "(Settings below switch with the display mode)",
    "桌面浮窗左上角的屏幕横向绝对像素坐标":
        "Absolute horizontal screen pixel coordinate of the overlay's top-left corner",
    "桌面浮窗左上角的屏幕纵向绝对像素坐标":
        "Absolute vertical screen pixel coordinate of the overlay's top-left corner",
    "桌面浮窗宽度（像素,最小 40）": "Overlay width (pixels, min 40)",
    "桌面浮窗高度（像素,最小 24）": "Overlay height (pixels, min 24)",
    "全屏拖拽框选浮窗位置,松开后回填 X/Y/宽/高 并立即预览":
        "Drag on screen to select the overlay position; X/Y/width/height are "
        "filled in and previewed on release",
    "浮窗背景色,十六进制写法（如 #000000）；也可点「选色…」拾取":
        "Overlay background color in hex (e.g. #000000); or pick via \"Pick color…\"",
    "0%=完全透明,100%=完全不透明；点击滑动条任意位置即可定位":
        "0% = fully transparent, 100% = opaque; click anywhere on the slider to set",
    "回答文字颜色,十六进制写法（如 #FFFFFF）":
        "Answer text color in hex (e.g. #FFFFFF)",
    "0%=文字完全透明,100%=完全不透明": "0% = text fully transparent, 100% = opaque",
    "回答文字使用的字体（内置字体文件）": "Font for answer text (bundled font files)",
    "回答文字大小（8~72 磅）": "Answer text size (8~72 pt)",
    "开启后桌面浮窗始终显示在其他窗口之上":
        "Keep the overlay above all other windows",
    "开启后鼠标点击穿透浮窗直接作用于下方窗口；取消勾选后浮窗可正常点击":
        "Clicks pass through the overlay to windows below; uncheck to interact "
        "with the overlay",
    "回答超过浮窗高度时不截断,按行轮播：每隔该秒数滚动一行（0.5~60）；\n"
    "0=不轮播（只显示第一屏,超出部分显示「已截断」标记）。\n"
    "另：取消鼠标穿透后,可拖动浮窗移动位置,双击/右键可复制回答全文":
        "When the answer exceeds the overlay height it is not truncated but scrolls "
        "line by line every N seconds (0.5~60);\n"
        "0 = no scrolling (first screen only, overflow shows a \"truncated\" marker).\n"
        "Also: with click-through off, drag the overlay to move it; double-click/"
        "right-click copies the full answer",
    "「任务栏内」=嵌入任务栏托盘区左侧（TrafficMonitor 同款）；\n"
    "其余为停靠屏幕边缘的浮动文本条":
        "\"In taskbar\" = embedded left of the taskbar tray area (like TrafficMonitor);\n"
        "others are floating bars docked to screen edges",
    "文本条同时显示的行数（1~10）；超出部分按行轮播,不截断":
        "Lines shown at once (1~10); overflow scrolls line by line, never truncated",
    "内容超过显示行数时按行轮播：每隔该秒数滚动一行（0.5~60）,\n不截断":
        "When content exceeds visible lines it scrolls one line every N seconds "
        "(0.5~60),\nnever truncated",
    "每行最多显示的字符数（0~200）。\n"
    "0=按像素宽度自动折行；任务栏模式建议 20~40。\n"
    "回答中的换行符按空格处理":
        "Max characters per line (0~200).\n"
        "0 = wrap by pixel width; 20~40 recommended for taskbar mode.\n"
        "Newlines in answers become spaces",
    "文本条文字颜色,十六进制写法（如 #FFFFFF）":
        "Text bar text color in hex (e.g. #FFFFFF)",
    "文本条背景色,十六进制写法（如 #1A1A1A）":
        "Text bar background color in hex (e.g. #1A1A1A)",
    "文本条文字使用的字体（内置字体文件）": "Font for text bar (bundled font files)",
    "文本条文字大小（8~72 磅）": "Text bar font size (8~72 pt)",

    # ---- 监控区域页 ----
    "监控区域（屏幕绝对像素坐标）": "Monitor Region (absolute screen pixels)",
    "变化检测": "Change Detection",
    "区域指示框": "Region Indicator",
    "常用操作": "Quick Actions",
    "监控间隔(秒)": "Interval (s)",
    "变化阈值(0~64)": "Change threshold (0~64)",
    "冷却(秒)": "Cooldown (s)",
    "比较算法": "Hash algorithm",
    "颜色": "Color",
    "不透明度": "Opacity",
    "启动时显示指示框（下次启动生效；运行中用按钮或快捷键切换）":
        "Show indicator at startup (next launch; toggle at runtime via button or hotkey)",
    "监控区域左上角的屏幕横向绝对像素坐标（与桌面浮窗的 X 同义）":
        "Absolute horizontal pixel coordinate of region top-left (same as overlay X)",
    "监控区域左上角的屏幕纵向绝对像素坐标（与桌面浮窗的 Y 同义）":
        "Absolute vertical pixel coordinate of region top-left (same as overlay Y)",
    "监控区域宽度（像素,最小 16）": "Region width (pixels, min 16)",
    "监控区域高度（像素,最小 16）": "Region height (pixels, min 16)",
    "每隔多少秒截屏一次并检测画面变化（0.2~3600）":
        "Seconds between screenshots and change detection (0.2~3600)",
    "画面哈希距离超过该值才判定为变化；越大越不灵敏（0~64）":
        "Change is detected when hash distance exceeds this; larger = less sensitive (0~64)",
    "两次回答之间的最小间隔秒数（0~3600）,防止连续频繁调用大模型":
        "Minimum seconds between answers (0~3600), prevents frequent LLM calls",
    "画面变化检测算法：dhash 默认,速度与灵敏度均衡；phash 更稳但稍慢":
        "Change detection algorithm: dhash (default) balances speed and sensitivity; "
        "phash is steadier but slower",
    "监控区域指示框的边框颜色,十六进制写法（如 #00FFFF）":
        "Indicator border color in hex (e.g. #00FFFF)",
    "指示框边框不透明度；0%=完全透明,100%=完全不透明":
        "Indicator border opacity; 0% = transparent, 100% = opaque",
    "勾选后程序每次启动自动显示指示框；运行中的显隐用下方按钮或快捷键切换":
        "Show the indicator automatically at every launch; toggle at runtime via "
        "the button below or hotkey",

    # ---- 大模型页 ----
    "配置方案": "Profiles",
    "主接口（OpenAI 兼容端点）": "Main API (OpenAI-compatible endpoint)",
    "图像转文字（可选,端点+模型全填才启用）":
        "Image-to-Text (optional; enabled when endpoint & model are both set)",
    "端点": "Endpoint",
    "密钥": "API key",
    "显示密钥": "Show key",
    "模型": "Model",
    "场景模板": "Scenario preset",
    "提示词": "Prompt",
    "温度(0~1)": "Temperature (0~1)",
    "超时(秒)": "Timeout (s)",
    "重试次数 ": "Retries ",
    "发送长边": "Max edge (px)",
    "JPEG质量(1~95)": "JPEG quality (1~95)",
    "（选择场景模板…）": "(Choose a scenario…)",
    "题目解答": "Solve question",
    "题目解析": "Explain solution",
    "原样转录": "Transcribe",
    "翻译成中文": "Translate to Chinese",
    "内容总结": "Summarize",
    "术语讲解": "Explain terms",
    "公式计算": "Formula calculation",
    "主模型 OpenAI 兼容接口地址（/chat/completions 的服务根地址）":
        "OpenAI-compatible API root of the main model (base URL before /chat/completions)",
    "服务方提供的 API Key,仅保存在本机 settings.json":
        "API key from your provider; stored only in local settings.json",
    "主模型名称,如 glm-4v-flash。未配置图像转文字时需为视觉模型（支持图片输入）；\n"
    "配置图像转文字后可为纯文本大语言模型。可点「检测模型」拉取端点可用模型列表":
        "Main model name, e.g. glm-4v-flash. Without image-to-text it must be a "
        "vision model (image input);\n"
        "with image-to-text it can be a text-only LLM. Click \"Detect models\" to "
        "list endpoint models",
    "向端点查询可用模型列表（GET /models）填充左侧下拉框；\n"
    "部分服务不支持该接口,检测失败时可直接手动输入模型名":
        "Query the endpoint for available models (GET /models) to fill the dropdown;\n"
        "some services lack this API — enter the model name manually if detection fails",
    "常见应用场景的提示词预设；\n"
    "选择后会把模板内容填入下方提示词框（覆盖现有内容,可再手工修改）":
        "Prompt presets for common scenarios;\n"
        "choosing one fills the prompt box below (overwrites content, editable afterwards)",
    "发送给主模型的指令（可留空）": "Instruction sent to the main model (optional)",
    "主模型收到的指令（图像转文字模型有单独的提示词,见下方区域）。留空=不附加指令。\n"
    "未配置图像转文字时,截图随本提示词直发主模型（需视觉模型）；\n"
    "配置后主模型收到纯文本：转写结果嵌入位置——\n"
    "· 本提示词含 {{OCR_TEXT}} 动态变量：转写结果替换该变量"
    "（不区分大小写,可放任意位置自由组织语序）\n"
    "· 未出现时：转写结果以「【图片内容转写】」小节追加到提示词末尾":
        "Instruction for the main model (the image-to-text model has its own prompt "
        "below). Empty = no instruction.\n"
        "Without image-to-text, the screenshot is sent with this prompt to the main "
        "model (must be a vision model);\n"
        "with it, the main model receives pure text — where the transcription is "
        "embedded:\n"
        "· If this prompt contains the {{OCR_TEXT}} variable: the transcription "
        "replaces it (case-insensitive, place it anywhere)\n"
        "· Otherwise: the transcription is appended to the prompt as an "
        "\"[Image Transcription]\" section",
    "主模型采样温度：越低回答越稳定保守,越高越发散（回答场景建议 0~0.5）；\n"
    "图像转文字调用固定 0.1,不使用该值":
        "Main model sampling temperature: lower = steadier, higher = more creative "
        "(0~0.5 recommended for QA);\nimage-to-text calls use a fixed 0.1",
    "限制主模型回答最大 token 数；0=不限制（不下发该字段）":
        "Max tokens of the main model answer; 0 = unlimited (field omitted)",
    "单次 HTTP 请求的超时秒数；主模型与图像转文字调用共用":
        "HTTP timeout in seconds; shared by main and image-to-text calls",
    "请求失败后的重试次数（指数退避：1s/2s/4s…上限 8s）；\n"
    "429 限流单独处理：遵循服务端 Retry-After 或 5s→10s→20s 长退避（上限 60s）；\n"
    "主模型与图像转文字调用共用":
        "Retries after a failed request (exponential backoff 1s/2s/4s… cap 8s);\n"
        "HTTP 429 handled separately: honors Retry-After or long backoff "
        "5s→10s→20s (cap 60s);\nshared by main and image-to-text calls",
    "上传前把截图长边等比缩放到该像素值以减小体积；0=原图直传。\n"
    "截图发给图像转文字模型（启用时）或主模型（未启用时）":
        "Scale the screenshot's longest edge to this pixel size before upload to "
        "reduce size; 0 = send original.\nScreenshot goes to the image-to-text model "
        "(if enabled) or the main model",
    "截图 JPEG 压缩质量：越低体积越小、上传越快,但清晰度下降。\n"
    "截图发给图像转文字模型（启用时）或主模型（未启用时）":
        "JPEG compression quality: lower = smaller upload but less detail.\n"
        "Screenshot goes to the image-to-text model (if enabled) or the main model",
    "图像转文字模型的 OpenAI 兼容端点（留空=不启用,截图直发主模型）":
        "OpenAI-compatible endpoint of the image-to-text model (empty = disabled, "
        "screenshot goes straight to the main model)",
    "图像转文字模型的 API Key（本地服务可留空）":
        "API key of the image-to-text model (optional for local services)",
    "图像转文字视觉模型名,如 glm-4v-flash（需支持图片输入）。\n"
    "工作流程：截图→该模型转成文字→文字嵌入主模型提示词"
    "（动态变量 {{OCR_TEXT}} 或追加末尾）\n"
    "→主模型（可为纯文本模型）回答":
        "Vision model name for image-to-text, e.g. glm-4v-flash (image input required).\n"
        "Flow: screenshot → this model transcribes it → the text is embedded into "
        "the main prompt (via {{OCR_TEXT}} or appended)\n"
        "→ the main model (may be text-only) answers",
    "向图像转文字端点查询可用模型列表填充左侧下拉框；\n检测失败时可直接手动输入模型名":
        "Query the image-to-text endpoint for available models to fill the dropdown;\n"
        "enter the model name manually if detection fails",
    "发送给图像转文字模型的指令（留空=内置默认转写指令）":
        "Instruction for the image-to-text model (empty = built-in transcription prompt)",
    "图像转文字模型收到的指令,要求它把截图转成文字（不要作答）。\n"
    "留空使用内置默认指令：「请原样输出图片中的全部文字内容,不要回答、不要解释」。"
    "转写结果嵌入主模型提示词的方式,见主接口提示词说明":
        "Instruction for the image-to-text model: transcribe the screenshot verbatim "
        "(do not answer).\n"
        "Empty = built-in default instruction. See the main prompt help for how the "
        "transcription is embedded",

    # ---- 快捷键页 ----
    "全局快捷键（点击「录入」后按下目标组合键自动录入）":
        "Global hotkeys (click \"Capture\", then press the key combo)",
    "选择监控区域": "Select monitor region",
    "手动回答": "Answer now",
    "暂停/恢复监控": "Pause/Resume monitoring",
    "显示/隐藏桌面浮窗": "Show/Hide overlay",
    "当前键位（只读）；点击右侧「录入」后按下新组合键即替换":
        "Current binding (read-only); click \"Capture\" and press a new combo to replace",
    "支持键盘组合键与鼠标按键（左/右/中/侧键,可叠加 Ctrl/Shift/Alt\n"
    "等修饰键,如 Ctrl+侧键）。键盘按下的第一个非修饰键即定型\n"
    "（无需等待松开）,鼠标按键按下即定型；点击「录入」后 0.3 秒内\n"
    "的鼠标点击会被忽略（保护期）。鼠标热键无法拦截点击（点击会透传）。\n"
    "按 ESC 放弃键盘录入":
        "Supports keyboard combos and mouse buttons (left/right/middle/side, plus "
        "modifiers like Ctrl/Shift/Alt,\ne.g. Ctrl+side button). The first non-modifier "
        "key pressed finalizes the combo\n(no need to wait for release); mouse buttons "
        "finalize on press. Mouse clicks within 0.3s\nafter clicking \"Capture\" are "
        "ignored (protection window). Mouse hotkeys cannot block the click "
        "(it passes through).\nPress ESC to cancel keyboard capture",
    "清空该行键位；应用并保存后此功能不再绑定快捷键（仍可通过托盘菜单触发）":
        "Clear this binding; after Apply & Save the action has no hotkey "
        "(still available in the tray menu)",

    # ---- 通用页 ----
    "启动行为（下次启动生效）": "Startup behavior (takes effect on next launch)",
    "启动时暂停定时监控": "Pause monitoring at startup",
    "启动时隐藏桌面浮窗": "Hide overlay at startup",
    "日志与记录": "Logging & History",
    "日志级别": "Log level",
    "记录分析截图与回答": "Save screenshots & answers",
    "记录目录": "History folder",
    "语言": "Language",
    "勾选后每次启动不自动定时监控（可手动回答,或稍后通过托盘/快捷键恢复监控）":
        "Do not start periodic monitoring automatically (you can still answer "
        "manually or resume via tray/hotkey)",
    "勾选后每次启动不显示回答窗口（可通过托盘菜单或快捷键再显示）":
        "Do not show the answer window at startup (re-show via tray menu or hotkey)",
    "日志详细程度：DEBUG 最详细,ERROR 只记错误；排查问题选 DEBUG":
        "Log verbosity: DEBUG most detailed, ERROR errors only; use DEBUG for "
        "troubleshooting",
    "每次回答把问题截图和回答文本成对保存到下方记录目录的当日日期子目录；\n"
    "取消勾选后不再落盘（已有历史保留）。应用并保存后生效":
        "Each answer saves the question screenshot and answer text into today's "
        "subfolder of the history directory below;\nuncheck to stop saving (existing "
        "history kept). Applies after Apply & Save",
    "问题截图与回答的保存目录（相对程序目录,默认 QA_History）,\n"
    "按日期建子目录（如 QA_History\\2026-11-12\\）,历史永久保留；\n"
    "应用后新记录写入新目录":
        "Folder for question screenshots and answers (relative to the app folder, "
        "default QA_History),\nwith per-date subfolders (e.g. QA_History\\2026-11-12\\); "
        "history is kept forever;\nafter Apply new records go to the new folder",
    "界面语言（中文/English）；切换并保存后重启程序生效":
        "UI language (Chinese/English); takes effect after saving and restarting the app",

    # ---- 任务栏停靠位置（taskbarwin） ----
    "任务栏内（托盘区左侧）": "In taskbar (left of tray)",
    "底部居中": "Bottom center",
    "底部左侧": "Bottom left",
    "底部右侧": "Bottom right",
    "顶部居中": "Top center",
    "顶部左侧": "Top left",
    "顶部右侧": "Top right",

    # ---- 浮窗（overlaywin） ----
    "等待监控...": "Waiting for screen...",
    "复制所选": "Copy selection",
    "复制回答全文": "Copy full answer",
    "移动浮窗:按住 Alt 拖动 / 缩放:拖右下角":
        "Move: hold Alt and drag / Resize: drag bottom-right corner",

    # ---- 渲染截断标记（imagerender） ----
    "…(内容过长已截断)": "…(truncated)",

    # ---- 托盘菜单（trayicon） ----
    "桌面智能监控回答": "Desktop Screen QA Monitor",
    "暂停/恢复定时监控": "Pause/Resume monitoring",
    "框选监控区域": "Select monitor region",
    "设置": "Settings",
    "退出": "Exit",

    # ---- 弹窗（settingsui） ----
    "另存为方案": "Save as new profile",
    "请输入方案名称：": "Enter profile name:",
    "名称无效": "Invalid name",
    "方案名称不能为空。": "Profile name cannot be empty.",
    "输入有误": "Invalid input",
    "已保存": "Saved",
    "方案「{name}」已保存并生效。": "Profile \"{name}\" saved and applied.",
    "无法删除": "Cannot delete",
    "至少保留一个方案。": "At least one profile must remain.",
    "删除方案": "Delete profile",
    "确定删除方案「{name}」？": "Delete profile \"{name}\"?",
    "无法检测": "Cannot detect",
    "请先填写端点地址。": "Please fill in the endpoint first.",
    "检测失败": "Detection failed",
    "获取模型列表失败：{err}\n\n"
    "请检查端点/密钥是否正确；部分服务不支持 /models 接口,\n"
    "此时请直接手动输入模型名。":
        "Failed to fetch model list: {err}\n\n"
        "Check the endpoint/API key; some services do not support /models.\n"
        "Enter the model name manually instead.",
    "检测结果": "Detection result",
    "端点未返回任何模型,请手动输入模型名。":
        "The endpoint returned no models; enter the model name manually.",
    "检测完成": "Detection complete",
    "获取到 {n} 个可用模型,已填充下拉框。":
        "Fetched {n} available models; dropdown filled.",
    "热键恢复失败": "Hotkey restore failed",
    "热键注册失败": "Hotkey registration failed",
    "{err}\n\n其他设置已生效；快捷键保留原键位。":
        "{err}\n\nOther settings applied; hotkeys keep their previous bindings.",
    "{err}\n\n其他设置已生效；快捷键保留原键位,未写入配置。":
        "{err}\n\nOther settings applied; hotkeys keep their previous bindings "
        "(not saved).",
    "保存失败": "Save failed",
    "设置已实时生效,但写回 settings.json 失败（详见日志）,\n重启后将恢复为原配置。":
        "Settings applied, but writing settings.json failed (see log).\nThe previous "
        "config will be restored after restart.",
    "语言设置": "Language",
    "界面语言将在重启程序后生效。": "The UI language takes effect after restarting the app.",

    # ---- 校验消息（settingsui._collect/_int/_float） ----
    "{name} 必须为整数": "{name} must be an integer",
    "{name} 必须为数字": "{name} must be a number",
    "{name} 需在 {lo}~{hi} 之间": "{name} must be between {lo} and {hi}",
    "浮窗{key}": "overlay {key}",
    "浮窗宽/高过小（至少 40x24）": "Overlay width/height too small (minimum 40x24)",
    "坐标异常": "Coordinates out of range",
    "{key} 颜色不能为空": "{key} color cannot be empty",
    "任务栏文本条颜色不能为空": "Taskbar text bar color cannot be empty",
    "指示框颜色不能为空": "Indicator color cannot be empty",
    "大模型端点与模型名不能为空": "LLM endpoint and model name cannot be empty",
    "图像转文字模型需要「端点」和「模型」同时填写（密钥可留空）,或全部留空":
        "Image-to-text requires \"endpoint\" and \"model\" filled together "
        "(API key optional), or all left empty",
    "快捷键「{combo}」含未知鼠标按键（可选 left/right/middle/x/x2）":
        "Hotkey \"{combo}\" contains an unknown mouse button "
        "(choose left/right/middle/x/x2)",
    "快捷键「{combo}」被重复使用": "Hotkey \"{combo}\" is used more than once",
    "记录目录不能为空": "History folder cannot be empty",

    # ---- 关于块（settingsui 通用页） ----
    "关于": "About",
    "版本": "Version",
    "程序当前版本（与 exe 文件属性/发布 tag 一致）":
        "Current app version (matches the exe file properties / release tag)",
    "项目主页": "Project page",
    "点击打开项目 GitHub 仓库（查看更新/提交 Issue）":
        "Open the GitHub repository (check for updates / file issues)",
    "点击在浏览器中打开项目主页": "Click to open the project page in your browser",
    "复制项目链接": "Copy link",
    "把项目主页地址复制到剪贴板": "Copy the project page URL to the clipboard",

    # ---- 场景模板正文（settingsui：英文模式下选模板填入英文提示词） ----
    "请识别并回答图片中的题目，直接给出正确答案（选项或数值），并用一句话说明理由。":
        "Identify and answer the question in the image; give the correct answer "
        "(option or value) directly, with a one-sentence justification.",
    "请识别图片中的题目，给出正确答案，并分步骤讲解解题过程与涉及的知识点。":
        "Identify the question in the image, give the correct answer, and explain "
        "the solution step by step with the knowledge points involved.",
    "请原样输出图片中的全部文字内容，不要回答、不要解释。":
        "Output all text in the image verbatim; do not answer or explain.",
    "请把图片中的文字翻译成中文，保持原有的标题、列表、表格结构。":
        "Translate the text in the image into Chinese, preserving the original "
        "headings, lists and table structure.",
    "请提取图片内容的要点，用简洁的条目式列表总结。":
        "Extract the key points of the image content and summarize them as a "
        "concise bulleted list.",
    "请识别图片中的术语、概念或专有名词，逐条给出通俗易懂的解释。":
        "Identify terms, concepts or proper nouns in the image and explain each "
        "one in plain language.",
    "请识别图片中的公式或算式，给出计算过程与最终结果。":
        "Identify formulas or equations in the image; show the calculation steps "
        "and the final result.",

    # ---- 浮窗/任务栏运行时状态文本（controller/monitor/main） ----
    "[定时监控已暂停]": "[Monitoring paused]",
    "[定时监控已恢复]": "[Monitoring resumed]",
    "[区域已更新] {region}": "[Region updated] {region}",
    "[手动捕获错误] {err}": "[Manual capture error] {err}",
    "[捕获错误] {err}": "[Capture error] {err}",
    "[区域指示框已显示]": "[Region indicator shown]",
    "[区域指示框已隐藏]": "[Region indicator hidden]",
    "[错误] {err}": "[Error] {err}",

    # ---- 键位标签 ----
    "未设置": "not set",

    # ---- 日志文案（controller/monitor/llmclient/appconfig/imagerender/main） ----
    "开始框选监控区域": "Start selecting monitor region",
    "手动触发回答": "Manual answer triggered",
    "打开设置窗口": "Opening settings window",
    "保存分析记录失败: %s": "Failed to save analysis record: %s",
    "检测到画面变化": "Screen change detected",
    "画面未变化": "Screen unchanged",
    "已保存分析记录": "Analysis record saved",
    "定时监控 %s": "Periodic monitoring %s",
    "暂停": "paused",
    "恢复": "resumed",
    "回答展示（任务栏文本条） %s": "Answer display (taskbar text bar) %s",
    "桌面浮窗 %s": "Desktop overlay %s",
    "区域指示框 %s": "Region indicator %s",
    "显示": "shown",
    "隐藏": "hidden",
    "移除热键 %s 失败: %s": "Failed to remove hotkey %s: %s",
    "未知鼠标按键: {combo}": "Unknown mouse button: {combo}",
    "热键已更新: %s": "Hotkeys updated: %s",
    "（全部未绑定）": "(none bound)",
    "托盘菜单刷新失败: %s": "Failed to refresh tray menu: %s",
    "[%s] 调用地址: %s | 模型: %s%s": "[%s] URL: %s | model: %s%s",
    " | 附图: 是": " | image: yes",
    "[%s] 提示词: %s": "[%s] prompt: %s",
    "[%s] 返回消息: %s": "[%s] response: %s",
    "%s 调用失败(第%d次): %s；已限流,%g 秒后重试%s":
        "%s call failed (attempt %d): %s; rate limited, retrying in %g s%s",
    "%s 调用失败(第%d次): %s": "%s call failed (attempt %d): %s",
    "（服务端指定）": "(server-specified)",
    "图像转文字模型": "image-to-text model",
    "图像转文字失败,回退为截图直发主模型: %s":
        "Image-to-text failed; falling back to sending the screenshot directly "
        "to the main model: %s",
    "写回 settings.json 失败（仅本次运行生效）: %s":
        "Failed to write settings.json (effective for this run only): %s",
    "日志文件创建失败（仅控制台输出）: {err}":
        "Failed to create log file (console output only): {err}",
    "监控区域已更新并持久化: {region}": "Monitor region updated and persisted: {region}",
    "监控区域仅本次运行生效（settings.json 写盘失败）":
        "Monitor region effective for this run only (failed to write settings.json)",
    "颜色值非法: %r,回退为白色": "Invalid color value: %r, falling back to white",
    "部分热键注册失败: %s": "Some hotkeys failed to register: %s",
    "已启动（托盘常驻）。键位可在托盘设置窗口修改（持久化于 settings.json）。":
        "Started (tray resident). Hotkeys can be changed in the tray settings window "
        "(persisted in settings.json).",
}


def set_language(lang: str):
    """设定界面语言（进程级,启动时由 appconfig 调用一次；切换需重启生效）。"""
    global _LANG
    _LANG = lang if lang in LANGUAGES else "zh"


def get_language() -> str:
    return _LANG


def t(s: str) -> str:
    """翻译用户可见文案：中文环境原样返回（中文原文即键）；
    英文环境查 _EN 表,未收录键回退中文原文（漏配不报错不空白）。"""
    if _LANG != "en":
        return s
    return _EN.get(s, s)
