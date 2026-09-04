"""
BuiltinTools — 内置工具注册器

集中管理内置工具的参数 schema 和注册逻辑。
被以下模块使用：
- agent_core.py          → BuiltinToolRegistry, get_builtin_tool_params
- agent/tool_executor.py → get_builtin_tool_params
- context/orchestrator.py → get_builtin_tool_params
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# 内置工具参数 Schema（单一事实源）
# ═══════════════════════════════════════════════════════════════

_BUILTIN_SCHEMAS: Dict[str, Dict] = {
    "recall_history": {
        "description": "【历史召回】召回本会话被折叠/驱逐出当前上下文窗口的早期对话内容（P1-1③）。当用户提到“之前讨论过”“刚才说的”而当前上下文里找不到时，用本工具按关键词召回被压缩归档的历史轮次。与 memory_search 的区别：memory_search 查长期记忆库（跨会话持久），本工具查当前会话的上下文台账（本会话内被折叠的内容）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "召回关键词（在折叠台账中匹配，留空返回最近折叠的内容）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 10},
            },
        },
    },
    "memory_search": {
        "description": "【内部记忆检索】仅搜索本Agent自身存储的历史对话和记忆条目。不能搜索互联网、不能查天气、不能查新闻、不能获取任何外部实时信息。仅用于回忆用户之前说过的话或Agent之前记录的内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（在自身记忆库中匹配）"},
                "category": {"type": "string", "description": "记忆类别过滤"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 5},
            },
            "required": ["query"],
        },
    },
    "file_read": {
        "description": "读取文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "description": "起始行号"},
                "encoding": {"type": "string", "description": "文件编码", "default": "utf-8"},
            },
            "required": ["file_path"],
        },
    },
    "file_write": {
        "description": "写入文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
                "encoding": {"type": "string", "description": "文件编码", "default": "utf-8"},
            },
            "required": ["file_path", "content"],
        },
    },
    "file_create": {
        "description": "创建新文件",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "初始内容"},
            },
            "required": ["file_path"],
        },
    },
    "file_delete": {
        "description": "删除文件",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
            },
            "required": ["file_path"],
        },
    },
    "file_edit": {
        "description": "编辑文件（查找替换）",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "old_str": {"type": "string", "description": "待替换文本"},
                "new_str": {"type": "string", "description": "替换后文本"},
            },
            "required": ["file_path", "old_str", "new_str"],
        },
    },
    "computer_screenshot": {
        "description": "截取屏幕截图",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "computer_click": {
        "description": "点击屏幕指定位置",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X 坐标"},
                "y": {"type": "number", "description": "Y 坐标"},
                "button": {"type": "string", "description": "鼠标按钮", "default": "left"},
            },
            "required": ["x", "y"],
        },
    },
    "computer_type": {
        "description": "键盘输入文本",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "输入文本"},
            },
            "required": ["text"],
        },
    },
    "computer_scroll": {
        "description": "滚动屏幕",
        "parameters": {
            "type": "object",
            "properties": {
                "scroll_x": {"type": "integer", "description": "水平滚动量", "default": 0},
                "scroll_y": {"type": "integer", "description": "垂直滚动量", "default": 0},
            },
            "required": [],
        },
    },
    "computer_shell": {
        "description": "执行 shell 命令",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "shell 命令"},
            },
            "required": ["command"],
        },
    },
    # ── 浏览器操作工具（BrowserManager 多后端：Playwright/Scrapling）──
    # 执行过程的页面截图会实时推送到聊天页的电脑操作分屏面板
    "browser_navigate": {
        "description": "【浏览器导航】在内置自动化浏览器中打开指定 URL。这是工具阶梯中最重的一档：仅当 web_search/web_fetch 无法完成任务（需要页面交互、登录或 JS 动态渲染）时才使用；纯读取内容一律先用 web_search 搜索、web_fetch 抓取。打开后可用 browser_extract_text 提取正文、browser_click/browser_type 交互、browser_screenshot 截图。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要访问的完整 URL（含 https://）"},
            },
            "required": ["url"],
        },
    },
    "browser_click": {
        "description": "【浏览器点击】点击当前页面上的元素。selector 支持 CSS 选择器或 Playwright 的 text= 文本定位；也可只传 text 按可见文本查找（如'登录'按钮）。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS 选择器（如 #submit-btn、a.login）"},
                "text": {"type": "string", "description": "按可见文本匹配元素（selector 的替代方案）"},
            },
            "required": [],
        },
    },
    "browser_type": {
        "description": "【浏览器输入】向页面输入框填写文本。先清空原内容再输入，适合搜索框、表单、登录框等。",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "目标输入框的 CSS 选择器"},
                "text": {"type": "string", "description": "要输入的文本"},
            },
            "required": ["selector", "text"],
        },
    },
    "browser_screenshot": {
        "description": "【浏览器截图】截取当前浏览器页面的画面。截图会实时显示在聊天页的电脑操作面板中，并返回页面标题和 URL。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "browser_extract_text": {
        "description": "【浏览器提取文本】提取当前浏览器页面的正文文字内容，用于阅读网页、总结文章、获取搜索结果等。建议先用 browser_navigate 打开页面。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # ── 可访问性快照 + role 定位（观察优先协议）──
    # 协议：先 browser_dom_snapshot 拿结构化页面事实，再从快照里取 role+name 交互；
    # 快照已包含目标信息时禁止用 evaluate/HTML 探索；禁止猜测 CSS 选择器
    "browser_dom_snapshot": {
        "description": "【页面可访问性快照】获取当前页面的 aria 结构化树（按钮/链接/输入框等元素的角色和名称）。与页面交互前必须先调用本工具，从快照事实中获取目标元素的 role 和 name，再用 browser_click_role/browser_fill_role 精确定位；不要凭空猜测 CSS 选择器。返回含本次快照对应的 generation。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。持有的页面代数；页面已变化时返回过期错误提示重新快照"},
            },
            "required": [],
        },
    },
    "browser_click_role": {
        "description": "【按角色点击】通过 ARIA 角色和可访问名称点击页面元素（如 role=button, name=登录）。参数必须来自 browser_dom_snapshot 快照中的事实，不要编造。元素不可点击或页面已变化（generation 过期）时返回错误说明。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "ARIA 角色（button/link/textbox/checkbox 等，来自快照）"},
                "name": {"type": "string", "description": "可访问名称（来自快照，如按钮文字）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；页面被外部操作导航过后会拒绝并提示重新快照"},
            },
            "required": ["role"],
        },
    },
    "browser_fill_role": {
        "description": "【按角色输入】通过 ARIA 角色和可访问名称定位输入框并填写文本（如 role=textbox, name=用户名）。参数必须来自 browser_dom_snapshot 快照；text 传空串表示清空输入框。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "ARIA 角色（textbox/searchbox 等，来自快照）"},
                "name": {"type": "string", "description": "可访问名称（来自快照，如输入框标签）"},
                "text": {"type": "string", "description": "要填写的文本（空串=清空）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；页面已变化时会拒绝并提示重新快照"},
            },
            "required": ["role", "text"],
        },
    },
    # ── 互联网平台直达（Web Reach，对标 Agent-Reach 零配置路径）──
    "youtube_transcript": {
        "description": "【YouTube 字幕】提取 YouTube 视频的字幕/自动字幕文本，用于总结视频内容、翻译、要点提取。仅支持 youtube.com/watch 或 youtu.be 链接。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube 视频链接"},
            },
            "required": ["url"],
        },
    },
    "browser_read": {
        "description": "【浏览器读取】通过 Playwright 驱动真实浏览器，渲染 JavaScript 密集型网页（SPA / 客户端渲染 / 反爬轻量页面）并提取为干净 Markdown 文本。与 web_read（Jina Reader）互补：web_read 适合静态页，browser_read 处理 JS 渲染页。注意：首次使用需安装浏览器（playwright install chromium）。返回文本上限 60,000 字符。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要读取的网页 URL（http/https）"},
                "timeout": {"type": "number", "description": "超时秒数（默认 30，单次读取建议 ≤60）"},
            },
            "required": ["url"],
        },
    },
    "bilibili_search": {
        "description": "【B站搜索】搜索 B 站视频，返回标题与链接。用于查找中文视频教程、评测、讲解等内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回条数（默认 5）"},
            },
            "required": ["query"],
        },
    },
    "rss_read": {
        "description": "【RSS 阅读】读取 RSS/Atom 订阅源的最新条目（标题/链接/摘要）。用于追踪博客、播客、新闻源更新。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "RSS/Atom 源地址"},
                "limit": {"type": "integer", "description": "返回条数（默认 10）"},
            },
            "required": ["url"],
        },
    },
    "v2ex_hot": {
        "description": "【V2EX 热门】获取 V2EX 社区当前热门帖子（标题/链接/回复数/作者）。用于了解开发者社区热议话题。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数（默认 10）"},
            },
            "required": [],
        },
    },
    "social_search": {
        "description": "【社交平台搜索】查询社交平台（twitter/reddit/xiaohongshu/facebook/instagram/linkedin）的搜索接入状态。已配置登录态后端时返回后端与命令信息；未配置时返回配置引导。不自动登录。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台名（twitter/reddit/xiaohongshu/facebook/instagram/linkedin）"},
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["platform", "query"],
        },
    },
    "planning": {
        "description": "【任务计划】创建和管理结构化任务计划，适合多步骤长任务：先 create 建立步骤清单，执行过程中用 mark_step 标记各步状态（completed/in_progress/blocked），让用户和后续轮次都能看到全局进度。计划持久化存储，重启后仍可 get 查询继续推进。对于需要多轮才能完成的任务，开工前先建计划。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["create", "update", "list", "get", "set_active", "mark_step", "delete"],
                    "description": "子命令：create 建计划 / update 改标题或步骤 / list 列出全部 / get 查看计划全文（含进度）/ set_active 设为当前活跃计划 / mark_step 标记步骤状态 / delete 删除",
                },
                "plan_id": {"type": "string", "description": "计划 ID；create 必填，get/mark_step 缺省时取当前活跃计划"},
                "title": {"type": "string", "description": "计划标题（create 必填）"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "步骤文本列表（create 必填；update 传入时替换步骤清单，已有状态保留）",
                },
                "step_index": {"type": "integer", "description": "mark_step：目标步骤下标（0 起）"},
                "step_status": {
                    "type": "string",
                    "enum": ["not_started", "in_progress", "completed", "blocked"],
                    "description": "mark_step：要设置的状态",
                },
                "step_notes": {"type": "string", "description": "mark_step：可选的步骤备注（如完成摘要）"},
            },
            "required": ["command"],
        },
    },
    "emotion_analyze": {
        "description": "分析文本情感",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待分析文本"},
            },
            "required": ["text"],
        },
    },
    "asr_transcribe": {
        "description": "将音频转写为文本（语音识别）",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_data": {"type": "string", "description": "Base64编码的音频数据"},
                "language": {"type": "string", "description": "语言代码（如 zh, en）", "default": "zh"},
                "engine": {"type": "string", "description": "ASR 引擎（如 funasr, whisper, auto）", "default": "auto"},
            },
            "required": ["audio_data"],
        },
    },
    "tts_synthesize": {
        "description": "将文本合成为语音",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要合成的文本"},
                "voice": {"type": "string", "description": "音色名称（如 zh-CN-XiaoxiaoNeural）", "default": "default"},
                "engine": {
                    "type": "string",
                    "description": "TTS 引擎（如 edge-tts, moss-nano, auto）",
                    "default": "auto",
                },
            },
            "required": ["text"],
        },
    },
    "voice_memory_search": {
        "description": "【内部语音记忆检索】仅搜索用户之前通过语音说过的内容（语音转写后的记录）。不能搜索互联网、不能查天气、不能获取外部信息。仅用于回忆用户语音对话历史。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（在语音记忆中匹配）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 5},
            },
            "required": ["query"],
        },
    },
    # Bug W-1 修复: 补齐 weather / web_search schema
    # 原本 tool_executor.py 已实现 _execute_weather / _execute_web_search，
    # 但未注册到 _BUILTIN_SCHEMAS（LLM 工具列表的单一事实源），
    # 导致 LLM 永远看不到这两个工具，agent 只能回复"无法获取实时信息"。
    # 参数与 tool_executor._execute_weather / _execute_web_search 的读取逻辑对齐。
    "weather": {
        "description": "【实时天气查询】通过 wttr.in 服务获取指定地点的实时天气信息。可查询当前天气、温度、降水、风力等。支持中文城市名（如'许昌'、'北京'）或英文地名。需要实时天气信息时必须调用此工具，不要回复'无法获取'。",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "查询地点（城市名，如'许昌'、'北京'、'Shanghai'）",
                },
                "city": {
                    "type": "string",
                    "description": "城市名（location 的别名，二选一即可）",
                },
                "query": {
                    "type": "string",
                    "description": "地点查询字符串（location 的别名，二选一即可）",
                },
            },
            "required": ["location"],
        },
    },
    "web_search": {
        "description": "【实时网络搜索】通过搜索引擎查询互联网上的实时信息（新闻、股价、百科、技术文档等）。当用户需要 memory_search 无法提供的实时或外部信息时调用此工具。返回搜索结果摘要文本。工具选择阶梯（最轻优先）：不知道网址先用本工具搜索 → 拿到具体网址后用 web_fetch 读取 → 仅当页面需要交互/登录/动态渲染才升级 browser_* 工具，不要直接开浏览器做纯检索。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询词",
                },
                "q": {
                    "type": "string",
                    "description": "搜索查询词（query 的别名，二选一即可）",
                },
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词（query 的别名，二选一即可）",
                },
            },
            "required": ["query"],
        },
    },
    "spawn_subagent": {
        "description": "【蜂群派生子Agent】将一个子任务派交给另一个 Agent 执行（蜂群编排）。当任务可分解为多个相对独立的子任务（如：多主题调研、多文件分析、多视角评审）时，对每个子任务各调用一次本工具即可并行蜂群执行。每个子 Agent 拥有独立的人设/记忆/模型配置。前台模式等待完成并返回最终报告；background=true 立即返回 subagent_id（用 subagent_status 查询结果）。子 Agent 的执行过程会实时显示在聊天界面的子 Agent 小窗中。可先用 list_agents 查看可用的子 Agent。配额纪律（系统强制，超限派生会被数据层直接拒绝）：任务要求 N 个子任务就只调 N 次；用户未指定数量时每层 1-3 个；禁止为同一子任务重复派生；禁止派生与当前任务无关的子 Agent；并发上限 5，超限先 subagent_status 等待回收再派生。",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "交给子 Agent 的完整、自包含的任务描述（子 Agent 看不到当前对话历史，任务描述必须包含它需要的全部上下文）",
                },
                "agent_id": {
                    "type": "string",
                    "description": "目标子 Agent ID（可选，留空使用默认 Agent；建议先用 list_agents 查看可用 Agent 及其专长）",
                },
                "background": {
                    "type": "boolean",
                    "description": "是否后台执行（true=立即返回，稍后用 subagent_status 查询；false=等待完成直接返回报告）",
                },
            },
            "required": ["task"],
        },
    },
    "subagent_status": {
        "description": "【查询子Agent状态】查询蜂群派生的后台子 Agent 的执行状态与最终报告。配合 spawn_subagent(background=true) 使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {
                    "type": "string",
                    "description": "spawn_subagent 返回的 subagent_id",
                },
            },
            "required": ["subagent_id"],
        },
    },
    "list_agents": {
        "description": "【列出可用Agent】列出系统中所有可用的 Agent（含各自的名字、职责描述、模型配置）。在蜂群派生（spawn_subagent）前调用，以便为子任务挑选最合适的执行者。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "create_skill": {
        "description": "【创建可执行技能】当你发现一组工具调用反复出现（可由 LLM 直接复用）时，把它们组合成持久化的可执行技能；之后任何对话都能通过 `name` 一键调用。技能 = 一次或多次工具调用的有序执行 + 可选的步间占位符（`{step_<idx>.<field>}` 引用前序步骤的输出字段）。创建后立即在本会话与 SkillRegistry 中可见可调。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能唯一标识（小写下划线），例：weather_then_save"},
                "description": {"type": "string", "description": "技能的功能与触发场景说明，LLM 用此判断是否调用"},
                "steps": {
                    "type": "array",
                    "description": "按顺序执行的工具步骤列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "被调用的内置工具名，如 web_search / browser_screenshot / file_write"},
                            "params": {
                                "type": "object",
                                "description": "传给该工具的参数字典（支持 `{step_<idx>.<field>}` 占位符引用前序步骤输出）",
                            },
                        },
                        "required": ["name", "params"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["name", "description", "steps"],
        },
    },
    # ── 常规 Agent 工具（2026-08 扩充，对标主流 harness 标配工具基座）──
    # file_list/file_search ↔ Claude Code Glob/Grep、OpenHands glob/search
    # web_fetch ↔ Claude Code WebFetch；run_code ↔ DeepSeek code_interpreter
    # （run_code 执行体早已存在于 tool_executor，此处补 schema 使其对 LLM 可见）
    # calculator/get_datetime ↔ Hermes function calling 标配
    "file_list": {
        "description": "【文件枚举】按 glob 模式列出文件（如 *.py、docs/**/*.md），支持递归子目录。用于查看某目录下存在哪些文件。找到文件后可用 file_read 读取内容，或用 file_search 按内容关键词搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 匹配模式，如 *.py、*.json"},
                "path": {"type": "string", "description": "搜索的根目录（默认当前工作目录）"},
                "recursive": {"type": "boolean", "description": "是否递归子目录（默认 true）"},
            },
            "required": ["pattern"],
        },
    },
    "file_search": {
        "description": "【文件内容搜索】按关键词或正则在文件内容中搜索（类似 grep），返回匹配的文件、行号和行内容。可搜索单个文件或整个目录。用于定位某段代码/配置/文本出现在哪些文件的哪一行。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（支持正则；非法正则自动降级为字面量匹配）"},
                "path": {"type": "string", "description": "要搜索的文件或目录路径"},
                "include": {"type": "string", "description": "搜索目录时的文件名过滤，如 *.py（可选）"},
                "max_results": {"type": "integer", "description": "返回的最大匹配条数", "default": 50},
            },
            "required": ["pattern", "path"],
        },
    },
    "web_fetch": {
        "description": "【网页抓取】抓取指定 URL 的内容并转为纯文本（阅读文章、文档、API 响应等）。已知网址要读取其内容时用此工具；不知道网址先用 web_search 搜索。仅支持 http/https 协议。若本工具返回空或内容不完整（JS 动态页），再升级 browser_* 工具处理，不要跳过本工具直接用浏览器。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的完整 URL（含 https://）"},
                "max_chars": {"type": "integer", "description": "返回内容最大字符数（默认 8000，超出截断）"},
            },
            "required": ["url"],
        },
    },
    "run_code": {
        "description": "【代码执行】运行一段 Python 或 shell 代码，返回 stdout/stderr/退出码。用于数据处理、批量文件操作、验证代码逻辑等。代码在本地运行时执行，受治理策略约束。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码字符串"},
                "language": {"type": "string", "description": "代码语言：python（默认）或 shell"},
                "timeout": {"type": "integer", "description": "执行超时秒数（默认 60）"},
            },
            "required": ["code"],
        },
    },
    "calculator": {
        "description": "【计算器】精确计算数学表达式。支持 + - * / // % **、括号，以及 sqrt/abs/round/min/max/sin/cos/tan/log/floor/ceil 函数和 pi/e 常量。涉及数值计算时应调用此工具，不要心算，避免算术错误。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式，如 (1+2)*3、sqrt(16)、round(pi*2, 2)"},
            },
            "required": ["expression"],
        },
    },
    "get_datetime": {
        "description": "【日期时间】获取当前日期时间（含星期、ISO 格式、Unix 时间戳），或将 Unix 时间戳换算为指定时区的日期时间。用于需要当前时间、时区换算、时间戳换算的场合。",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "时区名（如 Asia/Shanghai、UTC）或偏移（如 +08:00），默认系统本地时区"},
                "timestamp": {"type": "number", "description": "Unix 时间戳（秒）；提供时换算该时间戳而非当前时间"},
            },
            "required": [],
        },
    },
    # ── 画布交互工具（Phase 1）：Agent 直接搭建/修改/运行画布工作流 ──
    # 语义操作层（canvas_ops）统一写入口，与用户手动编辑共享乐观锁版本；
    # 用户可随时抢占编辑，携带 base_version 的过期操作会返回
    # code=version_conflict + current_version，此时应 canvas_read 重读后重试。
    "canvas_create": {
        "description": "【创建画布】新建一张空白工作流画布，返回 canvas_id（后续所有 canvas_* 操作都需要它）。当用户希望你搭建/设计/制作一个工作流、流水线、流程图时先调用本工具。画布会实时显示在前端协作画布页。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "画布名称（简洁描述工作流用途）"},
                "description": {"type": "string", "description": "画布用途说明（可选）"},
            },
            "required": ["name"],
        },
    },
    "canvas_read": {
        "description": "【读取画布】读取画布完整快照（节点、连线、各节点配置和当前 version）。用于：了解画布现状、version_conflict 后重新获取最新版本再重试。返回的 version 应作为后续修改操作的 base_version。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
            },
            "required": ["canvas_id"],
        },
    },
    "canvas_add_node": {
        "description": "【添加节点】向画布添加一个节点。node_type 必须是节点库中已注册的类型（不确定时先用 canvas_list_nodes 查询）。返回新节点（含自动生成的 id 与自动落位）。可选携带 base_version 做乐观锁校验。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "node_type": {"type": "string", "description": "节点类型（如 builtin:start、builtin:llm_chat），用 canvas_list_nodes 查询可用类型"},
                "config": {"type": "object", "description": "节点初始配置（键为节点表单字段 id，可选）"},
                "label": {"type": "string", "description": "节点显示名称（可选，默认用节点库名称）"},
                "position": {"type": "object", "description": "坐标 {x, y}（可选，缺省自动落位）"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id", "node_type"],
        },
    },
    "canvas_connect": {
        "description": "【连接节点】在画布上把两个节点用连线接起来（source_node 的输出 → target_node 的输入）。端口 id 缺省时使用默认端口。重复连线会返回 duplicate_edge 错误。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "source_node": {"type": "string", "description": "上游节点 id"},
                "target_node": {"type": "string", "description": "下游节点 id"},
                "source_port": {"type": "string", "description": "上游输出端口 id（可选，默认第一个输出）"},
                "target_port": {"type": "string", "description": "下游输入端口 id（可选，默认第一个输入）"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id", "source_node", "target_node"],
        },
    },
    "canvas_set_config": {
        "description": "【配置节点】修改画布上某节点的配置项（浅合并：只覆盖传入的键，其余保留）。values 的键是节点表单字段 id（可通过 canvas_read 查看节点现有 config）。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "node_id": {"type": "string", "description": "节点 id"},
                "values": {"type": "object", "description": "要合并进节点配置的键值对"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id", "node_id", "values"],
        },
    },
    "canvas_move_node": {
        "description": "【移动节点】调整画布上某节点的坐标位置。一般搭完流程后直接用 canvas_layout 自动布局即可，仅在需要微调时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "node_id": {"type": "string", "description": "节点 id"},
                "x": {"type": "number", "description": "横坐标"},
                "y": {"type": "number", "description": "纵坐标"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id", "node_id", "x", "y"],
        },
    },
    "canvas_remove_node": {
        "description": "【删除节点】从画布删除某节点，与其相连的连线会一并删除（返回删除的连线数）。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "node_id": {"type": "string", "description": "要删除的节点 id"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id", "node_id"],
        },
    },
    "canvas_layout": {
        "description": "【自动布局】按拓扑分层对画布全部节点自动排版（上游在左、下游在右）。建议在添加完节点和连线后调用一次，让画布整齐可读。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "base_version": {"type": "integer", "description": "读取画布时的版本号（可选，用于并发冲突检测）"},
            },
            "required": ["canvas_id"],
        },
    },
    "canvas_run": {
        "description": "【运行画布】把画布编译为工作流并同步执行，返回整体状态与每个节点的执行结果（状态/输出/错误/耗时）。搭完工作流后用它验证流程是否跑通。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "inputs": {"type": "object", "description": "工作流全局输入（可选，键值对）"},
            },
            "required": ["canvas_id"],
        },
    },
    "canvas_list_nodes": {
        "description": "【查询节点库】列出/搜索可用节点类型（含 type、名称、分类、来源）。添加节点前如不确定 node_type，先用本工具查询；搜索无果说明节点库缺少该能力，可考虑建议用户创建自定义节点。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "按名称/类型/描述模糊搜索（可选，缺省列出全部）"},
                "category": {"type": "string", "description": "按分类过滤（可选）"},
                "limit": {"type": "integer", "description": "最多返回条数（默认 20）"},
            },
            "required": [],
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# 内置工具执行映射（占位，实际执行逻辑在 ToolExecutor）
# ═══════════════════════════════════════════════════════════════

_BUILTIN_EXEC_MAP: Dict[str, Callable] = {}


def get_builtin_tool_params(tool_name: str) -> Optional[Dict]:
    """
    获取内置工具的参数 schema

    Args:
        tool_name: 工具名称

    Returns:
        工具参数 schema，如果不存在则返回 None
    """
    return _BUILTIN_SCHEMAS.get(tool_name)


def register_builtin_exec(tool_name: str, exec_func: Callable):
    """
    注册内置工具的执行函数

    Args:
        tool_name: 工具名称
        exec_func: 执行函数
    """
    _BUILTIN_EXEC_MAP[tool_name] = exec_func


@dataclass
class BuiltinTool:
    """内置工具数据结构"""

    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str] = field(default_factory=list)

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class BuiltinToolRegistry:
    """内置工具注册器"""

    def __init__(self):
        self._tools: Dict[str, BuiltinTool] = {}
        self._init_default_tools()

    def _init_default_tools(self):
        """初始化默认内置工具"""
        for tool_name, schema in _BUILTIN_SCHEMAS.items():
            tool = BuiltinTool(
                name=tool_name,
                description=schema["description"],
                parameters=schema["parameters"],
                required=schema["parameters"].get("required", []),
            )
            self._tools[tool_name] = tool

    def get_tool(self, tool_name: str) -> Optional[BuiltinTool]:
        """获取工具"""
        return self._tools.get(tool_name)

    def list_tools(self) -> List[BuiltinTool]:
        """列出所有工具"""
        return list(self._tools.values())

    def get_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())

    def get_openai_tools(self) -> List[Dict]:
        """获取 OpenAI function calling 格式的工具列表"""
        return [tool.to_openai_format() for tool in self._tools.values()]

    def has_tool(self, tool_name: str) -> bool:
        """检查工具是否存在"""
        return tool_name in self._tools

    def execute_tool(self, tool_name: str, params: Dict) -> Any:
        """
        执行工具

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            执行结果
        """
        if tool_name not in _BUILTIN_EXEC_MAP:
            raise ValueError(f"工具 {tool_name} 没有注册执行函数")

        exec_func = _BUILTIN_EXEC_MAP[tool_name]
        return exec_func(params)

    def register_tool(self, tool: BuiltinTool):
        """注册新工具"""
        self._tools[tool.name] = tool

    def unregister_tool(self, tool_name: str):
        """注销工具"""
        if tool_name in self._tools:
            del self._tools[tool_name]

    def get_tools_by_category(self, category: str) -> List[BuiltinTool]:
        """按类别获取工具（简单实现）"""
        # 这里可以扩展为更复杂的分类逻辑
        tools = []
        for tool in self._tools.values():
            if category in tool.name:
                tools.append(tool)
        return tools
