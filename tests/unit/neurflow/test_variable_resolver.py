"""
Neurflow 变量解析器测试
测试 $memory, $context, $emotion, $crystal 前缀支持
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from neurova.collaboration.neurflow.variable_resolver import (
    VariableResolver, ResolutionContext, ResolvedValue,
    get_variable_resolver
)


class TestResolutionContext:
    """ResolutionContext 数据类测试"""

    def test_defaults(self):
        """测试默认值"""
        ctx = ResolutionContext(
            workflow_id="wf_1",
            execution_id="exec_1"
        )
        assert ctx.workflow_id == "wf_1"
        assert ctx.execution_id == "exec_1"
        assert ctx.node_results == {}
        assert ctx.variables == {}
        assert ctx.inputs == {}
        assert ctx.agent_id is None
        assert ctx.user_id is None
        assert ctx.memory_manager is None
        assert ctx.context_pool is None
        assert ctx.emotion_module is None
        assert ctx.crystallizer is None

    def test_with_all_fields(self):
        """测试所有字段"""
        mock_memory = MagicMock()
        mock_context = MagicMock()
        mock_emotion = MagicMock()
        mock_crystal = MagicMock()

        ctx = ResolutionContext(
            workflow_id="wf_1",
            execution_id="exec_1",
            node_results={"n1": {"output": "test"}},
            variables={"max_iter": 10},
            inputs={"query": "hello"},
            agent_id="agent_1",
            user_id="user_1",
            memory_manager=mock_memory,
            context_pool=mock_context,
            emotion_module=mock_emotion,
            crystallizer=mock_crystal
        )

        assert ctx.memory_manager is mock_memory
        assert ctx.context_pool is mock_context
        assert ctx.emotion_module is mock_emotion
        assert ctx.crystallizer is mock_crystal


class TestVariableResolverPrefixes:
    """变量解析器前缀测试"""

    @pytest.fixture
    def resolver(self):
        """创建解析器实例"""
        return VariableResolver()

    @pytest.fixture
    def mock_memory_manager(self):
        """模拟记忆管理器"""
        mock = MagicMock()
        # 优先使用 search_memories/get_memory（真实 MemoryManager 接口）
        mock.search_memories.return_value = [
            {"content": "上周会议讨论了Q2目标", "score": 0.95},
            {"content": "会议决定增加预算", "score": 0.85}
        ]
        mock.get_memory.return_value = {"content": "特定记忆内容", "metadata": {"type": "fact"}}
        return mock

    @pytest.fixture
    def mock_context_pool(self):
        """模拟上下文池"""
        mock = MagicMock()
        mock.get_context.return_value = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": [{"role": "user", "content": "hello"}],
            "token_count": 150
        }
        return mock

    @pytest.fixture
    def mock_emotion_module(self):
        """模拟情感模块"""
        mock = MagicMock()
        mock.current.return_value = {
            "valence": 0.8,
            "arousal": 0.6,
            "dominance": 0.7,
            "primary_emotion": "joy"
        }
        return mock

    @pytest.fixture
    def mock_crystallizer(self):
        """模拟结晶器"""
        mock = MagicMock()
        mock.retrieve.return_value = [
            {"pattern": "写作技巧", "confidence": 0.9, "content": "使用清晰的结构"},
            {"pattern": "写作风格", "confidence": 0.8, "content": "保持简洁"}
        ]
        return mock

    @pytest.fixture
    def full_context(self, mock_memory_manager, mock_context_pool, mock_emotion_module, mock_crystallizer):
        """完整上下文"""
        return ResolutionContext(
            workflow_id="wf_1",
            execution_id="exec_1",
            inputs={"query": "帮我写一篇文章"},
            variables={"style": "formal"},
            memory_manager=mock_memory_manager,
            context_pool=mock_context_pool,
            emotion_module=mock_emotion_module,
            crystallizer=mock_crystallizer
        )

    # === $memory 前缀测试 ===

    def test_memory_search(self, resolver, full_context, mock_memory_manager):
        """测试 $memory.query 搜索记忆"""
        result = resolver.resolve("$memory.last_week_meeting", full_context)

        assert result.success is True
        mock_memory_manager.search_memories.assert_called_once_with("last_week_meeting")
        assert len(result.value) == 2
        assert result.value[0]["content"] == "上周会议讨论了Q2目标"

    def test_memory_search_no_path(self, resolver, full_context):
        """测试 $memory 无路径（返回 None）"""
        result = resolver.resolve("$memory", full_context)
        # 无路径时返回整个 memory_manager 对象
        assert result.success is True
        assert result.value is full_context.memory_manager

    def test_memory_search_no_manager(self, resolver):
        """测试无 memory_manager 时返回失败"""
        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$memory.test", ctx)

        assert result.success is False
        # 返回 None 导致 "未找到" 错误
        assert "未找到" in result.error

    def test_memory_get_specific(self, resolver, full_context, mock_memory_manager):
        """测试 $memory.get.id 获取特定记忆"""
        mock_memory_manager.get_memory.return_value = {"content": "特定内容"}

        result = resolver.resolve("$memory.get.mem_123", full_context)

        assert result.success is True
        mock_memory_manager.get_memory.assert_called_once_with("mem_123")

    def test_memory_search_empty_results(self, resolver, full_context, mock_memory_manager):
        """测试搜索返回空结果"""
        mock_memory_manager.search_memories.return_value = []

        result = resolver.resolve("$memory.nonexistent", full_context)

        assert result.success is True
        assert result.value == []

    # === $context 前缀测试 ===

    def test_context_get_all(self, resolver, full_context, mock_context_pool):
        """测试 $context 获取完整上下文"""
        result = resolver.resolve("$context", full_context)

        assert result.success is True
        mock_context_pool.get_context.assert_called_once()
        assert "system_prompt" in result.value

    def test_context_get_path(self, resolver, full_context, mock_context_pool):
        """测试 $context.system_prompt 获取特定路径"""
        result = resolver.resolve("$context.system_prompt", full_context)

        assert result.success is True
        assert result.value == "你是一个AI助手"

    def test_context_get_nested(self, resolver, full_context, mock_context_pool):
        """测试 $context.recent_messages.0 获取嵌套值"""
        result = resolver.resolve("$context.recent_messages.0.content", full_context)

        assert result.success is True
        assert result.value == "hello"

    def test_context_no_pool(self, resolver):
        """测试无 context_pool 时返回失败"""
        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$context", ctx)

        assert result.success is False
        assert "未找到" in result.error

    # === $emotion 前缀测试 ===

    def test_emotion_get_all(self, resolver, full_context, mock_emotion_module):
        """测试 $emotion 获取完整情感状态"""
        result = resolver.resolve("$emotion", full_context)

        assert result.success is True
        mock_emotion_module.current.assert_called_once()
        assert result.value["primary_emotion"] == "joy"

    def test_emotion_get_valence(self, resolver, full_context, mock_emotion_module):
        """测试 $emotion.valence 获取情感效价"""
        result = resolver.resolve("$emotion.valence", full_context)

        assert result.success is True
        assert result.value == 0.8

    def test_emotion_get_primary(self, resolver, full_context, mock_emotion_module):
        """测试 $emotion.primary_emotion 获取主要情感"""
        result = resolver.resolve("$emotion.primary_emotion", full_context)

        assert result.success is True
        assert result.value == "joy"

    def test_emotion_no_module(self, resolver):
        """测试无 emotion_module 时返回失败"""
        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$emotion.valence", ctx)

        assert result.success is False
        assert "未找到" in result.error

    # === $crystal 前缀测试 ===

    def test_crystal_retrieve(self, resolver, full_context, mock_crystallizer):
        """测试 $crystal.writing_tips 检索结晶经验"""
        result = resolver.resolve("$crystal.writing_tips", full_context)

        assert result.success is True
        mock_crystallizer.retrieve.assert_called_once_with("writing_tips")
        assert len(result.value) == 2

    def test_crystal_retrieve_no_path(self, resolver, full_context):
        """测试 $crystal 无路径"""
        result = resolver.resolve("$crystal", full_context)

        # 无路径时返回整个 crystallizer 对象
        assert result.success is True
        assert result.value is full_context.crystallizer

    def test_crystal_no_crystallizer(self, resolver):
        """测试无 crystallizer 时返回失败"""
        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$crystal.test", ctx)

        assert result.success is False
        assert "未找到" in result.error

    def test_crystal_empty_results(self, resolver, full_context, mock_crystallizer):
        """测试结晶经验为空"""
        mock_crystallizer.retrieve.return_value = []

        result = resolver.resolve("$crystal.nonexistent", full_context)

        assert result.success is True
        assert result.value == []

    # === 混合使用测试 ===

    def test_mixed_prefixes_in_text(self, resolver, full_context):
        """测试文本中混合多个前缀"""
        text = "基于$emotion.primary_emotion的情感，检索$memory.related_memories"
        result = resolver.resolve(text, full_context)

        assert result.success is True
        assert "joy" in result.value
        assert "上周会议讨论了Q2目标" in result.value

    def test_mixed_in_config(self, resolver, full_context):
        """测试配置中混合多个前缀"""
        config = {
            "prompt": "当前情感: $emotion.primary_emotion",
            "context": "$context.system_prompt",
            "memories": "$memory.related_memories",
            "static": "不变的值"
        }

        resolved = resolver.resolve_config(config, full_context)

        assert resolved["prompt"] == "当前情感: joy"
        assert resolved["context"] == "你是一个AI助手"
        assert len(resolved["memories"]) == 2
        assert resolved["static"] == "不变的值"

    # === 错误处理测试 ===

    def test_unknown_prefix(self, resolver, full_context):
        """测试未知前缀"""
        result = resolver.resolve("$unknown.value", full_context)

        assert result.success is False
        assert "未知" in result.error

    def test_handler_exception(self, resolver, full_context, mock_memory_manager):
        """测试处理器抛出异常"""
        mock_memory_manager.search_memories.side_effect = RuntimeError("数据库连接失败")

        result = resolver.resolve("$memory.test", full_context)

        assert result.success is False
        assert "数据库连接失败" in result.error


class TestVariableResolverSingleton:
    """单例测试"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        resolver1 = get_variable_resolver()
        resolver2 = get_variable_resolver()
        assert resolver1 is resolver2

    def test_has_new_prefixes(self):
        """测试单例包含新前缀"""
        resolver = get_variable_resolver()
        assert "memory" in resolver._prefix_handlers
        assert "context" in resolver._prefix_handlers
        assert "emotion" in resolver._prefix_handlers
        assert "crystal" in resolver._prefix_handlers


class TestCustomPrefixRegistration:
    """自定义前缀注册测试"""

    def test_register_custom_prefix(self):
        """测试注册自定义前缀"""
        resolver = VariableResolver()

        def custom_handler(path, context):
            return f"custom:{path}"

        resolver.register_prefix("custom", custom_handler)

        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$custom.test", ctx)

        assert result.success is True
        assert result.value == "custom:test"

    def test_override_existing_prefix(self):
        """测试覆盖现有前缀"""
        resolver = VariableResolver()

        def new_memory_handler(path, context):
            return "overridden"

        resolver.register_prefix("memory", new_memory_handler)

        ctx = ResolutionContext(workflow_id="wf_1", execution_id="exec_1")
        result = resolver.resolve("$memory.test", ctx)

        assert result.success is True
        assert result.value == "overridden"
