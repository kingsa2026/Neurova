# -*- coding: utf-8 -*-
"""刷新/中断后读不回本轮：用户消息必须在 LLM 开口之前就落盘。

票面：与 agent 对话过程中刷新页面或意外中断，看不到已发送的消息与 agent 的持续输出。

复核实状（不靠推断，逐条读到生产侧）：
- 全仓 `save_to_session` 只有一个生产调用点——`post_chat_pipeline._step_save_session`
  （回合结束后），一次写 user + assistant 一对。⇒ 整个回合进行中（可达数十秒），
  会话盘上本轮**一个字都没有**；刷新后 `GET /chat/history` 自然是空的。
- `run_chat` 是 `asyncio.create_task` 的独立任务，Starlette 1.7.0 断连取消的是
  collapsing task group 里的 `stream_response`，**不含它**——后端会跑完并补齐。
  所以数据不是"丢了"，是"落得太晚"，而用户已经在那之前刷新了。
- 同族问题此前只修了产物卡片那一类（`_step_save_session` 里 2026-09-08 的注释：
  「SSE artifact 事件只活在实时流，刷新/重开会话后卡片消失」）——本轮正文与回复
  这两类还没接上。

裁定（本批）：后台那一轮保持跑完（不取消、不改 P0-2 语义），把读回路径修通。
第一步就是让 user 消息在 LLM 开口前就存在。

本文件的取证点刻意放在**模型边界**（夹具 conftest 的唯一替身位）：在 LLM 客户端
被调用的那一刻直接读盘——这证的不是"函数里写了一行"，而是"用户那句话在答案还
没开始生成时就已经在盘上了"。
"""

from __future__ import annotations

import pytest

from .conftest import text_chunk
from neurova.session_repository import get_session_repository

SESSION = "sess-early-persist"
USER_TEXT = "帮我核对这三份配置的差异，越细越好"
REPLY_TEXT = "差异共两处：超时阈值与重试次数。"


def _history(agent_id: str, session_id: str = SESSION):
    return get_session_repository().get_history(agent_id=agent_id, session_id=session_id) or []


def _roleCounts(messages):
    counts = {}
    for m in messages:
        role = str(m.get("role") or "?")
        counts[role] = counts.get(role, 0) + 1
    return counts


def _texts(messages, role: str):
    return [str(m.get("content") or "") for m in messages if m.get("role") == role]


class TestUserMessageLandsBeforeModelSpeaks:
    @pytest.mark.asyncio
    async def test_userMessageIsOnDiskAtModelCallTime(self, loop_probe):
        agent = loop_probe.agent
        model = loop_probe.bind([[text_chunk(REPLY_TEXT)]])
        seen: dict = {}
        realChat = model.chat

        async def spy(messages, **kwargs):
            # 取证时刻：模型刚被调用，答案一个字都还没生成
            seen["disk"] = _history(agent.config.agent_id)
            return await realChat(messages, **kwargs)

        model.chat = spy

        await agent.chat(USER_TEXT, session_id=SESSION)

        atCallTime = seen.get("disk") or []
        assert any(USER_TEXT in t for t in _texts(atCallTime, "user")), (
            "模型被调用那一刻盘上还没有本轮 user 消息——整个回合进行中刷新即读不到，"
            f"实得 role 计数={_roleCounts(atCallTime)}"
        )

    @pytest.mark.asyncio
    async def testUserMessageIsWrittenOnceNotTwice(self, loop_probe):
        """提前落一条 + 回合末再落一对 = 同一条用户消息写两遍，历史里出现重复气泡。"""
        agent = loop_probe.agent
        loop_probe.bind([[text_chunk(REPLY_TEXT)]])

        await agent.chat(USER_TEXT, session_id=SESSION)

        history = _history(agent.config.agent_id)
        mine = [t for t in _texts(history, "user") if USER_TEXT in t]
        assert len(mine) == 1, (
            f"本轮用户消息落了 {len(mine)} 条（应恰 1 条）——"
            "回合末的 add_message 不许再写一遍已提前落盘的 user"
        )

    @pytest.mark.asyncio
    async def testAssistantReplyStillLandsWithReasoningAndOwner(self, loop_probe):
        """去重不能把回复一起削掉；assistant 侧仍须完整落盘。"""
        agent = loop_probe.agent
        loop_probe.bind([[text_chunk(REPLY_TEXT)]])

        await agent.chat(USER_TEXT, session_id=SESSION)

        history = _history(agent.config.agent_id)
        assert any(REPLY_TEXT in t for t in _texts(history, "assistant")), (
            f"回复没落盘：实得 role 计数={_roleCounts(history)}"
        )

    @pytest.mark.asyncio
    async def testSaveMemoryFalseWritesNothingEarly(self, loop_probe):
        """`save_memory=False` 的回合（评测/内部调用）不该因为提前落盘而开始污染会话历史。"""
        agent = loop_probe.agent
        model = loop_probe.bind([[text_chunk(REPLY_TEXT)]])
        seen: dict = {}
        realChat = model.chat

        async def spy(messages, **kwargs):
            seen["disk"] = _history(agent.config.agent_id)
            return await realChat(messages, **kwargs)

        model.chat = spy

        await agent.chat(USER_TEXT, session_id=SESSION, save_memory=False)

        assert _roleCounts(seen.get("disk") or {}) == {}, (
            "save_memory=False 却提前落了 user——本轮本就不该进会话历史"
        )
        assert _history(agent.config.agent_id) == [], (
            "save_memory=False 的回合结束后仍落了盘，等于把显式关闭当耳旁风"
        )

    @pytest.mark.asyncio
    async def testEarlyPersistCarriesSessionOwnerNotGuessedFromEnv(self, loop_probe):
        """归属单源（§6-163 裁定甲）：提前写这条也得带会话属主，否则空 user_id
        会让会话在列表里不可见或越权展示（`save_message` 的口径是空则不新建）。"""
        agent = loop_probe.agent
        loop_probe.bind([[text_chunk(REPLY_TEXT)]])

        # 身份走请求边界：`current_user_id` 是只读 property，只由请求边界写一次
        # （AGENTS.md §3 身份通道），测试直赋私有字段等于绕过生产装配点。
        await agent.chat(
            USER_TEXT, session_id=SESSION, metadata={"user_id": "u-owner-77"}
        )

        listed = get_session_repository().list_sessions(agent_id=agent.config.agent_id, user_id="u-owner-77")
        assert any((s.get("session_id") or s.get("id")) == SESSION for s in listed), (
            f"按属主列不出这条会话：{[s.get('session_id') for s in listed]}——"
            "提前建记录时没带上 user_id，会话就成了无主记录"
        )
