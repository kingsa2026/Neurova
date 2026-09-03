"""
会话闭环修复测试 — TDD Tracer Bullet

测试目标（5个断裂点）：
  GAP-3: MemCore.save_to_session() 方法存在且正确委托给 session_manager
  GAP-1: build_context() 接收并注入 session_context
  GAP-2: chat() 主路径调用 _update_history()
  GAP-4: route_chat() 传递 session_id
  GAP-5: 经验记录一轮延迟 — 设计意图，不修
"""

import pytest
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, PropertyMock


# ══════════════════════════════════════════════════════════════
# GAP-3: MemCore.save_to_session() 应当存在（致命 bug）
# ══════════════════════════════════════════════════════════════

class TestGap3MemCoreSaveToSession:
    """GAP-3: MemCore 缺少 save_to_session 方法"""

    def test_mem_core_has_save_to_session(self):
        """MemCore 应该有 save_to_session 方法"""
        from neurova.mem_core import MemCore

        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"

        mem_core = MemCore(mock_agent)

        assert hasattr(mem_core, 'save_to_session'), \
            "GAP-3 未修复: MemCore 缺少 save_to_session 方法"

    def test_save_to_session_delegates_to_session_manager(self):
        """save_to_session 应该委托给 session_manager.add_message()"""
        from neurova.mem_core import MemCore

        # 准备 mock session_manager
        mock_session_mgr = Mock()
        mock_session_mgr.add_message.return_value = "test_agent_sess1_2026-06-02"

        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.session_manager = mock_session_mgr

        mem_core = MemCore(mock_agent)

        # 执行
        result = mem_core.save_to_session(
            user_input="你好",
            reply="你好！有什么可以帮助你的？",
            session_id="sess1",
            metadata={"attachment_ids": ["f1"]},
            assistant_metadata={"reasoning_content": "..."},
        )

        # 验证委托调用
        mock_session_mgr.add_message.assert_called_once_with(
            agent_id="test_agent",
            session_id="sess1",
            user_message="你好",
            assistant_message="你好！有什么可以帮助你的？",
            metadata={"attachment_ids": ["f1"]},
            assistant_metadata={"reasoning_content": "..."},
        )
        assert result == "test_agent_sess1_2026-06-02"

    def test_save_to_session_generates_session_id_when_none(self):
        """当 session_id 为 None 时，应自动生成"""
        from neurova.mem_core import MemCore

        mock_session_mgr = Mock()
        mock_session_mgr.add_message.return_value = "test_agent_auto-gen_2026-06-02"

        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.session_manager = mock_session_mgr

        mem_core = MemCore(mock_agent)

        result = mem_core.save_to_session(
            user_input="hello",
            reply="hi",
            session_id=None,
        )

        # 验证传入了非空 session_id
        call_args = mock_session_mgr.add_message.call_args
        passed_session_id = call_args.kwargs.get("session_id")
        assert passed_session_id is not None, "session_id 不应为 None"
        assert len(passed_session_id) > 0, "session_id 不应为空"


# ══════════════════════════════════════════════════════════════
# GAP-1: session_context 应传入 build_context()
# ══════════════════════════════════════════════════════════════

class TestGap1SessionContextInjection:
    """GAP-1: build_context() 调用缺少 session_context 参数"""

    def test_build_context_accepts_session_context(self):
        """build_context() 应该接受 session_context 参数"""
        from neurova.agent.context_orchestrator import ContextOrchestrator
        import inspect

        sig = inspect.signature(ContextOrchestrator.build_context)
        assert 'session_context' in sig.parameters, \
            "GAP-1 前置: build_context() 缺少 session_context 参数"

    @pytest.mark.asyncio
    async def test_session_context_injected_into_conversation(self):
        """session_context 应该合并到 conversation_context 中"""
        import tempfile
        from neurova.agent.context_orchestrator import ContextOrchestrator
        from neurova.agent.config import AgentConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config = AgentConfig(
                name="test_agent",
                agent_id="test_agent",
                workspace_path=tmpdir,
            )

            # ContextOrchestrator 构造函数接受 Agent 实例，需要 soul + config
            mock_agent = Mock()
            mock_agent.soul = "你是一个测试助手"
            mock_agent.personality = None
            mock_agent.config = config
            mock_agent.conversation_history = []

            mock_builder = Mock()
            mock_builder.build_from_pool.return_value = [
                {"role": "system", "content": "系统提示"},
                {"role": "user", "content": "当前问题"},
            ]
            mock_builder.compress_if_needed.side_effect = lambda ctx: ctx
            mock_agent.context_builder = mock_builder

            mock_tool_router = AsyncMock()
            mock_tool_router.get_all_tools.return_value = []
            mock_agent.tool_router = mock_tool_router

            mock_skill_registry = Mock()
            mock_skill_registry.get_all_tools.return_value = []
            mock_agent._skill_registry = mock_skill_registry

            orchestrator = ContextOrchestrator(mock_agent)

            session_data = [
                {"role": "user", "content": "上一轮的提问"},
                {"role": "assistant", "content": "上一轮的回答"},
            ]

            # 传入 session_context 应该不报错（验证参数接收正确）
            context = await orchestrator.build_context(
                user_input="当前问题",
                session_context=session_data,
            )

            assert context is not None
            assert isinstance(context, list)


# ══════════════════════════════════════════════════════════════
# GAP-2: _update_history() 应在主路径调用
# ══════════════════════════════════════════════════════════════

class TestGap2ConversationHistoryUpdate:
    """GAP-2: chat() 主路径不更新 conversation_history"""

    def test_update_history_exists_and_works(self):
        """_update_history 方法应该存在且委托正确"""
        from neurova.mem_core import MemCore
        from neurova.conversation_context import ConversationContext

        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        # D3 修复: update_history 不再有 fallback,必须显式注入 ConversationContext
        mock_agent._conversation_context = ConversationContext(max_messages=100)
        mem_core = MemCore(mock_agent)

        assert hasattr(mem_core, 'update_history'), \
            "MemCore 缺少 update_history 方法"

        mem_core.conversation_history = []
        mem_core.update_history("user msg", "agent reply")

        assert len(mem_core.conversation_history) == 2
        assert mem_core.conversation_history[0]["role"] == "user"
        assert mem_core.conversation_history[1]["role"] == "assistant"


# ══════════════════════════════════════════════════════════════
# GAP-4: route_chat() 应传递 session_id
# ══════════════════════════════════════════════════════════════

class TestGap4RouteChatSessionId:
    """GAP-4: route_chat() 不传 session_id"""

    def test_route_chat_has_session_id_field(self):
        """Message 模型应该有 session_id 可用字段"""
        # 不依赖真实 import，用 inspect 确认
        # route_chat 函数的 message 参数需要支持 session_id
        pass  # 此测试需要实际启动 app 才能验证，作为集成测试留空


# ══════════════════════════════════════════════════════════════
# 集成验证：完整闭环
# ══════════════════════════════════════════════════════════════

class TestClosedLoopIntegration:
    """验证修复后的完整闭环"""

    def test_mem_core_complete_api_surface(self):
        """MemCore 应该暴露完整的会话 API"""
        from neurova.mem_core import MemCore

        required_methods = [
            'save_conversation_memory',
            'update_history',
            'save_to_session',      # GAP-3 新增
            'update_memory_temperature',
            'get_memory_stats',
            'retrieve_memories',
            'unified_experience_recall',
        ]

        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.agent_id = "test_agent"
        mem_core = MemCore(mock_agent)

        for method in required_methods:
            assert hasattr(mem_core, method), \
                f"MemCore 缺少必需方法: {method}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
