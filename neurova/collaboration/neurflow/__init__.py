"""
Neurflow — Neurova 协作系统的工作流模块

三面镜子架构：工作流是 Neurova 全部能力的可视化投射层
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

# 安全导入：任一子模块失败不阻塞整个包
try:
    from .models import (
        AgentInfo,
        ExecutionInstance,
        NodeCategory,
        NodeDefinition,
        NodeExecutionResult,
        NodePort,
        SubBlockConfig,
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
        WorkflowVariable,
    )
except ImportError as _e:
    _logger.debug("neurflow.models 未可用: %s", _e)

try:
    from .storage import NeurflowStorage
except ImportError as _e:
    _logger.debug("neurflow.storage 未可用: %s", _e)

try:
    from .node_registry import NodeRegistry, get_node_registry, reset_node_registry
except ImportError as _e:
    _logger.debug("neurflow.node_registry 未可用: %s", _e)

try:
    from .dag import CycleDetector, DAGValidator, TopologicalSorter, get_dag_validator
except ImportError as _e:
    _logger.debug("neurflow.dag 未可用: %s", _e)

try:
    from .variable_resolver import ResolutionContext, VariableResolver, get_variable_resolver
except ImportError as _e:
    _logger.debug("neurflow.variable_resolver 未可用: %s", _e)

try:
    from .execution_engine import (
        ExecutionEvent,
        ExecutionEventType,
        ExecutionStatus,
        WorkflowExecutor,
        get_workflow_executor,
    )
except ImportError as _e:
    _logger.debug("neurflow.execution_engine 未可用: %s", _e)

try:
    from .adapters import (
        TYPE_MAP,
        mcp_tool_to_node,
        param_to_sub_block,
        skill_to_node,
        sync_all,
        sync_mcp,
        sync_skills,
        sync_tools,
        tool_to_node,
    )
except ImportError as _e:
    _logger.debug("neurflow.adapters 未可用: %s", _e)

try:
    from .agent_manager import NeurflowAgentManager, get_agent_manager, reset_agent_manager
except ImportError as _e:
    _logger.debug("neurflow.agent_manager 未可用: %s", _e)

try:
    from .templates import TemplateRegistry, get_template_registry, reset_template_registry
except ImportError as _e:
    _logger.debug("neurflow.templates 未可用: %s", _e)

try:
    from .commerce_nodes import (
        COMMERCE_NODES,
        register_commerce_nodes,
        get_commerce_executors,
    )
except ImportError as _e:
    _logger.debug("neurflow.commerce_nodes 未可用: %s", _e)

try:
    from .drama_nodes import (
        DRAMA_NODES,
        register_drama_nodes,
        get_drama_executors,
    )
except ImportError as _e:
    _logger.debug("neurflow.drama_nodes 未可用: %s", _e)

__version__ = "1.0.0"

__all__ = [
    # 数据模型
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
    # 存储层
    "NeurflowStorage",
    # 节点注册表
    "NodeRegistry",
    "get_node_registry",
    "reset_node_registry",
    # DAG
    "CycleDetector",
    "TopologicalSorter",
    "DAGValidator",
    "get_dag_validator",
    # 变量解析
    "VariableResolver",
    "ResolutionContext",
    "get_variable_resolver",
    # 执行引擎
    "WorkflowExecutor",
    "ExecutionStatus",
    "ExecutionEventType",
    "ExecutionEvent",
    "get_workflow_executor",
    # 适配器
    "TYPE_MAP",
    "param_to_sub_block",
    "tool_to_node",
    "skill_to_node",
    "mcp_tool_to_node",
    "sync_all",
    "sync_tools",
    "sync_skills",
    "sync_mcp",
    # 团队 Agent 管理器
    "NeurflowAgentManager",
    "get_agent_manager",
    "reset_agent_manager",
    # 模板注册表
    "TemplateRegistry",
    "get_template_registry",
    "reset_template_registry",
    # 电商运营节点
    "COMMERCE_NODES",
    "register_commerce_nodes",
    "get_commerce_executors",
    # AI 短剧视频节点
    "DRAMA_NODES",
    "register_drama_nodes",
    "get_drama_executors",
    # 版本
    "__version__",
]
