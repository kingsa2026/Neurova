"""
节点配置校验器测试 — 执行前硬失败拦截（弹窗数据源）

契约（neurova/collaboration/neurflow/validation.py）：
- validate_node_configs 收集全图缺失（字段级 missing 清单 + 人类可读 message）
- llm/variable/transform/subflow/agent/approval/human_input 特例规则
- condition 有空默认值（expression=""→"True"）不告警
- 0/False 合法值不误报；已填字段不报
- issues_to_payload 输出前端可直接渲染的清单结构

TDD：先红后绿。
"""
import pytest

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)
from neurova.collaboration.neurflow.validation import (
    NodeConfigIssue,
    issues_to_payload,
    validate_node_configs,
)


def _make_workflow(nodes, workflow_id="wf_val"):
    return WorkflowDefinition(
        id=workflow_id,
        name="val",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=[],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


def _node(nid, ntype, config, label=None):
    return WorkflowNode(id=nid, type=ntype, position={"x": 0, "y": 0},
                        config=config, label=label)


class TestSpecialRules:
    def test_llm_missing_prompt_reported_with_field(self):
        issues = validate_node_configs(_make_workflow([
            _node("llm1", "builtin:llm", {}, "LLM1"),
        ]))
        assert len(issues) == 1
        i = issues[0]
        assert i.node_id == "llm1"
        assert "prompt" in i.missing[0]
        assert "LLM1" in i.message

    def test_llm_valid_prompt_passes(self):
        issues = validate_node_configs(_make_workflow([
            _node("llm1", "builtin:llm", {"prompt": "hi"}),
        ]))
        assert issues == []

    def test_llm_blank_prompt_reported(self):
        issues = validate_node_configs(_make_workflow([
            _node("llm1", "builtin:llm", {"prompt": "   "}),
        ]))
        assert len(issues) == 1

    def test_variable_requires_name(self):
        issues = validate_node_configs(_make_workflow([
            _node("v1", "builtin:variable", {"value": 1}),
        ]))
        assert issues and "name" in issues[0].missing[0]

    def test_subflow_requires_workflow_id(self):
        issues = validate_node_configs(_make_workflow([
            _node("s1", "builtin:subflow", {"input_mapping": "{}"}),
        ]))
        assert issues and "workflow_id" in issues[0].missing[0]

    def test_agent_requires_agent_id_and_task(self):
        issues = validate_node_configs(_make_workflow([
            _node("a1", "builtin:agent", {"agent_id": "default"}),
        ]))
        assert len(issues) == 1
        assert len(issues[0].missing) == 1  # task 缺

    def test_approval_requires_approver(self):
        issues = validate_node_configs(_make_workflow([
            _node("ap1", "builtin:approval", {"message": "ok"}),
        ]))
        assert issues and "approver" in issues[0].missing[0]

    def test_condition_empty_expression_is_ok(self):
        """condition 有默认 True：空 expression 不是缺失"""
        issues = validate_node_configs(_make_workflow([
            _node("c1", "builtin:condition", {}),
        ]))
        assert issues == []


class TestFalseyValues:
    def test_zero_and_false_not_reported(self):
        issues = validate_node_configs(_make_workflow([
            _node("v1", "builtin:variable", {"name": "x", "value": 0}),
            _node("tr1", "builtin:transform", {"expression": ""}),
        ]))
        # v1 合法；transform expression 空 → 报
        assert len(issues) == 1
        assert issues[0].node_id == "tr1"


class TestPayload:
    def test_issues_to_payload_shape(self):
        issue = NodeConfigIssue(node_id="llm1", label="LLM1", type="builtin:llm",
                                missing=["提示词（prompt）"], message="节点「LLM1」配置缺失: 提示词（prompt）")
        payload = issues_to_payload([issue])
        assert payload["code"] == 1
        assert "停止执行" in payload["message"]
        assert payload["errors"][0]["node_id"] == "llm1"
        assert payload["errors"][0]["missing"] == ["提示词（prompt）"]
