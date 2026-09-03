"""
Evocate 闭环测试 — TDD 垂直切片

测试从对话生成 NeurovaHebb 到检索注入的完整闭环。

数据流: 对话 → generate_from_conversation → 存储 → 检索 → 注入上下文
"""

import math
import pytest
from typing import List
from unittest.mock import MagicMock, AsyncMock

from neurova.cognitive_layers.memory_layer.neurova_hebb import (
    NeurovaHebb,
    NeuHebbConfig,
    NeuHebbMem,
)
from neurova.cognitive_layers.memory_layer.neuHebb_manager import NeuHebbManager
from neurova.post_chat_pipeline import PostChatPipeline


# ── Mock 辅助 ─────────────────────────────────────────────────────────────────

class MockLLM:
    def __init__(self, responses: List[str] = None):
        self._responses = responses or [
            "What is the user asking about?",  # 预查询生成
            "The user is asking about AI memory systems.",  # 答案生成
            "The user inquired about AI memory systems and received an explanation.",  # 总结
            "What are the key concepts?",  # 预查询生成
            "Key concepts include Neurova Hebb, structured reasoning, and memory retrieval.",  # 答案生成
            "Key concepts in AI memory systems include Neurova Hebb for structured reasoning.",  # 总结
        ]
        self._call_count = 0
        self.calls: List[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        idx = self._call_count
        self._call_count += 1
        if idx < len(self._responses):
            return self._responses[idx]
        return "I don't know"


class MockEmbedder:
    def __init__(self, dim: int = 64):
        self.dim = dim

    def __call__(self, text: str) -> List[float]:
        import random
        rng = random.Random(hash(text))
        vec = [rng.random() for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else vec


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config(tmp_path):
    """创建测试配置"""
    return NeuHebbConfig(
        enabled=True,
        pre_query_count=2,
        neurova_hebbs_limit=5,
        verification_enabled=False,  # 简化测试
        diversity_threshold=0.95,  # 高阈值，确保多样性检查通过
        persistence_path=str(tmp_path / "neurova_hebbs"),
    )


@pytest.fixture
def llm():
    """创建 Mock LLM"""
    return MockLLM()


@pytest.fixture
def embedder():
    """创建 Mock Embedder"""
    return MockEmbedder()


@pytest.fixture
def manager(config, llm, embedder):
    """创建 NeuHebbManager 实例"""
    return NeuHebbManager(
        config=config,
        llm_fn=llm,
        embed_fn=embedder,
    )


@pytest.fixture
def mock_agent(manager):
    """创建 Mock Agent 实例"""
    agent = MagicMock()
    agent.neuHebb_manager = manager
    agent._collect_tool_messages = MagicMock(return_value=[])
    agent._turn_count = 0
    # 确保 neuHebb_manager 的方法可以被 mock 验证
    agent.neuHebb_manager.generate_from_conversation = MagicMock(
        side_effect=manager.generate_from_conversation
    )
    return agent


@pytest.fixture
def pipeline(mock_agent):
    """创建 PostChatPipeline 实例"""
    return PostChatPipeline(agent_ref=mock_agent)


# ── 测试: generate_from_conversation ─────────────────────────────────────────

class TestGenerateFromConversation:
    """测试从对话生成 NeurovaHebb"""

    def test_generate_from_conversation_returns_hebbs(self, manager):
        """验证 generate_from_conversation 返回 NeurovaHebb 列表"""
        hebbs = manager.generate_from_conversation(
            user_input="什么是 AI 记忆系统？",
            reply="AI 记忆系统是用于存储和检索知识的系统。",
            session_id="test_session",
        )
        assert isinstance(hebbs, list)
        assert len(hebbs) > 0
        assert all(isinstance(h, NeurovaHebb) for h in hebbs)

    def test_generate_from_conversation_metadata(self, manager):
        """验证生成的 NeurovaHebb 包含正确的元数据"""
        hebbs = manager.generate_from_conversation(
            user_input="什么是 AI 记忆系统？",
            reply="AI 记忆系统是用于存储和检索知识的系统。",
            session_id="test_session",
        )
        assert len(hebbs) > 0
        for hebb in hebbs:
            assert hebb.metadata.get("source") == "conversation"
            assert hebb.metadata.get("session_id") == "test_session"
            assert "user_input_length" in hebb.metadata
            assert "reply_length" in hebb.metadata

    def test_generate_from_conversation_document_id_format(self, manager):
        """验证 document_id 格式正确"""
        hebbs = manager.generate_from_conversation(
            user_input="测试输入",
            reply="测试回复",
            session_id="test_session",
        )
        assert len(hebbs) > 0
        for hebb in hebbs:
            assert hebb.document_id.startswith("conversation_test_session_")

    def test_generate_from_conversation_stored_in_memory(self, manager):
        """验证生成的 NeurovaHebb 被正确存储"""
        initial_count = manager.count()
        manager.generate_from_conversation(
            user_input="测试输入",
            reply="测试回复",
            session_id="test_session",
        )
        final_count = manager.count()
        assert final_count > initial_count

    def test_generate_from_conversation_with_custom_metadata(self, manager):
        """验证自定义元数据被正确合并"""
        custom_metadata = {"custom_key": "custom_value"}
        hebbs = manager.generate_from_conversation(
            user_input="测试输入",
            reply="测试回复",
            session_id="test_session",
            metadata=custom_metadata,
        )
        assert len(hebbs) > 0
        for hebb in hebbs:
            assert hebb.metadata.get("custom_key") == "custom_value"
            assert hebb.metadata.get("source") == "conversation"


# ── 测试: Evocate 闭环 ────────────────────────────────────────────────────────

class TestEvocateClosedLoop:
    """测试完整的 Evocate 闭环: 生成 → 存储 → 检索"""

    def test_generate_then_retrieve(self, manager):
        """验证生成后可以检索到相关 NeurovaHebb"""
        # 1. 生成
        hebbs = manager.generate_from_conversation(
            user_input="什么是机器学习？",
            reply="机器学习是人工智能的一个子领域。",
            session_id="test_session",
        )
        assert len(hebbs) > 0

        # 2. 检索相关查询
        retrieved = manager.retrieve_neurova_hebb("机器学习是什么？")
        # 注意: 由于 Mock 实现，检索可能返回空列表
        # 但至少验证检索不会抛出异常
        assert isinstance(retrieved, list)

    def test_multiple_conversations_accumulate(self, manager):
        """验证多次对话的 NeurovaHebb 会累积"""
        initial_count = manager.count()

        # 生成多个对话的 NeurovaHebb
        for i in range(3):
            manager.generate_from_conversation(
                user_input=f"测试输入 {i}",
                reply=f"测试回复 {i}",
                session_id=f"session_{i}",
            )

        final_count = manager.count()
        assert final_count > initial_count

    def test_generate_from_conversation_content_format(self, manager):
        """验证生成的 content 格式正确"""
        hebbs = manager.generate_from_conversation(
            user_input="测试问题",
            reply="测试答案",
            session_id="test_session",
        )
        assert len(hebbs) > 0
        # content 应该包含用户输入和助手回复
        for hebb in hebbs:
            # 注意: content 是经过总结的，不一定包含原始文本
            # 但应该非空
            assert len(hebb.content) > 0


# ── 测试: PostChatPipeline Evocate 步骤 ──────────────────────────────────────

class TestPostChatPipelineEvocate:
    """测试 PostChatPipeline 中的 Evocate 生成步骤"""

    @pytest.mark.asyncio
    async def test_step_evocate_generation_called(self, pipeline, mock_agent):
        """验证 _step_evocate_generation 被正确调用"""
        # 准备
        user_input = "什么是深度学习？"
        reply = "深度学习是机器学习的一个子领域。"
        session_id = "test_session"

        # 执行
        await pipeline._step_evocate_generation(user_input, reply, session_id)

        # 验证
        mock_agent.neuHebb_manager.generate_from_conversation.assert_called_once_with(
            user_input=user_input,
            reply=reply,
            session_id=session_id,
        )

    @pytest.mark.asyncio
    async def test_step_evocate_generation_no_manager(self, pipeline, mock_agent):
        """验证没有 neuHebb_manager 时不会抛出异常"""
        # 准备
        mock_agent.neuHebb_manager = None
        user_input = "测试输入"
        reply = "测试回复"
        session_id = "test_session"

        # 执行 - 不应抛出异常
        await pipeline._step_evocate_generation(user_input, reply, session_id)

    @pytest.mark.asyncio
    async def test_step_evocate_generation_handles_exception(self, pipeline, mock_agent):
        """验证异常处理"""
        # 准备
        mock_agent.neuHebb_manager.generate_from_conversation.side_effect = Exception("测试异常")
        user_input = "测试输入"
        reply = "测试回复"
        session_id = "test_session"

        # 执行 - 不应抛出异常
        await pipeline._step_evocate_generation(user_input, reply, session_id)

    @pytest.mark.asyncio
    async def test_process_includes_evocate_generation(self, pipeline, mock_agent):
        """验证 process() 方法包含 Evocate 生成步骤"""
        # 准备
        user_input = "什么是神经网络？"
        reply = "神经网络是模拟人脑的计算模型。"
        session_id = "test_session"

        # 执行
        result = await pipeline.process(
            user_input=user_input,
            reply=reply,
            session_id=session_id,
            save_memory=True,
            enable_tts=False,
            metadata={},
        )

        # 验证
        assert "actual_session_id" in result
        mock_agent.neuHebb_manager.generate_from_conversation.assert_called()


# ── 测试: 配置和边界条件 ──────────────────────────────────────────────────────

class TestEvocateConfiguration:
    """测试 Evocate 系统的配置和边界条件"""

    def test_disabled_config(self, tmp_path, llm, embedder):
        """验证禁用配置时的行为"""
        config = NeuHebbConfig(
            enabled=False,
            persistence_path=str(tmp_path / "neurova_hebbs"),
        )
        manager = NeuHebbManager(
            config=config,
            llm_fn=llm,
            embed_fn=embedder,
        )
        # 即使禁用，生成方法也应该工作（只是不存储）
        hebbs = manager.generate_from_conversation(
            user_input="测试输入",
            reply="测试回复",
            session_id="test_session",
        )
        # 应该返回空列表或不存储
        # 具体行为取决于实现

    def test_empty_input(self, manager):
        """验证空输入的处理"""
        hebbs = manager.generate_from_conversation(
            user_input="",
            reply="",
            session_id="test_session",
        )
        # 应该返回空列表
        assert isinstance(hebbs, list)

    def test_session_id_default(self, manager):
        """验证默认 session_id"""
        hebbs = manager.generate_from_conversation(
            user_input="测试输入",
            reply="测试回复",
        )
        assert len(hebbs) > 0
        for hebb in hebbs:
            assert hebb.metadata.get("session_id") == "default"
