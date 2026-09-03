"""builtin:llm 节点 — 按 {provider, model} 路由测试

TDD 红绿灯：本文件先写（RED），要求 exec_llm 在显式指定 model_provider+model_name 时，
经多模型客户端对指定模型+Provider 真正发起调用；未指定时回退 Agent.chat()。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.collaboration.neurflow.builtin import exec_llm


@pytest.mark.asyncio
async def test_exec_llm_routes_to_multi_model_client():
    """显式 provider+model 时应调用多模型客户端（而非 Agent.chat）"""
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={
        "success": True,
        "response": {"choices": [{"message": {"content": "Model response"}}]},
        "model": "gpt-4",
        "provider": "openai",
    })

    with patch(
        "neurova.collaboration.neurflow.builtin._get_multi_model_client",
        return_value=fake_client,
    ):
        config = {
            "prompt": "Hello",
            "system_prompt": "You are a bot",
            "model_provider": "openai",
            "model_name": "gpt-4",
        }
        result = await exec_llm(config, {})

    assert result["status"] == "success"
    assert result["output"]["text"] == "Model response"
    # 必须按选定 provider/model 客户端调用
    call_args = fake_client.chat.call_args
    call_kwargs = call_args.kwargs
    assert call_kwargs["model"] == "gpt-4"
    assert call_kwargs["provider_id"] == "openai"
    # 消息应包含 system + user 两条（messages 可能为位置参数）
    messages = call_kwargs.get("messages") or (
        call_args.args[0] if call_args.args else None
    )
    assert any(m.get("role") == "system" for m in messages)
    assert any(m.get("role") == "user" for m in messages)


@pytest.mark.asyncio
async def test_exec_llm_model_route_failure_returns_failed():
    """多模型客户端失败时应返回 failed + error，不抛异常"""
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={
        "success": False,
        "error": "connection refused",
        "model": "gpt-4",
        "provider": "openai",
    })
    with patch(
        "neurova.collaboration.neurflow.builtin._get_multi_model_client",
        return_value=fake_client,
    ):
        config = {
            "prompt": "Hello",
            "model_provider": "openai",
            "model_name": "gpt-4",
        }
        result = await exec_llm(config, {})

    assert result["status"] == "failed"
    assert "connection refused" in result["error"]


@pytest.mark.asyncio
async def test_exec_llm_auto_falls_back_to_agent():
    """未指定 provider/model（auto）时应回退 Agent.chat()"""
    fake_agent = MagicMock()
    fake_agent.chat = AsyncMock(return_value="AI response")

    with patch(
        "neurova.collaboration.neurflow.builtin._get_agent", return_value=fake_agent
    ), patch(
        "neurova.collaboration.neurflow.builtin._get_multi_model_client",
        return_value=None,
    ):
        config = {"prompt": "Hello", "temperature": 0.7}
        result = await exec_llm(config, {})

    assert result["status"] == "success"
    assert result["output"]["text"] == "AI response"
    # 不应走多模型客户端
    assert not hasattr(result["output"], "provider")
    fake_agent.chat.assert_called_once()


@pytest.mark.asyncio
async def test_exec_llm_routing_unavailable_falls_back_to_agent():
    """模型路由客户端不可用且未指定模型时，回退 Agent.chat"""
    fake_agent = MagicMock()
    fake_agent.chat = AsyncMock(return_value="fallback")

    with patch(
        "neurova.collaboration.neurflow.builtin._get_agent", return_value=fake_agent
    ), patch(
        "neurova.collaboration.neurflow.builtin._get_multi_model_client",
        return_value=None,
    ):
        config = {"prompt": "Hi"}
        result = await exec_llm(config, {})

    assert result["status"] == "success"
    assert result["output"]["text"] == "fallback"
