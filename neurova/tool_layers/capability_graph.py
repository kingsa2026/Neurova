"""
Tool Capability Graph v1.0.0 — 工具能力关系图

职责:
- 编码工具间的语义关系（依赖/协作/降级）
- 生成 LLM 可读的工具关系上下文
- 为 ToolOrchestrator (Phase 3) 和工具选择提供关系数据

隔离层级: 与 ToolRouter 平级，通过能力图适配器集成
"""

import collections
from dataclasses import dataclass, field
import logging
import typing
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class ToolCapabilityNode:
    """工具能力节点"""
    tool_name: str
    capabilities: typing.List[str] = field(default_factory=list)
    dependencies: typing.List[str] = field(default_factory=list)
    fallbacks: typing.List[str] = field(default_factory=list)
    companions: typing.List[str] = field(default_factory=list)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)


class ToolCapabilityGraph:
    """
    工具能力关系图
    
    编码工具间的语义关系，支持：
    - 依赖关系（前置工具）
    - 协作关系（常用组合）
    - 降级关系（备用工具）
    - 共现关系（统计关联）
    """
    
    def __init__(self):
        """初始化图"""
        self._nodes: typing.Dict[str, ToolCapabilityNode] = {}
        self._adjacency: typing.Dict[str, typing.List[str]] = {}
        self._reverse_adjacency: typing.Dict[str, typing.List[str]] = {}
        self._co_occurrence: typing.Dict[typing.Tuple[str, str], float] = {}
        self._capability_index: typing.Dict[str, typing.List[str]] = {}
        
        # 构建默认图
        self._build_default_graph()
    
    def add_node(self, node: ToolCapabilityNode) -> None:
        """添加节点到图"""
        self._nodes[node.tool_name] = node
        
        # 初始化邻接表
        if node.tool_name not in self._adjacency:
            self._adjacency[node.tool_name] = []
        if node.tool_name not in self._reverse_adjacency:
            self._reverse_adjacency[node.tool_name] = []
        
        # 建立依赖边
        for dep in node.dependencies:
            if dep not in self._adjacency:
                self._adjacency[dep] = []
            if dep not in self._reverse_adjacency:
                self._reverse_adjacency[dep] = []
            
            # 正向边：依赖 -> 工具
            if node.tool_name not in self._adjacency[dep]:
                self._adjacency[dep].append(node.tool_name)
            # 反向边：工具 -> 依赖
            if dep not in self._reverse_adjacency[node.tool_name]:
                self._reverse_adjacency[node.tool_name].append(dep)
        
        # 更新能力索引
        for cap in node.capabilities:
            if cap not in self._capability_index:
                self._capability_index[cap] = []
            if node.tool_name not in self._capability_index[cap]:
                self._capability_index[cap].append(node.tool_name)
    
    def get_node(self, tool_name: str) -> typing.Optional[ToolCapabilityNode]:
        """获取节点"""
        return self._nodes.get(tool_name)
    
    def add_co_occurrence(self, tool1: str, tool2: str, weight: float = 1.0) -> None:
        """添加共现关系（双向）"""
        key1 = (tool1, tool2)
        key2 = (tool2, tool1)
        self._co_occurrence[key1] = weight
        self._co_occurrence[key2] = weight
        
        # 自动更新 companions
        if tool1 in self._nodes and tool2 not in self._nodes[tool1].companions:
            self._nodes[tool1].companions.append(tool2)
        if tool2 in self._nodes and tool1 not in self._nodes[tool2].companions:
            self._nodes[tool2].companions.append(tool1)
    
    def get_prerequisites(self, tool_name: str) -> typing.List[str]:
        """获取工具的前置依赖（直接依赖）"""
        node = self._nodes.get(tool_name)
        if not node:
            return []
        return list(node.dependencies)
    
    def suggest_fallback(self, tool_name: str) -> typing.List[str]:
        """建议降级工具"""
        node = self._nodes.get(tool_name)
        if not node:
            return []
        return list(node.fallbacks)
    
    def suggest_companion_tools(self, tool_name: str) -> typing.List[str]:
        """建议协作工具"""
        node = self._nodes.get(tool_name)
        if not node:
            return []
        return list(node.companions)
    
    def topological_sort(self) -> typing.List[str]:
        """
        拓扑排序（Kahn 算法）
        
        返回:
            工具执行顺序列表
            
        异常:
            ValueError: 如果存在循环依赖
        """
        # 计算入度
        in_degree = {node: 0 for node in self._nodes}
        for node in self._nodes:
            for dep in self._reverse_adjacency.get(node, []):
                if dep in self._nodes:
                    in_degree[node] += 1
        
        # 初始化队列（入度为0的节点）
        queue = deque()
        for node, degree in in_degree.items():
            if degree == 0:
                queue.append(node)
        
        result = []
        while queue:
            current = queue.popleft()
            result.append(current)
            
            # 减少邻居的入度
            for neighbor in self._adjacency.get(current, []):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
        
        # 检查是否有循环
        if len(result) != len(self._nodes):
            # 找出循环中的节点
            remaining = set(self._nodes.keys()) - set(result)
            raise ValueError(f"Graph contains cycle involving nodes: {remaining}")
        
        return result
    
    def find_path_to_capability(self, capability: str) -> typing.Optional[typing.List[str]]:
        """
        查找获得指定能力的路径
        
        参数:
            capability: 目标能力
            
        返回:
            从基础工具到目标工具的路径，如果不存在则返回 None
        """
        # 找到拥有该能力的工具
        target_tools = self._capability_index.get(capability, [])
        if not target_tools:
            return None
        
        target_tool = target_tools[0]  # 取第一个匹配的工具
        
        # BFS 找最短路径
        visited = set()
        queue = deque([(target_tool, [target_tool])])
        
        while queue:
            current, path = queue.popleft()
            
            if current in visited:
                continue
            visited.add(current)
            
            # 检查是否到达基础工具（无依赖）
            node = self._nodes.get(current)
            if not node or not node.dependencies:
                return list(reversed(path))  # 反转得到从基础到目标的路径
            
            # 继续搜索依赖
            for dep in node.dependencies:
                if dep not in visited:
                    queue.append((dep, path + [dep]))
        
        return None
    
    def build_execution_plan(self, target_tools: typing.List[str]) -> typing.List[str]:
        """
        构建执行计划
        
        参数:
            target_tools: 需要执行的目标工具列表
            
        返回:
            按依赖顺序排列的完整执行计划
        """
        # 收集所有需要的工具
        needed = set()
        queue = deque(target_tools)
        
        while queue:
            tool = queue.popleft()
            if tool in needed:
                continue
            
            needed.add(tool)
            node = self._nodes.get(tool)
            if node:
                for dep in node.dependencies:
                    if dep not in needed:
                        queue.append(dep)
        
        # 创建子图并进行拓扑排序
        subgraph_nodes = {name: node for name, node in self._nodes.items() if name in needed}
        
        # 临时图用于排序
        temp_graph = ToolCapabilityGraph()
        for node in subgraph_nodes.values():
            # 只添加在子图中的依赖
            filtered_deps = [d for d in node.dependencies if d in needed]
            temp_node = ToolCapabilityNode(
                tool_name=node.tool_name,
                capabilities=node.capabilities,
                dependencies=filtered_deps,
                fallbacks=node.fallbacks,
                companions=node.companions,
                metadata=node.metadata
            )
            temp_graph.add_node(temp_node)
        
        return temp_graph.topological_sort()
    
    def to_llm_context(self, tool_name: str) -> str:
        """
        生成 LLM 可读的工具上下文
        
        参数:
            tool_name: 工具名称
            
        返回:
            描述工具关系的上下文文本
        """
        node = self._nodes.get(tool_name)
        if not node:
            return f"Tool '{tool_name}' not found in capability graph."
        
        lines = [f"Tool: {tool_name}"]
        
        if node.capabilities:
            lines.append(f"Capabilities: {', '.join(node.capabilities)}")
        
        if node.dependencies:
            lines.append(f"Dependencies: {', '.join(node.dependencies)}")
        
        if node.fallbacks:
            lines.append(f"Fallbacks: {', '.join(node.fallbacks)}")
        
        if node.companions:
            lines.append(f"Often used with: {', '.join(node.companions)}")
        
        if node.metadata:
            for key, value in node.metadata.items():
                lines.append(f"{key}: {value}")
        
        return "\n".join(lines)
    
    def _build_default_graph(self) -> None:
        """构建默认工具关系图"""
        # 基础工具
        default_tools = [
            ToolCapabilityNode(
                tool_name="file_read",
                capabilities=["read_file", "read_path"],
                companions=["file_write", "file_search"],
                metadata={"category": "filesystem", "description": "读取文件内容"}
            ),
            ToolCapabilityNode(
                tool_name="file_write",
                capabilities=["write_file", "create_file"],
                companions=["file_read"],
                metadata={"category": "filesystem", "description": "写入文件内容"}
            ),
            ToolCapabilityNode(
                tool_name="file_search",
                capabilities=["search_files", "find_files"],
                companions=["file_read"],
                metadata={"category": "filesystem", "description": "搜索文件"}
            ),
            ToolCapabilityNode(
                tool_name="memory_search",
                capabilities=["search_memory", "recall"],
                companions=["memory_save"],
                metadata={"category": "memory", "description": "搜索记忆"}
            ),
            ToolCapabilityNode(
                tool_name="memory_save",
                capabilities=["save_memory", "remember"],
                companions=["memory_search"],
                metadata={"category": "memory", "description": "保存记忆"}
            ),
            ToolCapabilityNode(
                tool_name="web_search",
                capabilities=["search_web", "internet_search"],
                companions=["web_fetch"],
                metadata={"category": "web", "description": "网络搜索"}
            ),
            ToolCapabilityNode(
                tool_name="web_fetch",
                capabilities=["fetch_url", "get_webpage"],
                dependencies=["web_search"],
                metadata={"category": "web", "description": "获取网页内容"}
            ),
            ToolCapabilityNode(
                tool_name="code_execute",
                capabilities=["run_code", "execute_python"],
                fallbacks=["code_analyze"],
                metadata={"category": "code", "description": "执行代码"}
            ),
            ToolCapabilityNode(
                tool_name="code_analyze",
                capabilities=["analyze_code", "lint_code"],
                companions=["code_execute"],
                metadata={"category": "code", "description": "分析代码"}
            ),
            ToolCapabilityNode(
                tool_name="data_process",
                capabilities=["process_data", "transform_data"],
                dependencies=["file_read"],
                fallbacks=["memory_search"],
                metadata={"category": "data", "description": "处理数据"}
            ),
        ]
        
        for tool in default_tools:
            self.add_node(tool)
        
        # 添加共现关系
        co_occurrences = [
            ("file_read", "file_write", 0.9),
            ("file_read", "file_search", 0.8),
            ("memory_search", "memory_save", 0.7),
            ("web_search", "web_fetch", 0.9),
            ("code_execute", "code_analyze", 0.6),
        ]
        
        for tool1, tool2, weight in co_occurrences:
            self.add_co_occurrence(tool1, tool2, weight)