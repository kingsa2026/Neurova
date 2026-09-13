# -*- coding: utf-8 -*-
"""飞书 Stream 回调签名回归钉（"发消息无响应"根因）。

lark-oapi 的 P2ImMessageReceiveV1Processor.do 以 self.f(data) 单参数调用注册的
handler（data=P2ImMessageReceiveV1，.event 为数据体）。若 _handle_message_event
签名多一个形参（历史 bug：(self, ctx, event)），data 绑到 ctx、event 缺参 →
TypeError 被 SDK 吞掉 → 收消息静默丢弃。本测试锁死签名恰为 (self, event)。
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.feishu import FeishuAdapter


def _adapter():
    return FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="a", app_secret="s"))


def test_handler_signature_is_single_arg_plus_self():
    params = list(inspect.signature(FeishuAdapter._handle_message_event).parameters)
    assert params == ["self", "event"], (
        f"lark 以单参数调用 handler，签名须恰为 (self, event)，实为 {params}"
    )


def test_handler_processes_one_arg_event_and_emits():
    """用真实 lark 事件形状（单参数 data.event.message/sender）驱动 handler，须发出事件。"""
    import asyncio

    a = _adapter()
    received = []

    async def cb(event_type, msg):
        received.append((event_type, msg))

    a.set_event_callback(cb)

    data = SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="text",
                content=json.dumps({"text": "你好"}),
                message_id="m1",
                chat_id="c1",
                chat_type="p2p",
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(user_id="u1")),
        ),
    )

    async def drive():
        loop = asyncio.get_running_loop()
        a._main_loop = loop
        a._handle_message_event(data)  # 单参数调用（复刻 processor 的 f(data)）
        # handler 经 run_coroutine_threadsafe 调度到主 loop，让回调跑完
        for _ in range(20):
            await asyncio.sleep(0.01)
            if received:
                break

    asyncio.run(drive())

    assert received, "单参数事件未被处理（签名/调度回归）"
    et, msg = received[0]
    assert et == ChannelEventType.MESSAGE_RECEIVED
    assert msg.content == "你好"
    assert msg.chat_id == "c1"
    assert msg.sender_id == "u1"
