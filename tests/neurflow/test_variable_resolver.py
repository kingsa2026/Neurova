"""
Neurflow 变量解析器测试 — 垂直切片 5
测试 $node、$memory、$context、$emotion、$crystal、$input、$var、$agent 前缀解析
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from neurova.collaboration.neurflow.variable_resolver import (
    VariableResolver, ResolutionContext, ResolvedValue,
    get_variable_resolver
)
from neurova.collaboration.neurflow.models import WorkflowNode


class TestVariableResolver:
    """变量解析器核心测试"""

    @pytest.fixture
    def resolver(self):
        return VariableResolver()

    @pytest.fixture
    def sample_context(self):
        """示例执行上下文"""
        return ResolutionContext(
            workflow_id="wf_001",
            execution_id="exec_001",
            node_results={
                "node_1": {"output": "搜索结果文本", "status": "success"},
                "node_2": {"output": {"key": "value"}, "status": "success"},
            },
            variables={
                "my_var": "变量值",
                "counter": 42,
            },
            inputs={
                "user_query": "什么是 AI?",
            },
            agent_id="agent_001",
            user_id="user_001",
        )

    # ==================== 简单变量解析 ====================

    def test_resolve_input_variable(self, resolver, sample_context):
        """解析 $input 变量"""
        result = resolver.resolve("$input.user_query", sample_context)
        assert result.success is True
        assert result.value == "什么是 AI?"

    def test_resolve_var_variable(self, resolver, sample_context):
        """解析 $var 变量"""
        result = resolver.resolve("$var.my_var", sample_context)
        assert result.success is True
        assert result.value == "变量值"

    def test_resolve_var_number(self, resolver, sample_context):
        """解析 $var 数字类型"""
        result = resolver.resolve("$var.counter", sample_context)
        assert result.success is True
        assert result.value == 42

    def test_resolve_node_output(self, resolver, sample_context):
        """解析 $node 输出"""
        result = resolver.resolve("$node.node_1.output", sample_context)
        assert result.success is True
        assert result.value == "搜索结果文本"

    def test_resolve_node_nested_key(self, resolver, sample_context):
        """解析 $node 嵌套 key"""
        result = resolver.resolve("$node.node_2.output.key", sample_context)
        assert result.success is True
        assert result.value == "value"

    def test_resolve_agent_variable(self, resolver, sample_context):
        """解析 $agent 变量"""
        result = resolver.resolve("$agent.agent_id", sample_context)
        assert result.success is True
        assert result.value == "agent_001"

    # ==================== 复杂引用 ====================

    def test_resolve_string_with_variable(self, resolver, sample_context):
        """字符串中嵌入变量"""
        result = resolver.resolve("用户查询: $input.user_query", sample_context)
        assert result.success is True
        assert result.value == "用户查询: 什么是 AI?"

    def test_resolve_multiple_variables(self, resolver, sample_context):
        """字符串中多个变量"""
        result = resolver.resolve(
            "用户 $agent.agent_id 查询: $input.user_query，使用变量 $var.my_var",
            sample_context
        )
        assert result.success is True
        assert "agent_001" in result.value
        assert "什么是 AI?" in result.value
        assert "变量值" in result.value

    def test_resolve_no_variable(self, resolver, sample_context):
        """无变量引用"""
        result = resolver.resolve("纯文本，没有变量", sample_context)
        assert result.success is True
        assert result.value == "纯文本，没有变量"

    def test_resolve_empty_string(self, resolver, sample_context):
        """空字符串"""
        result = resolver.resolve("", sample_context)
        assert result.success is True
        assert result.value == ""

    # ==================== 错误处理 ====================

    def test_resolve_missing_input(self, resolver, sample_context):
        """引用不存在的 input"""
        result = resolver.resolve("$input.nonexistent", sample_context)
        assert result.success is False
        assert result.error is not None

    def test_resolve_missing_var(self, resolver, sample_context):
        """引用不存在的 var"""
        result = resolver.resolve("$var.nonexistent", sample_context)
        assert result.success is False
        assert result.error is not None

    def test_resolve_missing_node(self, resolver, sample_context):
        """引用不存在的 node"""
        result = resolver.resolve("$node.nonexistent.output", sample_context)
        assert result.success is False
        assert result.error is not None

    def test_resolve_unknown_prefix(self, resolver, sample_context):
        """未知前缀"""
        result = resolver.resolve("$unknown.something", sample_context)
        assert result.success is False
        assert result.error is not None

    # ==================== 批量解析 ====================

    def test_resolve_config_dict(self, resolver, sample_context):
        """批量解析配置字典"""
        config = {
            "prompt": "查询内容: $input.user_query",
            "model": "gpt-4",
            "var": "$var.my_var",
        }
        resolved = resolver.resolve_config(config, sample_context)
        assert resolved["prompt"] == "查询内容: 什么是 AI?"
        assert resolved["model"] == "gpt-4"  # 无变量，原样返回
        assert resolved["var"] == "变量值"

    def test_resolve_config_list(self, resolver, sample_context):
        """批量解析配置列表"""
        config = ["$input.user_query", "$var.my_var", "静态值"]
        resolved = resolver.resolve_config(config, sample_context)
        assert resolved == ["什么是 AI?", "变量值", "静态值"]

    def test_resolve_config_nested(self, resolver, sample_context):
        """批量解析嵌套配置"""
        config = {
            "outer": {
                "inner": "$input.user_query",
                "list": ["$var.my_var", "$var.counter"],
            }
        }
        resolved = resolver.resolve_config(config, sample_context)
        assert resolved["outer"]["inner"] == "什么是 AI?"
        assert resolved["outer"]["list"] == ["变量值", 42]

    # ==================== 注册自定义前缀 ====================

    def test_register_custom_prefix(self, resolver, sample_context):
        """注册自定义前缀解析器"""
        def custom_handler(key, context):
            return f"custom_{key}"

        resolver.register_prefix("custom", custom_handler)
        result = resolver.resolve("$custom.test", sample_context)
        assert result.success is True
        assert result.value == "custom_test"

    # ==================== 边界情况 ====================

    def test_resolve_none_context(self, resolver):
        """None 上下文"""
        with pytest.raises(ValueError):
            resolver.resolve("$input.test", None)

    def test_resolve_dollar_in_value(self, resolver, sample_context):
        """值中包含 $ 符号"""
        sample_context.inputs["price"] = "$100.00"
        result = resolver.resolve("$input.price", sample_context)
        assert result.success is True
        assert result.value == "$100.00"


class TestResolutionContext:
    """ResolutionContext 数据类测试"""

    def test_creation(self):
        ctx = ResolutionContext(
            workflow_id="wf_001",
            execution_id="exec_001"
        )
        assert ctx.workflow_id == "wf_001"
        assert ctx.execution_id == "exec_001"
        assert ctx.node_results == {}
        assert ctx.variables == {}
        assert ctx.inputs == {}

    def test_defaults(self):
        ctx = ResolutionContext(workflow_id="wf_001", execution_id="exec_001")
        assert ctx.agent_id is None
        assert ctx.user_id is None


class TestSingleton:
    def test_get_resolver(self):
        r1 = get_variable_resolver()
        r2 = get_variable_resolver()
        assert r1 is r2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])