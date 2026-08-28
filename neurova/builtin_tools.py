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
        "description": "【浏览器导航】在内置自动化浏览器中打开指定 URL。适合访问网页、查看在线内容、登录网站等。打开后可用 browser_extract_text 提取正文、browser_click/browser_type 交互、browser_screenshot 截图。",
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
        "description": "【实时网络搜索】通过搜索引擎查询互联网上的实时信息（新闻、股价、百科、技术文档等）。当用户需要 memory_search 无法提供的实时或外部信息时调用此工具。返回搜索结果摘要文本。",
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
        "description": "【蜂群派生子Agent】将一个子任务派交给另一个 Agent 执行（蜂群编排）。当任务可分解为多个相对独立的子任务（如：多主题调研、多文件分析、多视角评审）时，对每个子任务各调用一次本工具即可并行蜂群执行。每个子 Agent 拥有独立的人设/记忆/模型配置。前台模式等待完成并返回最终报告；background=true 立即返回 subagent_id（用 subagent_status 查询结果）。子 Agent 的执行过程会实时显示在聊天界面的子 Agent 小窗中。可先用 list_agents 查看可用的子 Agent。",
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
