"""
工作流 → Agent 编译（P2 Step 1+2）

把已发布的 WorkflowDefinition 编译为 AgentManifest，并落到 agents 表
（AgentInfo.metadata.source_type = "workflow"），使 chat 页可作为 Agent 选用。
纯函数 + 工厂，不直接依赖存储/引擎。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from neurova.collaboration.neurflow.models import AgentInfo, WorkflowDefinition

logger = logging.getLogger(__name__)

_SOURCE_TYPE = "workflow"


@dataclass
class AgentManifest:
    """工作流 Agent 的发布清单（publish 端点产物）。"""

    agent_id: str
    name: str
    workflow_id: str
    entry_node_id: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


def compile_workflow_agent(workflow: WorkflowDefinition) -> AgentManifest:
    """从 WorkflowDefinition 编译 AgentManifest。

    规则：
    - entry_node_id：第一个 builtin:start 节点（缺失抛 ValueError）
    - input_schema：start 节点 config 的键集合
    - output_schema：end 节点 config 的键集合（无 end 则为空）
    """
    start = next(
        (n for n in workflow.nodes if n.type == "builtin:start"),
        None,
    )
    if start is None:
        raise ValueError("workflow has no start node; cannot compile to agent")

    end = next((n for n in workflow.nodes if n.type == "builtin:end"), None)

    return AgentManifest(
        agent_id=f"wf_agent_{workflow.id}",
        name=workflow.name,
        workflow_id=workflow.id,
        entry_node_id=start.id,
        input_schema={k: {"type": "string"} for k in (start.config or {}).keys()},
        output_schema={k: {"type": "string"} for k in (end.config or {}).keys()} if end else {},
        description=workflow.description or "",
    )


def manifest_to_agent_info(manifest: AgentManifest) -> AgentInfo:
    """把 manifest 落成 agents 表记录（source_type=workflow 标记）。"""
    return AgentInfo(
        agent_id=manifest.agent_id,
        name=manifest.name,
        role="workflow-triggered agent",
        config={
            "entry_node_id": manifest.entry_node_id,
            "input_schema": manifest.input_schema,
            "output_schema": manifest.output_schema,
        },
        metadata={
            "source_type": _SOURCE_TYPE,
            "workflow_id": manifest.workflow_id,
        },
        capabilities=["workflow"],
    )


def list_workflow_agents(agents: List[AgentInfo]) -> List[AgentInfo]:
    """从 agent 列表过滤出工作流 Agent（chat 页选择器用）。"""
    return [
        a
        for a in agents
        if (a.metadata or {}).get("source_type") == _SOURCE_TYPE
    ]


# deps 工厂注册表（装配方启动时注入；本模块零存储 import）
_deps_provider = None


def set_workflow_agent_deps(provider) -> None:
    """注册默认 deps 工厂（应用启动装配时调用一次）。"""
    global _deps_provider
    _deps_provider = provider


async def execute_workflow_agent(
    agent_id: str,
    inputs: Dict[str, Any],
    deps: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """chat 侧派发桥接（P2 Step 4）：按 agent_id 找到绑定的工作流并执行。

    deps 键（可注入；缺省走 set_workflow_agent_deps 注册的工厂）：
      load_agent(agent_id) → AgentInfo | None
      load_published_workflow(workflow_id) → WorkflowDefinition | None
      run_workflow(workflow, inputs) → ExecutionInstance（awaitable）

    返回统一信封：{success, outputs[, error, execution_id]}。
    本函数不触碰 chat_pipeline 主干——接入点由 tool_executor 层调用。
    """
    if deps is None:
        if _deps_provider is None:
            return {"success": False, "error": "WORKFLOW_AGENT_DEPS_NOT_CONFIGURED"}
        deps = _deps_provider()

    agent = deps["load_agent"](agent_id)
    if agent is None:
        return {"success": False, "error": "AGENT_NOT_FOUND"}
    if (agent.metadata or {}).get("source_type") != _SOURCE_TYPE:
        return {"success": False, "error": "NOT_A_WORKFLOW_AGENT"}

    workflow_id = agent.metadata.get("workflow_id")
    workflow = deps["load_published_workflow"](workflow_id)
    if workflow is None:
        return {"success": False, "error": "WORKFLOW_NOT_PUBLISHED"}

    instance = await deps["run_workflow"](workflow, inputs)
    status_value = getattr(instance, "status", None)
    return {
        "success": getattr(status_value, "value", "") == "completed",
        "outputs": getattr(instance, "outputs", None),
        "error": getattr(instance, "error", None),
        "execution_id": getattr(instance, "id", None),
    }
