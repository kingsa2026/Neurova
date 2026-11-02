# -*- coding: utf-8 -*-
"""批 D：入站队列不可用——有界直发＋旁路台账（T4 已裁）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 D）：
`IngressQueueUnavailable` 时 fail-open 直发是**静默绕过**——没有台账行、没有
计数、面板读不到"队列坏了多久"。T4 裁定：有界直发（同一 dispatch 路径消灭
行为分叉）＋旁路台账行＋计数读数——旁路计数成为常驻读数后，队列可用性本身
有了事实判据。入站去重键（平台消息 id）不动。
"""
import asyncio
from types import SimpleNamespace

import pytest

from neurova.channels.channel_ingress_queue import IngressQueueUnavailable
from neurova.channels.outbound_ledger import ChannelBypassLedger


class _BrokenQueue:
    """enqueue 必炸的队列（模拟 DB 故障）。"""

    def enqueue(self, message):
        raise IngressQueueUnavailable("db broken (live-verify 桩)")


class _HealthyQueue:
    """最小健康队列：入队成功、可认领。"""

    def __init__(self):
        self.pending = []

    def enqueue(self, message):
        self.pending.append(message)
        return True

    def claim(self, worker="inline"):
        if self.pending:
            msg = self.pending.pop(0)
            return SimpleNamespace(event_id="ev_1", message=msg)
        return None

    def ack(self, event_id):
        return True

    def nack(self, event_id, reason):
        return True


@pytest.fixture()
def manager(tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    ChannelManager._instance = None
    mgr = get_channel_manager()

    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_d",
                                          app_secret="sec", use_stream=False))
    adapter._connected = True
    sent = []

    async def _record(chat_id, content, message_type="text", **kwargs):
        sent.append(content)
        return "msg_d"

    adapter.send_message = _record
    mgr.register_adapter(adapter, agent_id="default")

    async def _noSessionSync(*args, **kwargs):
        return None

    mgr._sync_reply_to_session = _noSessionSync

    async def _echoHandler(message):
        # 处理器里做一次真实外发——旁路/健康两条路都要能走到 adapter.send
        await mgr.send_message(channel_type=message.channel_type,
                               chat_id=message.chat_id,
                               content=message.content, agent_id="default")
        return None

    mgr.add_message_handler(_echoHandler, priority=1)
    ledger = ChannelBypassLedger(db_path=tmp_path / "bypass.db")
    mgr.bypass_ledger = ledger
    try:
        yield mgr, sent, ledger
    finally:
        mgr.remove_message_handler(_echoHandler)
        mgr.unregister_adapter("feishu", agent_id="default")
        ledger.close()
        ChannelManager._instance = None


def _inbound(message_id="om_d"):
    from neurova.channels.base import ChannelEventType, ChannelMessage

    return ChannelMessage(channel_type="feishu", message_id=message_id, sender_id="ou_d",
                          sender_name="ou_d", content="旁路一条", chat_id="oc_d")


class TestBypassOnQueueUnavailable:
    def test_bypassStillDispatchesAndRecords(self, manager):
        """队列不可用：同一 dispatch 路径直发（行为不分叉）＋旁路台账行落库。"""
        mgr, sent, ledger = manager
        mgr.ingress_queue = _BrokenQueue()

        asyncio.run(mgr._on_channel_event(_noopEvent(), _inbound("om_x")))

        assert sent == ["旁路一条"], "旁路直发没有走到分发（可用性被砍了）"
        rows = ledger.queryBypass()
        assert len(rows) == 1, f"旁路直发没有落台账（仍是静默绕过）：{len(rows)} 行"
        assert rows[0]["message_id"] == "om_x"
        assert "feishu" == rows[0]["channel_type"]
        assert rows[0]["reason"], "旁路原因没记"

    def test_healthyQueueLeavesNoBypassRows(self, manager):
        """对照：队列健康时零旁路行。"""
        mgr, sent, ledger = manager
        mgr.ingress_queue = _HealthyQueue()

        asyncio.run(mgr._on_channel_event(_noopEvent(), _inbound("om_y")))

        assert sent == ["旁路一条"], "健康队列路径的分发被改坏了"
        assert ledger.queryBypass() == []

    def test_readoutExposesCountAndRecent(self, manager):
        """读面（T4 的'常驻读数'）：总数 + 最近行，台账不可用如实报。"""
        mgr, sent, ledger = manager
        mgr.ingress_queue = _BrokenQueue()
        asyncio.run(mgr._on_channel_event(_noopEvent(), _inbound("om_z")))

        readout = mgr.getIngressBypassReadout()
        assert readout["available"] is True
        assert readout["total"] == 1
        assert readout["recent"][0]["message_id"] == "om_z"

        mgr.bypass_ledger = False  # 强制关台账 → 读数如实报不可用
        assert mgr.getIngressBypassReadout()["available"] is False


def _noopEvent():
    from neurova.channels.base import ChannelEventType

    return ChannelEventType.MESSAGE_RECEIVED


class TestBypassLedgerStandalone:
    def test_recordAndFilter(self, tmp_path):
        ledger = ChannelBypassLedger(db_path=tmp_path / "b.db")
        try:
            ledger.recordBypass(channel_type="feishu", chat_id="oc_1",
                                message_id="m1", reason="db broken")
            ledger.recordBypass(channel_type="qq", chat_id="oc_2",
                                message_id="m2", reason="db broken")
            assert ledger.countBypass() == 2
            onlyFeishu = ledger.queryBypass(channel_type="feishu")
            assert len(onlyFeishu) == 1 and onlyFeishu[0]["message_id"] == "m1"
        finally:
            ledger.close()
