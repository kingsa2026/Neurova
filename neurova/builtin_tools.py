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
# 有界口径的**单源**：`query_database` 的 row_limit 默认值与上界取自
# `attachment_dataset`（与工具执行体同一份常量），schema 文案不另写一份。
# ═══════════════════════════════════════════════════════════════
from neurova.attachment_dataset import (
    MAX_ROWS_DEFAULT as MAX_DATASET_ROWS_DEFAULT,
    MAX_ROWS_LIMIT as MAX_DATASET_ROWS_LIMIT,
)


# ═══════════════════════════════════════════════════════════════
# 内置工具参数 Schema（单一事实源）
# ═══════════════════════════════════════════════════════════════

_BUILTIN_SCHEMAS: Dict[str, Dict] = {
    "recall_history": {
        # 并行能力声明：本地会话折叠台账的只读召回（执行体只读存储，无写作用域）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【历史召回】取回被移出上下文窗口的原文。①见『[工具输出已移出上下文…call=<id>]』占位时传 tool_call_id 直取该次结果全文；②子 Agent 会话整取须同时传 agent_id 与 session_id；③用户提“之前说的”用 query 模糊匹配折叠台账。【何时不用】跨会话记忆用 memory_search；语音用 voice_memory_search；上下文还找得到的不召回。",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_call_id": {"type": "string", "description": "直取模式：占位指针里的 call= 值（如 tc-123），与 session_id 联用精确取回该次工具结果全文"},
                "session_id": {"type": "string", "description": "目标会话 id：直取模式可选（缺省用当前会话）；整取模式（带 agent_id）必填"},
                "agent_id": {"type": "string", "description": "整取模式必填：目标会话的属主 agent_id（取终态信封 transcript.agent_id 的值）。给了它就按 (agent_id, session_id) 整取该会话原文；不给时既有语义不变（按当前 Agent 的属主读台账）"},
                "query": {"type": "string", "description": "召回关键词（在折叠台账中匹配，留空返回最近折叠的内容）"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 10},
            },
        },
    },
    "recall_context_span": {
        # 并行能力声明：按折叠索引只读取回原文，无写作用域。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【分层摘要下钻】按『[早期对话摘要]』尾部 covers_ref=fold:<层序>@<会话> 引用，确定性取回该档摘要覆盖的全部原文（不受相关性门槛影响）。【何时不用】无 covers_ref 的旧摘要不调用；按词搜索用 recall_history；跨会话用 memory_search。",
        "parameters": {
            "type": "object",
            "properties": {
                "covers_ref": {"type": "string", "description": "摘要行尾部的引用串（如 covers_ref=fold:2@sess-A）；可直接整行粘贴，本工具自行解析"},
                "limit": {"type": "integer", "description": "返回原文条数上限", "default": 200},
            },
            "required": ["covers_ref"],
        },
    },
    "recall_query": {
        # QwenPaw 对照批 B3：受限 Python 表达式查询（只读、白名单 AST 校验）。
        # 并行能力声明：只读召回条目的纯计算，无写作用域，保守不并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("none",)},
        "description": "【受限 Python 查询】对当前会话的召回条目做组合/统计/过滤等纯计算。可用变量：items（召回条目列表，每条含 content/turn_id/recalled_from）。仅支持单个表达式；禁止 import、赋值、下划线属性、I/O。【何时用】recall_history 的模糊匹配不够、需要对召回内容做再加工时。【何时不用】精确指针直取 recall_history；语义检索 memory_search。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "单个 Python 表达式，如 [i['content'][:30] for i in items if '报错' in i['content']]"},
                "query": {"type": "string", "description": "预取召回条目的关键词（同 recall_history 的 query）"},
                "limit": {"type": "integer", "description": "预取召回条数上限", "default": 200},
            },
            "required": ["expression"],
        },
    },
    "context_compress": {
        # B1（对照改进项）：模型自决触发折叠。折叠只影响视图，原文在归档池
        # （零丢失），与 /compact 命令同一折叠机构。
        # 并行能力声明：改写当前会话视图（折叠落代际），触碰共享会话态，不可并行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【上下文主动折叠】把窗口里较老的消息折叠成摘要（原文仍在归档池，可经 recall_history 找回）。折叠成功的回执附 recall_guide：covers_ref 引用与三条找回路径（recall_history / pool_search / recall_context_span）。【何时用】任务步骤完成、早期内容短期不再需要时。【何时不用】调试/推理中途；只查历史用 recall_history。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "折叠原因（进读数，便于归因），如“阶段完成”“切换话题前清理”"},
            },
        },
    },
    "context_status": {
        # B1（对照改进项）：上下文盘点（只读）。
        # SC-3：回执附折叠时机判读块（判定单源复用 decideFoldTrigger + 元认知读数），
        # 只走模型主动查询面，不进上下文信封恒定注入。
        # 并行能力声明：只读健康/预算读数，但走同步 SQLite/内存读，保守不并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("none",)},
        "description": "【上下文盘点】返回窗口 token 估算/预算、折叠代际与最近触发原因、池归档规模、取水读数，并附折叠时机判读 fold_timing：增长门四判据读数与当前该不该折叠的判定、元认知状态（未编译事件/距上次反思/活跃教训）。【何时用】决定是否 context_compress 前。",
        "parameters": {"type": "object", "properties": {}},
    },
    "pool_search": {
        # B9（对照改进项）：归档池语义检索（与视图抽屉同一打分面）。
        # 并行能力声明：只读池+FTS 同步读，保守不并行（与 recall_history 同判）。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("none",)},
        "description": "【归档语义检索】对归档池做向量语义检索（含被折叠原文），按相关性排序。【何时用】按语义找历史原文。【何时不用】精确指针直取 recall_history；分层下钻 recall_context_span；跨会话记忆 memory_search。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索需求（自然语言，同义表达即可命中）"},
                "limit": {"type": "integer", "description": "返回条数上限", "default": 8},
            },
            "required": ["query"],
        },
    },
    "memory_search": {
        # 并行能力声明：长期记忆库只读检索，无写作用域。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【内部记忆检索】仅搜本 Agent 自身的历史对话与记忆条目；不能搜互联网/天气/新闻等外部实时信息。【何时不用】外部信息 web_search；本会话折叠对话 recall_history；语音内容 voice_memory_search。",
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
    "graph_search": {
        # 并行能力声明：知识图谱只读走查（递归 CTE 只读，无写作用域）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【知识图谱检索】查本 Agent 知识图谱的结构化关系。walk：从主体多跳走查（A 与 B 什么关系）；global：社区摘要匹配；drift：实体邻域＋社区图景。记忆原文用 memory_search；网页用 web_search；术语/本体走 ontology 管理面。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本（walk 提取主体锚点；global 匹配社区摘要；drift 为实体标签）"},
                "mode": {"type": "string", "enum": ["walk", "global", "drift"], "description": "检索模式", "default": "walk"},
                "max_hops": {"type": "integer", "description": "walk 模式最大跳数（2-4，默认 2，超出钳位）", "default": 2},
                "limit": {"type": "integer", "description": "返回数量上限（默认 8，上界 50）", "default": 8},
            },
            "required": ["query"],
        },
    },
    "file_read": {
        # 并行能力声明：本地文件只读（执行体 to_thread 打开只读句柄），无写作用域。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【文件读取】读取指定路径文件的内容。已知确切路径时用本工具；还不知道路径先用 file_list 枚举、按内容找用 file_search。【何时不用】大文件建议带 offset 分段读；网页内容不要用本工具（用 web_fetch）。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "description": "起始行号"},
                "encoding": {"type": "string", "description": "文件编码", "default": "utf-8"},
            },
            "required": ["file_path"],
        },
    },
    "file_parse": {
        # 并行能力声明：本地文件解析只读；大文件解析落线程池，不持有共享态。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【文档解析】把 PDF/Word/Excel/PPT/RTF/ODF 等二进制文档抽取为纯文本。【何时不用】纯文本/代码/markdown/json 用 file_read；网页用 web_fetch；图片/音频/视频走 vision/asr。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文档路径（相对锚定工作区，绝对路径按原语义）"},
                "max_chars": {"type": "integer", "description": "返回文本上限（默认 50000，超出截断并标 truncated）", "default": 50000},
            },
            "required": ["file_path"],
        },
    },
    "query_database": {
        # 并行能力声明：语义只读但作用域为共享（执行体经 attachment_dataset.materializeReadOnlyCopy
        # 把只读副本写进共享查询缓存根）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": (
            "【数据集查询】按附件句柄只读查询用户上传的 SQLite 数据集（.db/.sqlite）："
            "缺省列全部表、每表列定义、行数与样例行；给了 sql 则执行该只读查询。"
            "当附件抽取通道报「未能抽取文本内容」而扩展名是 .db/.sqlite 时用本工具——"
            "那是原始二进制容器，只有它读得出。"
            "【何时不用】纯文本/代码用 file_read；PDF/Office 文档用 file_parse；"
            "平台自有库（users.db 等）与任意路径都不在本工具范围内，它只认附件句柄。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "【数据集查询】按附件句柄只读查询用户上传的 SQLite 数据集：缺省列表结构/行数/样例，给 sql 执行只读查询。附件通道报「未能抽取文本」的 .db/.sqlite 用它。文本/代码用 file_read；PDF/Office 用 file_parse；不认平台自有库与任意路径。",
                },
                "sql": {
                    "type": "string",
                    "description": "只读 SQL（可选，缺省=列 schema 与样例）。只允许 SELECT / WITH … SELECT / 只读 PRAGMA；写型语句、ATTACH、多语句一律拒绝。",
                },
                "row_limit": {
                    "type": "integer",
                    "description": f"最多返回行数（可选，默认 {MAX_DATASET_ROWS_DEFAULT}，上界 {MAX_DATASET_ROWS_LIMIT}；超限截断并在结果里标 truncated）",
                },
            },
            "required": ["file_id"],
        },
    },
    "file_write": {
        # 并行能力声明：整体覆盖写工作区文件——工作区是共享态，两个并发写同一路径会互相覆盖。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【文件写入】写入（整体覆盖）指定路径文件的内容。【何时不用】对已有文件做局部修改改用 file_edit（查找替换，避免整文件重写）；创建全新文件用 file_create。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入内容"},
                "encoding": {"type": "string", "description": "文件编码", "default": "utf-8"},
            },
            "required": ["file_path", "content"],
        },
    },
    "file_create": {
        # 并行能力声明：新建工作区文件——工作区是共享态，与同批任何写操作并发都会互相覆盖。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "创建新文件",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "初始内容"},
            },
            "required": ["file_path"],
        },
    },
    "file_delete": {
        # 并行能力声明：删除工作区文件——工作区是共享态，并发下"先判存在再删"是 TOCTOU，与写操作互踩。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "删除文件",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文件路径"},
            },
            "required": ["file_path"],
        },
    },
    "file_edit": {
        # 并行能力声明：读-改-写序列改工作区文件——工作区是共享态，两路并发改同一文件必丢更新。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【文件编辑】查找替换方式修改已有文件：old_str 必须与文件内容逐字符一致且在文件中唯一（含足够上下文行），不唯一则不执行替换。对已有文件的局部修改一律用本工具。【何时不用】整体重写文件用 file_write；新建文件用 file_create。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"format": "path", "type": "string", "description": "文件路径"},
                "old_str": {"type": "string", "description": "待替换文本（须逐字符一致且唯一，建议带前后各几行上下文）"},
                "new_str": {"type": "string", "description": "替换后文本"},
            },
            "required": ["file_path", "old_str", "new_str"],
        },
    },
    "computer_screenshot": {
        # 并行能力声明：只读但作用域为共享（整屏/窗口截图，读的是共享桌面的瞬时画面）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "截取屏幕截图。结果回带 screen 元数据（宽高/DPI scale/虚拟屏原点）与引导信息；UI 元素事实（按钮/输入框/菜单）不要靠反复截图观察，用 computer_dom_snapshot 获取。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "computer_click": {
        # 执行语义声明：改变共享桌面的画面（鼠标落点）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面——鼠标与焦点是全局单例，并发点击会互相打断。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "点击屏幕指定位置",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X 坐标"},
                "y": {"type": "number", "description": "Y 坐标"},
                "button": {"type": "string", "description": "鼠标按钮", "default": "left"},
                "frame_id": {"type": "string", "description": "可选。最近一次 computer_screenshot/computer_som_snapshot 返回的帧 id；携带时校验帧新鲜度，画面已变则拒绝（stale_frame）并要求重新观察"},
            },
            "required": ["x", "y"],
        },
    },
    "computer_type": {
        # 执行语义声明：改变共享桌面的画面（键盘输入）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面——键盘焦点是全局单例，并发输入会串到对方的窗口。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 执行语义声明：改变共享桌面的画面（视口滚动）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面——滚动作用于当前指针位置的全局滚动目标。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：只读但作用域为共享（UIA 树快照，读的是共享桌面的瞬时结构）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【桌面可访问性快照】枚举前台（或指定标题）窗口控件树（index/角色/名称/矩形/可交互/层级）。桌面交互前必先调用，按快照 index 用 computer_click_element/computer_set_value 语义操作，勿盲猜坐标；窗口变化后 generation 递增需重快照。truncated=true 表示节点数或深度任一不完整；出现 depth_truncated 时树被深度剪枝（observed_max_depth=实际走到的深度，被切元素带 subtree_truncated 标记）——勿把残树当全貌，可对 subtree_truncated 元素用 root_index/root_runtime_id 下钻其子树（新元素 index 续接进缓存），或提高 max_depth/max_nodes 重新观察。skeleton=true 为骨架概览：折叠无名且不可交互的容器（omitted_count 计数），适合密集树先看骨架再下钻。",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {"type": "string", "description": "可选。目标窗口标题（包含匹配，不区分大小写）；缺省为当前前台窗口"},
                "max_nodes": {"type": "integer", "description": "可选。最多枚举的控件节点数（默认 400）", "minimum": 1},
                "max_depth": {"type": "integer", "description": "可选。控件树最大深度（默认 32）", "minimum": 1},
                "root_index": {"type": "integer", "description": "可选。下钻根元素序号（drill-down，必须来自本窗口已有快照）；提供后只枚举该元素子树，新元素 index 续接进缓存。root 不在已有快照中会被拒绝（ref_not_found）", "minimum": 0},
                "root_runtime_id": {"type": "string", "description": "可选。下钻根元素 runtime_id（优先于 root_index）"},
                "skeleton": {"type": "boolean", "description": "可选。骨架概览模式：折叠无名且不可交互的容器/文本（返回 omitted_count），保留结构根/有名/可交互元素；配合 root_index 下钻使用"},
            },
            "required": [],
        },
    },
    "computer_click_element": {
        # 执行语义声明：改变共享桌面的画面（语义点击）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面（五级递降链的语义点击）——桌面聚焦与快照代次是全局单例。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 执行语义声明：改变共享桌面的画面（控件赋值）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面（UIA ValuePattern 直写控件）——目标控件与快照代次是全局单例。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：只读但作用域为共享（SOM 标注快照，读的是共享桌面的瞬时画面）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【SOM 视觉快照】对无 UIA 树的目标（自绘 UI/游戏/像素流）把截图标注成编号可交互区域图（marks：id/中心/label），用 computer_click_mark 点击。【何时不用】有 UIA 树先 computer_dom_snapshot。",
        "parameters": {
            "type": "object",
            "properties": {
            },
            "required": [],
        },
    },
    "computer_click_mark": {
        # 执行语义声明：改变共享桌面的画面（SOM 编号点击）⇒ 动作后补拍有意义。
        # 补登：它一直就在刷新链上（执行体调 _emit_action_refreshed_screenshot），
        # 而旧的刷新名单没跟着扩——漏登正是本声明位要根修的那条漂移。
        "interactive_desktop": True,
        # 并行能力声明：操作共享宿主桌面，且读本实例最近一次 SOM 快照的编号表——两处都是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【按 SOM 编号点击】点击 computer_som_snapshot 返回的某个编号区域中心（内部经 id2xy 解算像素坐标并走 DPI/多屏换算的点击链）。编号来自最近一次 SOM 快照，过期需重新快照。",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "SOM 编号（来自 computer_som_snapshot 的 marks.id）"},
                "button": {"type": "string", "description": "鼠标按钮 left/right/middle", "default": "left"},
                "frame_id": {"type": "string", "description": "可选。最近一次 computer_som_snapshot 返回的帧 id；携带时校验帧新鲜度，画面已变则拒绝（stale_frame）并要求重新快照"},
            },
            "required": ["index"],
        },
    },
    "computer_list_windows": {
        # 并行能力声明：只读（窗口清单枚举，读共享桌面的瞬时状态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【窗口清单】枚举桌面顶层窗口（标题/类名/PID/矩形/是否前台）。用于定位目标窗口（配合 computer_dom_snapshot 的 window_title 参数）或确认某应用是否在跑。只读动作，无副作用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "computer_key": {
        # 执行语义声明：改变共享桌面的画面（全局键盘）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：键盘焦点是全局单例，并发按键会串到对方的窗口。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【按键】向桌面发送按键或组合键（如 enter、ctrl+s、alt+f4），repeat 可重复。用于快捷键/确认框/切窗口；别名自动归一（cmd→win、esc→escape 等），键表外键名会被拒绝。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名或 + 组合键，如 enter / ctrl+s / alt+f4"},
                "repeat": {"type": "integer", "description": "重复次数（默认 1）", "minimum": 1},
                "interval": {"type": "number", "description": "重复间隔秒（默认 0.05）"},
            },
            "required": ["key"],
        },
    },
    "computer_paste": {
        # 执行语义声明：改变共享桌面的画面（键盘输入）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：写系统剪贴板+派发 ctrl+v——剪贴板与键盘焦点都是全局单例。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【粘贴】把文本写入系统剪贴板并派发 ctrl+v 到当前焦点控件（比逐字符键入快，适合长文本/特殊字符）。目标控件需已聚焦（可先 computer_click/computer_click_element 聚焦）；粘贴后剪贴板内容即为本文本。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要粘贴的文本"},
            },
            "required": ["text"],
        },
    },
    "computer_drag": {
        # 执行语义声明：改变共享桌面的画面（鼠标拖拽）⇒ 动作后补拍有意义。
        "interactive_desktop": True,
        # 并行能力声明：鼠标是全局单例，并发拖拽会互相打断。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【拖拽】按截图像素坐标把鼠标从起点拖到终点（默认左键拖拽，时长可调）。坐标口径同 computer_click（截图像素坐标，DPI/多屏换算已内置）。适合滑块/拖放排序/画布类交互。",
        "parameters": {
            "type": "object",
            "properties": {
                "start_x": {"type": "number", "description": "起点 X（截图像素坐标）"},
                "start_y": {"type": "number", "description": "起点 Y（截图像素坐标）"},
                "end_x": {"type": "number", "description": "终点 X（截图像素坐标）"},
                "end_y": {"type": "number", "description": "终点 Y（截图像素坐标）"},
                "duration": {"type": "number", "description": "拖拽时长秒（默认 0.5，过快可能丢事件）"},
                "button": {"type": "string", "description": "鼠标按钮 left/right/middle", "default": "left"},
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    },
    "computer_ssh_exec": {
        # 壳方言声明：command 文本交给真 shell 执行（|/;/&& 是命令连接符），
        # 故它必须走分段审批面（成员资格收口到本声明，见 governance.listSegmentedShellTools）。
        "shell_dialect": True,
        # 执行语义声明：把 command 文本当命令在远端机器上执行——
        # 高危档（任意命令）与远端档的成员资格均由本处声明推导，
        # 桌面档不另持手写名单（见 computer_use/runtime_policy.py）。
        "arbitrary_command": True,
        "remote_execution": True,
        # 并行能力声明：在远端机器执行命令——共享远端会话与凭据分桶，输出经同一终端面板渲染。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【SSH 远程命令】经 SSH 在远程 Linux/macOS 执行命令，返回 stdout/stderr/退出码，操作在终端窗口展示。host 必填，凭据从 SSH 配置读取（platform=ssh）。【何时不用】本机 computer_shell；数据处理 run_code。",
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
        # 壳方言声明：command 文本交给真 shell 执行（|/;/&& 是命令连接符），
        # 故它必须走分段审批面（成员资格收口到本声明，见 governance.listSegmentedShellTools）。
        "shell_dialect": True,
        # 执行语义声明：把 command 文本当命令在**本机**执行——有任意命令语义，
        # 但动作落本机（非远端），故只声明前者。
        "arbitrary_command": True,
        # 并行能力声明：在用户计算机上执行 shell 命令——共享宿主机状态与终端面板。
        # 超时处置 KILL：同 exec_command，放弃即须终止那个 shell 进程。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",),
                       "timeoutDisposition": "kill"},
        "description": "【Shell 命令】在用户计算机执行 shell 命令（Windows 经 cmd.exe /c）：进程/服务、环境变量、批量文件整理、装依赖。cmd 不认单引号，含空格/特殊字符的路径参数必须双引号；【何时不用】数据处理/计算用 run_code（数值禁止心算），抓网页用 web_fetch。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "shell 命令（Windows 下为 cmd.exe 语法，字符串参数用双引号包裹）"},
            },
            "required": ["command"],
        },
    },
    # ── 浏览器操作工具──
    # 执行过程的页面截图会实时推送到聊天页的电脑操作分屏面板
    "browser_navigate": {
        # 并行能力声明：驱动同一个内置浏览器实例——页面是共享态，并发导航会互相顶掉对方的页。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【浏览器导航】在内置自动化浏览器打开 URL——工具阶梯最重档，仅当 web_search/web_fetch 搞不定（交互/登录/JS 渲染）才用。打开后可 extract_text/click/type/screenshot。【何时不用】静态页直接 web_fetch；站内搜索用 web_search 等垂直工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要访问的完整 URL（含 https://）"},
            },
            "required": ["url"],
        },
    },
    "browser_click": {
        # 并行能力声明：驱动同一个内置浏览器实例——并发点击会互相打断对方的页面动作。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：驱动同一个内置浏览器实例——并发输入会串到对方的焦点元素。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：语义只读但作用域为共享（取同一浏览器实例的瞬时画面）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【浏览器截图】截取当前浏览器页面的画面。截图会实时显示在聊天页的电脑操作面板中，并返回页面标题和 URL。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "browser_extract_text": {
        # 并行能力声明：语义只读但作用域为共享（读同一浏览器实例的当前页正文，并发会拿到对方翻页后的中间态）
        # ⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【浏览器提取文本】提取当前页面正文文字（阅读/总结/搜索结果）。先 browser_navigate 打开页面。【何时不用】长文分片用 browser_dom_read；静态页直接 web_fetch。",
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
        # 并行能力声明：语义只读但作用域为共享（aria 快照读同一浏览器实例的当前页与代次游标）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【页面可访问性快照】取当前页面 aria 树（角色/名称）。交互前必先调用，从快照拿 role/name 再 click_role/fill_role 定位，勿盲猜选择器。超上限时跨全树等距折叠并如实上报 folded 计数；要完整正文用 browser_dom_read。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。持有的页面代数；页面已变化时返回过期错误提示重新快照"},
                "max_nodes": {"type": "integer", "description": "可选。最多保留的快照节点数；**不传则不裁剪**（无默认值）", "minimum": 1},
                "max_depth": {"type": "integer", "description": "可选。快照树最大深度；**不传则不限深度**（无默认值）", "minimum": 1},
            },
            "required": [],
        },
    },
    "browser_click_role": {
        # 并行能力声明：驱动同一个内置浏览器实例（按 ARIA 角色定位）——页面与代次是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：驱动同一个内置浏览器实例（按 ARIA 角色写入）——页面与代次是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
    # ── ref 一等寻址（T-08）：同名元素的唯一出路 ──
    # 为什么必须有它：`get_by_role` 遇重名是 strict mode 硬失败，而真页的重名率实测 56%
    # （MDN 一页 618 条可交互行去重后 429）。没有 ref，`smart-click` 的 409 只能把候选
    # 列出来却动不了；有了它，模型可以照着候选里的 `[eN]` 直接点第 k 个。
    # D-2：参数面只有 ref/generation（fill 另有 text），不提供 selector/xpath——不给模型
    # 留一条绕开快照事实去猜选择器的路。
    "browser_click_ref": {
        # 并行能力声明：驱动同一个内置浏览器实例（按快照编号定位）——编号表、页面与代次是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【按快照编号点击】点击快照正文标 `[eN]` 的元素（role+name 无法唯一化、smart-click 回 409 列候选时用）。编号仅本次快照内有效，页面一变即失效；自证不符时拒绝发动作。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "快照行尾的编号（形如 e3，必须来自最近一次 browser_dom_snapshot）"},
                "generation": {"type": "integer", "description": "可选。该快照返回的 generation；跨代即拒绝并提示重新快照"},
            },
            "required": ["ref"],
        },
    },
    "browser_fill_ref": {
        # 并行能力声明：驱动同一个内置浏览器实例（按快照编号写入）——编号表、页面与代次是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【按快照编号输入】在 browser_dom_snapshot 正文里标了 `[eN]` 的输入元素中填写文本。失效、自证与拒绝语义同 browser_click_ref；text 传空串表示清空。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "快照行尾的编号（形如 e5，须指向 textbox/searchbox 一类可输入元素）"},
                "text": {"type": "string", "description": "要填写的文本（空串=清空）"},
                "generation": {"type": "integer", "description": "可选。该快照返回的 generation；跨代即拒绝并提示重新快照"},
            },
            "required": ["ref", "text"],
        },
    },
    # ── 多标签页管理（底层 PlaywrightBackend.open/list/switch/close_target 的工具面）──
    # 每个 tab 持独立 generation 游标；切回旧 tab 后，旧 tab 的快照事实仍按它自己的代次校验。
    "browser_tab_open": {
        # 并行能力声明：驱动同一个内置浏览器实例（新开 tab 并激活）——tab 表与活动指针是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【新开标签页】新开并激活一个浏览器标签页，可顺带导航。用于需同时保持多页面的任务；每标签页独立 generation，交互前仍需 dom_snapshot。【何时不用】单页任务直接 browser_navigate；静态读取 web_fetch。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "可选。新标签页要打开的 URL；省略则打开空白页"},
            },
            "required": [],
        },
    },
    "browser_tab_list": {
        # 并行能力声明：读共享浏览器实例的 tab 表（瞬时态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【列出标签页】列出当前浏览器的全部标签页（target_id、URL、是否活动、generation）。需要切换或关闭某个标签页时，先用本工具拿 target_id，再调 browser_tab_switch / browser_tab_close。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "browser_tab_switch": {
        # 并行能力声明：改共享浏览器实例的活动 tab 指针。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【切换标签页】把指定 target_id 的标签页设为活动页，此后 browser_* 交互都作用于它；可带 generation 校验。切换后需重新 browser_dom_snapshot。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "目标标签页 ID（来自 browser_tab_list）"},
                "generation": {"type": "integer", "description": "可选。该标签页的代数；与当前不符时拒绝切换"},
            },
            "required": ["target_id"],
        },
    },
    "browser_tab_close": {
        # 并行能力声明：改共享浏览器实例的 tab 表与活动指针。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【关闭标签页】关闭指定 target_id 的标签页。关闭活动页时自动回落到剩余的第一个标签页；全部关闭后需重新 browser_navigate 或 browser_tab_open。可携带 generation 做新旧校验。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "要关闭的标签页 ID（来自 browser_tab_list）"},
                "generation": {"type": "integer", "description": "可选。该标签页的代数；与当前不符时拒绝关闭"},
            },
            "required": ["target_id"],
        },
    },
    # ── 页面脚本逃逸舱（快照协议覆盖不到的读取/轻操作）──
    "browser_eval": {
        # 并行能力声明：在共享浏览器实例的当前页执行任意 JS——页面态是共享的。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        # 任意命令执行语义（与 computer_shell 同档）：脚本文本由调用方给，页面里执行。
        "arbitrary_command": True,
        "description": "【执行页面脚本】在当前页面执行 JavaScript 并返回 JSON 可序列化结果，用于快照协议覆盖不到的读取（localStorage/页面变量）。【何时不用】优先 dom_snapshot＋role/ref 定位；抓正文用 browser_read/web_fetch。脚本出错如实返回。",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "要执行的 JavaScript 表达式或函数体（在页面上下文中 evaluate）"},
            },
            "required": ["script"],
        },
    },
    # ── 页面级动作（P2 批A）：导航补全/等待/滚动/按键 ──
    # 底层走 PlaywrightBackend.go_back/go_forward/reload_page/wait_for/scroll_by/press_key；
    # 导航类动作使活动页快照事实失效（generation 递增），交互前须重新 dom_snapshot。
    "browser_back": {
        # 并行能力声明：驱动同一个内置浏览器实例的会话历史——历史游标是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【浏览器后退】回退到本次会话的上一个页面（等价浏览器后退键）。导航使当前页快照事实失效（generation 递增），后续交互前需重新 browser_dom_snapshot。已在会话第一个页面时诚实报错「无后退历史」。【何时不用】刚 browser_navigate 打开的第一个页面没有可退历史。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": [],
        },
    },
    "browser_forward": {
        # 并行能力声明：驱动同一个内置浏览器实例的会话历史——历史游标是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【浏览器前进】前进到本次会话退回前的下一个页面（等价浏览器前进键）。失效语义同 browser_back；已在最新页面时诚实报错「无前进历史」。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": [],
        },
    },
    "browser_reload": {
        # 并行能力声明：驱动同一个内置浏览器实例的当前页——页面与代次是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【刷新页面】重新加载当前活动页（等价浏览器刷新键）。页面内未保存的表单输入会丢失；导航使快照事实失效（generation 递增），交互前需重新 browser_dom_snapshot。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": [],
        },
    },
    "browser_wait": {
        # 并行能力声明：只读等待但作用域为共享（等待期间共享页面的时序在推进）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【等待条件】等待页面达到指定条件再继续，三种条件可组合、至少给一个：固定毫秒（≤30000）、等待某 CSS 选择器的元素出现、等待加载状态（load/domcontentloaded/networkidle）。用于 SPA 异步渲染后的时序对齐——先等元素出现再 browser_dom_snapshot，不要靠盲等硬凑。",
        "parameters": {
            "type": "object",
            "properties": {
                "ms": {"type": "integer", "description": "固定等待毫秒数（上限 30000，超出按 30000 计）", "minimum": 1, "maximum": 30000},
                "selector": {"type": "string", "description": "等待该 CSS 选择器匹配的元素出现"},
                "state": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "description": "等待页面加载状态"},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝等待"},
            },
            "required": [],
        },
    },
    "browser_scroll": {
        # 并行能力声明：改共享浏览器实例当前页的视口滚动位置。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【滚动页面】按像素相对滚动当前页（正=右/下，负=左/上），返回滚动后的绝对位置。用于触发懒加载、查看长页下方内容。滚动不改变 aria 快照的可交互结构，但两个滚动量全为 0 时拒绝。【何时不用】要读页面正文用 browser_extract_text/browser_read。",
        "parameters": {
            "type": "object",
            "properties": {
                "scroll_x": {"type": "integer", "description": "横向滚动像素（正=右，负=左）"},
                "scroll_y": {"type": "integer", "description": "纵向滚动像素（正=下，负=上）"},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝滚动"},
            },
            "required": [],
        },
    },
    "browser_press": {
        # 并行能力声明：向共享浏览器实例的当前页派发键盘事件。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【键盘按键】向当前页面派发单个按键（Enter/Escape/Tab/ArrowDown/a 等，组合键用 + 连接如 Control+a）。用于提交表单、关闭弹层、键盘导航。按键可能触发页面行为，快照事实随之失效（generation 递增）。【何时不用】向输入框填文本用 browser_fill_role/fill_ref（更精确）；按键后要继续交互先重新 browser_dom_snapshot。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "键名（如 Enter/Escape/Tab/ArrowDown/a；组合键用 + 连接，如 Control+a）"},
                "delay": {"type": "integer", "description": "可选。按下到抬起的间隔毫秒", "minimum": 0},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": ["key"],
        },
    },
    # ── 元素交互扩展（P2 批B）：role+name 定位协议补齐悬停/下拉/勾选 ──
    "browser_hover": {
        # 并行能力声明：语义只读（悬停本身不改 DOM），但作用域为共享（共享页面指针）⇒ 可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【悬停元素】把鼠标悬停到指定 ARIA role+name 的元素上，触发悬停类交互（下拉菜单展开、tooltip 显示等）。悬停可能使页面结构变化（菜单展开），快照事实随之失效（generation 递增），后续交互前需重新 browser_dom_snapshot。参数必须来自最近一次快照事实。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "ARIA 角色（button/link/menuitem 等，来自快照）"},
                "name": {"type": "string", "description": "可访问名称（来自快照）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；跨代即拒绝"},
            },
            "required": ["role"],
        },
    },
    "browser_select": {
        # 并行能力声明：驱动同一个内置浏览器实例（按 ARIA 角色改写表单选中态）——共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【下拉选择】在指定 ARIA role+name 的下拉框（combobox/select）中选中一个或多个选项（values 为 option 的 value 或可见标签）。改写页面表单状态，快照事实随之失效（generation 递增）。参数必须来自最近一次快照事实；选完表单未提交时用 browser_press(key=Enter) 或点击提交按钮。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "ARIA 角色（combobox/select，来自快照）"},
                "values": {"type": "array", "items": {"type": "string"}, "description": "要选中的 option 值或可见标签（多选框可给多个）"},
                "name": {"type": "string", "description": "可访问名称（来自快照，如字段标签）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；跨代即拒绝"},
            },
            "required": ["role", "values"],
        },
    },
    "browser_check": {
        # 并行能力声明：驱动同一个内置浏览器实例（按 ARIA 角色改写勾选态）——共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【勾选/取消勾选】勾选（checked=true）或取消勾选（checked=false）指定 ARIA role+name 的复选框/单选框。改写页面表单状态，快照事实随之失效（generation 递增）。参数必须来自最近一次快照事实。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "ARIA 角色（checkbox/radio，来自快照）"},
                "checked": {"type": "boolean", "description": "true=勾选，false=取消勾选"},
                "name": {"type": "string", "description": "可访问名称（来自快照，如选项文字）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；跨代即拒绝"},
            },
            "required": ["role", "checked"],
        },
    },
    # ── 页面状态面（P2/P3 批C）：cookies / web storage / console 缓冲 ──
    "browser_cookies": {
        # 并行能力声明：改共享浏览器实例的 context 级 Cookie（跨 tab 生效）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【Cookie 管理】读取（get，可按 url 过滤）、写入（set，需 name+value，定位用 url 或 domain+path）、清空（clear）当前浏览器会话的 Cookie。用于登录态检查与保持。【何时不用】只是查看页面内容不需要动 Cookie；set 前先 get 确认现有值，避免误覆盖登录态。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set", "clear"], "description": "get=读取 / set=写入 / clear=清空"},
                "name": {"type": "string", "description": "Cookie 名（set 必填）"},
                "value": {"type": "string", "description": "Cookie 值（set 必填，可为空串）"},
                "url": {"type": "string", "description": "Cookie 关联 URL（set 时与 domain+path 二选一；get 时可作过滤）"},
                "domain": {"type": "string", "description": "Cookie 域（set 定位用）"},
                "path": {"type": "string", "description": "Cookie 路径（set 定位用）"},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": ["action"],
        },
    },
    "browser_storage": {
        # 并行能力声明：读写共享浏览器实例当前页的 web storage。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【页面存储】读写 localStorage/sessionStorage（kind=local/session）：get（给 key 取单键，省略取全部）、set（key+value）、remove（key）、clear。用于检查页面本地状态、注入测试令牌等。set/remove/clear 会使快照事实失效（generation 递增）。【何时不用】大体积数据读写不要走本工具（受工具结果字符预算约束）。",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["local", "session"], "description": "localStorage 或 sessionStorage"},
                "action": {"type": "string", "enum": ["get", "set", "remove", "clear"], "description": "读/写/删/清"},
                "key": {"type": "string", "description": "存储键（set/remove 必填；get 省略则取全部）"},
                "value": {"type": "string", "description": "存储值（set 必填，可为空串）"},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": ["kind", "action"],
        },
    },
    "browser_console": {
        # 并行能力声明：只读共享实例的会话内事件缓冲。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【控制台读数】读取本次浏览器会话累积的 console 输出与页面错误（pageerror），返回最近的 limit 条（type=console/pageerror）。用于交互后检查报错、验证页面行为。缓冲上限 200 条、只保留最近记录。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回最近多少条（默认 50，上限 200）", "minimum": 1, "maximum": 200},
            },
            "required": [],
        },
    },
    # ── 采集与扩展（P3 批D）：PDF 打印 / 文件下载 / 拖拽 / 上传 ──
    "browser_pdf": {
        # 并行能力声明：采集当前页并落产物目录（重放登记出第二份产物）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【页面转 PDF】把当前活动页打印成 PDF 并落产物目录，返回文件路径与字节数。用于网页存档、报表出件。【何时不用】只要正文文字用 browser_extract_text；要排版文档用 write_pdf（Markdown→PDF）。",
        "parameters": {
            "type": "object",
            "properties": {
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": [],
        },
    },
    "browser_download": {
        # 并行能力声明：拉取远端字节落产物目录（重放登记出第二份产物）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【文件下载】用浏览器会话的网络栈拉取 URL 的原始字节并落产物目录（二进制保真），返回文件路径、字节数与 HTTP 状态。适合下载 zip/csv/图片等二进制文件；非 2xx 诚实报错。【何时不用】纯文本/API JSON 读取用 web_fetch（更轻）；需要登录态的下载本工具会带上会话 Cookie。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要下载的文件 URL（http/https）"},
                "filename": {"type": "string", "description": "可选。产物文件名前缀（扩展名从 URL 自动推断）"},
                "generation": {"type": "integer", "description": "可选。当前页代数；页面已被外部改变时拒绝"},
            },
            "required": ["url"],
        },
    },
    "browser_drag": {
        # 并行能力声明：驱动同一个内置浏览器实例（改写页面元素位置/状态）——共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【拖拽元素】把 source（ARIA role+name 定位）拖拽到 target 上。用于拖拽排序、滑块、看板移动等交互。拖拽改页面状态，快照事实随之失效（generation 递增）。参数必须来自最近一次快照事实。",
        "parameters": {
            "type": "object",
            "properties": {
                "source_role": {"type": "string", "description": "拖拽起点的 ARIA 角色（来自快照）"},
                "source_name": {"type": "string", "description": "拖拽起点的可访问名称"},
                "target_role": {"type": "string", "description": "拖拽落点的 ARIA 角色（来自快照）"},
                "target_name": {"type": "string", "description": "拖拽落点的可访问名称"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；跨代即拒绝"},
            },
            "required": ["source_role", "target_role"],
        },
    },
    "browser_upload": {
        # 并行能力声明：驱动同一个内置浏览器实例（向文件输入元素写文件）——共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【文件上传】向指定 ARIA role+name 的文件输入元素（input[type=file]）上传一个或多个本地文件（paths 须为存在的绝对路径）。上传改页面状态，快照事实随之失效（generation 递增）。",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "文件输入元素的 ARIA 角色（来自快照）"},
                "name": {"type": "string", "description": "可访问名称（来自快照）"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "要上传的本地文件绝对路径列表（须存在）"},
                "generation": {"type": "integer", "description": "可选。最近一次快照返回的 generation；跨代即拒绝"},
            },
            "required": ["role", "paths"],
        },
    },
    # ── 环境自举：浏览器内核缺失时的受控安装（先经 ask_user 征得用户同意）──
    "browser_install": {
        # 并行能力声明：改本机浏览器环境（下载内核 + 重建后端），独占执行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        # 任意命令执行语义（与 computer_shell 同档）：内部固定跑 playwright install。
        "arbitrary_command": True,
        "description": "【安装浏览器内核】当 browser_* 工具报「浏览器内核缺失」时，安装 Playwright 管理的 Chromium 内核并自动重探恢复。这是环境变更动作：会下载数百 MB 到本机 Playwright 缓存目录——**调用前必须先向用户说明并征得同意**（用 ask_user），不得静默安装。仅支持 chromium；playwright 库本身未安装时会报错并指引 pip install playwright。",
        "parameters": {
            "type": "object",
            "properties": {
                "browser": {"type": "string", "enum": ["chromium"], "description": "要安装的内核（当前仅 chromium）"},
            },
            "required": [],
        },
    },
    # ── 互联网平台直达（Web Reach，零配置路径）──
    "youtube_transcript": {
        # 并行能力声明：语义只读但作用域为共享（yt-dlp 的 YouTube extractor 会把播放器
        # 数据写进固定的进程外缓存根，本仓不可控；字幕本体写本次调用的临时目录并清理）
        # ⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
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
        # 并行能力声明：只读但作用域为共享（分片续读推进同一个浏览器页面的游标（session_id 跨调用共享））⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【浏览器读取】Playwright 渲染 JS 密集页（SPA/客户端渲染）并提取为 Markdown（静态页直接 web_fetch）。首次使用需 playwright install chromium。长文自动分片：首读返回前 60,000 字符＋session_id/can_continue/next_offset，未读完带 session_id 续读至 can_continue=false。【何时不用】已开页面提正文用 browser_extract_text。",
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
        # 并行能力声明：只读但作用域为共享（分片续读推进同一页面的可访问性树游标）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【页面快照分片读取】取 aria 树正文，长快照分片：首读前 8,000 字符＋session_id/can_continue/next_offset，续读至 can_continue=false；快照未截断时直接消费 browser_dom_snapshot。【何时不用】交互定位用 browser_dom_snapshot；未开页面先 browser_navigate。",
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
        # 并行能力声明：无副作用远端读（B 站搜索走独立子进程（yt-dlp bilisearch），只取远端结果，不落本地态。）
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
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
        # 并行能力声明：无副作用远端读（RSS/Atom 读取只发 GET 并解析响应，不落本地态。）
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【RSS 阅读】读取 RSS/Atom 订阅源最新条目（标题/链接/摘要）。【何时不用】要全文拿链接用 web_fetch；源失效/非 RSS 地址用 web_search；搜未知站点不用本工具。",
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
        # 并行能力声明：无副作用远端读（V2EX 热门榜只发 GET 并解析响应，不落本地态。）
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
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
        # 并行能力声明：语义只读但作用域为共享（凭据经 SecretStore.get_secret 读取时会
        # 回写该密钥的访问元数据与访问日志——共享凭据桶）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【社交平台搜索】查询 twitter/reddit/xiaohongshu/facebook/instagram/linkedin 的搜索接入状态（已配置返回后端与命令，未配置返回引导）；不自动登录。【何时不用】通用搜索 web_search；未配置勿重试。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台名（twitter/reddit/xiaohongshu/facebook/instagram/linkedin）"},
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["platform", "query"],
        },
    },
    "agent_reach": {
        # 并行能力声明：语义只读（不发帖不写用户工作区），但运行态归上游 CLI 的
        # 共享状态目录（~/.agent-reach，含渠道浏览器会话）⇒ 作用域 shared，
        # 合取判据自动串行，避免并发调用争用同一渠道会话。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【跨平台内容直达】经本机 agent-reach CLI 读取/搜索 GitHub、雪球、Boss直聘/LinkedIn、小宇宙、B站/YouTube/V2EX、小红书/Reddit 等。mode=channels 列渠道与动作语法；mode=read 按链接自动选渠道读取；mode=action 调渠道动作。普通网页用 web_fetch；垂直内容优先专用工具。需本机装有该 CLI，缺失时返回安装指引。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["channels", "read", "action"],
                    "description": "channels=列渠道语法；read=读链接；action=调渠道动作",
                },
                "url": {"type": "string", "description": "mode=read：完整链接（http/https，自动选渠道）"},
                "channel": {"type": "string", "description": "mode=action：渠道名（先用 mode=channels 查可用渠道）"},
                "action": {"type": "string", "description": "mode=action：动作名（如 search/read/quote/transcribe/subtitle）"},
                "target": {"type": "string", "description": "mode=action：位置参数（搜索词/仓库/股票代码/链接等，不能以 - 开头）"},
                "limit": {"type": "integer", "description": "mode=action：返回条数上限 1..100（映射 --limit，部分动作支持）"},
                "extra_args": {"type": "array", "items": {"type": "string"}, "description": "mode=action：额外 flags（如 [\"--lang\", \"zh\"]），逐元素原样直传"},
            },
            "required": ["mode"],
        },
    },
    "planning": {
        # 并行能力声明：计划存储的增删改（PlanStore 落盘）——存储是共享态；与 update_plan 的分工见其声明。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【任务计划】创建/管理结构化任务计划（多步骤长任务）：create 建清单，mark_step 标状态，持久化可续推。纪律：同时至多一个 in_progress；完成立即标记不攒批；探索/阅读不登记为步骤；大改先说明理由。",
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
        # 并行能力声明：纯文本打分（EmotionAnalyzer.analyze 只读预编译正则，不写实例态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
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
        # 并行能力声明：语义只读但作用域为共享（执行体先 await manager.initialize() 懒建共享引擎，
        # 两路并发会重复加载同一模型）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
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
        # 并行能力声明：语义只读但作用域为共享（懒初始化同一个 tts_manager，且音频落共享临时目录）
        # ⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
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
        # 并行能力声明：与 memory_search 走**同一条** recall 路径（同一记忆库的只读检索），无写作用域。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【内部语音记忆检索】仅搜用户之前通过语音说过的内容（语音转写记录）。不能搜互联网、不能查天气/外部信息。仅用于回忆用户语音对话历史。【何时不用】打字/文字对话记忆用 memory_search；本会话折叠内容用 recall_history；两者都不足再回退本工具，不要每次查三路。",
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
    # Wave F DiscoverSkills：目录被裁剪
    # 或 schema 预算化时，模型主动发现技能库的元数据检索面——只回
    # name/description/调用提示，绝不回指令正文（正文经 $mention 按需加载）。
    "discover_skills": {
        # 并行能力声明：语义只读但作用域为共享（语义档会懒建模块级向量缓存条目并把
        # 向量写进 embeddings.json）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【技能发现】按查询词检索已安装技能库，返回候选技能的元数据清单（名称/描述/何时用）。当你判断需要某个已有技能、但它不在当前工具面时调用；确认要用后，通过 $技能名 加载完整指令执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "能力关键词或自然语言描述"},
                "limit": {"type": "integer", "description": "最多返回条数，默认 5"},
            },
            "required": ["query"],
        },
    },
    "weather": {
        # 并行能力声明：远端天气查询为无副作用读（只发 GET，不改远端状态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
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
        # 并行能力声明：联网检索为无副作用读（只发 GET，不改远端状态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        # P1-1 逐工具结果预算：搜索结果（多条摘要+链接）在 8K 全局阈值下
        # 常被压成 500 字符预览，信息损失大；放宽到 16K（仍低于回环 B7
        # 单结果封顶 20000），超限依旧落盘引用+预览。
        "result_budget_chars": 16384,
        "description": "【实时网络搜索】查互联网实时信息（新闻/股价/百科/文档）。工具选择阶梯（最轻优先）：先搜索拿网址 → web_fetch 读取 → 需交互/登录/动态渲染才升级 browser_*。【何时不用】已知 URL 直接 web_fetch；站点限定用垂直工具；内部记忆问题用 memory_search。",
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
        # 并行能力声明：派生子 Agent 有副作用（蜂群记录 + 父会话邮箱投递），不是只读工具。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【蜂群派生子Agent】把子任务派交给另一 Agent 执行（蜂群编排）；子任务可拆时每任务各调一次并行执行，子 Agent 有独立人设/记忆/模型。background=true 立即返回 subagent_id（用 subagent_status 查询），前台等完成返回报告。纪律：N 个子任务只调 N 次；每层默认 1-3 个；禁重复/无关/嵌套派生；并发上限 5。【何时不用】固定步骤序列用 canvas_run；单步能完成的不派生。",
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
                "subagent_type": {
                    "type": "string",
                    "enum": ["general", "explore"],
                    "description": "子代理类型：general（全工具面，默认）/ explore（只读检索型——工具面收窄为只读白名单，适合信息搜集与侦察，不能写）",
                },
                "task_unit": {
                    "type": "object",
                    "description": "结构化任务单元（可选，P1-1）：把目标/预期产物/验收条件结构化交给蜂群——验收条件用于终态验收门与（reviewMode=supervisor 时的）提交前评审；dependencies 声明依赖的前置 subagent_id",
                    "properties": {
                        "goal": {"type": "string", "description": "任务目标（必填，与 task 描述一致或更精炼）"},
                        "expectedResult": {"type": "string", "description": "预期产物（交付物形态与内容要求）"},
                        "acceptanceCriteria": {"type": "array", "items": {"type": "string"}, "description": "验收条件逐条列出（可执行、可核对；未满足将被验收门打回）"},
                        "requiredInputs": {"type": "array", "items": {"type": "string"}, "description": "完成任务所需的输入"},
                        "artifactOwnership": {"type": "string", "description": "产物归属与后续用途"},
                        "reviewMode": {"type": "string", "enum": ["none", "supervisor"], "description": "评审方式：none 不评审（默认）/ supervisor 回流前由发起方按验收条件评审"},
                        "dependencies": {"type": "array", "items": {"type": "string"}, "description": "依赖的前置 subagent_id 列表（全部验收通过后本任务才启动）"},
                        "untrustedPayload": {"type": "string", "description": "不可信外部内容槽位（P3-4 数据面围栏）：来自外部检索/用户材料的原文放这里，渲染时被隔离进显式不可信段并做注入特征扫描（命中只标记告警，不改写不阻断）；不要把任务指令混进这个字段"},
                    },
                    "required": ["goal"],
                },
            },
            "required": ["task"],
        },
    },
    "list_teams": {
        # 并行能力声明：只读团队名册快照（teams_api JSON 落盘，本执行体不落盘）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【列出固定团队】列出可派活的固定团队（id/名称/成员与职责摘要）。在 dispatch_team 前调用，以便挑选合适的团队。把本次蜂群组合沉淀为新团队用 propose_team（需人批准）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "dispatch_team": {
        # 并行能力声明：按名册多路派生（每路都有蜂群副作用），非只读、不可重放。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【派活固定团队】把一个固定团队整体派活：按名册为每个成员各派一路子任务（成员职责 prompt 自动注入任务书角色段）；task_unit.dependencies 可按名册序号（\"0\"/\"1\"…）或成员 id/名声明步间依赖，派生时映射为对应成员的 subagent_id。每一路都走完整治理三明治（广度/预算/冷却照算），默认后台执行，用 subagent_status 轮询。【何时不用】只需单个成员时直接 spawn_subagent；自由临时组队也用 spawn_subagent（本工具只按既有固定团队名册派活）。",
        "parameters": {
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "string",
                    "description": "固定团队 ID（先用 list_teams 查看可用团队与成员职责）",
                },
                "task": {
                    "type": "string",
                    "description": "交给团队的完整、自包含任务描述（每个成员都会收到，成员职责段按名册自动注入）",
                },
                "task_unit": {
                    "type": "object",
                    "description": "结构化任务单元（可选，同 spawn_subagent.task_unit）；dependencies 按名册序号/成员 id/成员名声明步间依赖（如 [\"0\"] = 等名册第 1 个成员的产出）",
                    "properties": {
                        "goal": {"type": "string", "description": "任务目标（必填）"},
                        "expectedResult": {"type": "string", "description": "预期产物"},
                        "acceptanceCriteria": {"type": "array", "items": {"type": "string"}, "description": "验收条件逐条列出"},
                        "requiredInputs": {"type": "array", "items": {"type": "string"}, "description": "所需输入"},
                        "artifactOwnership": {"type": "string", "description": "产物归属与后续用途"},
                        "reviewMode": {"type": "string", "enum": ["none", "supervisor"], "description": "评审方式：none（默认）/ supervisor"},
                        "dependencies": {"type": "array", "items": {"type": "string"}, "description": "依赖的名册成员（序号如 \"0\"，或成员 id/名）；派生时映射为该成员的 subagent_id"},
                        "untrustedPayload": {"type": "string", "description": "不可信外部内容槽位（数据面围栏）"},
                    },
                    "required": ["goal"],
                },
                "background": {
                    "type": "boolean",
                    "description": "是否后台执行（默认 true=立即返回各成员 subagent_id；false=等待全部完成）",
                },
                "command_id": {
                    "type": "string",
                    "description": "幂等命令 ID（可选）：网络重试/断线重发时传同一 ID，只有第一次会真正派活，后续重试返回上次结果（replayed=true）；不传则不做幂等去重",
                },
            },
            "required": ["team_id", "task"],
        },
    },
    "propose_team": {
        # 并行能力声明：写团队单源（经审批后）+ 审批单副作用，非只读、不可重放。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【提议沉淀团队】把一次成功的蜂群组合（成员+职责快照）提议沉淀为固定团队。走治理审批（L1）：人批准后才写入团队列表——团队是用户资产，agent 不得自行立队；未经批准不会生效。批准后新团队可用 list_teams 查到、可用 dispatch_team 派活。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "提议的团队名称"},
                "description": {"type": "string", "description": "团队职责说明"},
                "members": {
                    "type": "array",
                    "description": "成员与职责快照（来自本次蜂群 run 的实际组合，至少一名成员）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "userId": {"type": "string", "description": "成员 Agent ID"},
                            "name": {"type": "string", "description": "成员显示名"},
                            "role": {"type": "string", "description": "团队角色（author/reviewer/…）"},
                            "prompt": {"type": "string", "description": "成员职责描述"},
                        },
                        "required": ["userId"],
                    },
                },
                "promoted_from_run": {
                    "type": "string",
                    "description": "来源 subagent_id（本次成功 run 的溯源标，可选）",
                },
            },
            "required": ["name", "members"],
        },
    },
    "project_create": {
        # 并行能力声明：写共享项目存储（collaboration_isolation 单源）+ 审批单副作用。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【发起项目】agent 发起创建一个协作项目（创建即建协作房间：project_id=room_id）。直接可建，但强制审计与预算入账；项目所有者记为发起 agent 的属主用户，发起 agent 自动成为项目成员。治理约束：新增人类成员（memberUserIds）或把可见性放宽为 team 走审批链 L1（人批准才生效，未批准不生效）；对外公开（public）不开放给 agent——L2 判定保留给人。名称/描述过数据面围栏扫描（命中只标记不阻断）。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "项目名称（必填）"},
                "description": {"type": "string", "description": "项目描述"},
                "visibility": {
                    "type": "string",
                    "enum": ["private", "team"],
                    "description": "可见性：private 仅成员可见（默认）；team 团队可见（需 L1 审批）。public 对外分享不开放给 agent（L2 保留给人）",
                },
                "memberAgentIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "直接加入的 agent 成员 id 列表（可选）",
                },
                "memberUserIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "拟加入的人类用户 id 列表（可选）——影响人必须过人：走 L1 审批，未批准不生效",
                },
            },
            "required": ["name"],
        },
    },
    "project_list": {
        # 并行能力声明：只读项目名册快照（collaboration_isolation 内存态读）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【列出项目】列出当前 agent 可见的项目：自己是成员的、属主用户参与的、以及公开项目。返回项目 id（同时是协作房间 room_id）、名称、可见性、initiator 标（agent 发起的项目带 initiator=agent）。配合 project_detail 查看详情。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "project_detail": {
        # 并行能力声明：只读项目详情快照（collaboration_isolation 内存态读）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【项目详情】查看单个项目的成员、可见性、状态、团队/任务计数与 initiator 标。仅对当前 agent 可见的项目返回（非成员且非公开一律拒绝）。",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "项目 ID（project_list 返回的 project_id，同时是协作房间 room_id）",
                },
            },
            "required": ["project_id"],
        },
    },
    "room_post": {
        # 并行能力声明：向共享房间投递消息（RoomStore 落库 + 事件广播）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【房间发言】向自己所在的项目协作房间发一条消息（kind=report 进展汇报 / question 提问 / note 备注）。仅限自己为成员的房间（非成员一律拒绝）；治理限频防刷屏（超频被拒）。审批/升级/候选请走既有专用通道（request_approval / escalate / submit_result），本工具是通用发言面。",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "项目/房间 ID（project_id=room_id）",
                },
                "message": {"type": "string", "description": "消息内容（非空）"},
                "kind": {
                    "type": "string",
                    "enum": ["report", "question", "note"],
                    "description": "消息种类：report 进展汇报 / question 提问 / note 备注（默认 note）",
                },
            },
            "required": ["project_id", "message"],
        },
    },
    "subagent_status": {
        # 并行能力声明：只读蜂群运行记录（SwarmManager 的 status/list_all 在 RLock 下读内存态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【查询子Agent状态】查蜂群子 Agent 的执行状态与最终报告；配合 background=true 或前台转后台后的轮询。subagent_id 省略时返回最近派生列表（新→旧，report 截断）。view=integration 返回集成前核对面（各子任务验收/评审/依赖状态与 blockers）。view=events 返回该 run 的事件账本（spawned/started/stalled/escalated/terminal 全程 + 因果链，H-4）。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {
                    "type": "string",
                    "description": "spawn_subagent 返回的 subagent_id；省略时返回最近派生列表",
                },
                "view": {
                    "type": "string",
                    "enum": ["runs", "integration", "events"],
                    "description": "runs（默认）按 run 查询；integration（P2-4）返回集成前核对面：integration_ready + blockers + 各子任务验收/评审状态——主任务汇总前用它确认无未验收挂账；events（H-4）返回该 run 的事件账本（需 subagent_id）",
                },
            },
            "required": [],
        },
    },
    "list_agents": {
        # 并行能力声明：只读 Agent 注册表快照（注册表写点由 RLock 串行，本执行体不落盘）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【列出可用Agent】列出系统中所有可用的 Agent（含各自的名字、职责描述、模型配置）。在蜂群派生（spawn_subagent）前调用，以便为子任务挑选最合适的执行者。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "create_skill": {
        # 并行能力声明：注册技能并落盘技能库——技能注册表是共享态，并发注册同名技能会互相覆盖。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【创建可执行技能】把反复出现的工具调用组合成持久化技能，之后经 `name` 一键调用。技能＝有序工具调用＋可选步间占位符（{step_<idx>.<field>} 引用前序输出）。创建后本会话与 SkillRegistry 立即可调。",
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
    "ask_user": {
        # 并行能力声明：写构建会话的交互记录并暂停当前步，属共享状态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【向用户提问】构建/修复工作流遇不明确、需选择、需补参数或凭据时，弹交互面板并暂停当前步，回答后恢复。凭据用 kind=secret + secret_key（入 SecretStore），禁止聊天正文粘贴。",
        "parameters": {
            "type": "object",
            "properties": {
                "build_session_id": {
                    "type": "string",
                    "description": "构建会话 ID；缺省读当前请求的构建上下文（通常不用手填）",
                },
                "question": {"type": "string", "description": "问题文本；必须写清楚要用户决定什么"},
                "kind": {
                    "type": "string",
                    "enum": ["choice", "multi", "text", "secret", "confirm"],
                    "description": "choice 单选 / multi 多选 / text 文本 / secret 凭据 / confirm 确认",
                },
                "options": {
                    "type": "array",
                    "description": "选项列表；元素为字符串或 {label, description, recommended}",
                    "items": {},
                },
                "multi": {"type": "boolean", "description": "是否多选（kind=multi 时自动为真）"},
                "allow_custom": {"type": "boolean", "description": "是否允许自由补充"},
                "why": {"type": "string", "description": "为什么问（给用户看）"},
                "impact": {"type": "string", "description": "回答会影响什么（给用户看）"},
                "secret_key": {"type": "string", "description": "kind=secret 时必填：写入 SecretStore 的键名"},
                "timeout_seconds": {"type": "integer", "description": "面板等待超时；超时只暂停不失败"},
            },
            "required": ["question"],
        },
    },
    "escalate": {
        # 并行能力声明：子代理升级是通知面（邮箱投递+运行记录），不改共享存储，
        # 只读且可并发。P2-10 增强。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【子代理升级】子代理遇阻时把问题升级给主代理/用户：说明卡点、已尝试与需要的决策。仅子代理运行内可用；升级后请在最终回复说明已升级并结束本轮。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "升级原因：卡点是什么、为什么自己解决不了"},
                "question": {"type": "string", "description": "需要用户/主代理决策的问题（可选）"},
                "severity": {"type": "string", "enum": ["normal", "urgent"], "description": "严重程度，默认 normal"},
                "suggested_action": {"type": "string", "enum": ["clarify", "reassign", "revise_dependency", "retry", "none"], "description": "建议主代理采取的处置：澄清/改派/修订依赖/重试/无需动作（P2-5 升级闭环）"},
                "action_note": {"type": "string", "description": "对建议处置的补充说明（改派给谁、依赖哪里要修订等）"},
            },
            "required": ["reason"],
        },
    },
    "submit_result": {
        # 并行能力声明：子代理结果提交是通知面（邮箱投递+运行记录），不改共享存储，
        # 只读且可并发。P2-10 增强。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【子代理结果提交】子代理以结构化形态提交最终结果（摘要/状态），主代理与用户会收到通知。仅子代理运行内可用；提交后请在最终回复中重述要点。",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "结果摘要（结论/关键数据/未尽事项）"},
                "status": {"type": "string", "enum": ["success", "partial", "failed"], "description": "结果状态，默认 success"},
            },
            "required": ["summary"],
        },
    },
    "continue_subagent": {
        # 并行能力声明：续跑/改需求/fork 走 spawn 同一条治理闸与执行路径（子代理可能跑任意工具），非只读。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【续跑/改需求子代理】对子代理下达追加指令。已结束（completed/failed）的子代理被复活：member 会话历史保留（不是从零重派），上一段产出自动附带衔接。运行中的子代理也可改需求：mode=steer 把新指令注入其会话（下一工具轮生效，尽力而为）；mode=restart 先叫停再按新指令重派（保留溯源）；mode=fork 从该子代理派生一个新分支 run（新会话起步、原 run 不叫停不改动）。适用：失败续跑、追加分析、修正方向。仅主代理可用（子代理不得续跑兄弟——与递归派生同禁）。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "要续跑/改需求的子代理 ID（spawn_subagent/subagent_status 返回的 subagent_id）"},
                "message": {"type": "string", "description": "续跑/修正指令：接着做什么/修正什么/补充什么约束"},
                "background": {"type": "boolean", "description": "是否后台执行（默认 false，前台等结果；仅终态续跑时有效）"},
                "mode": {"type": "string", "enum": ["steer", "restart", "resume", "fork"], "description": "改需求/派生方式：steer 注入运行中会话（下一工具轮生效，尽力而为，默认）/ restart 先叫停再按新指令重派（保留溯源）/ resume 续跑已终态子代理（缺省行为，member 会话复用）/ fork 从该子代理派生新分支 run（新会话起步、原 run 不受影响，返回新 subagent_id）。已终态子代理的 steer/restart 视同 resume"},
                "command_id": {"type": "string", "description": "幂等命令 ID（可选）：重试时传同一 ID 防重复注入/重派；不传则不做幂等去重"},
            },
            "required": ["subagent_id", "message"],
        },
    },
    "cancel_subagent": {
        # 并行能力声明：叫停会改共享运行状态并终止成员任务，非只读、不可重放。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【叫停子代理】取消一个运行中的子代理：终态以 failed(subagent_cancelled) 落账，已产出的部分报告随失败交接保留，派生槽立即释放；依赖等待中的派生件被叫停后不再被拉起。已终态的运行无需叫停（幂等失败）。仅主代理可用（子代理不得叫停自己/兄弟）。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "要叫停的子代理 ID（spawn_subagent/subagent_status 返回的 subagent_id）"},
                "reason": {"type": "string", "description": "叫停原因（留痕进事件账本与失败交接文案）"},
                "command_id": {"type": "string", "description": "幂等命令 ID（可选）：重试时传同一 ID 防重复执行；不传则不做幂等去重"},
            },
            "required": ["subagent_id"],
        },
    },
    "rollback_subagent": {
        # 并行能力声明：回滚会重写 member 会话存储（删后重建），非只读、不可重放
        # （重放会再生成一份 pre-restore 快照并再次改写会话）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【回滚子代理会话】把子代理的成员会话恢复到最近一次检查点（事务化：恢复前自动留档 pre-restore 快照，恢复失败自动回滚）。适用于成员跑偏后回到最近已知良好状态再续派。无检查点、恢复失败或成员未声明会话回滚能力时，诚实返回失败原因。仅主代理可用。",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "要回滚成员会话的子代理 ID（spawn_subagent/subagent_status 返回的 subagent_id）"},
                "command_id": {"type": "string", "description": "幂等命令 ID（可选）：重试时传同一 ID 防重复执行；不传则不做幂等去重"},
            },
            "required": ["subagent_id"],
        },
    },
    "request_approval": {
        # 并行能力声明：写共享审批存储（ApprovalManager）并可能阻塞等待裁决，非只读。
        "capability": {"readOnly": False, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【请求审批】子代理要执行超出自身授权的操作时，向父代理/用户发起审批请求（跨 agent 审批链）。等级：L0 低危可逆（自动放行+记账）/ L1 中危（请父代理裁决）/ L2 高危不可逆（强制人工确认）。返回 approved=true 才可执行；pending/denied 都不得执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "要请求执行的具体操作（做什么、对哪个对象；会做危险命令检测，命中将至少按 L1 处理）"},
                "reason": {"type": "string", "description": "为什么需要这个操作（给裁决人看）"},
                "level": {"type": "string", "enum": ["L0", "L1", "L2"], "description": "自评危险等级：L0 可逆低危 / L1 中危 / L2 高危不可逆（默认 L1）"},
                "context": {"type": "string", "description": "补充上下文（影响范围、备选方案等）"},
            },
            "required": ["action"],
        },
    },
    "decide_subagent_approval": {
        # 并行能力声明：裁决写共享审批存储并唤醒等待中的子代理，非只读、不可重放。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【裁决子代理审批】对子代理发起的审批单（request_approval 创建）做批准/拒绝。只受理蜂群审批单；已裁决的幂等失败。仅主代理可用（子代理工具面已剔除本工具）。",
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "审批单 ID（邮箱审批信封/审批记录中的 request_id）"},
                "decision": {"type": "string", "enum": ["approve", "reject"], "description": "approve 批准 / reject 拒绝"},
                "note": {"type": "string", "description": "裁决备注（会随结果回传给子代理）"},
            },
            "required": ["request_id", "decision"],
        },
    },
    "custom_node_create": {
        # 并行能力声明：写共享的自定义节点注册表——同批两个创建会撞同一份注册表与版本表。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【创建自定义节点·草稿】在已批准构建批次内创建 L1/L2 自定义节点，默认 draft 不可被画布引用，需 custom_node_activate 激活。tier=declarative 需 executor_body.template；composite 需 steps。",
        "parameters": {
            "type": "object",
            "properties": {
                "spec": {"type": "object", "description": "节点 spec：type/label/description/tier/executor_body/form_schema/inputs/outputs/env_requirements"},
            },
            "required": ["spec"],
        },
    },
    "custom_node_update": {
        # 并行能力声明：改共享的节点定义（读-改-写）——并发改同一节点必丢更新。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【更新自定义节点·草稿】只允许更新 draft 节点；active 节点需新批次/审批，本工具拒绝。",
        "parameters": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "自定义节点类型，如 custom:campaign_audit"},
                "spec": {"type": "object", "description": "要更新的字段（label/description/tier/executor_body/form_schema/inputs/outputs/env_requirements）"},
            },
            "required": ["node_type", "spec"],
        },
    },
    "custom_node_activate": {
        # 并行能力声明：激活会动共享注册表与画布引用面，同批并发与写操作互踩。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【激活自定义节点】把本构建批次内创建的 draft 节点提升为 active；节点 batch_id 必须与当前 BuildSession 批次一致。",
        "parameters": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "自定义节点类型"},
            },
            "required": ["node_type"],
        },
    },
    "custom_node_delete": {
        # 并行能力声明：删除共享注册表条目——并发下"先判引用再删"是 TOCTOU。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【删除自定义节点·草稿】只允许删除 draft 节点；active 节点需先停用/新批次处理，本工具拒绝。",
        "parameters": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "自定义节点类型"},
            },
            "required": ["node_type"],
        },
    },
    "workflow_definition_get": {
        # 并行能力声明：只读定义，但已发布工作流可能补安全版本基线（写共享库）⇒ 不可并行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【读取工作流定义】返回节点/边/变量、当前版本、状态与安全版本。修改已发布工作流前先用本工具拿 base_version；已发布但无有效安全版本时会先为当前内容建立基线。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流 ID"},
            },
            "required": ["workflow_id"],
        },
    },
    "workflow_definition_update": {
        # 并行能力声明：写共享的工作流定义表（版本自增）——并发写同一定义必撞版本号。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【修改工作流定义】直接修改已发布或草稿工作流（无需先复制）。必须带 base_version 乐观锁；已发布会先确保安全版本；DAG/节点类型/端口/草稿自定义节点校验失败时不写入。整个任务批次一次审批、逐条审计。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流 ID"},
                "nodes": {
                    "type": "array",
                    "description": "完整节点列表；元素含 id/type/position/config/label。缺省表示不改节点。",
                    "items": {"type": "object"},
                },
                "edges": {
                    "type": "array",
                    "description": "完整边列表；元素含 id/source/target/source_handle/target_handle。缺省表示不改边。",
                    "items": {"type": "object"},
                },
                "base_version": {"type": "integer", "description": "读取到的当前定义版本（乐观锁）"},
                "batch_id": {"type": "string", "description": "构建批次 ID；构建会话内缺省取会话批次"},
                "note": {"type": "string", "description": "本次变更摘要（写入审计）"},
            },
            "required": ["workflow_id", "base_version"],
        },
    },
    "workflow_definition_duplicate": {
        # 并行能力声明：复制会往共享定义表插新行并读源定义，两端都是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【复制为草稿】把工作流复制成 DRAFT 草稿副本（修复循环的暂存落点）。草稿试跑通过后再发布或回滚，避免直接打断正在运行的已发布流程。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "源工作流 ID"},
                "name": {"type": "string", "description": "草稿名称（可选）"},
                "batch_id": {"type": "string", "description": "构建批次 ID（可选，写入草稿元数据）"},
            },
            "required": ["workflow_id"],
        },
    },
    "workflow_rollback": {
        # 并行能力声明：回滚把共享定义表整体推回旧版本——与任何写同一定义的操作互斥。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【回滚工作流】回滚到指定版本；不传 target_version 时回到安全版本。回滚本身产生新版本（undo-friendly），安全版本标记不变。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流 ID"},
                "target_version": {"type": "integer", "description": "目标版本号（可选，缺省用安全版本）"},
                "batch_id": {"type": "string", "description": "构建批次 ID（可选，写入审计）"},
            },
            "required": ["workflow_id"],
        },
    },
    "workflow_publish": {
        # 并行能力声明：发布改共享定义的发布态与安全版本基线，并发发布会双写基线。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【发布工作流】校验并发布（DRAFT→PUBLISHED），同时编译工作流 Agent。发布动作把当前版本设为安全基线；校验或编译失败不改变状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流 ID"},
                "note": {"type": "string", "description": "发布说明（可选）"},
                "batch_id": {"type": "string", "description": "构建批次 ID（可选，写入审计）"},
            },
            "required": ["workflow_id"],
        },
    },
    "workflow_execute": {
        # 并行能力声明：执行会落共享的执行实例与状态表；同批两路执行互相污染运行态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【执行工作流定义】执行并返回节点级结果；默认只允许已发布工作流，草稿试跑需 allow_draft=true。已发布执行成功会把当前版本提升为安全版本（执行校验凭据）。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "工作流 ID"},
                "inputs": {"type": "object", "description": "工作流输入（可选）"},
                "allow_draft": {"type": "boolean", "description": "允许执行 DRAFT 草稿（修复试跑用，默认 false）"},
            },
            "required": ["workflow_id"],
        },
    },
    "node_env_preflight": {
        # 并行能力声明：只读环境变量名与 SecretStore 键名，不读取凭据值。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【环境预检】检查节点类型声明的环境变量/凭据是否可用，返回缺失变量名与配置来源提示。只读键名，不读取、不回显任何凭据值。缺凭据时先用本工具确认缺哪些，再用 ask_user(kind=secret) 向用户索取。",
        "parameters": {
            "type": "object",
            "properties": {
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "节点类型列表，如 builtin:ad-streaming、custom:campaign_audit",
                },
            },
            "required": ["types"],
        },
    },
    "workflow_repair": {
        # 并行能力声明：修复在草稿上多轮试跑并可能提交共享定义/画布——写入面是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【工作流自愈】对失败工作流/画布做最多 5 轮修复：DRAFT 副本执行、读 failed 节点、查 EKB 经验、生成补丁并重跑评估，通过才提交。需 NEUROVA_NODE_REPAIR=1；提交已发布面需批次审批；换节点需 allow_replacements=true。workflow_id/canvas_id 二选一。",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "要修复的工作流 ID"},
                "canvas_id": {"type": "string", "description": "要修复的画布 ID（先编译为工作流草稿）"},
                "inputs": {"type": "object", "description": "每次试跑的输入（可选）"},
                "max_rounds": {"type": "integer", "description": "最大修复轮次（1-5，默认 5）"},
                "commit": {"type": "boolean", "description": "草稿通过后是否提交目标（默认 true）"},
                "allow_replacements": {"type": "boolean", "description": "显式批准换节点候选（语义不保证等价；默认 false）"},
                "batch_id": {"type": "string", "description": "构建批次 ID（可选，构建会话内缺省取会话批次）"},
            },
            "required": [],
        },
    },
    "build_batch_compensate": {
        # 并行能力声明：按批次逆序回滚多个共享 surface（画布/节点/定义），同批并发会重放同一条补偿。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【批次补偿】按构建批次补偿日志逆序回滚画布快照/新建画布/自定义节点激活/工作流定义版本。用于一次任务里后一个 surface 失败、需要回收前面已提交变更的场景；已补偿条目不重放。缺省使用当前构建会话的 batch_id。",
        "parameters": {
            "type": "object",
            "properties": {
                "batch_id": {"type": "string", "description": "构建批次 ID；缺省取当前构建会话批次"},
            },
            "required": [],
        },
    },
    "sync_nodes": {
        # 并行能力声明：写进程内共享节点注册表。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【同步节点库】把工具、技能、MCP、电商、短剧、ComfyUI、自定义节点重新注册进当前进程的节点注册表，让刚创建的技能/自定义节点马上能被 canvas_add_node 使用。幂等；不写持久化数据。add_node 报未知类型但确认能力已存在时先调用本工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "tools", "skills", "mcp", "custom", "commerce", "drama", "comfyui"],
                    "description": "同步范围，默认 all",
                }
            },
        },
    },
    "run_scripted_workflow": {
        # 并行能力声明：脚本化工作流有副作用（ctx.callTool 走治理管线、journal 落盘）
        # ——脚本本体无 I/O 原语（AST 白名单 + 受限内建）。P3-14。重放会重跑副作用，
        # 故登记进 _NON_REPRODUCIBLE_TOOLS（不可重现）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【脚本化工作流】把一段受限 Python 脚本（必须定义 async def main(ctx)）交给沙箱执行：ctx.callTool(工具名, 参数) 走完整治理管线（审批/审计不旁路），ctx.log/setVar/getVar 管理过程状态，ctx.sleep 有限等待。脚本禁 import/eval/exec/open 等危险调用与 dunder 属性；journal 逐调用落盘，传 resume_run_id 可从中断处续跑（已执行调用复用结果不重复执行）。适合多步骤确定性编排；探索性任务请用 planning。",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "受限 Python 脚本：必须定义 async def main(ctx)；禁 import/eval/exec/open/getattr 等危险调用与 __dunder__ 属性",
                },
                "name": {"type": "string", "description": "工作流名（run_id 前缀，默认 scripted）"},
                "resume_run_id": {"type": "string", "description": "续跑的 run_id（从中断点继续，已执行调用复用结果）"},
                "timeout": {"type": "number", "description": "执行超时秒（5-600，默认 120）"},
            },
            "required": ["script"],
        },
    },
    "schedule_task": {
        # 并行能力声明：调度任务落共享存储，建/取消都会改共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【定时任务】定时任务全生命周期：create 新建 / list 查看 / update 修改（cron、间隔、名称、次数）/ pause 暂停 / resume 恢复 / cancel 取消（留痕）/ delete 删除。到点让指定 Agent 执行消息或跑工作流/画布。cron 5 段（分 时 日 月 周，0=周一）或固定间隔；重启后自动恢复。【何时不用】只跑一次用普通工具；需人盯的流程用审批节点。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "pause", "resume", "cancel", "delete"],
                    "description": "create 新建；list 查看自己 Agent 的任务；update 修改任务（cron/间隔/名称/描述/最大次数）；pause 暂停；resume 恢复；cancel 取消（留痕可查）；delete 删除",
                },
                "task_id": {"type": "string", "description": "cancel 时必填：任务 ID"},
                "name": {"type": "string", "description": "任务名称（create 时建议填写）"},
                "description": {"type": "string", "description": "任务说明（create 时可选）"},
                "agent_id": {
                    "type": "string",
                    "description": "执行任务的 Agent；缺省=当前 Agent。只能给自己建任务",
                },
                "cron_expression": {
                    "type": "string",
                    "description": "5 段 cron（分 时 日 月 周，0=周一）。与 interval_seconds 二选一",
                },
                "interval_seconds": {
                    "type": "integer",
                    "description": "重复间隔（秒）。与 cron_expression 二选一",
                },
                "message": {
                    "type": "string",
                    "description": "到点让 Agent 执行的提示词；没有 workflow_id / canvas_id 时必填",
                },
                "workflow_id": {
                    "type": "string",
                    "description": "改为运行已发布工作流（NeurFlow workflow id）",
                },
                "canvas_id": {
                    "type": "string",
                    "description": "改为运行已保存画布（canvas_* 创建），每次触发按当时版本编译执行",
                },
                "max_runs": {
                    "type": "integer",
                    "description": "最多执行次数；缺省不限",
                },
            },
            "required": ["action"],
        },
    },
    # ── 常规 Agent 工具（2026-08 扩充，run_code ↔ DeepSeek code_interpreter
    # （run_code 执行体早已存在于 tool_executor
    "file_list": {
        # 并行能力声明：本地目录枚举只读，无写作用域。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【文件枚举】按 glob 列出文件（如 *.py、docs/**/*.md），支持递归。找到后用 file_read 读、file_search 按内容搜；截断时带 next_offset 续拉。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 匹配模式，如 *.py、*.json"},
                "path": {"format": "path", "type": "string", "description": "搜索的根目录（默认当前工作目录）"},
                "recursive": {"type": "boolean", "description": "是否递归子目录（默认 true）"},
                "max_results": {
                    "type": "integer",
                    "description": "本页返回的最大条目数（默认 500，上限 2000）",
                    "default": 500,
                },
                "offset": {
                    "type": "integer",
                    "description": "跳过前 N 条后再返回（翻页用，配合响应的 next_offset）",
                    "default": 0,
                },
            },
            "required": ["pattern"],
        },
    },
    "file_search": {
        # 并行能力声明：本地内容搜索只读（打开的文件全部来自校验后基准目录内的 os.walk 结果）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【文件内容搜索】按关键词或正则搜文件内容（类 grep），返回文件/行号/行内容，可搜单文件或目录。截断时带 truncated=true 与 next_offset 续拉，勿改写 pattern 猜剩余。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（支持正则；非法正则自动降级为字面量匹配）"},
                "path": {"format": "path", "type": "string", "description": "要搜索的文件或目录路径"},
                "include": {"type": "string", "description": "搜索目录时的文件名过滤，如 *.py（可选）"},
                "max_results": {"type": "integer", "description": "返回的最大匹配条数", "default": 50},
                "offset": {
                    "type": "integer",
                    "description": "跳过前 N 条匹配后再返回（翻页用，配合响应的 next_offset）",
                    "default": 0,
                },
            },
            "required": ["pattern", "path"],
        },
    },
    "write_pdf": {
        # 并行能力声明：产物落盘并注册 artifact——产物目录与登记表都是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【PDF 出件】把 Markdown 渲染为 PDF 产物，返回文件名/产物目录/鉴权下载地址（报告、归档、交付清单）。【何时不用】读 file_read；写文本 file_write；网页另存 browser_*。warnings 非空（如字体降级）必须如实转达。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Markdown 正文（子集：# 标题、段落、- 与 1. 列表、**粗体**、*斜体*、`行内码`、| 表格 |、![说明](图片路径或 http(s) 链接)、--- 分隔线）。与 content_html 二选一",
                },
                "content_html": {
                    "type": "string",
                    "description": "HTML 正文（子集：h1-h6/p/ul/ol/li/table/tr/th/td/img/b/strong/i/em/code/pre/hr/br）。script/style/link/iframe 会被丢弃并在 warnings 点名，href 不进 PDF。与 content 二选一",
                },
                "title": {"type": "string", "description": "文档标题（进 PDF 元数据与页眉；不参与文件名）"},
                "template": {
                    "type": "string",
                    "enum": ["blank", "report", "cover"],
                    "description": "模板预设：blank 无页眉页脚无页码；report（默认）页眉=标题、页脚=日期、带页码；cover 在 report 前加一页封面",
                },
                "header_text": {"type": "string", "description": "页眉文字，覆盖模板默认（传空串是「关掉页眉」，不是「没填」）"},
                "footer_text": {"type": "string", "description": "页脚文字，覆盖模板默认（传空串是「关掉页脚」）"},
                "page_number": {"type": "boolean", "description": "是否画页码（缺省跟随模板：report/cover 开，blank 关）"},
                "margin_mm": {"type": "number", "description": "四边页边距（毫米，默认 18）"},
                "path": {"format": "path", 
                    "type": "string",
                    "description": "落到工作区内的指定路径（必须以 .pdf 结尾，越出工作区会被拒）；省略则落产物目录并返回鉴权 download_url",
                },
            },
            "required": [],
        },
    },
    "git": {
        # 并行能力声明：含写子命令（commit/push/checkout）会抢同一 .git/index.lock；工具粒度从严，与
        # _NON_REPRODUCIBLE_TOOLS 把整个 git 列为不可重现同一处置。
        # 超时处置 KILL：`_execute_git` 起真 git 进程（经 to_thread 下沉），放弃它
        # 即意味着那个进程还得死——`Task.cancel()` 对已进线程池的调用只丢结果。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",),
                       "timeoutDisposition": "kill"},
        "description": "【Git 仓库操作】在指定仓库执行 git 命令（command 含 git 前缀，如 'git status --short'）；目录由 path 锚定，禁止 --git-dir/-C/--work-tree 逃逸。读操作直接执行，写操作（add/commit/push/checkout/reset…）触发人工确认。GitHub 远程操作用 github MCP；通用 shell 用 run_code/computer_shell。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "完整 git 命令行，必须以 git 开头（如 git log --oneline -10）"},
                "path": {"format": "path", "type": "string", "description": "仓库目录（相对锚定 agent 工作区；缺省为工作区根）", "default": "."},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 60},
            },
            "required": ["command"],
        },
    },
    "deep_research": {
        # 并行能力声明：内层已有并发扇出（检索 gather + 抓取限流信号量 6）——外层再并行是**叠乘**，
        # 缺的是资源护栏而不是作用域隔离，故用并发位表达、作用域仍是 none。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("none",)},
        "description": "【深度研究采集】对主题多源检索＋摘录，返回带 [n] 引用的源料包（title/url/excerpt），你据此写带引用的报告；比逐条 search+fetch 省往返。可传 sub_queries 拆角度。单链接用 web_fetch；简单事实用 web_search；本工具不写结论。",
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
        # 并行能力声明：网页抓取为无副作用读（只发 GET，不改远端状态）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【网页抓取】抓取 URL 内容转纯文本（文章/文档/API 响应）。已知网址时用；仅 http/https。结果空或不完整（JS 动态页）再升级 browser_*。【何时不用】没 URL 先 web_search；JS/登录页 browser_read；本地文件 file_read。",
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
        # 并行能力声明：任意代码执行——共享解释器与工作目录，副作用面不可预判。
        # 超时处置 KILL：本工具起真进程（`LocalExecutor` / Docker），放弃它就意味着
        # 那个进程还得死——否则占 CPU、持句柄、继续写盘，而界面已认为中止。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",),
                       "timeoutDisposition": "kill"},
        "description": "【代码执行】运行 Python 或 shell 代码，返回 stdout/stderr/退出码。用于数据处理、算法计算、文本批量处理、验证逻辑。【何时不用】系统操作类命令用 computer_shell；纯数值计算禁止心算，一律本工具跑 Python。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码字符串"},
                "language": {"type": "string", "description": "代码语言：python（默认）/ shell / javascript（经 node -e 执行，node 缺席时诚实报错）"},
                "timeout": {"type": "integer", "description": "执行超时秒数（默认 60）"},
                "runtime_type": {"type": "string", "description": "运行时类型：local（默认）或 docker", "enum": ["local", "docker"], "default": "local"},
                "cwd": {"type": "string", "description": "工作目录（可选，默认执行器当前目录）"},
                "env": {"type": "object", "description": "附加环境变量字典（可选，如 {\"KEY\": \"value\"}）"},
                "isolation": {"type": "string", "enum": ["default", "strong"], "default": "default",
                              "description": "隔离档位：default=本机执行器；strong=Docker 强隔离容器（无网络+只读根+资源上限+非 root；docker 不可用时诚实拒绝，不回退明文执行）"},
            },
            "required": ["code"],
        },
    },
    "exec_command": {
        # 壳方言声明：command 文本交给常驻真 shell 执行（`shell_sessions` 用
        # `shell=True`），|/;/&& 是命令连接符 ⇒ 必须走分段审批面。
        "shell_dialect": True,
        # 并行能力声明：启动常驻 shell 进程——进程与 workdir 是共享资源，并发启动会互抢同一工作目录。
        # 超时处置 KILL：常驻进程超时后必须终止（会话的 terminate 注册为杀灭回调），
        # 否则它会随应用退出而泄漏。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",),
                       "timeoutDisposition": "kill"},
        "description": "【会话式命令执行】启动常驻 shell 进程并等 yield_time_ms 毫秒：完成返回输出与退出码；未结束返回 session_id（running），用 write_stdin 写入/轮询。适合构建/测试/dev server。【何时不用】一次性命令用 computer_shell；Python 处理用 run_code。",
        "sandbox_required": True,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "workdir": {"format": "path", "type": "string", "description": "工作目录（相对路径锚定 agent 工作区，缺省为工作区根）"},
                "yield_time_ms": {"type": "integer", "description": "等待毫秒数（250-30000，超时未结束则返回 session_id 继续后台运行，默认 1000）"},
                "max_output_tokens": {"type": "integer", "description": "返回输出 token 上限（超出保留首尾并标注，默认 10000）"},
                "isolation": {"type": "string", "enum": ["default", "strong"], "default": "default",
                              "description": "隔离档位：default=本机执行器；strong=Docker 强隔离容器（无网络+只读根+资源上限+非 root；docker 不可用时诚实拒绝，不回退明文执行）"},
                "timeout": {"type": "integer", "description": "strong 档容器内命令预算秒数（default 档不使用——会话语义由 yield_time_ms 承载；默认 60）"},
            },
            "required": ["command"],
        },
    },
    "write_stdin": {
        # 并行能力声明：向既有 shell 会话写输入并推进输出游标——会话是共享态，两路并发会交错丢输出。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【会话输入/轮询】向 exec_command 返回的 session_id 会话写入文本（自动补换行）并等待新输出；chars 传空串表示纯轮询输出。进程结束后返回 exit_code。【何时不用】没有进行中的 exec_command 会话时不要调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "integer", "description": "exec_command 返回的会话 id"},
                "chars": {"type": "string", "description": "要写入的文本（空串=纯轮询；写命令时以 \\n 结尾或自动补）"},
                "yield_time_ms": {"type": "integer", "description": "等待毫秒数（250-30000，默认 1000）"},
                "max_output_tokens": {"type": "integer", "description": "返回输出 token 上限（默认 10000）"},
            },
            "required": ["session_id"],
        },
    },
    "calculator": {
        # 并行能力声明：纯函数式计算，不触碰任何外部状态。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【计算器】精确计算数学表达式。支持 + - * / // % **、括号，以及 sqrt/abs/round/min/max/sin/cos/tan/log/floor/ceil 函数和 pi/e 常量。涉及数值计算时应调用此工具，不要心算，避免算术错误。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式，如 (1+2)*3、sqrt(16)、round(pi*2, 2)"},
            },
            "required": ["expression"],
        },
    },
    "update_plan": {
        # 并行能力声明：纯本地校验后原样返回计划（无落盘、无事件、无共享态）；计划**持久化**面在
        # planning 工具，本工具只产出结果供前端时间轴消费。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
        "description": "【任务计划】维护当前任务的步骤清单（todo list）：复杂/多阶段任务开工前建立计划，每完成一步立即更新状态，计划变化时说明原因。约束：同一时刻至多一个 in_progress。【何时不用】简单单步任务不要建计划。",
        "parameters": {
            "type": "object",
            "properties": {
                "explanation": {"type": "string", "description": "计划或状态变化的简要说明（可选）"},
                "plan": {
                    "type": "array",
                    "description": "步骤清单（全量提交，覆盖上一版计划）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string", "description": "步骤内容"},
                            "status": {"type": "string", "description": "pending / in_progress / completed", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["step", "status"],
                    },
                },
            },
            "required": ["plan"],
        },
    },
    "get_datetime": {
        # 并行能力声明：本地时钟/时区换算，不触碰任何外部状态。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("none",)},
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
        # 并行能力声明：新建共享画布（CanvasOpService 服务端状态）——服务是共享态。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：只读但作用域为共享（读共享画布快照与 version（并发读会互相拿到对方的中间态））⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
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
        # 并行能力声明：改动共享画布内容（服务端状态 + 乐观锁版本号）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：改动共享画布连线（服务端状态 + 乐观锁版本号）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：改动共享画布节点配置（浅合并，服务端状态）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：改动共享画布节点坐标（服务端状态 + 乐观锁版本号）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：改动共享画布结构（连删节点与其连线，服务端状态）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：全量重排共享画布节点（服务端状态 + 乐观锁，与同批任何画布改动作业互踩）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
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
        # 并行能力声明：编译并同步执行整张共享画布（内层跑工作流，副作用面不可预判）。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【运行画布】把画布编译为工作流并同步执行，返回整体状态与每个节点的结果（状态/输出/错误/耗时）。搭完工作流用它验证跑通。【何时不用】长期执行交 spawn_subagent；一次性简单任务直接用对应工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "inputs": {"type": "object", "description": "工作流全局输入（可选，键值对）"},
            },
            "required": ["canvas_id"],
        },
    },
    "canvas_apply_batch": {
        # 并行能力声明：整批画布操作在一个事务里提交——画布是共享对象，与任何画布写互斥。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【批量画布操作·原子提交】多条操作一个事务：任一步失败整批不落盘；成功只出一个新版本。构建批次内优先于逐条 add_node/connect/set_config。支持 add_node/connect/set_config/move_node/remove_node/remove_edge/layout。",
        "parameters": {
            "type": "object",
            "properties": {
                "canvas_id": {"type": "string", "description": "画布 ID"},
                "operations": {
                    "type": "array",
                    "description": "按顺序执行的 op 列表；元素含 op 及该 op 的参数（add_node 可带 id，后续 connect/set_config 可直接引用）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["add_node", "connect", "set_config", "move_node", "remove_node", "remove_edge", "layout"],
                            },
                            "id": {"type": "string", "description": "add_node：可选节点 id，供同批后续 op 引用"},
                            "node_type": {"type": "string"},
                            "config": {"type": "object"},
                            "position": {"type": "object"},
                            "label": {"type": "string"},
                            "source_node": {"type": "string"},
                            "target_node": {"type": "string"},
                            "source_port": {"type": "string"},
                            "target_port": {"type": "string"},
                            "node_id": {"type": "string"},
                            "values": {"type": "object"},
                            "replace": {"type": "boolean"},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "edge_id": {"type": "string"},
                        },
                    },
                },
                "base_version": {"type": "integer", "description": "读取画布时的版本号（乐观锁）"},
            },
            "required": ["canvas_id", "operations"],
        },
    },
    "canvas_list_nodes": {
        # 并行能力声明：只读但作用域为共享（读共享节点库快照）⇒ 推导判为不可并行。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【查询节点库】列出/搜索可用节点类型，返回参数表单（sub_blocks/默认值/必填）、输入输出端口、环境变量需求与来源。添加节点前先查本工具；搜索无果说明节点库缺少该能力，可考虑建自定义节点（draft）或先调 sync_nodes。",
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
    "node_schema": {
        # 并行能力声明：只读节点库，作用域共享（读进程内注册表快照）。
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ("shared",)},
        "description": "【节点完整契约】按精确 type 查询一个节点的参数表单、默认值、必填项、输入/输出端口、环境变量需求与版本。添加节点前用它确认要填哪些参数；找不到时返回候选类型。",
        "parameters": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "精确节点类型，如 builtin:ad-streaming、tool:web_search"},
            },
            "required": ["node_type"],
        },
    },
    "orchestrate_tools": {
        # 并行能力声明：内层按步骤表跑任意工具链（可含写操作）——外层再并行是叠乘且副作用面不可预判。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【多步编排】按显式步骤表一次跑完工具链：层内无依赖并行、有依赖按序，失败跳过下游并点名原因。已知确切顺序且要一次拿到整链成败时用。【何时不用】固化复用用 create_skill；单工具直调；可视化编排用画布。",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "maxItems": 12,
                    "description": "按声明执行的步骤表；同层（互不依赖）并行，声明 depends_on 的步进等前置完成",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string", "description": "被编排的工具名（必须真实存在，如 web_search / file_write / get_datetime）"},
                            "params": {"type": "object", "description": "传给该工具的参数（支持 {step_<idx>.<field>} 占位符引用前序步骤输出字段）"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "本步依赖的前置工具名列表（缺省时按能力图取该工具的前置）",
                            },
                        },
                        "required": ["tool"],
                    },
                    "minItems": 1,
                },
                "goal": {
                    "type": "string",
                    "description": "用一句目标描述让编排器自己规划步骤（与 steps 二选一；两者都给时以 steps 为准）",
                },
            },
        },
    },
    # P2-2 车道D（蜂群只读分析档）：企业源 text2SQL 只读问数，成员可用。
    # 只读强制在连接器层（connectors_sql.assertReadonlySelect），不靠提示词自觉；
    # 总闸 NEUROVA_NL2SQL_ENABLED 关时返回结构化 capability_disabled。
    "enterprise_data_query": {
        # 并行能力声明：SQL 生成走 LLM、执行走连接器只读短连接（每操作开短连接），
        # 不触共享会话/工作区写态；保守不并行（生成是串行 LLM 往返，扇出无收益）。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("none",)},
        "description": "【企业数据只读问数】把自然语言数据问题转成只读 SQL（NL2SQL）"
                       "在企业数据源上执行，只返回查询结果；任何写意图"
                       "（INSERT/UPDATE/DELETE/DROP 等）被连接器只读断言拒绝。【何时用】"
                       "统计/明细/汇总企业数据源里的业务数据，如“最近 10 笔订单”。"
                       "【何时不用】查本 Agent 记忆 memory_search；知识库 knowledge_search；"
                       "会话附件数据集 query_database。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "自然语言数据问题，如“最近 10 笔订单”“每个客户的订单总额”"},
                "source_id": {"type": "string", "description": "企业数据源 id（可选；缺省时本租户目录恰有一个源则自动选定，多源时必须指名）"},
                "max_rows": {"type": "integer", "description": "返回行数上限（默认 50，上界 200）", "default": 50},
            },
            "required": ["question"],
        },
    },
    # ── 设备桥（移动端执行端，2026-11-23 计划卡 B3）：指挥已配对手机执行动作 ──
    # 能力词表/帧型单源见 neurova/tunnel/protocol.py；执行体在 neurova/device_bridge/。
    # 能力协商：仅当设备经 device:hello 宣称了对应能力且总闸
    # NEUROVA_DEVICE_BRIDGE_ENABLED 开启时可执行；无在线设备 / 能力未宣称 /
    # 后台不可靠一律结构化拒绝（device_offline / unsupported_method /
    # background_unavailable），不重试沉默失败。
    "device_open_url": {
        # 并行能力声明：动作落在用户的同一台手机上（设备是批内共享执行体，
        # 并发命令会在端上互相穿插）⇒ 与桌面动作同判，不可并行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】在用户已配对的手机上打开一个 http/https 网址（系统浏览器或默认打开方式）。【何时不用】要在手机上装东西、发消息等写操作不在本工具；设备离线会明确报 device_offline。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要打开的 http/https 地址"},
            },
            "required": ["url"],
        },
    },
    "device_open_app": {
        # 并行能力声明：动作落在用户的同一台手机上（设备是批内共享执行体，
        # 并发命令会在端上互相穿插）⇒ 与桌面动作同判，不可并行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】在用户已配对的手机上打开指定应用（应用名或包名，由端上语义匹配后拉起）。【何时不用】只是打开网页用 device_open_url。",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "应用名或包名，如 weixin / com.tencent.mm"},
            },
            "required": ["app"],
        },
    },
    "device_clipboard_read": {
        # 并行能力声明：只读，但读的是同一台手机的瞬时状态（与 computer_screenshot
        # 同判：语义只读、作用域共享）⇒ 不可并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】读取用户手机剪贴板当前文本（需设备前台；后台会明确报不可用）。注意隐私：只在没有更间接的取数路径时使用。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "device_clipboard_write": {
        # 并行能力声明：动作落在用户的同一台手机上（设备是批内共享执行体，
        # 并发命令会在端上互相穿插）⇒ 与桌面动作同判，不可并行。
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】把一段文本写入用户手机剪贴板（供用户或应用粘贴）。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要写入剪贴板的文本"},
            },
            "required": ["text"],
        },
    },
    "device_app_list": {
        # 并行能力声明：只读，但读的是同一台手机的瞬时状态（与 computer_screenshot
        # 同判：语义只读、作用域共享）⇒ 不可并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】列出用户手机上可供交互的应用清单（名称/包名），用于后续 device_open_app 选目标。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "device_env": {
        # 并行能力声明：只读，但读的是同一台手机的瞬时状态（与 computer_screenshot
        # 同判：语义只读、作用域共享）⇒ 不可并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】读取用户手机的环境快照：电量/充电态、屏幕尺寸、系统版本、语言区域、网络状态等。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "device_notification_read": {
        # 并行能力声明：只读，但读的是同一台手机的瞬时状态（与 computer_screenshot
        # 同判：语义只读、作用域共享）⇒ 不可并行。
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【设备桥】读取用户手机最近的通知事件（按端上授权范围；默认只含应用名/标题/时间）。用于“帮我看看刚才有什么通知”类请求。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数上限（默认 10，上界 50）", "default": 10},
            },
            "required": [],
        },
    },
    # T1 工具运行时自发现目录（reference_af 拆解卡）：工具面大（146+），长尾工具
    # 靠猜名不可行——agent 先查目录再调用。数据单源=tools/catalog 投影层（builtin
    # 声明位推导），本处只声明面。只读、并发安全、无写作用域。
    "tool_catalog_search": {
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ["none"]},
        "description": "【工具目录】按关键字/标记检索当前可用的内置工具清单（名称/描述/只读性/使用范围/参数个数）。选工具前先查目录，避免猜工具名。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "关键字（大小写不敏感，匹配工具名与描述；空=列全部）"},
                "tag": {"type": "string", "description": "过滤标记：read_only / external_write / main_only"},
                "limit": {"type": "integer", "description": "最多返回条数（默认 20，上限 100）"},
            },
            "required": [],
        },
    },
    "tool_doc": {
        "capability": {"readOnly": True, "concurrentSafe": True, "writeScopes": ["none"]},
        "description": "【工具文档】返回单个内置工具的全量档案：描述、参数 JSON Schema、只读性、外部写判定、使用范围（all/main_only）。配合 tool_catalog_search 使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "工具注册名（来自 tool_catalog_search 的 name）"},
            },
            "required": ["tool_name"],
        },
    },
    # T2 语义指向（reference_af 拆解卡）：自然语言目标 → 屏幕坐标。UIA 树优先，
    # VLM 档灰度（NEUROVA_CU_VLM_POINTING，默认关）。瞬时快照族（每次取新截图）。
    "computer_point_at": {
        "capability": {"readOnly": True, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【语义指向】把自然语言目标描述解析成屏幕坐标（UIA 控件树优先；未命中且开启 VLM 档时用视觉模型指向）。拿到坐标后用 computer_click 点击。【何时不用】能用 computer_dom_snapshot 拿到控件树时优先走 UIA。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_description": {"type": "string", "description": "目标的一句话描述（如：右上角的设置齿轮图标）"},
                "window_title": {"type": "string", "description": "可选。UIA 档的目标窗口标题（缺省前台窗口）"},
            },
            "required": ["target_description"],
        },
    },
    # T4 结构化直写（reference_af 拆解卡）：xlsx/csv 文件级直写单元格+写后回读
    # 校验，绕开逐格 GUI 点击。写副作用（工作区共享态），不可重现族。
    "computer_doc_edit": {
        "capability": {"readOnly": False, "concurrentSafe": False, "writeScopes": ("shared",)},
        "description": "【结构化直写】对工作区内的 xlsx/xlsm/csv 文件按单元格引用（如 A1）直接批量写入值（数值/公式/文本自动推断），写后逐格回读校验并返回回读明细。绕开逐格 GUI 点击，适合表格批量修改。【何时不用】目标文件不在工作区时不可用；纯文本文件用 file_edit。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件路径（相对工作区或绝对路径，须在工作区内）"},
                "cell_values": {"type": "object", "description": "单元格写入表，如 {\"A1\": \"品名\", \"B2\": \"42\", \"C3\": \"=SUM(A1:B2)\"}"},
                "sheet_name": {"type": "string", "description": "可选。xlsx 工作表名（缺省活动表）"},
            },
            "required": ["file_path", "cell_values"],
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# U7 工具运行元数据（runtime 声明位）
# ═══════════════════════════════════════════════════════════════
# 语义：schema 条目可携带与 description/parameters 平级的 `runtime` 键，声明
# **执行期契约**：default_timeout_ms（建议超时）、timeout_ms_clamp（钳制域，
# 单源常量 RUNTIME_TIMEOUT_CLAMP_MS）、serializable（结果可稳定序列化）、
# ordered_group（同组调用须保序）、idempotent（重复执行是否安全，U11 重试
# 纪律消费）。
# 声明不进 to_openai_format()（模型可见面零变化）；执行体（ToolExecutor）
# 读取并**单源钳制**——声明越界时以执行体钳制为准，不另立第二份口径。
_RUNTIME_KEY = "runtime"

#: 超时钳制域（毫秒）：低于下界取下界、高于上界取上界（执行体单源钳制）。
RUNTIME_TIMEOUT_CLAMP_MS = (1000, 800000)

#: U7 首批声明（ssh / exec / file 写 / recall 族）——挂在各工具 schema 条目上。
#: default_timeout_ms 与 agent/tool_coordinator.TOOL_TIMEOUTS_S 的既有显式值
#: 对齐（表内无该工具时取其默认 60s），不新造第二套时长口径。
_RUNTIME_FIRST_BATCH: Dict[str, Dict[str, Any]] = {
    # ssh 族
    "computer_ssh_exec": {"default_timeout_ms": 180000, "serializable": True, "ordered_group": False, "idempotent": False},
    # exec 族（execute_code 是 run_code 的分派表别名，无独立 schema 条目，
    # 声明随 run_code 走）
    "exec_command": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": False, "idempotent": False},
    "computer_shell": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": False, "idempotent": False},
    "run_code": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": False, "idempotent": False},
    # file 写族（共享工作区变异，组内保序；overwrite 语义 → 幂等）
    "file_write": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": True, "idempotent": True},
    "file_create": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": True, "idempotent": True},
    "file_edit": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": True, "idempotent": False},
    "file_delete": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": True, "idempotent": True},
    # recall 族（只读召回）
    "recall_history": {"default_timeout_ms": 10000, "serializable": True, "ordered_group": False, "idempotent": True},
    "recall_context_span": {"default_timeout_ms": 10000, "serializable": True, "ordered_group": False, "idempotent": True},
    "recall_query": {"default_timeout_ms": 60000, "serializable": True, "ordered_group": False, "idempotent": True},
    "memory_search": {"default_timeout_ms": 10000, "serializable": True, "ordered_group": False, "idempotent": True},
}

for _toolName, _runtime in _RUNTIME_FIRST_BATCH.items():
    if _toolName in _BUILTIN_SCHEMAS and isinstance(_BUILTIN_SCHEMAS[_toolName], dict):
        _BUILTIN_SCHEMAS[_toolName][_RUNTIME_KEY] = {
            "default_timeout_ms": _runtime["default_timeout_ms"],
            "timeout_ms_clamp": list(RUNTIME_TIMEOUT_CLAMP_MS),
            "serializable": _runtime["serializable"],
            "ordered_group": _runtime["ordered_group"],
            "idempotent": _runtime.get("idempotent", False),
        }
del _toolName, _runtime


def get_builtin_tool_runtime(tool_name: str) -> Optional[Dict[str, Any]]:
    """读取工具的 runtime 运行元数据；未声明 / 非内置返回 None。

    返回**浅拷贝**——调用方改写不污染事实源。
    """
    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return None
    runtime = schema.get(_RUNTIME_KEY)
    return dict(runtime) if isinstance(runtime, dict) else None


def listRuntimeDeclaredTools() -> List[str]:
    """枚举声明了 runtime 的内置工具名（一致性判据的取数口）。"""
    return [
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and isinstance(schema.get(_RUNTIME_KEY), dict)
    ]


def clampRuntimeTimeoutMs(value: Any) -> int:
    """把声明超时钳进 RUNTIME_TIMEOUT_CLAMP_MS（执行体单源钳制）。

    非数值输入抛 ValueError——调用方（执行体解析器）据此回落既有超时表，
    不替臆造值编一个"看起来合法"的数。
    """
    lo, hi = RUNTIME_TIMEOUT_CLAMP_MS
    converted = int(value)
    return max(lo, min(hi, converted))


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
# 工具声明位
# schema 可携带与 description/parameters 平级的 sandbox_required 布尔键，
# 语义 = "该工具必须在沙箱隔离下执行"。
# 声明位不进入 to_openai_format()（模型可见面零变化），仅供治理与
# 展示面消费；NEUROVA_TOOL_SANDBOX_ENFORCE=1 时治理层强制路由。
# ═══════════════════════════════════════════════════════════════

_SANDBOX_REQUIRED_KEY = "sandbox_required"

# P1-#6 全量打标单源（用户拍板 2026-09-13）：此集合列"结果不可重现"的内置
# 工具（突变/副作用/瞬时快照类）——重放不可能或重放制造新副作用；集合之外
# 一律 True。误标 True 的后果=溢出文件 30 天被清且重放失败丢原文；误标
# False 的后果=会话文件偏大。方向上取"数据保真优先"，故名单从严。
#
# 与 `capability.readOnly`（并行轴）**不合并**：截图/快照是反例——语义只读，
# 却因"重放不回当时画面"必须留在此名单里。两轴各答一个事实，合并会造出一个
# 语义混淆的上帝字段。
#
# 但**单向蕴含**必须成立：声明了写作用域（`readOnly=False`）的工具，结果不可能
# "重放不制造新变更"。反向不成立（只读也可能不可重放），故只钉这一个方向。
#
# **同一只读族内还有两条子语义，各自取数、不得并成一个名单口径**：
#   瞬时快照（截图 / SOM / DOM 快照）― 冻结"当时"的画面与结构，重放取不回那一帧；
#   会话游标（browser_read / browser_dom_read）― 推进同一个页面的分片续读游标
#   （`session_id` 跨调用共享），同参数重放取回同一段文本，属可重放。
# 判据：tests/unit/tools/test_reproducible_flag.py 的
# TestWriteScopedToolsAreNeverReproducible 三面复算（正蕴含 / 反例仍在 / 消费面池），
# 与 tests/unit/tools/test_cross_axis_declarations.py 的
# TestCursorToolsAreADifferentAxis（快照族与游标族在重放轴上必须给出**不同**读数）。
_NON_REPRODUCIBLE_TOOLS = frozenset({
    # P3-14：受限脚本化工作流——重放会重跑脚本里的全部工具副作用，不可重现。
    "run_scripted_workflow",
    # B1：模型自决折叠改写当前会话视图（重放会产出第二次折叠回执），不可重现。
    "context_compress",
    # 任意代码/命令：输出依赖外部状态且可能已产生副作用
    "run_code", "computer_shell", "computer_ssh_exec",
    # git 含写子命令（commit/push/checkout），tool 粒度从严
    "git",
    # 文件/画布/技能写操作：结果即回执，重放制造新变更
    "file_write", "file_create", "file_edit", "file_delete",
    "create_skill", "planning",
    # 调度任务是写共享调度面：重放会建出第二份定时任务
    "schedule_task",
    # 提问会写构建会话交互并暂停当前步，重放会重复打扰用户
    "ask_user",
    # 同步会改进程内共享注册表，重放会重复注册
    "sync_nodes",
    "custom_node_create", "custom_node_update", "custom_node_activate", "custom_node_delete",
    # 工作流定义写操作：重放会再落一版/再回滚一次/重复发布
    "workflow_definition_get", "workflow_definition_update", "workflow_definition_duplicate",
    "workflow_rollback", "workflow_publish", "workflow_execute",
    # 自愈会执行草稿并可能提交目标，重放制造新版本/新画布状态
    "workflow_repair",
    # 批次补偿会回滚多个 surface，重放制造新的版本/删除
    "build_batch_compensate",
    # 产物件：落产物目录并注册 artifact（重放登记出第二份产物与下载口）
    "write_pdf",
    "canvas_add_node", "canvas_connect", "canvas_create", "canvas_remove_node",
    "canvas_move_node", "canvas_set_config", "canvas_layout", "canvas_run",
    "canvas_apply_batch",
    # 桌面/浏览器操作：突变或瞬时快照（截图重放不回当时画面）
    "computer_click", "computer_click_element", "computer_click_mark",
    "computer_type", "computer_scroll", "computer_set_value",
    # 桌面写动作（AD 批补齐）：拖拽/按键/粘贴改共享桌面状态，重放制造新副作用，
    # 与 computer_click/computer_type 同面同判
    "computer_drag", "computer_key", "computer_paste",
    "computer_doc_edit",
    "computer_screenshot", "computer_som_snapshot", "computer_dom_snapshot",
    "computer_point_at",
    "browser_click", "browser_click_role", "browser_fill_role",
    # ref 寻址族与 role 族同轴：都是对同一页面的突变，重放制造新变更
    "browser_click_ref", "browser_fill_ref",
    "browser_type", "browser_navigate", "browser_screenshot", "browser_dom_snapshot",
    # tab 管理（开/切/关改共享 tab 表与活动指针）与页面脚本（任意 JS 可写页面态）：
    # 重放会制造新 tab/新页面状态；tab_list 只读不入名单
    "browser_tab_open", "browser_tab_switch", "browser_tab_close", "browser_eval",
    # 页面级动作：导航改会话历史、滚动是相对量（重放继续滚）、按键可重复触发页面行为；
    # wait 是同参数同效果的纯等待，属可重现，不入名单
    "browser_back", "browser_forward", "browser_reload", "browser_scroll", "browser_press",
    # 元素交互扩展：select/check 与 fill_role 同轴（改写页面表单状态，重放可能选错/改状态）；
    # hover 悬停同参数同效果（无 DOM 突变），不入名单
    "browser_select", "browser_check",
    # 页面状态面：cookies/storage 是状态写（重放制造新状态）；console 是瞬时缓冲读数
    # （重放时缓冲可能已追加，与 screenshot 同属"只读也不可重放"反例族）
    "browser_cookies", "browser_storage", "browser_console",
    # 采集与扩展：download/pdf 落盘产物（重放登记第二份）；drag/upload 是页面写
    "browser_download", "browser_pdf", "browser_drag", "browser_upload",
    # 环境自举：装内核是环境变更，重放会再改环境
    "browser_install",
    # 会话式 shell：进程输出不可重放（重跑时系统状态已变）
    "exec_command", "write_stdin",
    # 子代理派生：spawn 有副作用
    "spawn_subagent",
    # 固定团队派活（S10）：按名册多路派生，重放制造新一整批子任务
    "dispatch_team",
    # 团队沉淀提议（S10）：重放会重复建审批单/重复写团队
    "propose_team",
    # 项目发起/房间发言（S13）：重放会建出第二个项目/重复投递房间消息
    "project_create",
    "room_post",
    # 子代理续跑：等价一次新派生（member 会话续写 + 邮箱投递），重放制造新运行
    "continue_subagent",
    # 跨 agent 审批链（P3-1）：建单/裁决都改共享审批状态，重放制造第二张审批单
    "request_approval", "decide_subagent_approval",
    # 叫停（H 批补差）：改共享运行状态并终止成员任务，重放制造第二次取消
    "cancel_subagent",
    # 会话回滚（C2 接线）：重放会再生成一份 pre-restore 快照并再次改写 member 会话
    "rollback_subagent",
    # 多步编排：内层步进可能含任意写操作，重放制造新变更
    "orchestrate_tools",
    # 设备桥（2026-11-23 计划 B3）：动作落用户真机——写操作制造设备侧变更，
    # 读操作是外部状态瞬时快照（与 computer_screenshot 同判），重放均不可复现
    "device_open_url", "device_open_app", "device_clipboard_read",
    "device_clipboard_write", "device_app_list", "device_env",
    "device_notification_read",
})

# 成员工具面剔除集（主 agent 专属工具）——**单一事实源**（教义第 6 条）。
# 消费方两处读同一份声明：swarm.computeSubagentToolAllowlist（白名单派生期剔除）
# 与 ToolExecutor._execute_single_tool 成员门（执行期结构化拒绝，纵深防御）。
# 语义分组：
# - 递归派生/续跑：子代理不得再拉起执行链（孙代理/兄弟续跑）；
# - 审批裁决（P3-1）：子代理不得裁决自己发起的审批单（自己批自己=审批链失效）；
# - 叫停（H 批补差）：子代理不得叫停自己/兄弟的运行；
# - 会话回滚（C2 接线）：子代理不得回滚自己/兄弟的 member 会话；
# - 团队编排三工具（S10）：成员自行派团/立队等于绕过发起者的治理面；
# - 项目/群聊四工具（S13）：成员建项目/房间发言须过主 agent 的治理面。
MAIN_AGENT_ONLY_TOOLS = frozenset({
    "spawn_subagent", "continue_subagent", "decide_subagent_approval",
    "cancel_subagent", "rollback_subagent", "list_teams", "dispatch_team",
    "propose_team", "project_create", "project_list", "project_detail",
    "room_post",
})


def get_registered_tool_names() -> List[str]:
    """内置工具注册名清单（**单源**读侧）。

    字母表类校验（合成器序列、附件提示文案）一律读这一处，不得各自持有
    一份名字表——第二份表就是幻名的温床（教义第 6 条）。
    """
    return sorted(_BUILTIN_SCHEMAS)


def is_builtin_tool_reproducible(tool_name: str) -> bool:
    """内置工具可重现性查询（单源 _NON_REPRODUCIBLE_TOOLS）；未知工具 False。"""
    if tool_name not in _BUILTIN_SCHEMAS:
        return False
    return tool_name not in _NON_REPRODUCIBLE_TOOLS


# ── 动态描述工厂（P2-2 车道D）────────────────────────────────────────────────
# 工具描述需要在暴露给模型时附加运行态上下文（如本租户可见企业数据源的
# schema 摘要）。工厂在 BuiltinTool.to_openai_format() 序列化时求值；描述
# 静态基线仍是 _BUILTIN_SCHEMAS 的唯一一份文案（不因动态化分裂出第二事实源）。
_DESCRIPTION_FACTORIES: Dict[str, Callable[[], str]] = {}


def register_description_factory(tool_name: str, factory: Callable[[], str]) -> None:
    """登记工具描述工厂（每次序列化求值；同名校覆盖）。"""
    _DESCRIPTION_FACTORIES[str(tool_name)] = factory


def _enterpriseDataQueryDescription() -> str:
    """enterprise_data_query 描述 = 静态基线 + 本租户可见数据源 schema 摘要。

    schema 摘要读 schema 目录（连接器 describeSchema 的既有落地面，P1-1 摄取），
    不新造元数据；目录不可用/为空时回退基线（fail-soft，不炸工具暴露面）。
    """
    base = str(_BUILTIN_SCHEMAS.get("enterprise_data_query", {}).get("description") or "")
    try:
        from neurova.auth.user_group_model import currentUserTenantId
        from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
        from neurova.knowledge.foundation import get_knowledge_fact_store

        catalog = SchemaCatalogStore(get_knowledge_fact_store())
        tables = catalog.listTables(currentUserTenantId(), limit=100)
        if not tables:
            return base + "\n（当前租户目录暂无已摄取数据源——先完成企业源 schema 目录摄取）"
        bySource: Dict[str, List[str]] = {}
        for row in tables:
            bySource.setdefault(str(row.get("source_id") or ""), []).append(
                "%s(%s列)" % (row.get("table_name"), row.get("column_count")))
        lines = [base, "当前可见数据源 schema 摘要（只读，来自 schema 目录）："]
        for sourceId in sorted(bySource)[:5]:
            lines.append("- source_id=%s 表：%s"
                         % (sourceId, ", ".join(sorted(bySource[sourceId])[:12])))
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 - 目录读面故障不炸工具暴露面，回退基线
        return base


register_description_factory("enterprise_data_query", _enterpriseDataQueryDescription)

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


# ═══════════════════════════════════════════════════════════════
# 工具并行能力声明位（事实源：每个工具自己的 schema）
# ═══════════════════════════════════════════════════════════════
# 语义：schema 可携带与 description/parameters 平级的 `capability` 键，声明该工具
# 的只读性 / 可并发性 / 写作用域（形状与推导在 `core/tool_capability.py`）。
# 未声明 = 最保守（不可并发、不算只读），与改造前的现网行为逐条一致。
# 声明位不进入 to_openai_format()（模型可见面零变化）。
#
# **为什么成员落在这里、而不是集中一份大名单**：能力是"这个工具自身"的属性，
# 定义该工具的 schema 就是它的自然归属。集中一份名单正是被替换掉的那种形态
# （`AGENTS.md` 修复教义第 6 条：单一事实源指"一个事实一处定义"，不是"所有
# 名单塞一个文件"）。
_CAPABILITY_KEY = "capability"

#: 壳方言声明键：工具的**命令文本**是否交给真 shell 解析。
#: 它答的是一件事：`|` / `;` / `&&` 在这份文本里是命令连接符还是普通字符。
#: 判据的**成员**落在这里（各工具声明处），**规则**在
#: `security/governance.py` 的分段审批面；两侧各持一份名单就会像 `exec_command`
#: 那样漂移（它跑真 shell 却不在分段面上，白名单前缀匹配放行了搭便车注入）。
_SHELL_DIALECT_KEY = "shell_dialect"


def get_builtin_tool_capability(tool_name: str):
    """读取内置工具的并行能力声明；未声明/形态非法/非内置一律返回 None。

    本函数只做"取那个声明位"，**解析**交给 `core/tool_capability.parseToolCapability`
    ——内置侧与 MCP 侧共用同一处口径，两处各写一遍就是给同一种输入两个事实。
    """
    from neurova.core.tool_capability import parseToolCapability

    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return None
    return parseToolCapability(schema.get(_CAPABILITY_KEY))


def getBuiltinToolShellDialect(tool_name: str) -> Optional[bool]:
    """读取工具的壳方言声明。

    Returns:
        True: 该工具的命令文本交给真 shell 执行，须走分段审批面
        None: 未声明（代码本体/非 shell 语义），调用方不得据此裁决
    """
    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return None
    return True if schema.get(_SHELL_DIALECT_KEY) is True else None


def listShellDialectTools() -> List[str]:
    """枚举声明了壳方言的内置工具名（分段审批面的**内置取数口**）。"""
    return [
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and schema.get(_SHELL_DIALECT_KEY) is True
    ]


def list_declared_capabilities() -> List[str]:
    """枚举**声明了**并行能力的内置工具名（装配期一致性判据的取数口）。"""
    return [
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and isinstance(schema.get(_CAPABILITY_KEY), dict)
    ]


# ═══════════════════════════════════════════════════════════════
# 执行语义声明位（两枚布尔键，Issue #271 M5 尾巴）
# ═══════════════════════════════════════════════════════════════
# 语义：schema 可携带与 description/parameters 平级的两个布尔键，各自回答
# **一个**事实，供 `computer_use/runtime_policy.py` 的桌面运行档按声明投影成员：
#
#   arbitrary_command  ― 该工具会把调用者给的文本当命令执行（任意命令执行语义）
#   remote_execution   ― 该工具在**远端**机器上执行动作（不是本机）
#   interactive_desktop ― 该动作会改变**共享桌面**的画面（故动作后补拍有意义）
#
# **为什么必须与 `capability` / `sandbox_required` 分开**（三条轴，各自答一个事实）：
#   `capability.readOnly`      问"两个调用同时跑会不会互踩"（并行轴）
#   `sandbox_required`         问"要不要真隔离执行"（P2-15 沙箱轴）
#   `arbitrary_command`        问"会不会执行任意命令"（桌面高危档）
#   `remote_execution`         问"动作落在本机还是远端"（远端档：进沙箱对它无意义）
#   `interactive_desktop`      问"动作会不会改变共享桌面画面"（动作后补拍面）
# 前两条与后两条当前在 `computer_*` 上成员恰好重合，但那是**巧合**——按教义第 6 条
# 不得把巧合当同源，也不得合并成上帝字段（合并后"去掉沙箱要求"会连带降级高危档）。
# `interactive_desktop` 与前几条的分界更直白：`computer_shell` 有任意命令语义，
# 但它改的是机器状态而不是桌面画面（跑完 shell 去补拍一张本机截图毫无意义）。
# 由 tests/unit/computer_use/{test_desktop_policy_projection,test_action_refresh_declaration}.py
# 把"不合并"钉成活判据。
#
# 声明位不进入 to_openai_format()（模型可见面零变化），仅供裁决面消费。
_ARBITRARY_COMMAND_KEY = "arbitrary_command"
_REMOTE_EXECUTION_KEY = "remote_execution"
_INTERACTIVE_DESKTOP_KEY = "interactive_desktop"

#: 三枚已登记的执行语义声明键（**唯一**登记处；取数口按本表校验未知键）。
_DECLARED_FLAG_KEYS = (
    _ARBITRARY_COMMAND_KEY,
    _REMOTE_EXECUTION_KEY,
    _INTERACTIVE_DESKTOP_KEY,
)


def get_builtin_tool_flags(tool_name: str) -> Dict[str, bool]:
    """读取工具的两枚执行语义声明。

    Returns:
        只含**显式置 True** 的键（未声明 = 缺省 = 不参与裁决，与改造前等价）。
    """
    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return {}
    return {
        key: True for key in _DECLARED_FLAG_KEYS if schema.get(key) is True
    }


def get_builtin_tool_result_budget(tool_name: str) -> Optional[int]:
    """读取工具的逐工具结果预算声明（P1-1）；未声明/非法返回 None（用全局默认）。

    声明位不进入 to_openai_format()（模型可见面零变化），仅供结果出流咽喉
    （tool_executor → maybe_output_ref）消费：结果序列化超过该值 → 落盘
    tool_outputs/ 引用 + 预览。非法声明（负数/非整数/布尔）按未声明处理，
    不炸取数口。
    """
    schema = _BUILTIN_SCHEMAS.get(tool_name)
    if not isinstance(schema, dict):
        return None
    value = schema.get("result_budget_chars")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def listBuiltinToolsWithFlag(flagKey: str) -> List[str]:
    """枚举显式声明了 `flagKey` 的内置工具名（裁决面的**内置取数口**）。

    只为两枚已登记的键取数：未知键返回空列表，不把拼错的键静默当成"无人声明"
    （那样裁决面会悄悄退回空集，而不是响亮点名）。
    """
    if flagKey not in _DECLARED_FLAG_KEYS:
        raise KeyError(f"未登记的执行语义声明键：{flagKey}")
    return [
        name
        for name, schema in _BUILTIN_SCHEMAS.items()
        if isinstance(schema, dict) and schema.get(flagKey) is True
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
    # P1-#6（§5.6 定稿）：结果可重现性——True=可用相同参数重放取回原文，
    # 溢出可外移工作区文件；False/None=当时的原文即唯一记录，禁止外移。
    # 不进入 to_openai_format()（模型可见面零变化）；外部注册未声明按
    # False 保守处理（register_tool fail-closed，数据保真优先）。
    reproducible: Optional[bool] = None
    # P2-2 车道D：动态描述工厂（每次序列化求值，如附数据源 schema 摘要）；
    # None=纯静态描述。
    description_factory: Optional[Callable[[], str]] = None

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式。

        B3：统一注入 taskNameActive/taskNameComplete 可选参数（执行摘要，
        直连时间轴 UI）；MCP/Skill 外来 schema 不经此处，自然不受影响。
        注入只落在出口副本上——就地 setdefault 会把展示参数写进
        `_BUILTIN_SCHEMAS` 这个事实源，之后按参数面判定的消费方读到的都是脏值。
        """
        params = self.parameters
        try:
            if isinstance(params, dict) and params.get("type") == "object":
                props = dict(params.get("properties") or {})
                for _pn, _pdef in _TASK_NAME_PARAM_DEFS.items():
                    props.setdefault(_pn, dict(_pdef))
                params = {**params, "properties": props}
        except Exception:  # noqa: BLE001 - 注入失败不阻断工具暴露
            pass
        description = self.description
        if self.description_factory is not None:
            try:
                description = self.description_factory() or self.description
            except Exception:  # noqa: BLE001 - 工厂故障回退静态基线
                description = self.description
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
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
                reproducible=is_builtin_tool_reproducible(tool_name),
                description_factory=_DESCRIPTION_FACTORIES.get(tool_name),
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
        """注册新工具。

        P1-#6 fail-closed：外部/动态注册未声明 reproducible → 保守判 False
        （不可重放即数据保真优先，大结果不外移工作区文件）；显式声明值保留。
        """
        if tool.reproducible is None:
            tool.reproducible = False
        self._tools[tool.name] = tool

    def is_tool_reproducible(self, tool_name: str) -> bool:
        """查询工具结果可重现性（溢出策略消费点）。未知工具一律 False。"""
        tool = self._tools.get(tool_name)
        if tool is not None:
            return bool(tool.reproducible)
        return is_builtin_tool_reproducible(tool_name)

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
