"""
NeurFlow P2-4.3 — 子工作流（subflow）核心逻辑测试

契约（neurova/collaboration/neurflow/subflow.py）：
- resolve_input_mapping(mapping, inputs, node_results)：
  "$input.key" → inputs[key]；"$node.nid.key" → node_results[nid].output[key]；
  普通值原样透传
- check_subflow_depth(depth, max_depth=5)：超限抛 SubflowDepthExceeded
- check_subflow_cycle(workflow_id, ancestor_chain)：成环抛 SubflowCycleDetected
- validate_subflow_config(config)：缺 workflow_id 抛 ValueError

TDD：先红后绿。纯函数，无存储/引擎依赖。
"""
import pytest

from neurova.collaboration.neurflow.subflow import (
    SubflowCycleDetected,
    SubflowDepthExceeded,
    check_subflow_cycle,
    check_subflow_depth,
    resolve_input_mapping,
    validate_subflow_config,
)


class TestResolveInputMapping:
    def test_plain_values_passthrough(self):
        mapping = {"k": "static"}
        assert resolve_input_mapping(mapping, {}, {}) == {"k": "static"}

    def test_input_prefix_resolves(self):
        mapping = {"msg": "$input.query"}
        assert resolve_input_mapping(mapping, {"query": "hi"}, {}) == {"msg": "hi"}

    def test_node_prefix_resolves_from_node_results(self):
        node_results = {"n1": {"output": {"answer": "42"}}}
        mapping = {"val": "$node.n1.answer"}
        assert resolve_input_mapping(mapping, {}, node_results) == {"val": "42"}

    def test_missing_source_resolves_none(self):
        mapping = {"msg": "$input.nope"}
        assert resolve_input_mapping(mapping, {}, {})["msg"] is None

    def test_empty_mapping_returns_empty(self):
        assert resolve_input_mapping({}, {"a": 1}, {}) == {}


class TestSubflowDepth:
    def test_within_depth_ok(self):
        check_subflow_depth(0)
        check_subflow_depth(4)

    def test_at_max_depth_rejected(self):
        with pytest.raises(SubflowDepthExceeded):
            check_subflow_depth(5)

    def test_custom_max_depth(self):
        check_subflow_depth(2, max_depth=3)
        with pytest.raises(SubflowDepthExceeded):
            check_subflow_depth(3, max_depth=3)


class TestSubflowCycle:
    def test_no_cycle_passes(self):
        check_subflow_cycle("wf_c", {"wf_a", "wf_b"})

    def test_self_reference_detected(self):
        with pytest.raises(SubflowCycleDetected):
            check_subflow_cycle("wf_a", {"wf_a"})

    def test_mutual_cycle_detected(self):
        with pytest.raises(SubflowCycleDetected):
            check_subflow_cycle("wf_b", {"wf_a", "wf_b"})


class TestValidateSubflowConfig:
    def test_valid_config_passes(self):
        validate_subflow_config({"workflow_id": "wf_1"})

    def test_missing_workflow_id_raises(self):
        with pytest.raises(ValueError):
            validate_subflow_config({})

    def test_blank_workflow_id_raises(self):
        with pytest.raises(ValueError):
            validate_subflow_config({"workflow_id": ""})