"""
Neurflow 数据模型 — 垂直切片 1
核心数据类：WorkflowDefinition, NodeDefinition, ExecutionInstance 等
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(Enum):
    """工作流状态枚举"""

    DRAFT = "draft"
    PUBLISHED = "published"
    RUNNING = "running"
    PAUSED = "paused"  # 等待人工审批
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggerType(Enum):
    """触发器类型枚举（P1 Step 2；P2 统一 trigger 面补 plugin）"""

    WEBHOOK = "webhook"
    CRON = "cron"
    MANUAL = "manual"
    # P2：插件事件触发（插件经 plugin_api_registry 投递事件 → 统一 dispatch）
    PLUGIN = "plugin"


@dataclass
class WorkflowTrigger:
    """工作流触发器（P1 Step 2）

    secret 绝不明文存储——入库前经 storage.hash_trigger_secret() 转 sha256 hex。
    """

    id: str
    workflow_id: str
    type: "TriggerType"
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    secret_hash: Optional[str] = None
    # P1 Step 4b — webhook 验签需原 secret（hash 不可逆），AES-GCM 可逆加密存储
    secret_encrypted: Optional[str] = None
    rate_limit_per_minute: Optional[int] = None
    created_at: float = 0.0
    updated_at: float = 0.0


class NodeCategory(Enum):
    """节点分类枚举"""

    FLOW = "flow"  # 流程控制：条件/循环/并行/合并
    TOOLS = "tools"  # ToolEngine 工具
    SKILLS = "skills"  # SkillRegistry 技能
    MCP = "mcp"  # MCP 外部工具
    AI = "ai"  # LLM/Agent/进化/TDD
    MEMORY = "memory"  # 记忆/上下文/情感
    MEDIA = "media"  # 媒体生成（图/音/视频）
    DOCUMENT = "document"  # 文档处理
    DATA = "data"  # 数据分析/抓取
    COMMERCE = "commerce"  # 电商运营
    WEB = "web"  # 网站维护
    INPUT = "input"  # 人工输入/审批


@dataclass
class SubBlockConfig:
    """节点参数配置 — 声明式定义，自动生成前端表单"""

    id: str
    title: str
    type: str  # input|textarea|select|slider|switch|code|json|model-selector|file
    placeholder: Optional[str] = None
    description: Optional[str] = None
    required: bool = False
    default_value: Optional[Any] = None
    options: Optional[List[Dict[str, Any]]] = None  # select: [{label, value}]
    min: Optional[float] = None
    max: Optional[float] = None
    language: Optional[str] = None  # code: "python"/"javascript"
    provider_capability: Optional[str] = None  # model-selector: "vision"/"text"
    file_types: Optional[List[str]] = None  # file: ["image/png", "audio/mp3"]
    condition: Optional[Dict[str, Any]] = None  # 条件可见: {field, operator, value}
    depends_on: Optional[List[str]] = None
    validation: Optional[Dict[str, Any]] = None


@dataclass
class NodePort:
    """节点端口定义"""

    id: str
    label: str
    type: str = "any"
    required: bool = False
    multiple: bool = False


@dataclass
class NodeDefinition:
    """节点类型定义 — 注册表条目"""

    type: str  # "tool:web_search" | "skill:article" | "builtin:condition"
    label: str
    icon: str  # emoji 或图标名
    category: str  # NodeCategory.value
    description: str
    sub_blocks: List[SubBlockConfig]
    inputs: List[NodePort]
    outputs: List[NodePort]
    source: str = "builtin"  # tool|skill|mcp|builtin|custom
    source_id: Optional[str] = None
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    deprecated: bool = False
    # ── 自定义节点（source="custom"）扩展字段 ──
    tier: Optional[str] = None  # declarative(L1) | composite(L2) | code(L3)
    executor_body: Optional[Dict[str, Any]] = None  # L1: {template,...} L2: {steps}
    status: str = "active"  # draft|pending|active|rejected（审批流用）
    created_by: Optional[str] = None


@dataclass
class WorkflowNode:
    """工作流节点实例"""

    id: str
    type: str  # NodeDefinition.type
    position: Dict[str, float]  # {x, y}
    config: Dict[str, Any]  # SubBlockConfig 的值
    label: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    # P0 Step 3 — 调试 Mock 输出：节点级运行时短路值
    # 命中条件：mock_output is not None（None/未设=走真实 executor）
    mock_output: Optional[Any] = None


@dataclass
class WorkflowEdge:
    """工作流边（连接）"""

    id: str
    source: str
    target: str
    source_handle: Optional[str] = None  # "true"/"false"/"loop_body"/"loop_done"
    target_handle: Optional[str] = None
    label: Optional[str] = None
    condition: Optional[str] = None


@dataclass
class WorkflowVariable:
    """工作流变量"""

    name: str
    type: str  # string|number|boolean|json|array
    default_value: Optional[Any] = None
    description: Optional[str] = None
    scope: str = "workflow"  # workflow|execution|node


@dataclass
class WorkflowDefinition:
    """工作流定义（序列化格式）"""

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
        """序列化为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "variables": [v.__dict__ for v in self.variables],
            "tags": self.tags,
            "category": self.category,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "template": self.template,
            "public": self.public,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowDefinition":
        """从字典反序列化"""
        return cls(
            id=data["id"],
            name=data["name"],
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


@dataclass
class NodeExecutionResult:
    """节点执行结果"""

    node_id: str
    status: str  # success|failed|skipped|pending
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
    """工作流执行实例"""

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


@dataclass
class AgentInfo:
    """团队 Agent 信息"""

    agent_id: str
    name: str
    role: str
    config: Dict[str, Any] = field(default_factory=dict)
    flow_id: Optional[str] = None
    created_at: float = 0.0
    archived_at: Optional[float] = None
    status: str = "active"  # active|archived|deleted
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoreConnection:
    """已连接店铺注册表行（不含任何密钥字段 — 密钥仅存 SecretStore）

    时间戳沿用本模块 REAL 时间戳约定；extra 为非敏感扩展参数
    （如 TikTok shop_cipher），以 JSON 列持久化。
    """

    store_id: str
    platform: str
    store_name: str
    user_id: str = ""  # 归属用户（多用户隔离；空=历史全局通道）
    seller_id: str = ""
    marketplace_id: str = ""
    region: str = ""
    status: str = "pending"  # pending|active|expired|error
    last_error: str = ""
    token_expires_at: float = 0.0  # epoch 秒；0=长期（如亚马逊自授权 refresh_token）
    extra: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    last_used_at: float = 0.0


# 便捷导出
__all__ = [
    "WorkflowStatus",
    "NodeCategory",
    "SubBlockConfig",
    "NodePort",
    "NodeDefinition",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowVariable",
    "WorkflowDefinition",
    "NodeExecutionResult",
    "ExecutionInstance",
    "AgentInfo",
    "StoreConnection",
]
