# -*- coding: utf-8 -*-
"""任务4（资源型修复登记台账 2026-09-11 第五节登记③）：mobile WS 双路径归一。

B-6 后 chat:send/chat:cancel 由 mobile_websocket 的 receive 循环统一拦截
（在流 task 路径），_handle_ws_message 内联 handlers 中的同名分支成为
永不触达的平行路径（双实现漂移风险）。

归一契约：分发器不再承载 chat:send/chat:cancel——两类消息唯一处理路径为
连接循环拦截；分发器对其返回 unknown_type（锁存：内联平行分支不得回流）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.api.endpoints import mobile_pairing as mp


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    mp._cancelled_sessions.clear()


def _ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"type": "chat:send", "content": "hi", "session_id": "s1"},
        {"type": "chat:cancel", "session_id": "s1"},
    ],
)
async def test_dispatcher_no_parallel_chat_paths(payload):
    """chat:send/chat:cancel 唯一入口=循环拦截；分发器不再内联分发（返回 unknown_type）"""
    ws = _ws()
    await mp._handle_ws_message(ws, payload, "user-1", "pair-1")

    sent = ws.send_json.call_args.args[0]
    assert sent["type"] == "error"
    assert sent["code"] == "unknown_type", (
        f"{payload['type']} 不得再经分发器内联分发（唯一路径=receive 循环拦截）"
    )


@pytest.mark.asyncio
async def test_dispatcher_still_dispatches_inline_types():
    """归一只删平行 chat 路径：其余内联类型（agent:switch 等）分发语义保持"""
    ws = _ws()
    await mp._handle_ws_message(ws, {"type": "agent:switch", "agent_id": "no-such-agent"}, "user-1", "pair-1")

    sent = ws.send_json.call_args.args[0]
    assert sent["type"] == "error"
    assert sent["code"] == "agent_not_found"
