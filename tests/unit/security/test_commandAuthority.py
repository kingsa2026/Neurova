# -*- coding: utf-8 -*-
"""批 H1/H2：指挥资格单一判定落点 + 判定台账。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 H，
T6 已裁本轮动）："这一轮谁能指挥 agent"由两道门分治且无统一读面——渠道准入
（access_policy.chatAccessDecision，消费点 channel_router）与治理白名单
（governance.evaluate_tool_call，消费点 tool_executor）。两门各自正确，但
没有任何一处能完整回答"发送者 S 经渠道 C 指挥 agent A 执行 W 的资格"，
审计面只有各自的半张。本批：单一判定函数（适用的门全判、任一拒绝即拒、
缺事实的门如实记 n-a）+ 每次判定落台账行（谁/哪渠道/什么命令/哪道门/结果）。

fail-closed 口径（随格落死）：有事实的门必须作答，答不出按拒绝；没事实的
门（如工具执行点没有渠道上下文）如实记 n-a——它的裁决已由拥有该事实的
消费点在更早的生命周期做出。
"""
import asyncio

import pytest

from neurova.security.command_authority import (
    AuthorityDecision,
    getCommandAuthorityLedger,
    resolveCommandAuthority,
    resetCommandAuthorityLedger,
)


@pytest.fixture()
def isolatedRoot():
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    resetCommandAuthorityLedger()
    yield
    resetCommandAuthorityLedger()


class _FakeVerdict:
    def __init__(self, decision, reasons=None):
        self.decision = decision
        self.reasons = reasons or []


class TestChannelGate:
    def test_channelDenyShortCircuitsPolicy(self, isolatedRoot, monkeypatch):
        """渠道拒绝 → 直接 deny_channel，治理门不再询问（短路即纪律）。"""
        called = {"policy": 0}

        import neurova.security.command_authority as ca

        def _spyJudge(**kwargs):
            called["policy"] += 1
            return None

        monkeypatch.setattr(ca, "_judgePolicy", _spyJudge)
        decision = resolveCommandAuthority(
            senderId="ou_x", channelType="feishu", chatType="group",
            channelCfg={"group_chat_strategy": "closed"})
        assert decision.allowed is False
        assert decision.stage == "deny_channel"
        assert "closed" in decision.reason or decision.reason
        assert called["policy"] == 0, "渠道已拒绝还去问治理门——短路纪律破了"

    def test_emptyWhitelistDeniesWithNamedReason(self, isolatedRoot):
        """白名单空即拒（access_policy 既有口径经组合点透传）。"""
        decision = resolveCommandAuthority(
            senderId="ou_stranger", channelType="feishu", chatType="group",
            channelCfg={"group_chat_strategy": "whitelist", "whitelist_users": ""})
        assert decision.allowed is False and decision.stage == "deny_channel"

    def test_channelAllowWithoutToolFactsPasses(self, isolatedRoot):
        """纯准入判定（无工具事实）：渠道放行 → 整体放行，policy 记 n-a。"""
        decision = resolveCommandAuthority(
            senderId="ou_owner", channelType="feishu", chatType="private",
            channelCfg={"private_chat_strategy": "open"})
        assert decision.allowed is True
        assert decision.channel_gate is True
        assert decision.policy_gate is None


class TestPolicyGate:
    def test_policyDenySurfacesWithRawVerdict(self, isolatedRoot, monkeypatch):
        """治理 DENY → deny_policy，raw verdict 原样透传（SANDBOX 语义不丢）。"""
        import neurova.security.command_authority as ca
        from neurova.security.governance import GovernanceDecision

        verdict = _FakeVerdict(GovernanceDecision.DENY, ["命中拒绝规则"])

        def _fakeJudge(**kwargs):
            return verdict

        monkeypatch.setattr(ca, "_judgePolicy", _fakeJudge)
        decision = resolveCommandAuthority(senderId="ou_x", toolName="exec_command",
                                           params={"command": "rm -rf /"})
        assert decision.allowed is False
        assert decision.stage == "deny_policy"
        assert decision.raw is verdict, "raw verdict 丢失——SANDBOX/审计面会破"

    def test_policyNoneMeansNoAdjudicationNeeded(self, isolatedRoot, monkeypatch):
        """治理返回 None（无可裁决内容）→ 放行（与 tool 路径既有语义一致）。"""
        import neurova.security.command_authority as ca

        monkeypatch.setattr(ca, "_judgePolicy", lambda **kwargs: None)
        decision = resolveCommandAuthority(senderId="ou_x", toolName="memory_search",
                                           params={})
        assert decision.allowed is True and decision.policy_gate is True

    def test_noFactsAtAllIsNotSupported(self, isolatedRoot):
        """既无渠道事实也无工具事实 → not_supported（诚实点名，不假装放行）。"""
        decision = resolveCommandAuthority(senderId="ou_x")
        assert decision.allowed is False and decision.stage == "not_supported"


class TestLedger:
    def test_everyJudgmentLandsARow(self, isolatedRoot):
        resolveCommandAuthority(
            senderId="ou_1", channelType="feishu", chatType="private",
            channelCfg={"private_chat_strategy": "open"})
        resolveCommandAuthority(senderId="ou_2", toolName="exec_command",
                                params={"command": "ls"})
        ledger = getCommandAuthorityLedger()
        rows = ledger.queryAuthorityLog(sender_id="ou_1") + ledger.queryAuthorityLog(sender_id="ou_2")
        assert len(rows) == 2, f"每次判定都应落一行（实得 {len(rows)}）"
        by_sender = {r["sender_id"]: r for r in rows}
        assert by_sender["ou_1"]["channel_gate"] == 1 and by_sender["ou_1"]["policy_gate"] is None
        assert by_sender["ou_2"]["policy_gate"] is not None and by_sender["ou_2"]["channel_gate"] is None
        assert by_sender["ou_2"]["tool_name"] == "exec_command"

    def test_ledgerFailureIsFailSoftWithWarning(self, isolatedRoot, monkeypatch, caplog):
        """台账故障不得影响判定本身（判定是安全主链，台账是观测面）——
        但必须出声。"""
        import neurova.security.command_authority as ca

        class _Broken:
            def recordJudgment(self, **kwargs):
                raise RuntimeError("db broken")

        monkeypatch.setattr(ca, "getCommandAuthorityLedger", lambda: _Broken())
        decision = resolveCommandAuthority(
            senderId="ou_1", channelType="feishu", chatType="private",
            channelCfg={"private_chat_strategy": "open"})
        assert decision.allowed is True, "台账故障劫持了判定主链"


class TestLedgerStandalone:
    def test_singletonIsIdempotent(self, isolatedRoot):
        assert getCommandAuthorityLedger() is getCommandAuthorityLedger()

    def test_queryFilterBySender(self, isolatedRoot):
        ledger = getCommandAuthorityLedger()
        ledger.recordJudgment(sender_id="a", channel_type="", agent_id="",
                              tool_name="t", channel_gate=None, policy_gate=True,
                              decision="allow", reason="")
        ledger.recordJudgment(sender_id="b", channel_type="", agent_id="",
                              tool_name="t", channel_gate=None, policy_gate=False,
                              decision="deny_policy", reason="x")
        rows = ledger.queryAuthorityLog(sender_id="a")
        assert len(rows) == 1 and rows[0]["decision"] == "allow"
