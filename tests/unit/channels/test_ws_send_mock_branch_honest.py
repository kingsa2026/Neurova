# -*- coding: utf-8 -*-
"""任务1（资源型修复登记台账 2026-09-11 渠道域收尾）：WebSocket 模拟分支诚实化。

缺陷：_send_unified 中 `not WEBSOCKETS_AVAILABLE or not self._ws_connection`
分支在 _connected=True 的窄窗口（断开收尾竞态 / 依赖缺失）可达时，
"[WebSocket模拟]" 假成功 return True——发送结果谎报成功。

契约：该分支 logger.warning + return False；防回归断言返回 False 且
"WebSocket模拟" 字样不得回流。
"""

import logging

import pytest

import neurova.channels.websocket as websocket_module
from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage
from neurova.channels.websocket import WebSocketAdapter


def _msg():
    return UnifiedMessage(
        message_id="m1",
        channel=MessageChannel.WEBSOCKET,
        content_type=ContentType.TEXT,
        content="hello",
        user_id="u1",
        chat_id="c1",
    )


def _adapter_in_narrow_window():
    """前置守卫（未初始化/未连接）通过、_ws_connection 缺失——精确命中目标分支"""
    adapter = WebSocketAdapter()
    adapter._initialized = True
    adapter._connected = True
    adapter._ws_connection = None
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("ws_available", [True, False])
async def test_send_unified_without_connection_honest_failure(monkeypatch, caplog, ws_available):
    """窄窗口（_connected=True 且 _ws_connection=None）必须诚实失败，禁止模拟假成功"""
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", ws_available)
    adapter = _adapter_in_narrow_window()

    with caplog.at_level(logging.WARNING):
        ok = await adapter._send_unified(_msg())

    assert ok is False, "无连接发送必须如实失败（原 [WebSocket模拟] return True 已清除）"
    assert "WebSocket模拟" not in caplog.text, "模拟字样不得回流"


@pytest.mark.asyncio
async def test_send_message_without_connection_returns_none(monkeypatch):
    """基类签名 send_message 经同一分支：诚实失败返回 None（非本地 id）"""
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)
    adapter = _adapter_in_narrow_window()

    assert await adapter.send_message("c1", "hello") is None
