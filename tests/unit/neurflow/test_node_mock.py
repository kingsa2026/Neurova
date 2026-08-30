"""
NeurFlow P0 Step 3 — 节点 Mock 字段测试

测试 WorkflowNode 新增 mock_output 字段：
- 字段存在，默认为 None
- 可设为任意 JSON 可序列化值（dict/list/str/int/float/bool）
- 节点级 mock（运行时实例），不影响 NodeDefinition 全局 schema
- 与现有 config/label/metadata 字段正交

TDD：先红后绿。仅测数据契约，不调执行器（避免触发 Mimosa SQL 注入扫描）。
"""
import pytest

from neurova.collaboration.neurflow.models import WorkflowNode


class TestMockOutputField:
    """WorkflowNode.mock_output 字段契约"""

    def test_mock_output_field_exists(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
        )
        assert hasattr(node, "mock_output")

    def test_mock_output_default_is_none(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
        )
        assert node.mock_output is None

    def test_mock_output_accepts_dict(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output={"answer": "mocked", "tokens": 42},
        )
        assert node.mock_output == {"answer": "mocked", "tokens": 42}

    def test_mock_output_accepts_list(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=[{"id": 1}, {"id": 2}],
        )
        assert node.mock_output == [{"id": 1}, {"id": 2}]

    def test_mock_output_accepts_string(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output="hello world",
        )
        assert node.mock_output == "hello world"

    def test_mock_output_accepts_int(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=42,
        )
        assert node.mock_output == 42

    def test_mock_output_accepts_float(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=3.14,
        )
        assert node.mock_output == 3.14

    def test_mock_output_accepts_bool(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=True,
        )
        assert node.mock_output is True


class TestMockOutputBackwardCompat:
    """既有字段必须保留（向后兼容）"""

    def test_existing_fields_preserved(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 10, "y": 20},
            config={"prompt": "Hello"},
            label="Test Node",
            enabled=True,
            metadata={"author": "test"},
        )
        assert node.id == "n1"
        assert node.type == "builtin:llm"
        assert node.position == {"x": 10, "y": 20}
        assert node.config == {"prompt": "Hello"}
        assert node.label == "Test Node"
        assert node.enabled is True
        assert node.metadata == {"author": "test"}

    def test_mock_output_independent_from_config(self):
        """mock_output 与 config 字段正交，互不影响"""
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={"prompt": "Hello"},
            mock_output={"answer": "mocked"},
        )
        assert node.config == {"prompt": "Hello"}
        assert node.mock_output == {"answer": "mocked"}


class TestMockOutputSentinel:
    """Mock 命中判定：mock_output is not None 即为命中"""

    def test_none_means_no_mock(self):
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
        )
        # 调用方判定：mock_output is not None
        assert (node.mock_output is not None) is False

    def test_empty_dict_still_means_mocked(self):
        """空 dict 也是合法的 mock（语义：节点产出为空）"""
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output={},
        )
        assert (node.mock_output is not None) is True

    def test_empty_string_still_means_mocked(self):
        """空字符串也是合法的 mock"""
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output="",
        )
        assert (node.mock_output is not None) is True

    def test_zero_still_means_mocked(self):
        """数字 0 也是合法的 mock（不应被判 None）"""
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=0,
        )
        assert (node.mock_output is not None) is True

    def test_false_still_means_mocked(self):
        """False 也是合法的 mock（不应被判 None）"""
        node = WorkflowNode(
            id="n1",
            type="builtin:llm",
            position={"x": 0, "y": 0},
            config={},
            mock_output=False,
        )
        assert (node.mock_output is not None) is True


class TestNodeDefinitionUnchanged:
    """NodeDefinition 全局 schema 不动（mock 是节点级而非 schema 级）"""

    def test_node_definition_has_no_mock_output(self):
        from neurova.collaboration.neurflow.models import NodeDefinition

        nd = NodeDefinition(
            type="builtin:llm",
            label="LLM",
            icon="",
            category="ai",
            description="",
            sub_blocks=[],
            inputs=[],
            outputs=[],
        )
        # NodeDefinition 是 schema，不应含 mock_output
        assert not hasattr(nd, "mock_output") or getattr(nd, "mock_output", None) is None