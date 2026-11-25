# -*- coding: utf-8 -*-
"""CHAN-06：入站分发失败必须 nack 重试/死信，不得吞掉后 ack。

审计证据（docs/05-reports/全仓逐文件审计报告_2026-11-25.md §8 CHAN-06）：
`ChannelManager._dispatch_message` 把处理器异常记日志后照常返回，
`_on_channel_event` 随即 `queue.ack`——Agent/工具失败的消息终态 done，
既不重试也不进死信；`channel_router` 更把 `agent.chat` 异常改写成
`return None`（看起来"本轮无回复"）；适配器基类 `_emit_event` 也把回调
异常吞成日志。三层同根：失败被伪装成成功。

判据：
1. 处理器抛异常 → 队列行保持 pending、attempt+1、last_error 记录原因；
2. 处理器异常不再被 _dispatch_message 吞（直接调用必须上抛）；
3. channel_router 在 agent.chat 失败时上抛而不是返回 None；
4. 适配器事件回调异常不再被 _emit_event 吞。
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType, ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue
from neurova.channels.manager import ChannelManager, get_channel_manager


def _msg(mid="m-chan06", chat="c1", channel="feishu", content="触发工具"):
    return ChannelMessage(
        channel_type=channel,
        message_id=mid,
        sender_id="u1",
        sender_name="User",
        content=content,
        chat_id=chat,
    )


@pytest.fixture()
def queue(tmp_path):
    q = ChannelIngressQueue(db_path=tmp_path / "ingress.db")
    yield q
    q.close()


@pytest.fixture()
def manager(queue, tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = queue
    mgr.outbound_ledger = False
    yield mgr
    mgr._message_handlers = []
    ChannelManager._instance = None


class TestQueueNacksHandlerFailure:
    def testHandlerFailureLeavesRowPending(self, manager, queue):
        async def _boom(message):
            raise RuntimeError("工具执行失败")

        manager.add_message_handler(_boom, priority=10)
        asyncio.run(
            manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, _msg())
        )

        with sqlite3.connect(queue.db_path) as conn:
            row = conn.execute(
                "SELECT status, attempt, last_error FROM channel_ingress_events"
                " WHERE message_id='m-chan06'"
            ).fetchone()
        assert row is not None, "消息未落队列入站表"
        status, attempt, last_error = row
        assert status == "pending", f"分发失败的消息被 ack 成 done（status={status}）"
        assert attempt == 1, f"失败未计入 attempt（实得 {attempt}）"
        assert "工具执行失败" in (last_error or ""), f"失败原因未落 last_error（实得 {last_error!r}）"

    def testDispatchRaisesInsteadOfSwallowing(self, manager):
        async def _boom(message):
            raise RuntimeError("处理器炸了")

        manager.add_message_handler(_boom, priority=10)
        with pytest.raises(Exception) as excinfo:
            asyncio.run(manager._dispatch_message(_msg()))
        assert "处理器炸了" in str(excinfo.value), (
            f"_dispatch_message 吞掉了处理器失败（抛出 {excinfo.value!r}）"
        )


class TestRouterAndAdapterDoNotFakeSuccess:
    def testRouterRaisesOnAgentChatFailure(self):
        from neurova.channels import channel_router

        class _FailingAgent:
            class config:
                owner_user_id = None

            async def chat(self, **kwargs):
                raise RuntimeError("模型后端 502")

        ChannelManager._instance = None
        mgr = ChannelManager()
        try:
            handler = channel_router.make_handler(mgr, agent_lookup=lambda aid: _FailingAgent())
            with pytest.raises(Exception) as excinfo:
                asyncio.run(handler(_msg()))
            assert "模型后端 502" in str(excinfo.value) or "chat 失败" in str(excinfo.value), (
                f"agent.chat 失败被改写成 None（抛出 {excinfo.value!r}）"
            )
        finally:
            ChannelManager._instance = None

    def testEmitEventDoesNotSwallowCallbackFailure(self):
        from neurova.channels.feishu import FeishuAdapter

        adapter = FeishuAdapter(
            ChannelConfig(channel_type="feishu", app_id="f", app_secret="s", use_stream=False)
        )

        async def _callback(event_type, message):
            raise RuntimeError("入站分发失败")

        adapter.set_event_callback(_callback)
        with pytest.raises(RuntimeError):
            asyncio.run(adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, _msg()))