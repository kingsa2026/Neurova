"""RES-P2-2 回归测试：/chat SSE 客户端断连必须取消后台生成任务。

背景（docs/资源型Bug扫描报告_2026-09-11.md P2-2）：
chat.py /stream 的 event_generator 断连（GeneratorExit）时不取消
run_chat 任务——孤儿任务继续跑完全程（LLM/工具/记忆落盘照常），
断连风暴下 token 白烧叠加；console /chat/stop 对其无效。
对照 console.py 同链路：已注册 task_tracker 且 finally 收尸。

验收：消费方 aclose 后，fake agent.chat 必须收到取消（finally 被执行）。
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import chat as chat_ep


@pytest.mark.asyncio
async def test_client_disconnect_cancels_run_chat(monkeypatch):
    cleanup = {"done": False}

    class FakeAgent:
        async def chat(self, user_input, stream=False, session_id=None, metadata=None):
            emitter = metadata["event_emitter"]
            emitter("content", "hello")
            try:
                await asyncio.sleep(30)  # 模拟长生成，被断连打断
            finally:
                cleanup["done"] = True
            return {"text": "done"}

    monkeypatch.setattr(chat_ep, "_get_agent", lambda agent_id: FakeAgent())
    monkeypatch.setattr(chat_ep, "_user_can_access_agent", lambda *a, **k: True)
    monkeypatch.setattr(chat_ep, "_get_request_id", lambda request: "req-test")

    body = chat_ep.ChatStreamRequest(message="hi", agent_id="a1", session_id="s1")
    resp = await chat_ep.chat_stream(
        request=MagicMock(), body=body, current_user={"user_id": "u1", "role": "admin"}
    )

    it = resp.body_iterator
    start = await it.__anext__()
    assert "event: start" in start
    content = await it.__anext__()
    assert "hello" in content

    # 模拟客户端断连：SSE 消费方提前关闭生成器
    await it.aclose()
    await asyncio.sleep(0.05)

    assert cleanup["done"] is True, (
        "断连后 run_chat 未被取消——孤儿任务继续跑完全程（RES-P2-2）"
    )
