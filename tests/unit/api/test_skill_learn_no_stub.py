"""
C4 测试：验证 learn_from_conversation 不再返回 stub，改为真实持久化

验证：
1. learn_from_conversation 不再返回 "Learning feature not implemented yet"
2. agent 不可用时，应持久化对话到记忆库（或明确返回 success=False）
3. 行为验证：mock memory_manager，验证对话被持久化
"""

import inspect
from unittest.mock import patch, MagicMock, AsyncMock


def test_learn_from_conversation_no_stub_message():
    """C4.1: learn_from_conversation 不应再返回 'Learning feature not implemented yet'"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.learn_from_conversation)
    assert "Learning feature not implemented yet" not in source, \
        "learn_from_conversation 不应再返回 'Learning feature not implemented yet' stub"


def test_learn_from_conversation_persists_when_agent_unavailable():
    """C4.2: agent 不可用时，learn_from_conversation 应持久化对话到记忆库"""
    from neurova.api.endpoints import skill as skill_module
    source = inspect.getsource(skill_module.learn_from_conversation)
    # 应包含某种持久化机制（记忆库或 evolution engine）
    assert "save_conversation_memory" in source or "memory_manager" in source or "save_to_session" in source, \
        "agent 不可用时，应通过记忆库持久化对话作为学习素材"


def test_learn_from_conversation_behavior_persists():
    """C4.3: 行为验证 — agent 不可用时，对话应被持久化"""
    import asyncio
    from fastapi import Request
    from neurova.api.endpoints import skill as skill_module
    from neurova.api.endpoints.skill import SkillLearnRequest, SkillLearnResponse

    # mock memory_manager
    mock_memory = MagicMock()
    mock_memory.save_conversation_memory = MagicMock(return_value=True)

    # mock _get_agent 返回 None
    with patch.object(skill_module, "_get_agent", return_value=None):
        # mock get_memory_manager（通过 deps）
        with patch("neurova.api.deps.get_memory_manager", return_value=mock_memory):
            request = MagicMock(spec=Request)
            request.state.request_id = "test"
            body = SkillLearnRequest(
                messages=[{"role": "user", "content": "hello"}],
                feedback="good",
            )
            result = asyncio.run(skill_module.learn_from_conversation(request, body))
            # 验证对话被持久化
            assert mock_memory.save_conversation_memory.called, \
                "agent 不可用时，应调用 save_conversation_memory 持久化对话"
            # 验证返回 success（不是 stub）
            assert result.success is True, "持久化成功后应返回 success=True"
            assert "not implemented" not in (result.message or "").lower(), \
                "不应返回 'not implemented' 消息"
