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
        "description": "【历史召回】召回本会话被折叠/驱逐出当前上下文窗口的早期对话内容（P1-1③）。当用户提到“之前讨论过”“刚才说的”而当前上下文里找不到时，用本工具按关键词召回被压缩归档的历史轮次。与 memory_search 的区别：memory_search 查长期记忆库（跨会话持久），本工具查当前会话的上下文台账（本会话内被折叠的内容）。【何时不用】查跨会话长期记忆改用 memory_search；查用户语音说过的话用 voice_memory_search；当前上下文里还找得到的内容不要召回。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "召回关键词（在折叠台账中匹配，留空返回最近折叠的内容）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 10},
            },
        },
    },
    "memory_search": {
        "description": "【内部记忆检索】仅搜索本Agent自身存储的历史对话和记忆条目。不能搜索互联网、不能查天气、不能查新闻、不能获取任何外部实时信息。仅用于回忆用户之前说过的话或Agent之前记录的内容。【何时不用】实时/外部信息改用 web_search；查本会话内被折叠的对话用 recall_history；查用户语音说过的话用 voice_memory_search。",
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
        "description": "【文件读取】读取指定路径文件的内容。已知确切路径时用本工具；还不知道路径先用 file_list 枚举、按内容找用 file_search。【何时不用】大文件建议带 offset 分段读；网页内容不要用本工具（用 web_fetch）。",
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
    "file_parse": {
        "description": "【文档解析】把 PDF/Word/Excel/PPT/RTF/ODF 等二进制文档抽取为纯文本（复用附件抽取通道）。已知是二进制办公文档时用本工具；【何时不用】纯文本/代码/markdown/json 用 file_read（保留行号/编码语义）；网页抓取用 web_fetch；图片/音频/视频不要用本工具（走 vision/asr 通道）。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文档路径（相对锚定工作区，绝对路径按原语义）"},
                "max_chars": {"type": "integer", "description": "返回文本上限（默认 50000，超出截断并标 truncated）", "default": 50000},
            },
            "required": ["file_path"],
        },
    },
    "file_write": {
        "description": "【文件写入】写入（整体覆盖）指定路径文件的内容。【何时不用】对已有文件做局部修改改用 file_edit（查找替换，避免整文件重写）；创建全新文件用 file_create。",
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
        "description": "【文件编辑】查找替换方式修改已有文件：old_str 必须与文件内容逐字符一致且在文件中唯一（含足够上下文行），不唯一则不执行替换。对已有文件的局部修改一律用本工具。【何时不用】整体重写文件用 file_write；新建文件用 file_create。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径"},
                "old_str": {"type": "string", "description": "待替换文本（须逐字符一致且唯一，建议带前后各几行上下文）"},
                "new_str": {"type": "string", "description": "替换后文本"},
            },
            "required": ["file_path", "old_str", "new_str"],
        },
    },
    "computer_screenshot": {
        "description": "截取屏幕截图。结果回带 screen 元数据（宽高/DPI scale/虚拟屏原点）与引导信息；UI 元素事实（按钮/输入框/菜单）不要靠反复截图观察，用 computer_dom_snapshot 获取。",
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
                "interval": {"type": "number", "description": "每字符输入间隔秒数（仅像素兜底路径生效，默认 0.05）"},
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
                "x": {"type": "integer", "description": "滚动位置横坐标（可选，不传则在当前指针位置滚动）"},
                "y": {"type": "integer", "description": "滚动位置纵坐标（可选，不传则在当前指针位置滚动）"},
            },
            "required": [],
        },
    },
    # ── 桌面可访问性快照 + 语义操作（观察优先协议，与浏览器侧 dom_snapshot 同构）──
    # 协议：先 computer_dom_snapshot 拿控件树事实，再按 index 语义操作；
    # 像素坐标 computer_click 仅作快照无法表达时的兜底
    "computer_dom_snapshot": {
        "description": "【桌面可访问性快照】枚举前台（或指定标题）窗口的控件树（按钮/输入框/菜单等，带 index、角色、名称、矩形、可交互标记）。桌面交互前必须先调用本工具，从快照事实中获取元素 index，再用 computer_click_element/computer_set_value 语义操作，不要盲猜屏幕坐标。窗口内容变化后旧快照失效（generation 递增），需重新快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {"type": "string", "description": "可选。目标窗口标题（包含匹配，不区分大小写）；缺省为当前前台窗口"},
                "max_nodes": {"type": "integer", "description": "可选。最多枚举的控件节点数（默认 400）", "minimum": 1},
                "max_depth": {"type": "integer", "description": "可选。控件树最大深度（默认 32）", "minimum": 1},
            },
            "required": [],
        },
    },
    "computer_click_element": {
        "description": "【按元素点击】通过快照元素 index 点击桌面控件（来自 computer_dom_snapshot 快照事实）。内部走语义动作→消息直投的递降链，默认不抢用户焦点、不移动真实光标。快照过期（generation 不符）会被拒绝并提示重新快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "元素序号（来自 computer_dom_snapshot 快照）"},
                "runtime_id": {"type": "string", "description": "可选。UIA runtime id（跨快照更稳，优先于 index）"},
                "window_title": {"type": "string", "description": "可选。目标窗口标题；缺省为最近快照的前台窗口"},
                "button": {"type": "string", "description": "鼠标按钮 left/right/middle", "default": "left"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；过期会被拒绝"},
            },
            "required": [],
        },
    },
    "computer_set_value": {
        "description": "【按元素赋值】通过快照元素 index 向桌面输入框/可编辑控件直接写入文本（UIA ValuePattern，比逐键敲入更快更可靠，且不依赖焦点位置）。参数必须来自 computer_dom_snapshot 快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "要写入的文本"},
                "index": {"type": "integer", "description": "元素序号（来自 computer_dom_snapshot 快照）"},
                "runtime_id": {"type": "string", "description": "可选。UIA runtime id"},
                "window_title": {"type": "string", "description": "可选。目标窗口标题"},
                "generation": {"type": "integer", "description": "可选。快照 generation"},
            },
            "required": ["value"],
        },
    },
    # ── SOM 视觉快照 + 编号点击（R3-1，无 UIA 树桌面的语义中间档）──
    "computer_som_snapshot": {
        "description": "【SOM 视觉快照】对自绘 UI/游戏/远程像素流等无 UIA 树的目标，把截图标注成编号可交互区域图（推操作面板），返回 marks（id/中心坐标/label）。拿到编号后用 computer_click_mark(index=编号) 点击。【何时不用】有 UIA 树的标准窗口一律先 computer_dom_snapshot（结构化更准），本工具是其无法表达时的兜底档。",
        "parameters": {
            "type": "object",
            "properties": {
                "max_marks": {"type": "integer", "description": "可选。最多标注区域数", "minimum": 1},
            },
            "required": [],
        },
    },
    "computer_click_mark": {
        "description": "【按 SOM 编号点击】点击 computer_som_snapshot 返回的某个编号区域中心（内部经 id2xy 解算像素坐标并走 DPI/多屏换算的点击链）。编号来自最近一次 SOM 快照，过期需重新快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "SOM 编号（来自 computer_som_snapshot 的 marks.id）"},
                "button": {"type": "string", "description": "鼠标按钮 left/right/middle", "default": "left"},
            },
            "required": ["index"],
        },
    },
    "computer_ssh_exec": {
        "description": "【SSH 远程命令】经 SSH 在远程 Linux/macOS 机器上执行命令，返回 stdout/stderr/退出码，操作在聊天页的终端窗口展示。用于远程跑命令（无需图形桌面）。host 必填；用户名/密钥/密码从你的 SSH 凭据配置读取（platform=ssh），不必在此传密码。【何时不用】本机命令用 computer_shell；数据处理/算法用 run_code。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "目标主机（IP 或域名）"},
                "command": {"type": "string", "description": "要在远端执行的命令"},
                "user": {"type": "string", "description": "可选。SSH 用户名（缺省用凭据配置）"},
                "port": {"type": "integer", "description": "可选。SSH 端口，默认 22"},
                "timeout": {"type": "number", "description": "可选。命令超时秒，默认 60"},
            },
            "required": ["host", "command"],
        },
    },
    "computer_shell": {
        "description": "【Shell 命令】在用户计算机上执行 shell 命令（Windows 下经 cmd.exe /c）。适合系统操作：进程/服务管理、环境变量、批量文件整理、安装依赖。Windows 注意：cmd.exe 不认单引号包裹的参数（会被当字面量），含空格/特殊字符的路径与参数必须用双引号（如 reg query \"HKLM\\...\"）；查询系统信息类需求优先用本机工具结果（如 computer_screenshot 回带的 screen 元数据），不要跑 reg query 探测。【何时不用】数据处理/算法计算/文本批量处理改用 run_code；纯数值计算禁止在本工具里心算或在 shell 里拼算式，用 run_code 跑 Python；抓取网页不要用 curl（用 web_fetch）。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "shell 命令（Windows 下为 cmd.exe 语法，字符串参数用双引号包裹）"},
            },
            "required": ["command"],
        },
    },
    # ── 浏览器操作工具（BrowserManager 多后端：Playwright/Scrapling）──
    # 执行过程的页面截图会实时推送到聊天页的电脑操作分屏面板
    "browser_navigate": {
        "description": "【浏览器导航】在内置自动化浏览器中打开指定 URL。这是工具阶梯中最重的一档：仅当 web_search/web_fetch 无法完成任务（需要页面交互、登录或 JS 动态渲染）时才使用；纯读取内容一律先用 web_search 搜索、web_fetch 抓取。打开后可用 browser_extract_text 提取正文、browser_click/browser_type 交互、browser_screenshot 截图。【何时不用】已知 URL 的静态页读取不要导航（直接 web_fetch）；站点内搜索不要用导航拼 URL（用 web_search 或 bilibili_search 等垂直工具）。",
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
        "description": "【浏览器提取文本】提取当前浏览器页面的正文文字内容，用于阅读网页、总结文章、获取搜索结果等。建议先用 browser_navigate 打开页面。【何时不用】还没打开页面时先 browser_navigate；需要完整长文分片阅读改用 browser_dom_read；未驱动浏览器前抓静态页直接 web_fetch，不要为本工具单独开浏览器。",
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
        "description": "【页面可访问性快照】获取当前页面的 aria 结构化树（按钮/链接/输入框等元素的角色和名称）。与页面交互前必须先调用本工具，从快照事实中获取目标元素的 role 和 name，再用 browser_click_role/browser_fill_role 精确定位；不要凭空猜测 CSS 选择器。返回含本次快照对应的 generation。可见长页面/长列表快照不完整时，可调大 max_nodes/max_depth 预算（默认节点 1200/深度 32）。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。持有的页面代数；页面已变化时返回过期错误提示重新快照"},
                "max_nodes": {"type": "integer", "description": "可选。最多渲染的快照节点数（默认 1200；长列表/表格可调大）", "minimum": 1},
                "max_depth": {"type": "integer", "description": "可选。快照树最大深度（默认 32）", "minimum": 1},
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
        "description": "【浏览器读取】通过 Playwright 驱动真实浏览器，渲染 JavaScript 密集型网页（SPA / 客户端渲染 / 反爬轻量页面）并提取为干净 Markdown 文本。与 web_fetch 互补：web_fetch 适合静态页，browser_read 处理 JS 渲染页。注意：首次使用需安装浏览器（playwright install chromium）。长文自动分片：首读返回前 60,000 字符 + session_id/can_continue/next_offset；正文未读完时必须带 session_id 续读直到 can_continue=false，不要凭首片下结论。【何时不用】静态页直接 web_fetch（更轻更快）；搜索发现 URL 先 web_search；已打开页面内的正文提取用 browser_extract_text。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要读取的网页 URL（http/https）；续读时可省略"},
                "timeout": {"type": "number", "description": "超时秒数（默认 30，单次读取建议 ≤60）"},
                "session_id": {"type": "string", "description": "可选。续读会话 ID（首读返回的 session_id）；传入后从缓存切片，不再访问网络"},
                "offset": {"type": "integer", "description": "可选。续读起始偏移（默认按上次位置顺序续读）；传 0 可回看首片"},
                "chunk_size": {"type": "integer", "description": "可选。单次返回的文本长度上限（默认 60000）"},
            },
            "required": [],
        },
    },
    "browser_dom_read": {
        "description": "【页面快照分片读取】获取当前页面的 aria 可访问性树正文，长快照自动分片：首读返回前 8,000 字符 + session_id/can_continue/next_offset。需要继续读取时带 session_id 续读直到 can_continue=false。与 browser_dom_snapshot 的区别：dom_snapshot 面向交互定位（拿 role+name），本工具面向完整阅读（分片拿全文）。页面导航/交互后旧 session 失效，需重新调用。【何时不用】快照未截断时不要调用（直接消费 browser_dom_snapshot 结果）；未打开页面前不要调用（先 browser_navigate）。",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "可选。续读会话 ID（首读返回的 session_id）"},
                "offset": {"type": "integer", "description": "可选。续读起始偏移（默认按上次位置顺序续读）"},
                "chunk_size": {"type": "integer", "description": "可选。单次返回的快照正文长度上限（默认 8000）"},
            },
            "required": [],
        },
    },
    "bilibili_search": {
        "description": "【B站搜索】搜索 B 站视频，返回标题与链接。用于查找中文视频教程、评测、讲解等内容。【何时不用】仅限 B 站内容；通用搜索/其他平台改用 web_search，拿到视频链接后要字幕内容用 youtube_transcript（仅限 YouTube）。",
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
        "description": "【RSS 阅读】读取 RSS/Atom 订阅源的最新条目（标题/链接/摘要）。用于追踪博客、播客、新闻源更新。【何时不用】需要条目全文时拿链接用 web_fetch 续读；源已失效或非 RSS 地址改用 web_search / web_fetch；搜索未知站点不要用本工具。",
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
        "description": "【V2EX 热门】获取 V2EX 社区当前热门帖子（标题/链接/回复数/作者）。用于了解开发者社区热议话题。【何时不用】仅限 V2EX 站点；查帖子全文拿链接用 web_fetch；通用技术搜索改用 web_search。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数（默认 10）"},
            },
            "required": [],
        },
    },
    "social_search": {
        "description": "【社交平台搜索】查询社交平台（twitter/reddit/xiaohongshu/facebook/instagram/linkedin）的搜索接入状态。已配置登录态后端时返回后端与命令信息；未配置时返回配置引导。不自动登录。【何时不用】仅限上述社交平台；通用搜索改用 web_search；本工具未配置接入时不要反复重试，按返回的配置引导提示用户。",
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
        "description": "【任务计划】创建和管理结构化任务计划，适合多步骤长任务：先 create 建立步骤清单，执行过程中用 mark_step 标记各步状态（completed/in_progress/blocked），让用户和后续轮次都能看到全局进度。计划持久化存储，重启后仍可 get 查询继续推进。对于需要多轮才能完成的任务，开工前先建计划。状态机纪律：同一时刻至多一个 in_progress 步骤；步骤完成立即标记，不要攒到最后批量勾选；探索/搜索/阅读类动作不要登记为步骤；计划需要大改时先说明理由再 update。",
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
        "description": "【内部语音记忆检索】仅搜索用户之前通过语音说过的内容（语音转写后的记录）。不能搜索互联网、不能查天气、不能获取外部信息。仅用于回忆用户语音对话历史。【何时不用】查打字/文字对话记忆改用 memory_search；查本会话被折叠内容用 recall_history；两者结果都不足时再回退本工具，不要每次都查三路。",
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
            # 三别名任一即合法——required 单指 location 与"二选一"矛盾（T2
            # 校验上线抓出的存量契约 bug，执行体 _execute_weather 本就三选一读参）
            "anyOf": [
                {"required": ["location"]},
                {"required": ["city"]},
                {"required": ["query"]},
            ],
        },
    },
    "web_search": {
        "description": "【实时网络搜索】通过搜索引擎查询互联网上的实时信息（新闻、股价、百科、技术文档等）。当用户需要 memory_search 无法提供的实时或外部信息时调用此工具。返回搜索结果摘要文本。工具选择阶梯（最轻优先）：不知道网址先用本工具搜索 → 拿到具体网址后用 web_fetch 读取 → 仅当页面需要交互/登录/动态渲染才升级 browser_* 工具，不要直接开浏览器做纯检索。【何时不用】已知确切 URL 直接 web_fetch；站点限定内容（B站/V2EX/RSS）用对应垂直工具；内部记忆问题用 memory_search。",
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
            # 同 weather：别名三选一，required 单指 query 与描述矛盾（T2 抓出）
            "anyOf": [
                {"required": ["query"]},
                {"required": ["q"]},
                {"required": ["keywords"]},
            ],
        },
    },
    "spawn_subagent": {
        "description": "【蜂群派生子Agent】将一个子任务派交给另一个 Agent 执行（蜂群编排）。当任务可分解为多个相对独立的子任务（如：多主题调研、多文件分析、多视角评审）时，对每个子任务各调用一次本工具即可并行蜂群执行。每个子 Agent 拥有独立的人设/记忆/模型配置。前台模式等待完成并返回最终报告；background=true 立即返回 subagent_id（用 subagent_status 查询结果）。子 Agent 的执行过程会实时显示在聊天界面的子 Agent 小窗中。可先用 list_agents 查看可用的子 Agent。配额纪律（系统强制，超限派生会被数据层直接拒绝）：任务要求 N 个子任务就只调 N 次；用户未指定数量时每层 1-3 个；禁止为同一子任务重复派生；禁止派生与当前任务无关的子 Agent；并发上限 5，超限先 subagent_status 等待回收再派生。【何时不用】固定步骤序列的自动化改用工作流/画布（canvas_run）；单步工具能完成的不要派生子 Agent。",
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
        "description": "【查询子Agent状态】查询蜂群派生的子 Agent 的执行状态与最终报告。配合 spawn_subagent(background=true) 或前台 spawn 转后台后的主动轮询使用。subagent_id 省略时返回最近派生的子 Agent 列表（新→旧，report 截断）。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {
                    "type": "string",
                    "description": "spawn_subagent 返回的 subagent_id；省略时返回最近派生列表",
                },
            },
            "required": [],
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
    "git": {
        "description": "【Git 仓库操作】在指定仓库执行 git 命令。command 为完整命令行（含 git 前缀），如 'git status --short'；仓库目录由 path 锚定（相对锚定工作区，默认工作区根，禁止 --git-dir/-C/--work-tree 等逃逸选项）。读操作（status/diff/log/show/blame/ls-files）直接执行；写操作（add/commit/push/checkout/reset…）触发人工确认。【何时不用】GitHub PR/issue/CI 等远程托管操作用 github MCP 工具；不要用本工具跑 shell 通用命令（用 run_code/computer_shell）；不要用 curl 代替 git fetch。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "完整 git 命令行，必须以 git 开头（如 git log --oneline -10）"},
                "path": {"type": "string", "description": "仓库目录（相对锚定 agent 工作区；缺省为工作区根）", "default": "."},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 60},
            },
            "required": ["command"],
        },
    },
    "deep_research": {
        "description": "【深度研究采集】对主题做多源检索+正文摘录，返回带 [n] 编号引用的源料包（title/url/excerpt），你在其基础上综合撰写带引用的研究报告。比逐条 web_search+web_fetch 省往返，适合'调研X现状/对比A与B'类任务。【何时不用】单条已知链接用 web_fetch；简单事实查 web_search；本工具只采集源料，不做结论（结论由你写）。可传 sub_queries 给出多个检索角度（拆解子问题）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "研究主题"},
                "sub_queries": {"type": "array", "items": {"type": "string"}, "description": "可选：拆解的检索角度/子问题（不传则仅用 query）"},
                "max_sources": {"type": "integer", "description": "去重后最多抓取正文的源数（默认 6，上限 15）", "default": 6},
            },
            "required": ["query"],
        },
    },
    "web_fetch": {
        "description": "【网页抓取】抓取指定 URL 的内容并转为纯文本（阅读文章、文档、API 响应等）。已知网址要读取其内容时用此工具；不知道网址先用 web_search 搜索。仅支持 http/https 协议。若本工具返回空或内容不完整（JS 动态页），再升级 browser_* 工具处理，不要跳过本工具直接用浏览器。【何时不用】未拿到具体 URL 时先用 web_search；JS 渲染/需登录页改用 browser_read；本地文件用 file_read。",
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
        "description": "【代码执行】运行一段 Python 或 shell 代码，返回 stdout/stderr/退出码。用于数据处理、算法计算、文本批量处理、验证代码逻辑等。代码在本地运行时执行，受治理策略约束。【何时不用】系统操作类命令（进程/服务/环境变量）改用 computer_shell；纯数值计算禁止心算，一律用本工具跑 Python。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码字符串"},
                "language": {"type": "string", "description": "代码语言：python（默认）或 shell"},
                "timeout": {"type": "integer", "description": "执行超时秒数（默认 60）"},
                "runtime_type": {"type": "string", "description": "运行时类型：local（默认）或 docker", "enum": ["local", "docker"], "default": "local"},
                "cwd": {"type": "string", "description": "工作目录（可选，默认执行器当前目录）"},
                "env": {"type": "object", "description": "附加环境变量字典（可选，如 {\"KEY\": \"value\"}）"},
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
        "description": "【运行画布】把画布编译为工作流并同步执行，返回整体状态与每个节点的执行结果（状态/输出/错误/耗时）。搭完工作流后用它验证流程是否跑通。【何时不用】把已保存的工作流交给子 Agent 长期执行改用 spawn_subagent；一次性简单任务不要包装成画布，直接用对应工具。",
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


# ═══════════════════════════════════════════════════════════════
# 工具声明位（P2-15，OpenClaw 对比 #15）
#
# schema 可携带与 description/parameters 平级的 sandbox_required 布尔键，
# 语义 = "该工具必须在沙箱隔离下执行"（OpenClaw exec 审批的声明面）。
# 声明位不进入 to_openai_format()（模型可见面零变化），仅供治理与
# 展示面消费；NEUROVA_TOOL_SANDBOX_ENFORCE=1 时治理层强制路由。
# ═══════════════════════════════════════════════════════════════

_SANDBOX_REQUIRED_KEY = "sandbox_required"

# B3（v0 启发）：执行摘要参数——模型自述"进行中/完成态"的 2-6 字动作短语，
# 经 SSE 透传给步骤化时间轴作段标题。单一注入点（to_openai_format），54 个
# 内置工具自动获得；执行层在分发前剥离（不污染真实参数）。
_TASK_NAME_PARAM_DEFS: Dict[str, Any] = {
    "taskNameActive": {
        "type": "string",
        "description": "可选。当前操作的 2-6 字动词短语（如\"读取配置文件\"），用于界面时间轴显示。",
    },
    "taskNameComplete": {
        "type": "string",
        "description": "可选。完成态的 2-6 字短语（如\"已读取配置\"），不带成败语义（成败由结果呈现）。",
    },
}


def get_task_name_param_defs() -> Dict[str, Any]:
    """taskName* 参数定义（单一事实源；BuiltinTool.to_openai_format 注入）。"""
    return _TASK_NAME_PARAM_DEFS


def get_builtin_tool_sandbox_declaration(tool_name: str) -> Optional[bool]:
    """读取工具的 sandbox_required 声明。

    Returns:
        True: 工具声明必须在沙箱下执行
        None: 未声明或声明值非法（缺省=旧行为，调用方不得据此裁决）
    """
    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return None
    value = schema.get(_SANDBOX_REQUIRED_KEY)
    return True if value is True else None


def list_sandbox_required_tools() -> List[str]:
    """枚举声明了 sandbox_required 的内置工具名（治理/展示批量消费）。"""
    return [
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and schema.get(_SANDBOX_REQUIRED_KEY) is True
    ]


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
    # P2-15 声明位：True=声明必须在沙箱下执行；None=未声明。
    # 不进入 to_openai_format()，模型可见面零变化。
    sandbox_required: Optional[bool] = None

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式。

        B3：统一注入 taskNameActive/taskNameComplete 可选参数（执行摘要，
        直连时间轴 UI）；MCP/Skill 外来 schema 不经此处，自然不受影响。
        """
        params = self.parameters
        try:
            if isinstance(params, dict) and params.get("type") == "object":
                props = params.setdefault("properties", {})
                for _pn, _pdef in _TASK_NAME_PARAM_DEFS.items():
                    props.setdefault(_pn, dict(_pdef))
        except Exception:  # noqa: BLE001 - 注入失败不阻断工具暴露
            pass
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
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
                sandbox_required=get_builtin_tool_sandbox_declaration(tool_name),
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
