# -*- coding: utf-8 -*-
"""失败轮也要有权威落点：LLM 抛错时，会话盘上不能只剩用户那一句。

复核实状（读到生产侧，不推断）：

- 后处理只在**正常收尾路径**上被调：`chat_pipeline._execute_steps` 一路走到
  `_step_post_processing`（:545）→ `_run_post_chat_pipeline`（:3107）→
  `post_chat_pipeline._step_save_session`（:1079）。
- LLM 供应商错误时异常从 `_step_llm_call`（:542）直接离开管线，**3107 那一步根本
  没跑到** ⇒ 会话盘上只有 §6-419 提前落好的 user 一条，assistant 一条都没有。
- 活体两条实证（同一台开发机）：
  · 09:29 那轮要 250 条，上游 5 分钟不吐字 → `Request timed out` → 候选模型
    400 `Requested model DeepSeek-V4-Flash-Vision-Exp not supported` → 管线不再
    fallback → 整轮以错误收场；复算时盘上 `messages` 只有 `[user]`，
    run 终态 `failed/chat_error`。
  · 前端因此永远挂着「本轮仍在生成中」（`GET /console/tasks` 已空、run 已终态，
    但读回的会话里没有任何东西说明这一轮结束了）——票面「刷新后看不到 agent 持续
    的输出」在失败分支上仍未闭合。

裁定（本批，沿用户裁「甲：统一到与响应解耦」）：失败的**终结**要有权威落点，
且必须是**诚实形态**（教义第 2 条）——异常照旧向上抛，SSE 的 `error` 帧、台账的
`failed` 终态一概不变；只是额外把"这一轮以失败收场"这件事写进会话历史，
让刷新后的读侧能看到终态而不是空白。

落点仍走既有单点 `post_chat_pipeline._step_save_session`（教义第 7 条：同一功能
只许一处实现，这里不另起第二份写会话的代码）。
"""

from __future__ import annotations

import pytest

from .conftest import text_chunk
from neurova.session_repository import get_session_repository

SESSION = "sess-failed-turn"
USER_TEXT = "把这份清单逐条核对一遍再回我"
ERROR_TEXT = "Error code: 400 - Requested model not supported"


def _history(agent_id: str):
    return get_session_repository().get_history(agent_id=agent_id, session_id=SESSION) or []


def _byRole(messages, role: str):
    return [m for m in messages if m.get("role") == role]


def _texts(messages, role: str):
    return [str(m.get("content") or "") for m in _byRole(messages, role)]


class TestFailedTurnLandsInSession:
    @pytest.mark.asyncio
    async def testLlmFailureStillWritesAssistantRecordIntoSession(self, loop_probe):
        """LLM 抛错 ⇒ 会话盘上应有一条 assistant 记录说"这轮失败了"，而不是只剩 user。"""
        agent = loop_probe.agent
        model = loop_probe.bind([[text_chunk("不会被用到的回复")]])

        async def failingChat(messages, **kwargs):
            raise RuntimeError(ERROR_TEXT)

        model.chat = failingChat

        with pytest.raises(RuntimeError):
            await agent.chat(USER_TEXT, session_id=SESSION)

        history = _history(agent.config.agent_id)
        assistants = _texts(history, "assistant")
        assert any(assistants), (
            f"失败轮在会话盘上没有任何落点（实得 role 计数="
            f"{ {r: len(_byRole(history, r)) for r in ('user', 'assistant')} }）——"
            "刷新后读侧只能看到自己那句问话，永远等不到这一轮的终态"
        )
        assert any(ERROR_TEXT[:18] in t or "未能生成回复" in t for t in assistants), (
            f"失败落点没有点名真因（实得 {assistants}）——只写一句空话等于把失败说成完成"
        )

    @pytest.mark.asyncio
    async def testFailureLandingDoesNotSwallowTheException(self, loop_probe):
        """反向钉：落点之后异常必须照旧外抛。把失败改成"静默回复"就是 §2 禁止的降级。"""
        agent = loop_probe.agent
        model = loop_probe.bind([[text_chunk("不会被用到的回复")]])

        async def failingChat(messages, **kwargs):
            raise RuntimeError(ERROR_TEXT)

        model.chat = failingChat

        raised = None
        try:
            await agent.chat(USER_TEXT, session_id=SESSION)
        except BaseException as exc:  # noqa: BLE001 - 本判据就是要验异常外抛
            raised = exc
        assert isinstance(raised, RuntimeError), (
            f"失败没有外抛（实得 {type(raised).__name__}: {raised}）——"
            "落点不能顺手把故障兜成成功"
        )

    @pytest.mark.asyncio
    async def testUserMessageIsNotWrittenTwiceOnFailure(self, loop_probe):
        """失败落点只补 assistant：提前落好的 user 不许被配对写第二遍。"""
        agent = loop_probe.agent
        model = loop_probe.bind([[text_chunk("不会被用到的回复")]])

        async def failingChat(messages, **kwargs):
            raise RuntimeError(ERROR_TEXT)

        model.chat = failingChat

        with pytest.raises(RuntimeError):
            await agent.chat(USER_TEXT, session_id=SESSION)

        mine = [t for t in _texts(_history(agent.config.agent_id), "user") if USER_TEXT in t]
        assert len(mine) == 1, f"本轮 user 落了 {len(mine)} 条（应恰 1 条）"

    @pytest.mark.asyncio
    async def testSuccessPathUnchangedByFailureLanding(self, loop_probe):
        """反向控制：正常轮仍按老样子落 user+assistant 一对，不多写失败记录。"""
        agent = loop_probe.agent
        loop_probe.bind([[text_chunk("一切正常")]])

        await agent.chat(USER_TEXT, session_id=SESSION)

        history = _history(agent.config.agent_id)
        assert len(_texts(history, "user")) == 1
        assistants = _texts(history, "assistant")
        assert len(assistants) == 1 and "一切正常" in assistants[0], (
            f"正常轮的落点被改动（实得 {assistants}）"
        )
