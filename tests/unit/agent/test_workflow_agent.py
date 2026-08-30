"""
NeurFlow P2 Step 1+2 — 工作流→Agent 编译测试（AgentManifest）

契约（neurova/agent/workflow_agent.py）：
- AgentManifest dataclass：agent_id/name/workflow_id/entry_node_id/
  input_schema/output_schema/description
- compile_workflow_agent(workflow) → AgentManifest（纯函数）：
  - entry_node_id = 第一个 builtin:start 节点；缺失 → ValueError
  - input_schema 从 start.config 键推导；output_schema 从 end.config 推导
  - agent_id = f"wf_agent_{workflow.id}"
- manifest_to_agent_info(manifest) → AgentInfo：
  - metadata.source_type == "workflow"；metadata.workflow_id 回填
  - capabilities 含 "workflow"
- list_workflow_agents(agents) 过滤器：只留 source_type=workflow 的

TDD：先红后绿。纯数据契约，不调执行器。
"""
import pytest

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _make_workflow(workflow_id="wf_compile", with_start=True, with_end=True):
    nodes = []
    if with_start:
        nodes.append(WorkflowNode(
            id="start", type="builtin:start",
            position={"x": 0, "y": 0},
            config={"message": "", "channel": "chat"},
        ))
    nodes.append(WorkflowNode(
        id="llm1", type="builtin:llm",
        position={"x": 100, "y": 0}, config={"prompt": "hi"},
    ))
    if with_end:
        nodes.append(WorkflowNode(
            id="end", type="builtin:end",
            position={"x": 200, "y": 0}, config={"reply": ""},
        ))
    return WorkflowDefinition(
        id=workflow_id,
        name="编译测试工作流",
        description="用于 manifest 编译",
        version="1.0.0",
        nodes=nodes,
        edges=[
            WorkflowEdge(id="e1", source="start", target="llm1"),
            WorkflowEdge(id="e2", source="llm1", target="end"),
        ],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


class TestAgentManifestModel:
    def test_manifest_importable(self):
        from neurova.agent.workflow_agent import AgentManifest

        assert AgentManifest is not None

    def test_manifest_fields(self):
        from neurova.agent.workflow_agent import AgentManifest

        m = AgentManifest(
            agent_id="wf_agent_x",
            name="n",
            workflow_id="wf_x",
            entry_node_id="start",
        )
        assert m.input_schema == {}
        assert m.output_schema == {}
        assert m.description == ""


class TestCompileWorkflowAgent:
    def test_compile_importable(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        assert callable(compile_workflow_agent)

    def test_compile_extracts_entry_node(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow())
        assert m.entry_node_id == "start"

    def test_compile_agent_id_convention(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow("wf_abc"))
        assert m.agent_id == "wf_agent_wf_abc"

    def test_compile_name_from_workflow(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow())
        assert m.name == "编译测试工作流"

    def test_compile_input_schema_from_start_config(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow())
        assert "message" in m.input_schema
        assert "channel" in m.input_schema

    def test_compile_output_schema_from_end_config(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow())
        assert "reply" in m.output_schema

    def test_compile_without_start_raises(self):
        from neurova.agent.workflow_agent import compile_workflow_agent

        with pytest.raises(ValueError):
            compile_workflow_agent(_make_workflow(with_start=False))

    def test_compile_without_end_ok_empty_output(self):
        """无 end 节点：output_schema 为空（不报错）"""
        from neurova.agent.workflow_agent import compile_workflow_agent

        m = compile_workflow_agent(_make_workflow(with_end=False))
        assert m.output_schema == {}


class TestManifestToAgentInfo:
    def test_to_agent_info_marks_source(self):
        from neurova.agent.workflow_agent import compile_workflow_agent, manifest_to_agent_info

        manifest = compile_workflow_agent(_make_workflow())
        info = manifest_to_agent_info(manifest)

        assert info.agent_id == manifest.agent_id
        assert info.name == manifest.name
        assert info.metadata.get("source_type") == "workflow"
        assert info.metadata.get("workflow_id") == manifest.workflow_id
        assert "workflow" in info.capabilities

    def test_to_agent_info_role(self):
        from neurova.agent.workflow_agent import compile_workflow_agent, manifest_to_agent_info

        info = manifest_to_agent_info(compile_workflow_agent(_make_workflow()))
        assert info.role  # 非空角色描述


class TestListWorkflowAgents:
    def test_filter_keeps_only_workflow_agents(self):
        from neurova.agent.workflow_agent import list_workflow_agents
        from neurova.collaboration.neurflow.models import AgentInfo

        wf_agent = AgentInfo(
            agent_id="wf_agent_1", name="a", role="workflow",
            metadata={"source_type": "workflow", "workflow_id": "wf_1"},
        )
        manual_agent = AgentInfo(agent_id="manual_1", name="b", role="chat")
        got = list_workflow_agents([wf_agent, manual_agent])
        assert [a.agent_id for a in got] == ["wf_agent_1"]