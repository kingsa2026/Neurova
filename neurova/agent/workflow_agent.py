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
