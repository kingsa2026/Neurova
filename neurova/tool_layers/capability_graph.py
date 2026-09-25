"""
Tool Capability Graph v1.0.0 — 工具能力关系图

职责:
- 编码工具间的语义关系（依赖/协作/降级）
- 生成 LLM 可读的工具关系上下文
- 为 ToolOrchestrator (Phase 3) 和工具选择提供关系数据

隔离层级: 与 ToolRouter 平级，通过能力图适配器集成
"""

from neurova.core.logger import get_logger
import re
import threading
import typing
from collections import deque
from dataclasses import dataclass, field

logger = get_logger(__name__)


@dataclass
class ToolCapabilityNode:
    """工具能力节点"""

    tool_name: str
    capabilities: typing.List[str] = field(default_factory=list)
    dependencies: typing.List[str] = field(default_factory=list)
    fallbacks: typing.List[str] = field(default_factory=list)
    companions: typing.List[str] = field(default_factory=list)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    # Phase3 契约字段（测试先行，见 tests/unit/tools/test_capability_graph_phase3
    # 的 xfail 规格钉）：provides=该工具产出的能力、requires=前置能力、
    # degrades_to=降级替代。默认图与既有消费方暂不使用，加性零影响。
    provides: typing.List[str] = field(default_factory=list)
    requires: typing.List[str] = field(default_factory=list)
    degrades_to: typing.List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 元检索工具名单（**单源**）
# ═══════════════════════════════════════════════════════════════
# 语义：这些工具只做"找/看/调已有的东西"，**结构上没有失败可能**（检索不到
# 返回空也是"成功执行"）。因此它们不能靠"本轮调用没报错"来证明任务被推进。
#
# 为什么名单落在这里：本模块已是能力语义的单源（工具名 → 能力/依赖/降级），
# 名单是同一类事实的自然延伸。不新增配置文件、不加 env 开关（D5）。
#
# 名单覆盖面（同根扫荡，教义第 5 条）：
#   - 记忆/历史检索：memory_search / voice_memory_search / recall_history
#   - 分层摘要下钻：recall_context_span（同一族：只做"取回已有的东西"）
#   - 技能目录检索：discover_skills
#   - 大目录延迟加载的控制工具（tool_search / tool_describe / tool_call）：
#     与 `context/tool_search.CONTROL_TOOL_NAMES` 同源，由测试断言咬合，
#     不在这里抄第二份字面量。
#: 记忆/历史检索 + 技能目录检索：名字在本模块**唯一**定义一次。
_META_RETRIEVAL_NAMES = frozenset({
    "memory_search",
    "voice_memory_search",
    "recall_history",
    "recall_context_span",
    "discover_skills",
})


def _metaRetrievalRoster() -> frozenset:
    """元检索名单的**单源**取值点（含控制工具）。

    控制工具名不在这里抄字面量：它们的定义处是
    `context/tool_search.CONTROL_TOOL_NAMES`（那次实现的事实源），
    本函数只是把它并进来。两侧漂移由测试咬合
    （`test_rosterCoversControlTools`），不靠人工同步。
    """
    global _META_RETRIEVAL_ROSTER
    if _META_RETRIEVAL_ROSTER is None:
        try:
            from neurova.context.tool_search import CONTROL_TOOL_NAMES

            controls = frozenset(CONTROL_TOOL_NAMES)
        except Exception:  # noqa: BLE001 - 控制工具面缺席不得让判断整体失败
            controls = frozenset()
        _META_RETRIEVAL_ROSTER = _META_RETRIEVAL_NAMES | controls
    return _META_RETRIEVAL_ROSTER


_META_RETRIEVAL_ROSTER: typing.Optional[frozenset] = None


def is_meta_retrieval_tool(tool_name: str) -> bool:
    """该工具是否属于"结构上不会失败"的元检索面。

    消费方是强化口径侧：遗传反哺与市场自动发布据此跳过（T-06）。
    """
    return str(tool_name or "") in _metaRetrievalRoster()


#: 反哺禁令命中计数的写侧（读侧见 `evolution/rsi/orchestrator`）。
#: 独立计数器而非塞进 capability_gap：语义不同（那是"能力不够"，
#: 这是"奖励发错了对象"），混在一起就再也分不清该补能力还是该收口径。
_REWARD_GUARD_LOCK = threading.RLock()
_REWARD_GUARD_SKIPS: typing.Dict[str, int] = {}


def noteMetaRewardSkip(tool_name: str, channel: str = "genetic_reward") -> None:
    """记一次"因属于元检索面而被跳过发奖"（可观测，不静默）。"""
    key = f"{channel}:{tool_name}"
    with _REWARD_GUARD_LOCK:
        _REWARD_GUARD_SKIPS[key] = _REWARD_GUARD_SKIPS.get(key, 0) + 1


def readRewardGuardSkips() -> typing.Dict[str, int]:
    """反哺禁令命中读侧（无命中时是空表，不是缺席）。"""
    with _REWARD_GUARD_LOCK:
        return dict(_REWARD_GUARD_SKIPS)


def resetRewardGuardSkips() -> None:
    """清空计数（仅测试与进程重置使用）。"""
    with _REWARD_GUARD_LOCK:
        _REWARD_GUARD_SKIPS.clear()


class ToolCapabilityGraph:
    """
    工具能力关系图

    编码工具间的语义关系，支持：
    - 依赖关系（前置工具）
    - 协作关系（常用组合）
    - 降级关系（备用工具）
    - 共现关系（统计关联）
    """

    def __init__(self, load_defaults: bool = True):
        """初始化图。

        load_defaults=False：空图（测试隔离/子图重建用）。原实现恒注入默认
        节点，曾致 `build_execution_plan` 临时子图混入默认工具——执行计划
        被无关工具污染（残留处理 2026-09-13 坐实的生产缺陷）。
        """
        self._nodes: typing.Dict[str, ToolCapabilityNode] = {}
        self._adjacency: typing.Dict[str, typing.List[str]] = {}
        self._reverse_adjacency: typing.Dict[str, typing.List[str]] = {}
        self._co_occurrence: typing.Dict[typing.Tuple[str, str], float] = {}
        self._capability_index: typing.Dict[str, typing.List[str]] = {}

        # 构建默认图
        if load_defaults:
            self._build_default_graph()

    @property
    def nodes(self) -> typing.Dict[str, "ToolCapabilityNode"]:
        """节点表公共视图（测试隔离清空/只读遍历；带结构的写入仍走 add_node）。"""
        return self._nodes

    def tools_for_capabilities(self, capabilities: typing.List[str]) -> typing.List[str]:
        """能力名→承载工具名映射（保持输入序，无承载者的能力跳过）。

        根治 tool_orchestrator 把能力名直接当 target_tools 传入
        build_execution_plan 的语义错配（恒空计划）。
        """
        out: typing.List[str] = []
        for cap in capabilities or []:
            for tool in self._capability_index.get(cap, []):
                if tool not in out:
                    out.append(tool)
        return out

    def register_tool(
        self,
        tool_name: str,
        capabilities: typing.Optional[typing.List[str]] = None,
        dependencies: typing.Optional[typing.List[str]] = None,
        fallbacks: typing.Optional[typing.List[str]] = None,
        companions: typing.Optional[typing.List[str]] = None,
        metadata: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> ToolCapabilityNode:
        """
        便捷方法：注册工具节点（自动创建 ToolCapabilityNode）

        返回:
            创建的节点
        """
        node = ToolCapabilityNode(
            tool_name=tool_name,
            capabilities=capabilities or [],
            dependencies=dependencies or [],
            fallbacks=fallbacks or [],
            companions=companions or [],
            metadata=metadata or {},
        )
        self.add_node(node)
        return node

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

        # 临时图用于排序——load_defaults=False：空图重建子图，否则默认节点
        # 混入排序结果，执行计划被无关工具污染（残留处理 2026-09-13 坐实）。
        temp_graph = ToolCapabilityGraph(load_defaults=False)
        for node in subgraph_nodes.values():
            # 只添加在子图中的依赖
            filtered_deps = [d for d in node.dependencies if d in needed]
            temp_node = ToolCapabilityNode(
                tool_name=node.tool_name,
                capabilities=node.capabilities,
                dependencies=filtered_deps,
                fallbacks=node.fallbacks,
                companions=node.companions,
                metadata=node.metadata,
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
        """构建默认工具关系图。

        节点名必须是**真实存在**的工具名（`builtin_tools._BUILTIN_SCHEMAS` 是工具清单的
        单一事实源）。历史实现点名的 `code_execute` / `data_process` / `memory_save` /
        `code_analyze` 从未注册过——据此产出的执行计划里每一步都是「未知工具」，
        能力图成了工具清单的第二份定义。未知工具名的缺席由
        `tests/unit/tools/test_tool_orchestrator_wiring.py` 常驻拦截。
        """
        default_tools = [
            ToolCapabilityNode(
                tool_name="file_read",
                capabilities=["read_file", "read_path"],
                companions=["file_write", "file_search"],
                metadata={"category": "filesystem", "description": "读取文件内容"},
            ),
            ToolCapabilityNode(
                tool_name="file_write",
                capabilities=["write_file", "create_file"],
                companions=["file_read"],
                metadata={"category": "filesystem", "description": "写入文件内容"},
            ),
            ToolCapabilityNode(
                tool_name="file_search",
                capabilities=["search_files", "find_files"],
                companions=["file_read"],
                metadata={"category": "filesystem", "description": "按内容搜索文件"},
            ),
            ToolCapabilityNode(
                tool_name="memory_search",
                capabilities=["search_memory", "recall"],
                companions=["planning"],
                metadata={"category": "memory", "description": "检索长期记忆"},
            ),
            ToolCapabilityNode(
                tool_name="web_search",
                capabilities=["search_web", "internet_search"],
                companions=["web_fetch", "deep_research"],
                metadata={"category": "web", "description": "网络搜索"},
            ),
            ToolCapabilityNode(
                tool_name="web_fetch",
                capabilities=["fetch_url", "get_webpage"],
                dependencies=["web_search"],
                metadata={"category": "web", "description": "获取网页内容"},
            ),
            ToolCapabilityNode(
                tool_name="deep_research",
                capabilities=["process_data", "transform_data"],
                dependencies=["web_search"],
                fallbacks=["web_fetch"],
                metadata={"category": "web", "description": "多源检索与摘录汇总"},
            ),
            ToolCapabilityNode(
                tool_name="run_code",
                capabilities=["run_code", "execute_code"],
                fallbacks=["computer_shell"],
                companions=["calculator"],
                metadata={"category": "code", "description": "执行代码或脚本"},
            ),
            ToolCapabilityNode(
                tool_name="calculator",
                capabilities=["calculate", "compute"],
                companions=["run_code"],
                metadata={"category": "code", "description": "安全数学计算"},
            ),
            ToolCapabilityNode(
                tool_name="planning",
                capabilities=["plan_task", "update_plan"],
                companions=["memory_search"],
                metadata={"category": "planning", "description": "任务计划读写"},
            ),
        ]

        for tool in default_tools:
            self.add_node(tool)

        # 共现关系（weight 越小表示同现越少见）
        co_occurrences = [
            ("file_read", "file_write", 0.9),
            ("file_read", "file_search", 0.8),
            ("web_search", "web_fetch", 0.9),
            ("web_search", "deep_research", 0.8),
            ("run_code", "calculator", 0.6),
            ("memory_search", "planning", 0.7),
        ]

        for tool1, tool2, weight in co_occurrences:
            self.add_co_occurrence(tool1, tool2, weight)
