"""
Neurflow — Neurova 协作系统的工作流模块

三面镜子架构：工作流是 Neurova 全部能力的可视化投射层
"""
from .models import (
    WorkflowStatus, NodeCategory, SubBlockConfig, NodePort,
    NodeDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowDefinition, NodeExecutionResult, ExecutionInstance, AgentInfo
)
from .storage import NeurflowStorage
from .node_registry import NodeRegistry, get_node_registry, reset_node_registry
from .dag import CycleDetector, TopologicalSorter, DAGValidator, get_dag_validator
from .variable_resolver import VariableResolver, ResolutionContext, get_variable_resolver
from .execution_engine import WorkflowExecutor, ExecutionStatus, ExecutionEventType, ExecutionEvent, get_workflow_executor
from .adapters import (
    TYPE_MAP, param_to_sub_block, tool_to_node, skill_to_node,
    mcp_tool_to_node, sync_all, sync_tools, sync_skills, sync_mcp
)
from .agent_manager import NeurflowAgentManager, get_agent_manager, reset_agent_manager
from .templates import TemplateRegistry, get_template_registry, reset_template_registry

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