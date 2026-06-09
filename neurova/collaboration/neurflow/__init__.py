"""
Neurflow — Neurova 协作系统的工作流模块

三面镜子架构：工作流是 Neurova 全部能力的可视化投射层
"""
import logging

_logger = logging.getLogger(__name__)

# 安全导入：任一子模块失败不阻塞整个包
try:
    from .models import (
        WorkflowStatus, NodeCategory, SubBlockConfig, NodePort,
        NodeDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
        WorkflowDefinition, NodeExecutionResult, ExecutionInstance, AgentInfo
    )
except ImportError as _e:
    _logger.debug(f"neurflow.models 未可用: {_e}")

try:
    from .storage import NeurflowStorage
except ImportError as _e:
    _logger.debug(f"neurflow.storage 未可用: {_e}")

try:
    from .node_registry import NodeRegistry, get_node_registry, reset_node_registry
except ImportError as _e:
    _logger.debug(f"neurflow.node_registry 未可用: {_e}")

try:
    from .dag import CycleDetector, TopologicalSorter, DAGValidator, get_dag_validator
except ImportError as _e:
    _logger.debug(f"neurflow.dag 未可用: {_e}")

try:
    from .variable_resolver import VariableResolver, ResolutionContext, get_variable_resolver
except ImportError as _e:
    _logger.debug(f"neurflow.variable_resolver 未可用: {_e}")

try:
    from .execution_engine import WorkflowExecutor, ExecutionStatus, ExecutionEventType, ExecutionEvent, get_workflow_executor
except ImportError as _e:
    _logger.debug(f"neurflow.execution_engine 未可用: {_e}")

try:
    from .adapters import (
        TYPE_MAP, param_to_sub_block, tool_to_node, skill_to_node,
        mcp_tool_to_node, sync_all, sync_tools, sync_skills, sync_mcp
    )
except ImportError as _e:
    _logger.debug(f"neurflow.adapters 未可用: {_e}")

try:
    from .agent_manager import NeurflowAgentManager, get_agent_manager, reset_agent_manager
except ImportError as _e:
    _logger.debug(f"neurflow.agent_manager 未可用: {_e}")

try:
    from .templates import TemplateRegistry, get_template_registry, reset_template_registry
except ImportError as _e:
    _logger.debug(f"neurflow.templates 未可用: {_e}")

__version__ = "0.1.0"

__all__ = [
    # 数据模型
    "WorkflowStatus", "NodeCategory", "SubBlockConfig", "NodePort",
    "NodeDefinition", "WorkflowNode", "WorkflowEdge", "WorkflowVariable",
    "WorkflowDefinition", "NodeExecutionResult", "ExecutionInstance", "AgentInfo",
    
    # 存储层
    "NeurflowStorage",
    
    # 节点注册表
    "NodeRegistry", "get_node_registry", "reset_node_registry",
    
    # DAG
    "CycleDetector", "TopologicalSorter", "DAGValidator", "get_dag_validator",
    
    # 变量解析
    "VariableResolver", "ResolutionContext", "get_variable_resolver",
    
    # 执行引擎
    "WorkflowExecutor", "ExecutionStatus", "ExecutionEventType", "ExecutionEvent", "get_workflow_executor",
    
    # 适配器
    "TYPE_MAP", "param_to_sub_block", "tool_to_node", "skill_to_node",
    "mcp_tool_to_node", "sync_all", "sync_tools", "sync_skills", "sync_mcp",
    
    # 团队 Agent 管理器
    "NeurflowAgentManager", "get_agent_manager", "reset_agent_manager",
    
    # 模板注册表
    "TemplateRegistry", "get_template_registry", "reset_template_registry",
    
    # 版本
    "__version__"
]
