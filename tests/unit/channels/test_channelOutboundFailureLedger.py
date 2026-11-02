# -*- coding: utf-8 -*-
"""批 F：出口失败片归宿——同片重试一次 + 落出口失败台账。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 F）：
`ChannelManager.send_message` 的失败片此前只有告警日志（manager.py:352-360）——
无台账行、无重试、无死信归宿，失败是半静默的。入站有持久队列兜可靠性，
出口的失败连一条可查的记录都没有。本批给失败片两个归宿：

① 同片重试一次（具名常量 `OUTBOUND_CHUNK_RETRIES=1`，抓瞬态失败）；
② 重试仍败落出口失败台账（渠道/会话/agent/片序/尝试数/原因/内容头），可查。

域边界：回合级错误（chat_error）归 `core/agent_run_ledger`（结算点早于出站）；
出口失败归 `outbound_ledger`——各自补域空白，不合并。
"""
import asyncio

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.manager import OUTBOUND_CHUNK_RETRIES, ChannelManager, get_channel_manager
from neurova.channels.outbound_ledger import OutboundFailureLedger


def _makeAdapter(sendFn):
    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_f",
                                          app_secret="sec", use_stream=False))
    adapter._connected = True
    adapter.send_message = sendFn
    return adapter


@pytest.fixture()
def manager(tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = False  # 入站持久队列不是本批主张，走直发路径

    async def _noSessionSync(*args, **kwargs):
        return None

    mgr._sync_reply_to_session = _noSessionSync  # 会话回写不是本批主张
    ledger = OutboundFailureLedger(db_path=tmp_path / "outbound.db")
    mgr.outbound_ledger = ledger  # 注入面与 ingress_queue 同款
    try:
        yield mgr, ledger
    finally:
        mgr.unregister_adapter("feishu", agent_id="default")
        ledger.close()
        ChannelManager._instance = None


class TestRetryPolicy:
    def test_retryConstantIsOneAndNamed(self):
        """重试预算是具名常量不是裸数字——预算口径只许一处定义。"""
        assert OUTBOUND_CHUNK_RETRIES == 1

    def test_failedChunkIsRetriedOnceThenRecovers(self, manager):
        """首发失败 → 同片重试一次成功：发送整体成功，台账零行（恢复了的不记账）。"""
        mgr, ledger = manager
        calls = {"n": 0}

        async def _flakySend(chat_id, content, message_type="text", **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # 适配器契约：失败返回 None
            return f"msg_ok_{calls['n']}"

        mgr.register_adapter(_makeAdapter(_flakySend), agent_id="default")
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                           content="首发失败重试就好的那条"))

        assert calls["n"] == 2, f"失败片没有被重试（实发 {calls['n']} 次）——瞬态失败直接丢片"
        assert mid == "msg_ok_2"
        assert ledger.queryFailures() == [], "恢复了的成功发送不该进失败台账"

    def test_successPathTouchesAdapterOnce(self, manager):
        """对照（不许顺手改坏）：全程成功只发一次，不多打重试。"""
        mgr, ledger = manager
        calls = {"n": 0}

        async def _okSend(chat_id, content, message_type="text", **kwargs):
            calls["n"] += 1
            return f"msg_{calls['n']}"

        mgr.register_adapter(_makeAdapter(_okSend), agent_id="default")
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                           content="全程成功的一条"))

        assert mid == "msg_1" and calls["n"] == 1, f"成功路被重试逻辑打扰：{calls['n']} 次"
        assert ledger.queryFailures() == []


class TestFailureLedgerDestination:
    def test_exhaustedChunkLandsInLedgerWithFullFacts(self, manager):
        """重试仍败 → 台账一行点名全部事实：渠道/会话/agent/片序/尝试数/内容头。"""
        mgr, ledger = manager

        async def _alwaysFail(chat_id, content, message_type="text", **kwargs):
            return None

        mgr.register_adapter(_makeAdapter(_alwaysFail), agent_id="default")
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_9",
                                           content="永远发不出去的一条", agent_id="default"))

        assert mid is None
        rows = ledger.queryFailures(channel_type="feishu")
        assert len(rows) == 1, f"失败片没有落台账（实得 {len(rows)} 行）——失败仍是半静默的"
        row = rows[0]
        assert row["channel_type"] == "feishu"
        assert row["chat_id"] == "oc_9"
        assert row["agent_id"] == "default"
        assert row["part_index"] == 1 and row["total_parts"] == 1
        assert row["attempts"] == OUTBOUND_CHUNK_RETRIES + 1, "台账里的尝试数与重试预算不符"
        assert "永远发不出去" in row["content_head"], "内容头没记——失败片查不到是哪句话"

    def test_multiChunkFailureNamesTheRightPart(self, manager, monkeypatch):
        """多片只坏一片：片序必须指到坏的那片（顺带钉 enumerate 口径——
        此前 parts.index(part) 遇重复片会报错序号）。分片表注入受控清单：
        chunker 内部归它自己的测试管，本批主张是片序与台账。"""
        mgr, ledger = manager
        import neurova.channels.message_chunker as chunkerModule

        monkeypatch.setattr(
            chunkerModule, "split_message",
            lambda content, limit: ["好片甲", "好片乙", "坏片丙"],
        )

        async def _byContent(chat_id, content, message_type="text", **kwargs):
            if "坏片" in content:
                return None
            return f"msg_{content}"

        mgr.register_adapter(_makeAdapter(_byContent), agent_id="default")
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_2",
                                           content="受控分片的三片内容"))

        assert mid == "msg_好片甲", "好片成功了，整体回执不该是 None"
        rows = ledger.queryFailures()
        assert len(rows) == 1, f"只坏一片却记了 {len(rows)} 行"
        assert rows[0]["part_index"] == 3 and rows[0]["total_parts"] == 3, (
            f"片序指错（实得 {rows[0]['part_index']}/{rows[0]['total_parts']}）"
        )
        assert "坏片丙" in rows[0]["content_head"]

    def test_duplicatePartsGetDistinctIndexes(self, manager, monkeypatch):
        """重复内容的两个坏片：两行各自片序正确（index() 老病在此复发即红）。"""
        mgr, ledger = manager
        import neurova.channels.message_chunker as chunkerModule

        monkeypatch.setattr(
            chunkerModule, "split_message",
            lambda content, limit: ["同文坏片", "同文坏片"],
        )

        async def _alwaysFail(chat_id, content, message_type="text", **kwargs):
            return None

        mgr.register_adapter(_makeAdapter(_alwaysFail), agent_id="default")
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_3",
                                     content="同文坏片\n\n同文坏片"))

        rows = ledger.queryFailures()
        assert sorted(r["part_index"] for r in rows) == [1, 2], (
            f"重复片的片序没有各自成立（实得 {[(r['part_index'], r['content_head'][:10]) for r in rows]}）"
        )

    def test_ledgerFiltersByChat(self, manager):
        """读面可按会话过滤——失败归宿必须能被"哪个会话在丢片"这类问题查到。"""
        mgr, ledger = manager

        async def _alwaysFail(chat_id, content, message_type="text", **kwargs):
            return None

        mgr.register_adapter(_makeAdapter(_alwaysFail), agent_id="default")
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_a", content="A 会话的失败"))
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_b", content="B 会话的失败"))

        assert len(ledger.queryFailures()) == 2
        onlyA = ledger.queryFailures(chat_id="oc_a")
        assert len(onlyA) == 1 and onlyA[0]["chat_id"] == "oc_a"
