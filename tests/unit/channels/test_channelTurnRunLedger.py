# -*- coding: utf-8 -*-
"""§6-46：渠道回合也要问让位闸、也要落 run 台账（拍板＝全量接：接闸 + park 复用台账）。

为什么这条是"能力缺失"而不是"再补一份记账"：让位闸护的是**同一份模型额度**，
而额度是多入口共享的。闸只挂在 `/console/chat` 时，渠道消息（飞书/Telegram 的突发
刷屏，恰是并发与间距最该生效的场景）完全绕过——同一 Agent 从两条路各花各的额度，
限额语义从"全局"降级成"网页面自己那一份"。

三条判据各对一个今天的缺失形态：
- 正常轮**根本没进台账**：没有 run 行 → 渠道回合不可审计、不可取消、重启即失忆；
- 超限轮**照跑**：闸没接，模型并发满时渠道照样往 LLM 上撞；
- 挂起行的**属主**必须是 agent 属主（`agent.config.owner_user_id`）——渠道会话本就落在
  该属主的控制台里（`channel_router.py:144-151` 的既定语义），所以"网页里点续跑"这句话
  才是真的；写成渠道 sender 的 open_id 就没人能续。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.channels import channel_router
from neurova.channels.base import ChannelMessage
from neurova.channels.manager import ChannelManager
from neurova.collaboration.glance_yield_rules import GlanceYieldChecker
from neurova.core import agent_run_store as ars

AGENT_ID = "chan-agent"
OWNER = "chan-owner"


class _FakeAgent:
    def __init__(self, reply="pong"):
        self.reply = reply
        self.calls = []
        self.config = SimpleNamespace(owner_user_id=OWNER, attachment_dir="")

    @property
    def current_reasoning(self):
        return ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id})
        return {"text": self.reply}


def _msg(content="刷屏一条", chat_id="oc_park", sender="ou_9"):
    return ChannelMessage(
        channel_type="feishu", message_id="m-park", sender_id=sender, sender_name=sender,
        content=content, chat_id=chat_id, chat_type="p2p", metadata={"agent_id": AGENT_ID},
    )


@pytest.fixture()
def runStore(tmp_path, monkeypatch):
    db = tmp_path / "chan.db"
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    # 一次都不等：第一发判定就让位 → 立刻挂起（预算本身由 test_yieldGateWaitPolicy.py 钉）
    monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "0")
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(db)
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


@pytest.fixture()
def yieldChecker(monkeypatch):
    """独占 checker（渠道侧不指定模型，未归因回合必须仍然可判，见 §6-5 第二批）。"""
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance",
        GlanceYieldChecker(),
        raising=False,
    )
    from neurova.collaboration import glance_yield_rules as gyr

    return gyr._glance_checker_instance


@pytest.fixture()
def manager():
    ChannelManager._instance = None
    m = ChannelManager()
    yield m
    ChannelManager._instance = None


def _sessionOf(manager, msg) -> str:
    return manager.resolve_session_scope_id(msg)


@pytest.mark.asyncio
async def testChannelTurnIsRecordedInRunLedger(manager, runStore, yieldChecker):
    """正常轮也要有 run 行：渠道回合第一次可审计、可取消、重启可见。"""
    agent = _FakeAgent("你好，我是Neurova")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    msg = _msg("正常一轮")

    reply = await handler(msg)

    assert reply == ["你好，我是Neurova"]
    rows = runStore.list_runs(_sessionOf(manager, msg))
    assert len(rows) == 1, "渠道回合没进 run 台账（不可审计、不可取消）"
    assert rows[0]["status"] == "completed"
    assert rows[0]["agent_id"] == AGENT_ID


@pytest.mark.asyncio
async def testChannelTurnConsultsGateAndParksWithoutRunning(manager, runStore, yieldChecker):
    """额度让位时：渠道这一轮**不许**打到 LLM，且要回一条带 run_id 的诚实回执。"""
    yieldChecker.trigger_rate_limit(AGENT_ID)
    agent = _FakeAgent()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    msg = _msg("刷屏一条")

    reply = await handler(msg)

    assert agent.calls == [], "闸没接上：并发已满时渠道照样往 LLM 上撞"
    text = "\n".join(reply or [])
    assert "parked" in text.lower() or "挂起" in text, f"回执没说明这一轮被挂起：{text!r}"

    rows = runStore.list_runs(_sessionOf(manager, msg))
    assert len(rows) == 1 and rows[0]["status"] == ars.PARKED_STATUS
    assert rows[0]["park_reason"]
    run_id = rows[0]["run_id"]
    assert run_id in text, "回执没带 run_id——用户无从续跑，等于挂起即丢失"
    assert "刷屏一条" in (rows[0]["resume_payload"] or "")


@pytest.mark.asyncio
async def testParkedChannelTurnBelongsToAgentOwner(manager, runStore, yieldChecker):
    """挂起行的属主＝agent 属主，"网页里点续跑"才成立（渠道会话本就落在他的控制台）。"""
    yieldChecker.trigger_rate_limit(AGENT_ID)
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: _FakeAgent())
    msg = _msg("归属检查")

    await handler(msg)

    rows = runStore.list_runs(_sessionOf(manager, msg))
    assert rows and rows[0]["user_id"] == OWNER, (
        f"挂起行属主写成 {rows[0]['user_id']!r}，属主在控制台里看不到这条，续跑无从谈起"
    )


@pytest.mark.asyncio
async def testChannelTurnStillWorksWhenLedgerIsUnhealthy(manager, runStore, yieldChecker, monkeypatch):
    """fail-open 契约与网页面一致：台账坏了不吞掉渠道应答。"""
    def _boom(*a, **k):
        raise RuntimeError("run store on fire")

    monkeypatch.setattr(ars.AgentRunStore, "intake", _boom)
    agent = _FakeAgent("照常回复")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    reply = await handler(_msg("台账坏了"))

    assert reply == ["照常回复"]
    assert agent.calls, "台账故障把渠道应答一起拖死了"
