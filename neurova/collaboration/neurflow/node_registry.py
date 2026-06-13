"""
Neurflow 节点注册表 — 垂直切片 3
单例模式，自动发现 + 手动注册，分类索引，模糊搜索
"""

import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from .models import NodeDefinition

# 单例实例
_node_registry_instance: Optional["NodeRegistry"] = None
_registry_lock = threading.RLock()


def get_node_registry() -> "NodeRegistry":
    """获取节点注册表单例"""
    global _node_registry_instance
    if _node_registry_instance is None:
        with _registry_lock:
            if _node_registry_instance is None:
                _node_registry_instance = NodeRegistry()
    return _node_registry_instance


def reset_node_registry() -> None:
    """重置节点注册表单例（用于测试）"""
    global _node_registry_instance
    with _registry_lock:
        if _node_registry_instance is not None:
            _node_registry_instance.clear()
        _node_registry_instance = None


class NodeRegistry:
    """
    节点注册表 — 单例模式

    核心功能：
    1. 节点注册/注销（线程安全）
    2. 多维度索引（分类、来源）
    3. 模糊搜索
    4. 执行器管理
    5. 自动发现（延迟触发）
    """

    def __init__(self):
        """初始化注册表"""
        self._lock = threading.RLock()
        self._nodes: Dict[str, NodeDefinition] = {}
        self._categories: Dict[str, List[str]] = defaultdict(list)
        self._sources: Dict[str, List[str]] = defaultdict(list)
        self._executors: Dict[str, Callable] = {}
        self._builtin_registered = False

    def register(self, definition: NodeDefinition, executor: Optional[Callable] = None) -> None:
        """
        注册节点定义

        Args:
            definition: 节点定义对象
            executor: 可选的执行器函数

        Raises:
            ValueError: 当节点类型为空或 None 时
        """
        if not definition.type:
            raise ValueError("节点类型不能为空")

        if definition.type is None:
            raise ValueError("节点类型不能为 None")

        with self._lock:
            # 如果已存在，先移除旧索引
            if definition.type in self._nodes:
                old_def = self._nodes[definition.type]
                self._remove_from_indexes(old_def)

            # 注册节点
            self._nodes[definition.type] = definition

            # 更新索引
            self._add_to_indexes(definition)

            # 注册执行器
            if executor is not None:
                self._executors[definition.type] = executor

    def unregister(self, node_type: str) -> bool:
        """
        注销节点定义

        Args:
            node_type: 节点类型

        Returns:
            bool: 注销是否成功
        """
        with self._lock:
            if node_type not in self._nodes:
                return False

            definition = self._nodes[node_type]

            # 移除索引
            self._remove_from_indexes(definition)

            # 移除节点
            del self._nodes[node_type]

            # 移除执行器
            if node_type in self._executors:
                del self._executors[node_type]

            return True

    def get(self, node_type: str) -> Optional[NodeDefinition]:
        """
        获取节点定义

        Args:
            node_type: 节点类型

        Returns:
            NodeDefinition 或 None
        """
        with self._lock:
            return self._nodes.get(node_type)

    def list_all(self) -> List[NodeDefinition]:
        """
        列出所有节点定义

        Returns:
            节点定义列表
        """
        with self._lock:
            return list(self._nodes.values())

    def list_by_category(self, category: str) -> List[NodeDefinition]:
        """
        按分类列出节点定义

        Args:
            category: 节点分类

        Returns:
            节点定义列表
        """
        with self._lock:
            node_types = self._categories.get(category, [])
            return [self._nodes[t] for t in node_types if t in self._nodes]

    def list_by_source(self, source: str) -> List[NodeDefinition]:
        """
        按来源列出节点定义

        Args:
            source: 节点来源

        Returns:
            节点定义列表
        """
        with self._lock:
            node_types = self._sources.get(source, [])
            return [self._nodes[t] for t in node_types if t in self._nodes]

    def search(self, query: str) -> List[NodeDefinition]:
        """
        模糊搜索节点定义

        Args:
            query: 搜索关键词

        Returns:
            匹配的节点定义列表
        """
        with self._lock:
            if not query:
                return []

            query_lower = query.lower()
            results = []

            for definition in self._nodes.values():
                # 搜索 label、description、tags
                searchable = [
                    definition.label.lower(),
                    definition.description.lower(),
                    *[tag.lower() for tag in definition.tags],
                ]

                if any(query_lower in text for text in searchable):
                    results.append(definition)

            return results

    def get_executor(self, node_type: str) -> Optional[Callable]:
        """
        获取节点执行器

        Args:
            node_type: 节点类型

        Returns:
            执行器函数或 None
        """
        with self._lock:
            return self._executors.get(node_type)

    def get_summary(self) -> Dict[str, Any]:
        """
        获取注册表统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            by_category = {}
            by_source = {}

            for definition in self._nodes.values():
                # 统计分类
                category = definition.category
                by_category[category] = by_category.get(category, 0) + 1

                # 统计来源
                source = definition.source
                by_source[source] = by_source.get(source, 0) + 1

            return {"total": len(self._nodes), "by_category": by_category, "by_source": by_source}

    def clear(self) -> None:
        """清空注册表"""
        with self._lock:
            self._nodes.clear()
            self._categories.clear()
            self._sources.clear()
            self._executors.clear()
            self._builtin_registered = False

    # ==================== 自动发现 ====================

    def ensure_builtin(self) -> None:
        """
        确保内置节点已注册（幂等）
        """
        with self._lock:
            if self._builtin_registered:
                return

            self._register_builtin_nodes()
            self._builtin_registered = True

    def sync_tools(self) -> int:
        """
        同步工具节点

        Returns:
            同步的工具数量
        """
        return _sync_tools_from_engine(self)

    def sync_skills(self) -> int:
        """
        同步技能节点

        Returns:
            同步的技能数量
        """
        return _sync_skills_from_registry(self)

    def sync_mcp(self) -> int:
        """
        同步 MCP 工具节点

        Returns:
            同步的 MCP 工具数量
        """
        return _sync_mcp_tools(self)

    def sync_all(self) -> Dict[str, int]:
        """
        同步所有节点

        Returns:
            同步结果字典
        """
        return {"tools": self.sync_tools(), "skills": self.sync_skills(), "mcp": self.sync_mcp()}

    # ==================== 内部方法 ====================

    def _add_to_indexes(self, definition: NodeDefinition) -> None:
        """添加到索引"""
        # 分类索引
        if definition.category not in self._categories:
            self._categories[definition.category] = []
        if definition.type not in self._categories[definition.category]:
            self._categories[definition.category].append(definition.type)

        # 来源索引
        if definition.source not in self._sources:
            self._sources[definition.source] = []
        if definition.type not in self._sources[definition.source]:
            self._sources[definition.source].append(definition.type)

    def _remove_from_indexes(self, definition: NodeDefinition) -> None:
        """从索引移除"""
        # 分类索引
        if definition.category in self._categories:
            if definition.type in self._categories[definition.category]:
                self._categories[definition.category].remove(definition.type)
            if not self._categories[definition.category]:
                del self._categories[definition.category]

        # 来源索引
        if definition.source in self._sources:
            if definition.type in self._sources[definition.source]:
                self._sources[definition.source].remove(definition.type)
            if not self._sources[definition.source]:
                del self._sources[definition.source]

    def _register_builtin_nodes(self) -> None:
        """注册内置节点定义和执行器"""
        try:
            from .builtin import BUILTIN_NODES, get_builtin_executors

            executors = get_builtin_executors()

            for node_dict in BUILTIN_NODES:
                node_type = node_dict["type"]
                definition = NodeDefinition(
                    type=node_type,
                    label=node_dict["label"],
                    icon=node_dict["icon"],
                    category=node_dict["category"],
                    description=node_dict["description"],
                    sub_blocks=node_dict.get("sub_blocks", []),
                    inputs=node_dict.get("inputs", []),
                    outputs=node_dict.get("outputs", []),
                    source=node_dict.get("source", "builtin"),
                )
                executor = executors.get(node_type)
                self.register(definition, executor=executor)
        except ImportError:
            # 后备：硬编码最小节点集
            builtin_nodes = [
                NodeDefinition(
                    type="builtin:start",
                    label="开始",
                    icon="▶️",
                    category="flow",
                    description="工作流开始节点",
                    sub_blocks=[],
                    inputs=[],
                    outputs=[{"id": "output", "label": "输出"}],
                    source="builtin",
                ),
                NodeDefinition(
                    type="builtin:end",
                    label="结束",
                    icon="⏹️",
                    category="flow",
                    description="工作流结束节点",
                    sub_blocks=[],
                    inputs=[{"id": "input", "label": "输入"}],
                    outputs=[],
                    source="builtin",
                ),
            ]
            for node in builtin_nodes:
                self.register(node)


# ==================== 自动发现适配器 ====================


def _sync_tools_from_engine(registry: NodeRegistry) -> int:
    """
    从 ToolEngine 同步工具节点

    Args:
        registry: 节点注册表

    Returns:
        同步的工具数量
    """
    try:
        from neurova.execution_engine.tool_engine import get_tool_engine

        tool_engine = get_tool_engine()

        count = 0
        for tool in tool_engine.list_tools():
            node_def = NodeDefinition(
                type=f"tool:{tool['name']}",
                label=tool.get("name", tool["name"]),
                icon="🔧",
                category="tools",
                description=tool.get("description", f"工具: {tool['name']}"),
                sub_blocks=[],
                inputs=[{"id": "input", "label": "输入"}],
                outputs=[{"id": "output", "label": "输出"}, {"id": "error", "label": "错误"}],
                source="tool",
                source_id=tool["name"],
                version=tool.get("version", "1.0.0"),
                tags=tool.get("tags", []),
            )
            registry.register(node_def)
            count += 1

        return count
    except ImportError:
        return 0


def _sync_skills_from_registry(registry: NodeRegistry) -> int:
    """
    从 SkillRegistry 同步技能节点

    Args:
        registry: 节点注册表

    Returns:
        同步的技能数量
    """
    try:
        from neurova.skill_system import get_skill_registry

        skill_registry = get_skill_registry()

        count = 0
        for skill in skill_registry.list_skills():
            node_def = NodeDefinition(
                type=f"skill:{skill['name']}",
                label=skill.get("name", skill["name"]),
                icon="📚",
                category="skills",
                description=skill.get("description", f"技能: {skill['name']}"),
                sub_blocks=[],
                inputs=[{"id": "input", "label": "输入"}],
                outputs=[{"id": "output", "label": "输出"}],
                source="skill",
                source_id=skill["name"],
                version=skill.get("version", "1.0.0"),
                tags=skill.get("tags", []),
            )
            registry.register(node_def)
            count += 1

        return count
    except ImportError:
        return 0


def _sync_mcp_tools(registry: NodeRegistry) -> int:
    """
    从 MCPToolClient 同步 MCP 工具节点

    Args:
        registry: 节点注册表

    Returns:
        同步的 MCP 工具数量
    """
    try:
        from neurova.mcp_client import get_mcp_client

        mcp_client = get_mcp_client()

        count = 0
        for tool in mcp_client.list_tools():
            node_def = NodeDefinition(
                type=f"mcp:{tool['name']}",
                label=tool.get("name", tool["name"]),
                icon="🔌",
                category="mcp",
                description=tool.get("description", f"MCP 工具: {tool['name']}"),
                sub_blocks=[],
                inputs=[{"id": "input", "label": "输入"}],
                outputs=[{"id": "output", "label": "输出"}],
                source="mcp",
                source_id=tool["name"],
                version=tool.get("version", "1.0.0"),
                tags=tool.get("tags", []),
            )
            registry.register(node_def)
            count += 1

        return count
    except ImportError:
        return 0


# 便捷导出
__all__ = ["NodeRegistry", "get_node_registry", "reset_node_registry"]
