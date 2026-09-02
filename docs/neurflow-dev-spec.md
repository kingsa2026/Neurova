# Neurflow 开发规范文档

> **版本**: 1.0.0 | **日期**: 2026-06-08  
> **定位**: Neurova 协作系统的核心工作流模块  
> **架构理念**: 三面镜子架构 — 工作流是 Neurova 全部能力的可视化投射层

---

## 目录

1. [模块定位与架构](#一模块定位与架构)
2. [核心数据模型](#二核心数据模型)
3. [节点注册系统（自动发现）](#三节点注册系统自动发现)
4. [执行引擎（DAG + 委托）](#四执行引擎dag--委托)
5. [变量解析器](#五变量解析器)
6. [团队 Agent 管理器](#六团队-agent-管理器)
7. [内置节点定义](#七内置节点定义)
8. [API 端点规范](#八api-端点规范)
9. [前端 UI 设计](#九前端-ui-设计)
10. [工作流模板](#十工作流模板)
11. [实施计划](#十一实施计划)

---

## 一、模块定位与架构

### 1.1 在 Neurova 中的位置

```
┌──────────────────────────────────────────────────────┐
│                  Neurova 协作系统                      │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐        │
│  │ 多Agent协作 │  │  Neurflow │  │ 权限&审计  │        │
│  └───────────┘  └───────────┘  └───────────┘        │
│  ┌──────────────────────────────────────────────────┐│
│  │           Neurova 核心能力层（不重写）              ││
│  │ ToolEngine SkillRegistry MCPToolClient           ││
│  │ MemoryManager EvolutionOrchestrator ContextPool  ││
│  │ ChannelManager Agent.chat() LLMRouter            ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
```

### 1.2 三面镜子架构

```
前端 UI（Vue + VueFlow 画布）
    │
    ├── 节点面板 ← Block Registry（自动发现层）
    │                ├── ToolEngine  → tool:{name} 节点
    │                ├── SkillRegistry → skill:{name} 节点
    │                ├── MCPToolClient → mcp:{server}:{tool} 节点
    │                └── 内置节点（条件/循环/LLM/记忆/进化/TDD/...）
    │
    ├── 变量系统 ← Neurova 上下文桥接
    │                ├── $node.xxx.output → 上游节点输出
    │                ├── $memory.query   → MemoryManager.search()
    │                ├── $context        → ContextPool.get()
    │                ├── $emotion        → EmotionModule.current()
    │                ├── $crystal        → PatternCrystallizer.retrieve()
    │                ├── $input          → 工作流输入
    │                ├── $var.xxx        → 工作流变量
    │                └── $agent.xxx      → 临时 Agent 属性
    │
    └── 执行引擎 ← 委托现有系统
                     ├── DAG 编排    → 拓扑排序 + 循环检测
                     ├── 工具执行    → ToolEngine
                     ├── 技能执行    → SkillChainExecutor
                     ├── LLM 调用   → Agent.chat()
                     ├── 人工审批    → ChannelManager
                     └── 进化反馈    → EvolutionOrchestrator
```

### 1.3 关键设计决策

| 决策 | 理由 |
|------|------|
| 序列化/执行期分离 | 保证动态变量引用在执行期正确解析 |
| 节点自动发现 | 注册新 Tool/Skill/MCP → 自动变成工作流节点，零前端代码 |
| 委托执行 | 不重新实现工具执行、LLM 调用、记忆检索 |
| 变量桥接 | $memory/$context/$emotion 直接访问 Neurova 核心能力 |
| 团队 Agent 临时创建 | 工作流可创建专用 Agent，执行完成后归档 |

### 1.4 模块文件结构

```
neurova/collaboration/neurflow/
├── __init__.py              # 导出入口
├── models.py                # 数据模型（WorkflowDefinition, NodeDefinition, etc.）
├── node_registry.py         # 节点注册表（单例，自动发现 + 手动注册）
├── adapters.py              # 适配器（ToolEngine/SkillRegistry/MCP → 节点）
├── builtin.py               # 内置节点定义（流程控制/LLM/记忆/进化/TDD/媒体/文档/数据）
├── dag.py                   # DAG 验证器（拓扑排序 + 循环检测 + 死循环防护）
├── variable_resolver.py     # 变量解析器（桥接 Neurova 上下文系统）
├── execution_engine.py      # 执行引擎（DAG 按序执行 + 委托）
├── agent_manager.py         # 团队 Agent 管理器（临时创建 + 归档）
├── storage.py               # 持久化存储（SQLite CRUD）
├── templates/               # 工作流模板
│   ├── __init__.py
│   ├── programming.py       # 编程工作流模板
│   ├── writing.py           # 文学创作模板
│   ├── media.py             # 媒体创作模板
│   ├── document.py          # 文档处理模板
│   ├── data_analysis.py     # 数据分析模板
│   ├── ecommerce.py         # 电商运营模板
│   └── web_maintenance.py   # 网站维护模板
└── api.py                   # API 端点

neuUI/src/workflow/
├── registry.ts              # 前端 Block 注册表
├── types.ts                 # 类型定义
├── validation.ts            # 工作流验证
├── serializer.ts            # 序列化/反序列化
├── blocks/
│   ├── builtin.ts           # 内置节点 UI 定义
│   └── adapters.ts          # Tool/Skill/MCP → Block 适配器
├── components/
│   ├── WorkflowCanvas.vue   # 画布主组件（VueFlow）
│   ├── NodePalette.vue      # 左侧节点面板（自动发现）
│   ├── NodeInspector.vue    # 右侧配置面板
│   ├── SubBlockRenderer.vue # 通用参数渲染器
│   ├── ModelSelector.vue    # LLM 选择器
│   ├── ExecutionPanel.vue   # 执行日志面板
│   └── nodes/
│       ├── BuiltinNode.vue  # 内置节点渲染
│       ├── ToolNode.vue     # 工具节点渲染
│       └── SkillNode.vue    # 技能节点渲染
└── composables/
    ├── useWorkflowStore.ts  # Pinia store
    ├── useWorkflowAPI.ts    # API 调用
    └── useExecution.ts      # 执行状态管理
```

---

## 二、核心数据模型

### 2.1 枚举与基础类型

```python
# neurova/collaboration/neurflow/models.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import time


class WorkflowStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RUNNING = "running"
    PAUSED = "paused"           # 等待人工审批
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeCategory(Enum):
    FLOW = "flow"               # 流程控制：条件/循环/并行/合并
    TOOLS = "tools"             # ToolEngine 工具
    SKILLS = "skills"           # SkillRegistry 技能
    MCP = "mcp"                 # MCP 外部工具
    AI = "ai"                   # LLM/Agent/进化/TDD
    MEMORY = "memory"           # 记忆/上下文/情感
    MEDIA = "media"             # 媒体生成（图/音/视频）
    DOCUMENT = "document"       # 文档处理
    DATA = "data"               # 数据分析/抓取
    COMMERCE = "commerce"       # 电商运营
    WEB = "web"                 # 网站维护
    INPUT = "input"             # 人工输入/审批
```

### 2.2 SubBlockConfig（参数配置 → 自动 UI 表单）

```python
@dataclass
class SubBlockConfig:
    """节点参数配置 — 声明式定义，自动生成前端表单"""
    id: str
    title: str
    type: str                   # input|textarea|select|slider|switch|code|json|model-selector|file
    placeholder: Optional[str] = None
    description: Optional[str] = None
    required: bool = False
    default_value: Optional[Any] = None
    options: Optional[List[Dict[str, Any]]] = None   # select: [{label, value}]
    min: Optional[float] = None
    max: Optional[float] = None
    language: Optional[str] = None                    # code: "python"/"javascript"
    provider_capability: Optional[str] = None         # model-selector: "vision"/"text"
    file_types: Optional[List[str]] = None            # file: ["image/png", "audio/mp3"]
    condition: Optional[Dict[str, Any]] = None        # 条件可见: {field, operator, value}
    depends_on: Optional[List[str]] = None
    validation: Optional[Dict[str, Any]] = None
```

### 2.3 节点类型定义

```python
@dataclass
class NodePort:
    id: str
    label: str
    type: str = "any"
    required: bool = False
    multiple: bool = False


@dataclass
class NodeDefinition:
    """节点类型定义 — 注册表条目"""
    type: str                   # "tool:web_search" | "skill:article" | "builtin:condition"
    label: str
    icon: str                   # emoji 或图标名
    category: str               # NodeCategory.value
    description: str
    sub_blocks: List[SubBlockConfig]
    inputs: List[NodePort]
    outputs: List[NodePort]
    source: str = "builtin"     # tool|skill|mcp|builtin
    source_id: Optional[str] = None
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    deprecated: bool = False
```

### 2.4 工作流定义（序列化格式）

```python
@dataclass
class WorkflowNode:
    id: str
    type: str                   # NodeDefinition.type
    position: Dict[str, float]  # {x, y}
    config: Dict[str, Any]      # SubBlockConfig 的值
    label: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    id: str
    source: str
    target: str
    source_handle: Optional[str] = None   # "true"/"false"/"loop_body"/"loop_done"
    target_handle: Optional[str] = None
    label: Optional[str] = None
    condition: Optional[str] = None


@dataclass
class WorkflowVariable:
    name: str
    type: str                   # string|number|boolean|json|array
    default_value: Optional[Any] = None
    description: Optional[str] = None
    scope: str = "workflow"     # workflow|execution|node


@dataclass
class WorkflowDefinition:
    id: str
    name: str
    description: str
    version: str
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    variables: List[WorkflowVariable]
    tags: List[str]
    category: str
    author: str
    created_at: float
    updated_at: float
    status: WorkflowStatus
    template: bool = False
    public: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "version": self.version,
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "variables": [v.__dict__ for v in self.variables],
            "tags": self.tags, "category": self.category, "author": self.author,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "status": self.status.value, "template": self.template,
            "public": self.public, "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowDefinition":
        return cls(
            id=data["id"], name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            nodes=[WorkflowNode(**n) for n in data.get("nodes", [])],
            edges=[WorkflowEdge(**e) for e in data.get("edges", [])],
            variables=[WorkflowVariable(**v) for v in data.get("variables", [])],
            tags=data.get("tags", []),
            category=data.get("category", "general"),
            author=data.get("author", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            status=WorkflowStatus(data.get("status", "draft")),
            template=data.get("template", False),
            public=data.get("public", False),
            metadata=data.get("metadata", {}),
        )
```

### 2.5 执行实例

```python
@dataclass
class NodeExecutionResult:
    node_id: str
    status: str                 # success|failed|skipped|pending
    output: Any
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: Optional[float] = None
    duration: Optional[float] = None
    tokens_used: Optional[int] = None
    cost: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionInstance:
    id: str
    workflow_id: str
    status: WorkflowStatus
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    node_results: Dict[str, NodeExecutionResult] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: Optional[float] = None
    duration: Optional[float] = None
    error: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 2.6 团队 Agent 模型

```python
@dataclass
class AgentInfo:
    agent_id: str
    name: str
    role: str
    config: Dict[str, Any]
    flow_id: Optional[str] = None
    created_at: float = 0.0
    archived_at: Optional[float] = None
    status: str = "active"      # active|archived|deleted
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

---

## 三、节点注册系统（自动发现）

### 3.1 架构

```
NodeRegistry（单例）
├── _nodes: Dict[type, NodeDefinition]    # 注册表
├── _categories: Dict[category, [type]]   # 分类索引
├── _sources: Dict[source, [type]]        # 来源索引
├── _executors: Dict[type, Callable]      # 执行器映射
└── auto-discovery（延迟触发）
    ├── sync_tools()   → ToolEngine.list_tools()
    ├── sync_skills()  → SkillRegistry.list_skills()
    └── sync_mcp()     → MCPToolClient.list_tools()
```

### 3.2 核心 API

```python
# node_registry.py 核心接口
registry = get_node_registry()

# 自动发现（延迟，首次查询时触发）
registry.ensure_builtin()

# 手动注册
registry.register(definition: NodeDefinition, executor: Callable)
registry.unregister(node_type: str)

# 查询
registry.get("tool:web_search")                    # 单个
registry.list_all()                                 # 全部
registry.list_by_category("tools")                  # 按分类
registry.list_by_source("mcp")                      # 按来源
registry.search("搜索")                             # 模糊搜索

# 执行器
executor = registry.get_executor("tool:web_search")
result = await executor(config, context)

# 统计
registry.get_summary()  # {"total": 47, "by_category": {...}, "by_source": {...}}
```

### 3.3 adapters.py — 自动发现适配器

```python
# adapters.py 核心逻辑

# 参数类型映射
_TYPE_MAP = {
    "string": "input", "number": "slider", "boolean": "switch",
    "enum": "select", "object": "json", "array": "json", "file": "file",
}

def tool_to_node(tool_def) -> NodeDefinition:
    """ToolEngine 工具 → 工作流节点"""
    return NodeDefinition(
        type=f"tool:{tool_def.name}",
        label=tool_def.display_name or tool_def.name,
        icon=tool_def.icon or "🔧",
        category="tools",
        description=tool_def.description,
        sub_blocks=[_param_to_sub_block(p) for p in tool_def.parameters],
        inputs=[NodePort(id="input", label="输入")],
        outputs=[NodePort(id="output", label="输出"), NodePort(id="error", label="错误")],
        source="tool", source_id=tool_def.name,
    )

def skill_to_node(skill_info) -> NodeDefinition:
    """SkillRegistry 技能 → 工作流节点"""
    # ...

def mcp_tool_to_node(server: str, tool_info) -> NodeDefinition:
    """MCP 工具 → 工作流节点"""
    # ...

def sync_all(registry) -> Dict[str, int]:
    """一键同步: tools + skills + mcp → 注册表"""
    return {"tools": N, "skills": N, "mcp": N}
```

---

## 四、执行引擎（DAG + 委托）

### 4.1 DAG 验证器

```python
# dag.py

class DAGValidator:
    """DAG 验证器 — 拓扑排序 + 循环检测 + 死循环防护"""

    def validate(self) -> List[str]:
        """返回错误列表（空=有效）"""
        errors = []
        errors.extend(self._detect_cycle_tarjan())     # Tarjan 强连通分量
        errors.extend(self._check_loop_safety())        # 循环节点必须有 max_iterations
        errors.extend(self._check_orphans())            # 孤立节点检测
        errors.extend(self._check_required_ports())     # 必填端口
        return errors

    def _check_loop_safety(self) -> List[str]:
        """循环节点必须有 max_iterations，且 <= 1000"""
        for node in self.nodes.values():
            if node.type == "builtin:loop":
                max_iter = node.config.get("max_iterations")
                if not max_iter or max_iter <= 0:
                    errors.append(f"循环节点 {node.id} 缺少 max_iterations")
                elif max_iter > 1000:
                    errors.append(f"循环节点 {node.id} 的 max_iterations={max_iter} 过大")

    def topological_sort(self) -> List[str]:
        """Kahn 算法拓扑排序"""
        # ...
```

### 4.2 执行引擎

```python
# execution_engine.py

class NeurflowExecutor:
    """工作流执行器 — DAG 按序执行 + 委托现有系统"""

    def __init__(self):
        self._registry = get_node_registry()
        self._var_resolver: Optional[VariableResolver] = None

    async def execute(self, workflow: WorkflowDefinition,
                      inputs: Dict[str, Any],
                      agent_id: str = None,
                      user_id: str = None) -> ExecutionInstance:
        """执行工作流"""
        # 1. DAG 验证
        validator = DAGValidator(workflow.nodes, workflow.edges)
        errors = validator.validate()
        if errors:
            return ExecutionInstance(..., status=WorkflowStatus.FAILED, error=str(errors))

        # 2. 拓扑排序
        sorted_ids = validator.topological_sort()

        # 3. 初始化变量解析器
        self._var_resolver = VariableResolver(
            workflow_variables={v.name: v.default_value for v in workflow.variables},
            input_variables=inputs, agent_id=agent_id, user_id=user_id,
        )

        # 4. 按拓扑顺序执行
        results: Dict[str, NodeExecutionResult] = {}
        for node_id in sorted_ids:
            node = workflow_node_map[node_id]

            # 条件跳过：检查是否在被跳过的分支
            if self._should_skip(node_id, workflow.edges, results):
                results[node_id] = NodeExecutionResult(node_id=node_id, status="skipped", output=None)
                continue

            # 解析变量
            resolved_config = self._var_resolver.resolve(node.config, results)

            # 执行节点（委托给注册表中的 executor）
            result = await self._execute_node(node, resolved_config, results)
            results[node_id] = result

            if result.status == "failed":
                # 根据错误处理策略决定是否继续
                break

        return ExecutionInstance(..., node_results=results)

    async def _execute_node(self, node, config, results):
        """按节点类型委托"""
        executor = self._registry.get_executor(node.type)
        if executor:
            return await executor(config, {"node_results": results})
        # 内置节点特殊处理
        if node.type == "builtin:condition":
            return await self._execute_condition(node, config, results)
        if node.type == "builtin:loop":
            return await self._execute_loop(node, config, results)
        if node.type == "builtin:llm":
            return await self._execute_llm(node, config, results)
        # ...

    async def _execute_condition(self, node, config, results):
        """条件分支节点"""
        expr = config.get("expression", "true")
        result = self._evaluate_expression(expr, results)
        return NodeExecutionResult(node_id=node.id, status="success", output={"branch": "true" if result else "false"})

    async def _execute_loop(self, node, config, results):
        """循环节点 — 必须有 max_iterations 防护"""
        max_iter = config.get("max_iterations", 10)
        # ...
```

---

## 五、变量解析器

### 5.1 变量前缀与映射

| 前缀 | 含义 | 示例 | 后端解析 |
|------|------|------|----------|
| `$node.xxx.output` | 上游节点输出 | `$node.llm_1.output.text` | `node_results["llm_1"]["output"]["text"]` |
| `$memory.query` | 记忆检索 | `$memory.上周会议内容` | `MemoryManager.search("上周会议内容")` |
| `$context` | 当前上下文 | `$context` | `ContextPool.get_context()` |
| `$emotion` | 当前情感状态 | `$emotion.valence` | `EmotionModule.current()` |
| `$crystal` | 结晶经验 | `$crystal.writing_tips` | `PatternCrystallizer.retrieve("writing_tips")` |
| `$input` | 工作流输入 | `$input.topic` | `inputs["topic"]` |
| `$var.xxx` | 工作流变量 | `$var.style` | `workflow_variables["style"]` |
| `$agent.xxx` | Agent 属性 | `$agent.name` | `agent_info["name"]` |

### 5.2 实现

```python
# variable_resolver.py

class VariableResolver:
    """变量解析器 — 桥接工作流和 Neurova 核心能力"""

    VAR_PATTERN = re.compile(
        r'\$(node|memory|context|emotion|crystal|input|var|agent)([\w.]*)'
    )

    def resolve(self, config: Dict[str, Any], node_results: Dict) -> Dict[str, Any]:
        """解析配置中的所有变量引用"""
        resolved = {}
        for key, value in config.items():
            resolved[key] = self._resolve_value(value, node_results)
        return resolved

    def _resolve_value(self, value, node_results):
        if isinstance(value, str):
            # 精确变量引用: "$node.llm_1.output"
            match = self.VAR_PATTERN.match(value)
            if match and match.group(0) == value:  # 全匹配
                return self._resolve_prefix(match.group(1), match.group(2), node_results)
            # 模板内嵌: "用户问了 {{topic}}，情感是 $emotion"
            return self.VAR_PATTERN.sub(
                lambda m: str(self._resolve_prefix(m.group(1), m.group(2), node_results)),
                value
            )
        if isinstance(value, dict):
            return {k: self._resolve_value(v, node_results) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(v, node_results) for v in value]
        return value

    def _resolve_prefix(self, prefix: str, suffix: str, node_results: Dict) -> Any:
        suffix = suffix.lstrip(".")
        if prefix == "node":
            return self._resolve_node(suffix, node_results)
        elif prefix == "memory":
            return self._resolve_memory(suffix)
        elif prefix == "context":
            return self._resolve_context()
        elif prefix == "emotion":
            return self._resolve_emotion(suffix)
        elif prefix == "crystal":
            return self._resolve_crystal(suffix)
        elif prefix == "input":
            return self._input_vars.get(suffix) if suffix else self._input_vars
        elif prefix == "var":
            return self._workflow_vars.get(suffix)
        elif prefix == "agent":
            return self._agent_info.get(suffix) if self._agent_info else None
        return None

    def _resolve_node(self, path: str, node_results: Dict) -> Any:
        """$node.xxx.output.text → node_results["xxx"]["output"]["text"]"""
        parts = path.split(".")
        node_id = parts[0]
        result = node_results.get(node_id)
        if not result:
            return None
        obj = result.output if hasattr(result, "output") else result
        for part in parts[1:]:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                obj = getattr(obj, part, None)
        return obj

    def _resolve_memory(self, query: str) -> Any:
        """$memory.query → MemoryManager.search(query)"""
        svc = self._get_service("memory")
        if svc and query:
            results = svc.search(query, limit=5)
            return [r.to_dict() if hasattr(r, "to_dict") else r for r in results]
        return []

    def _resolve_context(self) -> Any:
        svc = self._get_service("context")
        return svc.get_context() if svc else {}

    def _resolve_emotion(self, path: str) -> Any:
        svc = self._get_service("emotion")
        if not svc:
            return {}
        current = svc.get_current_emotion()
        if path:
            return getattr(current, path, None) if current else None
        return current

    def _resolve_crystal(self, query: str) -> Any:
        svc = self._get_service("crystal")
        if svc and query:
            return svc.retrieve(query)
        return []

    def _get_service(self, name: str):
        """延迟加载 Neurova 服务（避免循环导入）"""
        # ... 省略延迟加载逻辑
```

---

## 六、团队 Agent 管理器

```python
# agent_manager.py

class NeurflowAgentManager:
    """团队 Agent 管理器 — 支持临时创建和归档"""

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._archived: Dict[str, AgentInfo] = {}
        self._lock = threading.RLock()

    def create_agent(self, name: str, role: str,
                     config: Dict = None, flow_id: str = None) -> AgentInfo:
        """创建临时团队 Agent"""
        import uuid
        agent_id = f"neurflow_{uuid.uuid4().hex[:8]}"
        agent = AgentInfo(
            agent_id=agent_id, name=name, role=role,
            config=config or {}, flow_id=flow_id,
            created_at=time.time(), status="active",
        )
        with self._lock:
            self._agents[agent_id] = agent
        return agent

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        with self._lock:
            return self._agents.get(agent_id) or self._archived.get(agent_id)

    def list_agents(self, flow_id: str = None, include_archived: bool = False) -> List[AgentInfo]:
        with self._lock:
            pool = {**self._agents}
            if include_archived:
                pool.update(self._archived)
            if flow_id:
                pool = {k: v for k, v in pool.items() if v.flow_id == flow_id}
            return list(pool.values())

    def archive_agent(self, agent_id: str) -> bool:
        with self._lock:
            agent = self._agents.pop(agent_id, None)
            if not agent:
                return False
            agent.status = "archived"
            agent.archived_at = time.time()
            self._archived[agent_id] = agent
        return True

    def restore_agent(self, agent_id: str) -> bool:
        with self._lock:
            agent = self._archived.pop(agent_id, None)
            if not agent:
                return False
            agent.status = "active"
            agent.archived_at = None
            self._agents[agent_id] = agent
        return True

    def delete_agent(self, agent_id: str) -> bool:
        with self._lock:
            if self._agents.pop(agent_id, None):
                return True
            if self._archived.pop(agent_id, None):
                return True
            return False


def get_agent_manager() -> NeurflowAgentManager:
    if not hasattr(get_agent_manager, "_instance"):
        get_agent_manager._instance = NeurflowAgentManager()
    return get_agent_manager._instance
```

---

---

## 七、内置节点定义

### 7.1 builtin.py — 流程控制 + AI + 记忆

| 节点 type | 分类 | 功能 | 关键参数 |
|-----------|------|------|----------|
| `builtin:start` | flow | 工作流入口 | `inputs_schema` |
| `builtin:end` | flow | 工作流出口 | `output_mapping` |
| `builtin:condition` | flow | 条件分支 | `expression`, `branches:[{label,condition}]` |
| `builtin:loop` | flow | 循环 | `max_iterations`, `break_condition` |
| `builtin:parallel` | flow | 并行分支 | `branches_count` |
| `builtin:merge` | flow | 合并 | `strategy:first/all/custom` |
| `builtin:delay` | flow | 延时等待 | `seconds` |
| `builtin:llm` | ai | LLM 调用 | `prompt`, `model_provider`, `model_name`, `temperature`, `max_tokens` |
| `builtin:agent` | ai | 团队 Agent 调用 | `agent_name`, `agent_role`, `agent_config` |
| `builtin:evolution` | ai | 进化反馈 | `mode:learn/evaluate/optimize`, `feedback_data` |
| `builtin:tdd` | ai | TDD 模式 | `test_spec`, `implementation_prompt`, `max_iterations` |
| `builtin:memory-load` | memory | 加载记忆 | `query`, `limit`, `memory_type` |
| `builtin:memory-save` | memory | 保存记忆 | `content`, `importance`, `tags` |
| `builtin:context` | memory | 获取上下文 | `sources:[]`, `token_budget` |
| `builtin:emotion` | memory | 情感分析 | `text`, `mode:analyze/express` |

### 7.2 内置节点的执行器

```python
# builtin.py

def register_builtin_nodes(registry: NodeRegistry):
    """注册所有内置节点"""

    # ---- 流程控制 ----
    registry.register(NodeDefinition(
        type="builtin:condition", label="条件分支", icon="🔀",
        category="flow", description="根据条件表达式选择分支",
        sub_blocks=[
            SubBlockConfig(id="expression", title="条件表达式", type="input",
                          description="Python 表达式，如: len($node.llm1.output) > 100"),
            SubBlockConfig(id="branches", title="分支列表", type="json",
                          description='[{"label": "是", "condition": "true"}, {"label": "否", "condition": "false"}]'),
        ],
        inputs=[NodePort(id="input", label="输入")],
        outputs=[NodePort(id="true", label="真"), NodePort(id="false", label="假")],
    ))

    registry.register(NodeDefinition(
        type="builtin:loop", label="循环", icon="🔁",
        category="flow", description="循环执行子流程",
        sub_blocks=[
            SubBlockConfig(id="max_iterations", title="最大迭代次数", type="slider",
                          required=True, default_value=10, min=1, max=1000),
            SubBlockConfig(id="break_condition", title="跳出条件", type="input",
                          description="满足条件时跳出循环"),
        ],
        inputs=[NodePort(id="input", label="输入"), NodePort(id="loop_body", label="循环体")],
        outputs=[NodePort(id="loop_done", label="完成"), NodePort(id="current", label="当前迭代")],
    ))

    # ... (其他流程控制节点类似)

    # ---- AI 能力 ----
    registry.register(NodeDefinition(
        type="builtin:llm", label="LLM 调用", icon="🤖",
        category="ai", description="调用大语言模型",
        sub_blocks=[
            SubBlockConfig(id="prompt", title="提示词", type="textarea", required=True),
            SubBlockConfig(id="model_provider", title="模型提供商", type="select",
                          options=[{"label": "自动选择", "value": "auto"},
                                   {"label": "OpenAI", "value": "openai"},
                                   {"label": "Anthropic", "value": "anthropic"},
                                   {"label": "Qwen", "value": "qwen"}],
                          default_value="auto"),
            SubBlockConfig(id="model_name", title="模型名称", type="model-selector",
                          provider_capability="text"),
            SubBlockConfig(id="temperature", title="温度", type="slider",
                          default_value=0.7, min=0.0, max=2.0),
            SubBlockConfig(id="max_tokens", title="最大 Tokens", type="slider",
                          default_value=4096, min=100, max=128000),
            SubBlockConfig(id="system_prompt", title="系统提示", type="textarea"),
        ],
        inputs=[NodePort(id="input", label="输入")],
        outputs=[NodePort(id="output", label="输出"), NodePort(id="usage", label="Token 用量")],
    ))

    registry.register(NodeDefinition(
        type="builtin:evolution", label="进化能力", icon="🧬",
        category="ai", description="记录经验、评估性能、优化策略",
        sub_blocks=[
            SubBlockConfig(id="mode", title="模式", type="select", required=True,
                          options=[{"label": "学习", "value": "learn"},
                                   {"label": "评估", "value": "evaluate"},
                                   {"label": "优化", "value": "optimize"}]),
            SubBlockConfig(id="feedback_data", title="反馈数据", type="json"),
            SubBlockConfig(id="metric", title="评估指标", type="input"),
        ],
        inputs=[NodePort(id="input", label="输入"), NodePort(id="feedback", label="反馈")],
        outputs=[NodePort(id="output", label="结果"), NodePort(id="score", label="评分")],
    ))

    registry.register(NodeDefinition(
        type="builtin:tdd", label="TDD 模式", icon="🧪",
        category="ai", description="测试驱动开发：先写测试，再实现，自动迭代优化",
        sub_blocks=[
            SubBlockConfig(id="test_spec", title="测试规格", type="textarea", required=True,
                          description="描述期望行为，LLM 自动生成测试用例"),
            SubBlockConfig(id="implementation_prompt", title="实现提示", type="textarea"),
            SubBlockConfig(id="max_iterations", title="最大迭代次数", type="slider",
                          default_value=5, min=1, max=20),
            SubBlockConfig(id="pass_threshold", title="通过阈值", type="slider",
                          default_value=1.0, min=0.5, max=1.0),
        ],
        inputs=[NodePort(id="input", label="输入")],
        outputs=[NodePort(id="output", label="最终实现"), NodePort(id="tests", label="测试结果"),
                  NodePort(id="iterations", label="迭代次数")],
    ))

    # ... (memory/context/emotion 节点类似)


# 各节点执行器
async def _exec_condition(config, ctx):
    expr = config.get("expression", "true")
    result = eval(expr, {"$node": ctx.get("node_results", {}), "len": len, "str": str})
    return {"branch": "true" if result else "false", "result": result}

async def _exec_llm(config, ctx):
    from neurova.agent_core import Agent
    prompt = config.get("prompt", "")
    # 解析变量后的 prompt
    agent = Agent.get_instance()
    response = await agent.chat(prompt)
    return {"text": response, "usage": {}}

async def _exec_evolution(config, ctx):
    from neurova.evolution.closed_loop import get_evolution_orchestrator
    evo = get_evolution_orchestrator()
    mode = config.get("mode", "learn")
    if mode == "learn":
        evo.on_experience_recorded(config.get("feedback_data", {}))
        return {"status": "learned"}
    elif mode == "evaluate":
        score = evo.evaluate_performance(config.get("metric", "default"))
        return {"score": score}
    # ...

async def _exec_tdd(config, ctx):
    """TDD 节点执行器 — 先写测试，再实现，自动迭代"""
    max_iter = config.get("max_iterations", 5)
    test_spec = config.get("test_spec", "")
    impl_prompt = config.get("implementation_prompt", "")

    for i in range(max_iter):
        # 1. LLM 生成测试
        tests = await _call_llm(f"根据以下规格生成 Python 测试:\n{test_spec}")
        # 2. LLM 生成实现
        impl = await _call_llm(f"根据以下测试生成实现:\n{tests}\n{impl_prompt}")
        # 3. 执行测试
        test_result = await _run_tests(tests, impl)
        if test_result["pass_rate"] >= config.get("pass_threshold", 1.0):
            return {"output": impl, "tests": tests, "iterations": i + 1, "pass_rate": test_result["pass_rate"]}
        # 4. 失败时将错误信息反馈给下一轮
        impl_prompt = f"上次实现失败:\n{test_result['errors']}\n请修复。"

    return {"output": impl, "tests": tests, "iterations": max_iter, "pass_rate": test_result.get("pass_rate", 0)}
```

### 7.3 专用领域节点

#### 媒体创作（media）

| 节点 type | 功能 | 关键参数 |
|-----------|------|----------|
| `builtin:image-generate` | 图片生成 | `prompt`, `style`, `size`, `model` |
| `builtin:image-edit` | 图片编辑 | `image`, `instruction`, `mask` |
| `builtin:audio-generate` | 音频/配音生成 | `text`, `voice`, `speed`, `language` |
| `builtin:video-generate` | 视频生成 | `prompt`, `duration`, `style` |
| `builtin:tts` | 文字转语音 | `text`, `voice`, `engine` |
| `builtin:stt` | 语音转文字 | `audio_file`, `language` |

#### 文档处理（document）

| 节点 type | 功能 | 关键参数 |
|-----------|------|----------|
| `builtin:doc-read` | 读取文档 | `file_path`, `format:auto/docx/pdf/txt` |
| `builtin:doc-write` | 写入文档 | `content`, `format:docx/pdf/markdown`, `template` |
| `builtin:excel-read` | 读取 Excel | `file_path`, `sheet`, `range` |
| `builtin:excel-write` | 写入 Excel | `data`, `file_path`, `sheet` |
| `builtin:ppt-generate` | 生成 PPT | `outline`, `template`, `style` |
| `builtin:pdf-extract` | PDF 提取 | `file_path`, `pages` |
| `builtin:markdown-render` | Markdown 渲染 | `content`, `format:html/pdf` |

#### 数据分析（data）

| 节点 type | 功能 | 关键参数 |
|-----------|------|----------|
| `builtin:data-analyze` | 数据分析 | `data`, `analysis_type`, `columns` |
| `builtin:data-visualize` | 数据可视化 | `data`, `chart_type`, `x_axis`, `y_axis` |
| `builtin:web-scrape` | 网页抓取 | `url`, `selector`, `pagination` |
| `builtin:api-call` | API 调用 | `url`, `method`, `headers`, `body` |
| `builtin:csv-process` | CSV 处理 | `file_path`, `operation`, `filters` |

#### 电商运营（commerce）

| 节点 type | 功能 | 关键参数 |
|-----------|------|----------|
| `builtin:product-listing` | 商品上架 | `platform`, `product_info`, `images` |
| `builtin:price-monitor` | 价格监控 | `products`, `alert_threshold` |
| `builtin:review-respond` | 评价回复 | `reviews`, `tone`, `templates` |
| `builtin:inventory-sync` | 库存同步 | `platforms`, `sync_direction` |
| `builtin:ad-copy` | 广告文案 | `product`, `platform`, `style` |

#### 网站维护（web）

| 节点 type | 功能 | 关键参数 |
|-----------|------|----------|
| `builtin:content-publish` | 内容发布 | `platform`, `content`, `schedule` |
| `builtin:seo-optimize` | SEO 优化 | `content`, `keywords`, `target_url` |
| `builtin:broken-link-check` | 死链检测 | `url`, `depth` |
| `builtin:screenshot` | 网页截图 | `url`, `viewport`, `full_page` |

---

## 八、API 端点规范

### 8.1 节点发现 API

```
GET /api/v1/neurflow/nodes
    → 返回所有已注册节点（含自动发现的工具/技能/MCP）
    Query: ?category=tools&source=mcp&q=搜索

GET /api/v1/neurflow/nodes/summary
    → 返回节点统计 {"total": 47, "by_category": {...}, "by_source": {...}}

POST /api/v1/neurflow/nodes/sync
    → 手动触发同步（重新从 ToolEngine/SkillRegistry/MCP 拉取）

### 8.2 工作流 CRUD API

```
GET    /api/v1/neurflow/workflows                    # 列表（分页+筛选）
POST   /api/v1/neurflow/workflows                    # 创建
GET    /api/v1/neurflow/workflows/{id}               # 详情
PUT    /api/v1/neurflow/workflows/{id}               # 更新
DELETE /api/v1/neurflow/workflows/{id}               # 删除
POST   /api/v1/neurflow/workflows/{id}/duplicate     # 复制

PUT    /api/v1/neurflow/workflows/{id}/definition    # 更新定义（节点/边/变量）
GET    /api/v1/neurflow/workflows/{id}/definition    # 获取定义
PUT    /api/v1/neurflow/workflows/{id}/viewport      # 保存视口状态
POST   /api/v1/neurflow/workflows/{id}/validate      # 验证（DAG 检查）
POST   /api/v1/neurflow/workflows/{id}/publish       # 发布
```

### 8.3 执行 API

```
POST   /api/v1/neurflow/workflows/{id}/execute       # 执行
       Body: { inputs: {...}, agent_id: "...", async: true }
GET    /api/v1/neurflow/executions                    # 执行历史
GET    /api/v1/neurflow/executions/{exec_id}          # 执行详情
POST   /api/v1/neurflow/executions/{exec_id}/cancel   # 取消
POST   /api/v1/neurflow/executions/{exec_id}/resume   # 恢复（人工审批后）
```

### 8.4 团队 Agent API

```
GET    /api/v1/neurflow/agents                        # 列表
POST   /api/v1/neurflow/agents                        # 创建临时 Agent
POST   /api/v1/neurflow/agents/{agent_id}/archive     # 归档
POST   /api/v1/neurflow/agents/{agent_id}/restore     # 恢复
```

### 8.5 模板 API

```
GET    /api/v1/neurflow/templates                     # 模板列表
POST   /api/v1/neurflow/templates                     # 创建模板
POST   /api/v1/neurflow/templates/{id}/instantiate    # 从模板创建工作流
```

---

## 九、前端 UI 设计

### 9.1 技术栈

- **画布**: @vue-flow/core
- **状态**: Pinia
- **服务端状态**: @tanstack/vue-query
- **UI**: Ant Design Vue
- **代码编辑**: Monaco Editor

### 9.2 页面布局

```
┌──────────────────────────────────────────────────────┐
│  顶栏: 工作流名称 | 保存 | 发布 | 执行 | 设置        │
├──────┬──────────────────────────────┬────────────────┤
│ 节点 │        VueFlow 画布          │   配置面板     │
│ 面板 │   (无限画布，缩放/平移)       │  (选中节点后   │
│ 自动 │   节点间拖拽连线             │   显示参数     │
│ 发现 │   条件分支多出口             │   配置表单)    │
│ 节点 │   循环回边                   │  ┌──────────┐  │
│ 列表 │                              │  │SubBlock  │  │
│ 搜索 │                              │  │Renderer  │  │
│ 过滤 │                              │  └──────────┘  │
├──────┴──────────────────────────────┴────────────────┤
│  底部: 执行日志 | 变量监视 | 验证错误 | Token 用量    │
└──────────────────────────────────────────────────────┘
```

### 9.3 核心组件

```typescript
// types.ts
export interface SubBlockConfig {
  id: string; title: string
  type: 'input'|'textarea'|'select'|'slider'|'switch'|'code'|'json'|'model-selector'|'file'
  placeholder?: string; description?: string; required?: boolean; defaultValue?: any
  options?: Array<{label: string; value: any}>
  min?: number; max?: number; language?: string
  providerCapability?: string; fileTypes?: string[]
  condition?: {field: string; operator: string; value: any}
}
export interface NodeDefinition {
  type: string; label: string; icon: string; category: string; description: string
  subBlocks: SubBlockConfig[]; inputs: NodePort[]; outputs: NodePort[]
  source: 'tool'|'skill'|'mcp'|'builtin'; tags: string[]
}
```

### 9.4 SubBlockRenderer（替代 v-if 链）

```vue
<!-- SubBlockRenderer.vue -->
<template>
  <template v-for="block in visibleBlocks" :key="block.id">
    <a-form-item :label="block.title" :required="block.required">
      <a-input v-if="block.type === 'input'" v-model:value="values[block.id]" />
      <a-textarea v-else-if="block.type === 'textarea'" v-model:value="values[block.id]" />
      <a-select v-else-if="block.type === 'select'" v-model:value="values[block.id]" :options="block.options" />
      <a-slider v-else-if="block.type === 'slider'" v-model:value="values[block.id]" :min="block.min" :max="block.max" />
      <a-switch v-else-if="block.type === 'switch'" v-model:checked="values[block.id]" />
      <MonacoEditor v-else-if="block.type === 'code'" v-model="values[block.id]" :language="block.language" />
      <JsonEditor v-else-if="block.type === 'json'" v-model="values[block.id]" />
      <ModelSelector v-else-if="block.type === 'model-selector'" v-model="values[block.id]" />
    </a-form-item>
  </template>
</template>
```

### 9.5 NodePalette（自动发现）

```vue
<script setup lang="ts">
// 从后端自动发现所有可用节点
const { data: nodes } = useQuery({
  queryKey: ['neurflow-nodes'],
  queryFn: () => fetch('/api/v1/neurflow/nodes').then(r => r.json()),
  staleTime: 60_000,
})
// 按分类 + 搜索过滤 + 来源标签（T/S/M/B）
</script>
```

---

## 十、工作流模板

| 模板 | 分类 | 节点流 |
|------|------|--------|
| 编程助手 | programming | 需求分析 → TDD 实现 → 进化学习 |
| 文学创作 | writing | 大纲 → 检索参考 → 撰写 → 人工审核 → 润色 → 输出 |
| 视频创作 | media | 文案 → 配音 → 封面 → 视频 → 合成 |
| 文档处理 | document | 读取 → 分析 → 格式化 → 输出 DOC/PDF/PPT |
| 数据分析 | data | 抓取 → 清洗 → 分析 → 可视化 → 报告 |
| 电商运营 | commerce | 商品监控 → 价格分析 → 广告文案 → 自动回复 |
| 网站维护 | web | 内容抓取 → SEO 分析 → 内容更新 → 死链检测 |

---

## 十一、实施计划

### Phase 1: 核心骨架（5-7 天）

| 任务 | 天数 | 产出 |
|------|------|------|
| models.py 数据模型 | 0.5 | 数据类 + 序列化 |
| storage.py SQLite 持久化 | 0.5 | CRUD + 索引 |
| node_registry.py 注册表 | 1 | 单例 + 自动发现 + 查询 |
| adapters.py 适配器 | 1 | Tool/Skill/MCP → 节点 |
| builtin.py 内置节点 | 1.5 | 15 个内置节点 + 执行器 |
| dag.py DAG 验证 | 0.5 | 拓扑排序 + 循环检测 |
| api.py API 端点 | 1 | CRUD + 执行 + 节点发现 |

### Phase 2: 前端画布（5-7 天）

| 任务 | 天数 | 产出 |
|------|------|------|
| types.ts + registry.ts | 0.5 | 前端类型 + 注册表 |
| WorkflowCanvas.vue | 2 | VueFlow 画布 |
| NodePalette.vue | 1 | 自动发现节点面板 |
| SubBlockRenderer.vue | 1 | 通用参数渲染器 |
| NodeInspector.vue | 0.5 | 配置面板 |
| ExecutionPanel.vue | 1 | 执行日志面板 |
| 集成 WorkflowPage.vue | 1 | 替换旧页面 |

### Phase 3: 深度集成（5-7 天）

| 任务 | 天数 | 产出 |
|------|------|------|
| variable_resolver.py | 1.5 | 变量桥接 |
| execution_engine.py | 2 | DAG 执行 + 委托 |
| agent_manager.py | 1 | 团队 Agent 管理 |
| 工作流模板 | 1.5 | 7 个领域模板 |
| ChannelManager 集成 | 1 | 人工审批通知 |

---

## 附录 A: 集成清单

| Neurova 模块 | 集成方式 | Neurflow 角色 |
|-------------|---------|--------------|
| ToolEngine | 自动发现 → 节点 | `tool:{name}` |
| SkillRegistry | 自动发现 → 节点 | `skill:{name}` |
| MCPToolClient | 自动发现 → 节点 | `mcp:{server}:{tool}` |
| MemoryManager | `$memory.query` | `builtin:memory-load/save` |
| ContextPool | `$context` | 自动注入 |
| EmotionModule | `$emotion` | `builtin:emotion` |
| EvolutionOrchestrator | `builtin:evolution` | 进化反馈 |
| Agent.chat() | `builtin:llm` | LLM 调用 |
| ChannelManager | `builtin:review` | 人工审批 |
| LLMRouter | `builtin:llm` 自动路由 | 多模型选择 |

## 附录 B: 风险与缓解

| 风险 | 缓解 |
|------|------|
| 自动发现性能 | 分类懒加载 + 1 分钟缓存 |
| 循环检测误报 | SCC 排除 loop 节点 |
| 变量解析安全 | ast.literal_eval 替代 eval |
| 大工作流超时 | max_duration + 异步执行 |
| 前端 1000+ 节点卡顿 | 视口裁剪 + 节点虚拟化 |