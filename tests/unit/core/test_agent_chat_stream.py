"""
Agent.chat_stream 流式对话方法测试（TDD RED 阶段）

测试 Agent 类新增的 chat_stream 异步生成器方法。

背景:
- mobile_pairing.py 第 707 行 `if hasattr(agent, "chat_stream")` 检查
- chat.py SSE 端点同样期望 agent.chat_stream 存在
- 当前 Agent 类只有 chat() 方法，无 chat_stream，导致流式降级

设计决策:
- chat_stream 为异步生成器，逐 chunk yield 字符串
- 内部委托给 self.chat()，保证记忆/上下文/后处理完整
- 签名兼容 mobile_pairing.py 调用方式: user_input=, session_id=, metadata=
- 首版实现: chat() 返回完整文本后作为单 chunk yield（功能完整，后续可优化为真流式）
"""

import asyncio
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.agent_core import Agent, AgentConfig


# ---------------------------------------------------------------------------
# 辅助: 创建跳过 __init__ 的 Agent 实例
# ---------------------------------------------------------------------------


def _create_agent_without_init() -> Agent:
    """创建 Agent 实例但跳过 __init__（避免加载子系统）"""
    agent = Agent.__new__(Agent)
    # 设置 chat 为 AsyncMock，便于测试中验证调用
    agent.chat = AsyncMock()
    return agent


# ---------------------------------------------------------------------------
# 测试 1: chat_stream 方法存在且是异步生成器
# ---------------------------------------------------------------------------


class TestChatStreamMethodExists:
    """RED: Agent 类必须有 chat_stream 异步生成器方法"""

    def test_chat_stream_method_exists(self):
        """RED: Agent 类应定义 chat_stream 方法"""
        assert hasattr(Agent, "chat_stream"), "Agent 类必须定义 chat_stream 方法"

    def test_chat_stream_is_async_generator_function(self):
        """RED: chat_stream 必须是异步生成器函数（用 async def + yield）"""
        assert hasattr(Agent, "chat_stream"), "chat_stream 方法不存在"
        assert inspect.isasyncgenfunction(Agent.chat_stream), (
            "chat_stream 必须是异步生成器函数（async def + yield），"
            f"实际类型: {type(Agent.chat_stream)}"
        )

    def test_chat_stream_is_not_coroutine_function(self):
        """RED: chat_stream 不应是普通协程函数（必须是生成器）"""
        assert not inspect.iscoroutinefunction(Agent.chat_stream), (
            "chat_stream 不应是普通 async 函数，必须是异步生成器（含 yield）"
        )


# ---------------------------------------------------------------------------
# 测试 2: 签名兼容 mobile_pairing 调用方式
# ---------------------------------------------------------------------------


class TestChatStreamSignature:
    """RED: chat_stream 签名必须兼容 mobile_pairing.py 调用方式"""

    def test_signature_accepts_user_input_session_id_metadata(self):
        """RED: 签名必须支持 (user_input, session_id, metadata) 参数"""
        sig = inspect.signature(Agent.chat_stream)
        params = sig.parameters

        # 必须有 user_input 参数
        assert "user_input" in params, "chat_stream 必须接受 user_input 参数"
        # 必须有 session_id 参数（可有默认值）
        assert "session_id" in params, "chat_stream 必须接受 session_id 参数"
        # 必须有 metadata 参数（可有默认值）
        assert "metadata" in params, "chat_stream 必须接受 metadata 参数"

    def test_signature_allows_keyword_arguments(self):
        """RED: 必须支持关键字参数调用（mobile_pairing 用 user_input=, session_id=, metadata=）"""
        sig = inspect.signature(Agent.chat_stream)
        # mobile_pairing 调用方式: agent.chat_stream(user_input=..., session_id=..., metadata=...)
        # 这要求参数名匹配
        params = sig.parameters
        assert "user_input" in params
        assert "session_id" in params
        assert "metadata" in params


# ---------------------------------------------------------------------------
# 测试 3: chat_stream 逐 chunk yield 字符串
# ---------------------------------------------------------------------------


class TestChatStreamYieldsChunks:
    """RED: chat_stream 调用后应逐 chunk yield 字符串"""

    def test_yields_at_least_one_chunk(self):
        """RED: chat_stream 应至少 yield 一个 chunk"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "Hello world"})

        chunks = []
        agen = agent.chat_stream(user_input="hi")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        assert len(chunks) >= 1, f"应至少 yield 1 个 chunk，实际: {len(chunks)}"

    def test_yields_string_chunks(self):
        """RED: yield 的 chunk 必须是字符串"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "Hello"})

        chunks = []
        agen = agent.chat_stream(user_input="hi")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        for chunk in chunks:
            assert isinstance(chunk, str), f"chunk 必须是字符串，实际类型: {type(chunk)}"

    def test_yields_text_from_chat_response(self):
        """RED: yield 的内容应来自 chat() 返回的 text 字段"""
        agent = _create_agent_without_init()
        expected_text = "这是回复内容"
        agent.chat = AsyncMock(return_value={"text": expected_text})

        chunks = []
        agen = agent.chat_stream(user_input="问题")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        # 完整文本应出现在 chunks 拼接结果中
        full_reply = "".join(chunks)
        assert expected_text in full_reply, (
            f"chat() 返回的 text '{expected_text}' 应出现在 yield 的 chunks 中，"
            f"实际拼接: '{full_reply}'"
        )

    def test_yields_str_response_when_chat_returns_string(self):
        """RED: 当 chat() 返回字符串时，chat_stream 也应 yield 该字符串"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value="纯字符串回复")

        chunks = []
        agen = agent.chat_stream(user_input="hi")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        assert "".join(chunks) == "纯字符串回复"


# ---------------------------------------------------------------------------
# 测试 4: chat_stream 委托给 chat() 并传递参数
# ---------------------------------------------------------------------------


class TestChatStreamDelegatesToChat:
    """RED: chat_stream 应委托给 self.chat() 并正确传递参数"""

    def test_calls_chat_with_user_input(self):
        """RED: chat_stream 应将 user_input 传给 chat()"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "ok"})

        async def _run():
            async for _ in agent.chat_stream(user_input="你好"):
                pass
        asyncio.run(_run())

        agent.chat.assert_awaited_once()
        call_kwargs = agent.chat.call_args
        # user_input 可以是位置参数或关键字参数
        args = call_kwargs.args
        kwargs = call_kwargs.kwargs
        assert "你好" in args or kwargs.get("user_input") == "你好", (
            f"chat() 应收到 user_input='你好'，实际 args={args}, kwargs={kwargs}"
        )

    def test_passes_session_id_to_chat(self):
        """RED: chat_stream 应将 session_id 传给 chat()"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "ok"})

        async def _run():
            async for _ in agent.chat_stream(
                user_input="hi", session_id="session-123"
            ):
                pass
        asyncio.run(_run())

        call_kwargs = agent.chat.call_args
        kwargs = call_kwargs.kwargs
        assert kwargs.get("session_id") == "session-123", (
            f"chat() 应收到 session_id='session-123'，实际 kwargs={kwargs}"
        )

    def test_passes_metadata_to_chat(self):
        """RED: chat_stream 应将 metadata 传给 chat()"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "ok"})

        metadata = {"history": [], "attachments": ["file1.png"]}
        async def _run():
            async for _ in agent.chat_stream(
                user_input="hi", metadata=metadata
            ):
                pass
        asyncio.run(_run())

        call_kwargs = agent.chat.call_args
        kwargs = call_kwargs.kwargs
        assert kwargs.get("metadata") == metadata, (
            f"chat() 应收到 metadata={metadata}，实际 kwargs={kwargs}"
        )


# ---------------------------------------------------------------------------
# 测试 5: 异常处理
# ---------------------------------------------------------------------------


class TestChatStreamErrorHandling:
    """RED: chat_stream 异常时应正常结束生成器"""

    def test_chat_exception_propagates(self):
        """RED: chat() 抛异常时，chat_stream 应让异常传播（不吞错）"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(side_effect=RuntimeError("LLM 服务不可用"))

        async def _run():
            chunks = []
            try:
                async for chunk in agent.chat_stream(user_input="hi"):
                    chunks.append(chunk)
                return chunks
            except RuntimeError:
                return "propagated"

        result = asyncio.run(_run())
        assert result == "propagated", (
            "chat() 的异常应传播到 chat_stream 调用方，不应被吞掉"
        )

    def test_empty_response_yields_empty_string(self):
        """RED: chat() 返回空 text 时，chat_stream 应 yield 空字符串"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": ""})

        chunks = []
        agen = agent.chat_stream(user_input="hi")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        # 应至少 yield 一个 chunk（可能是空字符串）
        assert len(chunks) >= 1
        assert "".join(chunks) == ""

    def test_chat_returns_none_text_yields_empty(self):
        """RED: chat() 返回的 text 为 None 时，应 yield 空字符串而非 None"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": None})

        chunks = []
        agen = agent.chat_stream(user_input="hi")
        async def _collect():
            async for chunk in agen:
                chunks.append(chunk)
        asyncio.run(_collect())

        for chunk in chunks:
            assert chunk is not None, "不应 yield None"
            assert isinstance(chunk, str)


# ---------------------------------------------------------------------------
# 测试 6: 与 mobile_pairing._handle_chat_send 集成
# ---------------------------------------------------------------------------


class TestChatStreamIntegrationWithMobilePairing:
    """RED: chat_stream 必须能被 mobile_pairing._handle_chat_send 正确调用"""

    def test_hasattr_check_returns_true(self):
        """RED: hasattr(agent, 'chat_stream') 必须返回 True"""
        agent = _create_agent_without_init()
        assert hasattr(agent, "chat_stream"), (
            "mobile_pairing.py 第 707 行 hasattr(agent, 'chat_stream') 必须返回 True"
        )

    def test_can_be_consumed_by_async_for(self):
        """RED: chat_stream 返回的对象必须能用 'async for chunk in ...' 消费"""
        agent = _create_agent_without_init()
        agent.chat = AsyncMock(return_value={"text": "集成测试回复"})

        # 模拟 mobile_pairing._handle_chat_send 的消费方式
        async def _consume_like_mobile_pairing():
            chunks = []
            async for chunk in agent.chat_stream(
                user_input="测试消息",
                session_id="test-session",
                metadata={"history": [], "attachments": []},
            ):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(_consume_like_mobile_pairing())
        assert len(chunks) >= 1
        assert "集成测试回复" in "".join(chunks)
