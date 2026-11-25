# -*- coding: utf-8 -*-
"""CHAN-05：出站失败不得广播 AGENT_REPLY，失败适配器必须如实返回失败。

审计证据（docs/05-reports/全仓逐文件审计报告_2026-11-25.md §8 CHAN-05）：
1. `ChannelManager.send_message` 在分片失败后仍调用 `_sync_reply_to_session`，
   SessionSyncManager 把 AGENT_REPLY 广播给其他渠道——用户没收到，系统认为已发送；
2. `WeChatAdapter.send_message` 丢弃 mixin 返回的布尔，恒返回 ""（成功）；
3. `XiaoYiAdapter.send_message(message, session_id)` 与基类
   `(chat_id, content, message_type, **kwargs)` 参数错位，且返回 False 被
   manager 的 `result is not None` 判成成功。

判据：
- 失败片零同步、成功片照旧同步；
- 微信适配器把 mixin 的 False 映射为 None（失败）；
- 小艺适配器按基类契约发送（chat_id/content 各就各位）并返回 Optional[str]。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.manager import ChannelManager, get_channel_manager


def _makeAdapter(sendFn):
    adapter = FeishuAdapter(
        ChannelConfig(channel_type="feishu", app_id="cli_f", app_secret="sec", use_stream=False)
    )
    adapter._connected = True
    adapter.send_message = sendFn
    return adapter


@pytest.fixture()
def manager(tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = False
    mgr.outbound_ledger = False  # 台账归宿归批 F 测试；本判据只钉同步广播
    synced: list = []

    async def _recordSync(scope, part, channel_type):
        synced.append(part)

    mgr._sync_reply_to_session = _recordSync
    try:
        yield mgr, synced
    finally:
        mgr.unregister_adapter("feishu", agent_id="default")
        ChannelManager._instance = None


class TestFailureDoesNotSyncSuccess:
    def testFailedPartIsNotBroadcast(self, manager):
        mgr, synced = manager

        async def _alwaysFail(chat_id, content, message_type="text", **kwargs):
            return None

        mgr.register_adapter(_makeAdapter(_alwaysFail), agent_id="default")
        mid = asyncio.run(
            mgr.send_message(channel_type="feishu", chat_id="oc_fail", content="发不出去")
        )

        assert mid is None
        assert synced == [], (
            f"发送失败的片仍被广播成 AGENT_REPLY（实得 {synced}）——其他渠道看到'已发送'"
        )

    def testOnlySuccessfulPartsAreBroadcast(self, manager, monkeypatch):
        mgr, synced = manager
        import neurova.channels.message_chunker as chunkerModule

        monkeypatch.setattr(
            chunkerModule, "split_message", lambda content, limit: ["好片", "坏片"]
        )

        async def _byContent(chat_id, content, message_type="text", **kwargs):
            return f"msg_{content}" if content == "好片" else None

        mgr.register_adapter(_makeAdapter(_byContent), agent_id="default")
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_mix", content="两片"))

        assert synced == ["好片"], f"同步广播的片序/成败不匹配（实得 {synced}）"


class TestAdapterSendContract:
    def testWechatMapsMixinFalseToFailure(self, monkeypatch):
        from neurova.channels import wechat_messaging
        from neurova.channels.wechat import WeChatAdapter

        monkeypatch.setattr(
            wechat_messaging.WeChatMessagingMixin,
            "send_message",
            lambda self, message: False,
        )
        adapter = WeChatAdapter()
        assert asyncio.run(adapter.send_message("chat-1", "hi")) is None, (
            "微信 mixin 明确返回 False，适配器仍以 \"\" 报成功"
        )

        monkeypatch.setattr(
            wechat_messaging.WeChatMessagingMixin,
            "send_message",
            lambda self, message: True,
        )
        assert asyncio.run(adapter.send_message("chat-1", "hi")) == ""

    def testXiaoyiHonoursBaseSignatureAndSendsContent(self):
        from neurova.channels.xiaoyi import XiaoYiAdapter

        adapter = XiaoYiAdapter()
        adapter.authenticated = True
        adapter._connected = True
        sent: list = []

        class _FakeWs:
            async def send(self, payload):
                sent.append(json.loads(payload))

        adapter.ws = _FakeWs()
        result = asyncio.run(adapter.send_message("chat-9", "你好小艺", "text"))

        assert result == "", f"成功发送应返回非 None 回执（实得 {result!r}）"
        assert sent and sent[0]["content"] == "你好小艺", (
            f"参数错位：chat_id/content 没有各就各位（实得 {sent}）"
        )
        assert sent[0]["session_id"] == "chat-9"

    def testXiaoyiFailureReturnsNoneNotFalse(self):
        from neurova.channels.xiaoyi import XiaoYiAdapter

        adapter = XiaoYiAdapter()
        adapter.authenticated = True
        adapter._connected = False

        assert asyncio.run(adapter.send_message("chat-9", "hi")) is None, (
            "未连接时返回 False 会被 manager 的 result is not None 判成发送成功"
        )