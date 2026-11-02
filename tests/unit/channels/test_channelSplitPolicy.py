# -*- coding: utf-8 -*-
"""批 C：出口拆分策略登记表（T1 已裁仅系统生成文案）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 C）：
拆分此前只认渠道长度——审批通知这类结构化出口被拆散后上下文丢失；系统生成
文案没有字符预算。本批：策略登记表（allow/forbid）+ 禁拆类诚实截断
（显式标记 + 全文进日志），agent 正文与管理员手动发送行为不变（T1 范围）。
"""
import asyncio
import logging

import pytest

from neurova.channels.message_chunker import (
    SPLIT_POLICY_ALLOW,
    SPLIT_POLICY_FORBID,
    SYSTEM_NOTICE_MAX_CHARS,
    split_message,
    text_limit_for,
    truncate_forbidden,
)


class TestPolicyRegistry:
    def test_policiesAreNamedConstants(self):
        """策略是具名常量不是散落字符串——口径只许一处定义。"""
        assert SPLIT_POLICY_ALLOW == "allow" and SPLIT_POLICY_FORBID == "forbid"

    def test_truncationBudgetRespectsSmallestChannelLimit(self):
        """禁拆预算必须 ≤ 最小渠道上限（wecom 1800）——否则截断件仍会被平台拒。"""
        assert SYSTEM_NOTICE_MAX_CHARS <= min(
            v for k, v in {"wecom": 1800}.items()
        ), "系统文案预算高于最小渠道上限"

    def test_truncateForbiddenKeepsShortTextUntouched(self):
        assert truncate_forbidden("短通知", "feishu") == "短通知"

    def test_truncateForbiddenMarksAndNeverSplits(self):
        """超长禁拆：单条返回、带显式标记、不超渠道上限。"""
        text = "审批说明。" * 600          # 3600 字 > 预算
        out = truncate_forbidden(text, "wecom")
        assert isinstance(out, str)
        assert len(out) <= text_limit_for("wecom"), "截断件超出渠道上限"
        assert out.endswith("全文见服务端日志。"), "截断件没有显式标记——静默丢字符"
        assert text[:20] in out, "截断件丢了头部内容"


class TestManagerSplitPolicy:
    @pytest.fixture()
    def manager(self, tmp_path):
        from tests.manual._liveVerifyIsolation import isolatedDataRoot

        isolatedDataRoot()
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.manager import ChannelManager, get_channel_manager

        ChannelManager._instance = None
        mgr = get_channel_manager()
        mgr.ingress_queue = False
        mgr.outbound_ledger = False

        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_c",
                                              app_secret="sec", use_stream=False))
        adapter._connected = True
        sent = []

        async def _record(chat_id, content, message_type="text", **kwargs):
            sent.append(content)
            return "msg_c"

        adapter.send_message = _record
        mgr.register_adapter(adapter, agent_id="default")

        async def _noSessionSync(*args, **kwargs):
            return None

        mgr._sync_reply_to_session = _noSessionSync
        try:
            yield mgr, sent
        finally:
            mgr.unregister_adapter("feishu", agent_id="default")
            ChannelManager._instance = None

    def test_forbidPolicyNeverSplitsEvenWhenOverLimit(self, manager):
        """禁拆 + 超长：渠道只收到一条（带标记），修前会被拆成多条。"""
        mgr, sent = manager
        long_text = "审批上下文。" * 800      # 4800 字 > wecom/feishu 上限
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                     content=long_text, split_policy="forbid"))
        assert len(sent) == 1, f"禁拆类被拆成 {len(sent)} 条（结构化出口上下文丢了）"
        assert sent[0].endswith("全文见服务端日志。")

    def test_allowPolicyKeepsSplittingAgentReplies(self, manager):
        """对照（T1 范围不许扩大）：默认策略 agent 正文照旧拆分。"""
        mgr, sent = manager
        long_text = "正文段落。" * 1500      # 6000 字 → feishu 4000 拆两条
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                     content=long_text))
        assert len(sent) >= 2, "agent 正文的拆分行为被顺手改了"

    def test_unknownPolicyFallsBackToAllowWithWarning(self, manager, caplog):
        mgr, sent = manager
        with caplog.at_level(logging.WARNING, logger="neurova.channels.manager"):
            asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                         content="hi", split_policy="weird"))
        assert any("weird" in r.message for r in caplog.records), "未知策略静默吞了"

    def test_forbidPolicyNotLeakedToAdapter(self, manager):
        """策略参数是 manager 的分片决策，不许漏进适配器签名。"""
        mgr, sent = manager
        seen_kwargs = {}

        async def _probe(chat_id, content, message_type="text", **kwargs):
            seen_kwargs.update(kwargs)
            return "msg_x"

        mgr._adapters["feishu"].send_message = _probe
        asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                     content="x", split_policy="forbid"))
        assert "split_policy" not in seen_kwargs, "策略参数泄漏进适配器调用"
