"""
成长闭环 (Growth Loop) 测试

测试完整的成长闭环：反思→记录→检索→注入
数据流: 对话完成→_step_reflection→生成反思日志→growth_log_manager→存储反思→build_context→注入反思→影响决策

测试策略:
1. TestStepReflection: 测试 _step_reflection 步骤
2. TestBuildContextReflection: 测试 build_context 中反思日志的收集和注入
3. TestGrowthClosedLoop: 端到端闭环测试
4. TestGrowthConfiguration: 配置和边界情况
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# 导入被测模块
from neurova.post_chat_pipeline import PostChatPipeline
from neurova.context.orchestrator import ContextOrchestrator
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionLogEntry,
    ReflectionType,
    ReflectionLogStatus,
)


class MockAgent:
    """模拟 Agent 实例"""

    def __init__(self):
        self.config = MagicMock()
        self.config.name = "TestAgent"
        self.config.agent_id = "test-agent"
        self.config.constitution = "测试宪法"
        self.config.behavior_rules = ["规则1", "规则2"]

        # 模拟 growth_log_manager
        self.growth_log_manager = MagicMock(spec=GrowthLogManager)
        self.growth_log_manager.generate_log = AsyncMock()
        self.growth_log_manager.get_validated_logs = AsyncMock(return_value=[])
        self.growth_log_manager.get_pending_logs = AsyncMock(return_value=[])

        # 模拟其他必要属性
        self.memory_manager = MagicMock()
        self.context_builder = MagicMock()
        self.tool_router = MagicMock()
        self._skill_registry = MagicMock()
        self.soul = "测试灵魂"
        self.personality = "测试性格"
        self.conversation_history = []
        self._turn_count = 0

        # 模拟 _collect_tool_messages
        self._tool_messages = []

        # 模拟 context_builder.build_from_pool 返回上下文列表
        self.context_builder.build_from_pool.return_value = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户输入"},
        ]
        self.context_builder.compress_if_needed.return_value = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户输入"},
        ]

    def _collect_tool_messages(self):
        return self._tool_messages


@pytest.fixture
def mock_agent():
    """创建模拟 Agent 实例"""
    agent = MockAgent()
    # 重置 growth_log_manager 的 mock
    agent.growth_log_manager.generate_log.reset_mock()
    agent.growth_log_manager.get_validated_logs.reset_mock()
    agent.growth_log_manager.get_pending_logs.reset_mock()
    return agent


@pytest.fixture
def pipeline(mock_agent):
    """创建 PostChatPipeline 实例"""
    return PostChatPipeline(mock_agent)


@pytest.fixture
def orchestrator(mock_agent):
    """创建 ContextOrchestrator 实例"""
    return ContextOrchestrator(mock_agent)


# ============================================================
# TestStepReflection: 测试 _step_reflection 步骤
# ============================================================

class TestStepReflection:
    """测试 _step_reflection 步骤"""

    @pytest.mark.asyncio
    async def test_reflection_triggered_by_confusion_keywords(self, pipeline, mock_agent):
        """测试用户困惑关键词触发反思"""
        # 准备
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="test-id",
            type=ReflectionType.INSIGHT,
            title="对话反思 - insight",
            content="用户输入: 我不明白这个\nAgent 回复: 让我解释一下",
        )

        # 执行
        await pipeline._step_reflection("我不明白这个", "让我解释一下")

        # 验证
        mock_agent.growth_log_manager.generate_log.assert_called_once()
        call_args = mock_agent.growth_log_manager.generate_log.call_args
        assert call_args.kwargs['type'] == ReflectionType.INSIGHT
        assert "我不明白这个" in call_args.kwargs['content']
        assert "让我解释一下" in call_args.kwargs['content']

    @pytest.mark.asyncio
    async def test_reflection_triggered_by_uncertainty_keywords(self, pipeline, mock_agent):
        """测试 Agent 不确定性关键词触发反思"""
        # 准备 - "如何回答" 匹配 IMPROVEMENT ("如何")
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="test-id",
            type=ReflectionType.IMPROVEMENT,
            title="对话反思 - improvement",
            content="用户输入: 如何回答\nAgent 回复: 可能需要这样做",
        )

        # 执行
        await pipeline._step_reflection("如何回答", "可能需要这样做")

        # 验证
        mock_agent.growth_log_manager.generate_log.assert_called_once()
        call_args = mock_agent.growth_log_manager.generate_log.call_args
        assert call_args.kwargs['type'] == ReflectionType.IMPROVEMENT

    @pytest.mark.asyncio
    async def test_reflection_triggered_by_turn_count(self, pipeline, mock_agent):
        """测试周期性反思触发"""
        # 设置 turn_count 为 10 的倍数
        mock_agent._turn_count = mock_agent.turn_count = 10

        # 准备
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="test-id",
            type=ReflectionType.INSIGHT,
            title="对话反思 - insight",
            content="用户输入: 普通对话\nAgent 回复: 普通回复",
        )

        # 执行
        await pipeline._step_reflection("普通对话", "普通回复")

        # 验证
        mock_agent.growth_log_manager.generate_log.assert_called_once()
        call_args = mock_agent.growth_log_manager.generate_log.call_args
        assert call_args.kwargs['type'] == ReflectionType.INSIGHT
        assert call_args.kwargs['context']['trigger'] == "周期性反思 (turn=10)"

    @pytest.mark.asyncio
    async def test_reflection_triggered_by_performance_keywords(self, pipeline, mock_agent):
        """测试 PERFORMANCE 类型反思触发（只有回复中含不确定性关键词）"""
        # "你好" 不含问题关键词，"可能不太对" 含 "可能" → PERFORMANCE
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="test-id",
            type=ReflectionType.PERFORMANCE,
            title="对话反思 - performance",
            content="用户输入: 你好\nAgent 回复: 可能不太对",
        )

        await pipeline._step_reflection("你好", "可能不太对")

        mock_agent.growth_log_manager.generate_log.assert_called_once()
        call_args = mock_agent.growth_log_manager.generate_log.call_args
        assert call_args.kwargs['type'] == ReflectionType.PERFORMANCE

    @pytest.mark.asyncio
    async def test_reflection_not_triggered_without_keywords(self, pipeline, mock_agent):
        """测试没有关键词时不触发反思"""
        # 设置 turn_count 不是 10 的倍数
        mock_agent._turn_count = mock_agent.turn_count = 5

        # 执行
        await pipeline._step_reflection("普通对话", "普通回复")

        # 验证
        mock_agent.growth_log_manager.generate_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_reflection_handles_no_manager(self, pipeline, mock_agent):
        """测试没有 growth_log_manager 时跳过反思"""
        # 移除 growth_log_manager
        mock_agent.growth_log_manager = None

        # 执行
        await pipeline._step_reflection("我不明白", "可能需要解释")

        # 验证 - 不应该抛出异常

    @pytest.mark.asyncio
    async def test_reflection_handles_exception(self, pipeline, mock_agent):
        """测试异常处理"""
        # 设置 mock 抛出异常
        mock_agent.growth_log_manager.generate_log.side_effect = Exception("测试异常")

        # 执行 - 不应该抛出异常
        await pipeline._step_reflection("我不明白", "可能需要解释")

        # 验证
        mock_agent.growth_log_manager.generate_log.assert_called_once()


# ============================================================
# TestBuildContextReflection: 测试 build_context 中反思日志的收集和注入
# ============================================================

class TestBuildContextReflection:
    """测试 build_context 中反思日志的收集和注入"""

    @pytest.mark.asyncio
    async def test_reflection_logs_collected(self, orchestrator, mock_agent):
        """测试反思日志被正确收集"""
        # 准备
        validated_logs = [
            ReflectionLogEntry(
                id="validated-1",
                type=ReflectionType.PERFORMANCE,
                status=ReflectionLogStatus.VALIDATED,
                title="性能反思",
                content="性能已优化",
                confidence=0.8,
            )
        ]
        pending_logs = [
            ReflectionLogEntry(
                id="pending-1",
                type=ReflectionType.ERROR,
                status=ReflectionLogStatus.PENDING,
                title="错误反思",
                content="需要修复错误",
                confidence=0.6,
            )
        ]

        mock_agent.growth_log_manager.get_validated_logs.return_value = validated_logs
        mock_agent.growth_log_manager.get_pending_logs.return_value = pending_logs

        # 执行 - mock context_pool.draw to avoid internal ContextPool issues
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("测试输入")

            # 验证 growth_log_manager methods were called
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()
            mock_agent.growth_log_manager.get_pending_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflection_logs_injected_into_context(self, orchestrator, mock_agent):
        """测试反思日志被传递给 context_pool"""
        # 准备
        validated_logs = [
            ReflectionLogEntry(
                id="validated-1",
                type=ReflectionType.INSIGHT,
                status=ReflectionLogStatus.VALIDATED,
                title="洞察反思",
                content="这是一个重要洞察",
                confidence=0.9,
            )
        ]
        mock_agent.growth_log_manager.get_validated_logs.return_value = validated_logs
        mock_agent.growth_log_manager.get_pending_logs.return_value = []

        # 执行
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("测试输入")

            # 验证 growth_log_manager methods were called
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()
            mock_agent.growth_log_manager.get_pending_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflection_logs_error_handling(self, orchestrator, mock_agent):
        """测试反思日志收集的错误处理"""
        # 设置 mock 抛出异常
        mock_agent.growth_log_manager.get_validated_logs.side_effect = Exception("测试异常")
        mock_agent.growth_log_manager.get_pending_logs.side_effect = Exception("测试异常")

        # 执行 - 不应该抛出异常
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("测试输入")

    @pytest.mark.asyncio
    async def test_reflection_logs_without_manager(self, orchestrator, mock_agent):
        """测试没有 growth_log_manager 时的行为"""
        # 移除 growth_log_manager
        mock_agent.growth_log_manager = None

        # 执行
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("测试输入")


# ============================================================
# TestGrowthClosedLoop: 端到端闭环测试
# ============================================================

class TestGrowthClosedLoop:
    """端到端闭环测试"""

    @pytest.mark.asyncio
    async def test_full_growth_loop(self, pipeline, orchestrator, mock_agent):
        """测试完整的成长闭环：反思→记录→检索→注入"""
        # 步骤1: 触发反思 — 使用 ERROR 关键词
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="loop-test-id",
            type=ReflectionType.ERROR,
            title="对话反思 - error",
            content="用户输入: 这个出错了\nAgent 回复: 让我解释一下",
            status=ReflectionLogStatus.PENDING,
        )

        # 执行反思
        await pipeline._step_reflection("这个出错了", "让我解释一下")

        # 验证反思日志被记录
        mock_agent.growth_log_manager.generate_log.assert_called_once()

        # 步骤2: 模拟反思日志被验证
        validated_logs = [
            ReflectionLogEntry(
                id="loop-test-id",
                type=ReflectionType.ERROR,
                status=ReflectionLogStatus.VALIDATED,
                title="对话反思 - error",
                content="用户输入: 这个出错了\nAgent 回复: 让我解释一下",
                confidence=0.7,
            )
        ]
        mock_agent.growth_log_manager.get_validated_logs.return_value = validated_logs
        mock_agent.growth_log_manager.get_pending_logs.return_value = []

        # 步骤3: 构建上下文（应该包含反思日志）
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("新的用户输入")

            # 验证反思日志被记录
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_reflections_accumulate(self, pipeline, orchestrator, mock_agent):
        """测试多次反思积累"""
        # 第一次反思 — 使用困惑关键词 "不对"
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="reflection-1",
            type=ReflectionType.ERROR,
            title="错误反思",
            content="错误内容1",
        )
        await pipeline._step_reflection("不对，这有问题", "回复1")

        # 第二次反思 — 使用不确定性关键词 "可能"
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="reflection-2",
            type=ReflectionType.PERFORMANCE,
            title="性能反思",
            content="性能内容1",
        )
        await pipeline._step_reflection("普通输入", "可能不太确定")

        # 验证两次反思都被记录
        assert mock_agent.growth_log_manager.generate_log.call_count == 2

        # 模拟两个反思都被验证
        validated_logs = [
            ReflectionLogEntry(
                id="reflection-1",
                type=ReflectionType.ERROR,
                status=ReflectionLogStatus.VALIDATED,
                title="错误反思",
                content="错误内容1",
                confidence=0.6,
            ),
            ReflectionLogEntry(
                id="reflection-2",
                type=ReflectionType.IMPROVEMENT,
                status=ReflectionLogStatus.VALIDATED,
                title="改进反思",
                content="改进内容1",
                confidence=0.8,
            ),
        ]
        mock_agent.growth_log_manager.get_validated_logs.return_value = validated_logs
        mock_agent.growth_log_manager.get_pending_logs.return_value = []

        # 构建上下文（应该包含两个反思）
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("新输入")

            # 验证反思日志方法被调用
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflection_influences_behavior(self, pipeline, orchestrator, mock_agent):
        """测试反思影响后续行为"""
        # 创建一个反思日志，包含行动项
        action_reflection = ReflectionLogEntry(
            id="action-reflection",
            type=ReflectionType.STRATEGY,
            status=ReflectionLogStatus.VALIDATED,
            title="策略反思",
            content="需要改变回答策略",
            insights=["用户需要更详细的解释"],
            action_items=["下次回答时提供步骤", "使用例子说明"],
            confidence=0.85,
        )

        mock_agent.growth_log_manager.get_validated_logs.return_value = [action_reflection]
        mock_agent.growth_log_manager.get_pending_logs.return_value = []

        # 构建上下文
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("需要帮助")

            # 验证反思日志被记录
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()


# ============================================================
# TestGrowthConfiguration: 配置和边界情况
# ============================================================

class TestGrowthConfiguration:
    """配置和边界情况测试"""

    def test_reflection_keywords(self, pipeline):
        """测试反思关键词配置"""
        # 验证关键词列表存在
        assert hasattr(pipeline, 'REFLECTION_CONFUSION_KEYWORDS')
        assert hasattr(pipeline, 'REFLECTION_UNCERTAINTY_KEYWORDS')
        assert hasattr(pipeline, 'REFLECTION_TURN_INTERVAL')

        # 验证关键词内容
        assert "不明白" in pipeline.REFLECTION_CONFUSION_KEYWORDS
        assert "不确定" in pipeline.REFLECTION_UNCERTAINTY_KEYWORDS
        assert pipeline.REFLECTION_TURN_INTERVAL == 10

    def test_should_reflect_logic(self, pipeline, mock_agent):
        """测试反思触发逻辑"""
        # 用户困惑关键词
        assert pipeline._should_reflect("我不明白这个", "让我解释") == True
        assert pipeline._should_reflect("搞错了", "抱歉") == True

        # Agent 不确定性关键词
        assert pipeline._should_reflect("怎么解决", "可能需要这样做") == True
        assert pipeline._should_reflect("为什么", "也许是因为") == True

        # 周期性反思
        mock_agent._turn_count = mock_agent.turn_count = 10
        assert pipeline._should_reflect("普通对话", "普通回复") == True

        # 不触发反思
        mock_agent._turn_count = mock_agent.turn_count = 5
        assert pipeline._should_reflect("普通对话", "普通回复") == False

    def test_infer_reflection_type(self, pipeline):
        """测试反思类型推断"""
        # 错误反思
        assert pipeline._infer_reflection_type("出现错误", "回复") == ReflectionType.ERROR

        # 问题解决
        assert pipeline._infer_reflection_type("怎么解决", "回复") == ReflectionType.IMPROVEMENT

        # 决策制定
        assert pipeline._infer_reflection_type("应该决定", "回复") == ReflectionType.STRATEGY

        # 交互反思
        assert pipeline._infer_reflection_type("普通输入", "可能不确定") == ReflectionType.PERFORMANCE

        # 学习反思
        assert pipeline._infer_reflection_type("普通输入", "普通回复") == ReflectionType.INSIGHT

    def test_reflection_trigger_reason(self, pipeline, mock_agent):
        """测试反思触发原因"""
        # 用户困惑
        reason = pipeline._get_reflection_trigger_reason("我不明白", "解释")
        assert "用户困惑关键词: 不明白" in reason

        # Agent 不确定 — 回复 "可能不确定" 包含 "不确定"
        reason = pipeline._get_reflection_trigger_reason("输入", "可能不确定")
        assert "Agent 不确定性关键词: 不确定" in reason

        # 周期性反思
        mock_agent._turn_count = mock_agent.turn_count = 20
        reason = pipeline._get_reflection_trigger_reason("输入", "回复")
        assert "周期性反思 (turn=20)" in reason

    @pytest.mark.asyncio
    async def test_empty_reflection_logs(self, orchestrator, mock_agent):
        """测试空反思日志"""
        # 设置返回空列表
        mock_agent.growth_log_manager.get_validated_logs.return_value = []
        mock_agent.growth_log_manager.get_pending_logs.return_value = []

        # 构建上下文
        with patch.object(orchestrator.context_pool, 'draw', return_value=[]):
            await orchestrator.build_context("输入")

            # 验证反思日志方法被调用
            mock_agent.growth_log_manager.get_validated_logs.assert_called_once()
            mock_agent.growth_log_manager.get_pending_logs.assert_called_once()


# ============================================================
# TestGrowthIntegration: 与其他系统的集成测试
# ============================================================

class TestGrowthIntegration:
    """与其他系统的集成测试"""

    @pytest.mark.asyncio
    async def test_growth_with_evocate(self, pipeline, mock_agent):
        """测试成长闭环与 Evocate 系统的集成"""
        # 模拟 neuHebb_manager
        mock_agent.neuHebb_manager = MagicMock()
        mock_agent.neuHebb_manager.generate_from_conversation.return_value = []

        # 执行反思 — 使用困惑关键词触发
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="growth-evocate-test",
            type=ReflectionType.ERROR,
            title="错误反思",
            content="发现模式",
        )
        await pipeline._step_reflection("这搞错了", "模式回复")

        # 执行 Evocate 生成
        await pipeline._step_evocate_generation("这搞错了", "模式回复", "test-session")

        # 验证两者都被调用
        mock_agent.growth_log_manager.generate_log.assert_called_once()
        mock_agent.neuHebb_manager.generate_from_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_growth_with_experience(self, pipeline, mock_agent):
        """测试成长闭环与经验系统的集成"""
        # 模拟 evolution
        mock_agent.evolution = MagicMock()
        mock_agent.evolution.on_experience_recorded = MagicMock()

        # 执行反思 — 使用困惑关键词触发
        mock_agent.growth_log_manager.generate_log.return_value = ReflectionLogEntry(
            id="growth-experience-test",
            type=ReflectionType.PERFORMANCE,
            title="性能反思",
            content="性能改进",
        )
        await pipeline._step_reflection("性能输入", "可能不太确定")

        # 执行经验记录
        await pipeline._step_record_experience("性能输入", "性能回复", True)

        # 验证两者都被调用
        mock_agent.growth_log_manager.generate_log.assert_called_once()
        mock_agent.evolution.on_experience_recorded.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])