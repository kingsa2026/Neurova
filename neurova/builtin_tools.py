"""
BuiltinTools — 内置工具注册器

集中管理内置工具的参数 schema 和注册逻辑。
被以下模块使用：
- agent_core.py          → BuiltinToolRegistry, get_builtin_tool_params
- agent/tool_executor.py → get_builtin_tool_params
- context/orchestrator.py → get_builtin_tool_params
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 内置工具参数 Schema（单一事实源）
# ═══════════════════════════════════════════════════════════════

_BUILTIN_SCHEMAS: Dict[str, Dict] = {
    "memory_search": {
        "description": "搜索记忆库中的相关记忆",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
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