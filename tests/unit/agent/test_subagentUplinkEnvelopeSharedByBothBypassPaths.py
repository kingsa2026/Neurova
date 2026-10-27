# -*- coding: utf-8 -*-
"""旁路两条出口共用同一份上报信封（裁定：封装成信封，涵盖主要关键信息）。

蜂群的回程有两条旁路——父会话邮箱（`role:user` 注入）与发起者上下文池归档
（语义召回）。裁定是「上报封装成信封、正文靠下钻」，于是这两条必须投**同一份
投影**：各写一份就是第二个事实源（教义第 6 条），将来一处加字段、另一处漏加，
主 Agent 看到同一个终态会有两种长相。

判据不钉投影函数名，只钉可观察结果：两条出口的 JSON 键集合相等、都含 member
会话指针、都不含正文。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.mailbox import get_agent_mailbox, reset_agent_mailbox
from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager

PARENT_SESSION = "s-envelope"
REPORT_BODY = "这一大段是正文：逐项比对三套方案的写入放大与恢复窗口，结论取 β。"


def _parseSideChannel(text: str) -> dict:
    """旁路文本允许带一个人类可读前缀，但载荷必须是可解析的信封。"""
    payload = text.split("] ", 1)[-1] if text.startswith("[") else text
    return json.loads(payload)


@pytest.fixture
def swarm():
    reset_swarm_manager()
    reset_agent_mailbox()
    yield get_swarm_manager()
    reset_agent_mailbox()
    reset_swarm_manager()


class TestBothBypassPathsShareOneProjection:
    @pytest.mark.asyncio
    async def testMailAndPoolCarryTheSameEnvelopeFields(self, swarm):
        agent = MagicMock()
        agent.config.name = "对比子Agent"
        agent.chat = AsyncMock(return_value={"text": REPORT_BODY})

        initiator = MagicMock()
        captured: list = []
        initiator.context_pool.add_context = MagicMock(
            side_effect=lambda *a, **k: captured.append(a[0] if a else k.get("context"))
        )

        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="三套方案对比",
                session_id=PARENT_SESSION,
                initiator_agent=initiator,
            )

        mails = get_agent_mailbox().drain(PARENT_SESSION)
        assert len(mails) == 1
        assert captured, "池归档没落地，无从比对两份投影"

        mailEnv = _parseSideChannel(mails[0])
        poolEnv = _parseSideChannel(captured[0].content)
        assert mailEnv.keys() == poolEnv.keys(), (
            f"两条旁路各写了一份投影：邮箱 {sorted(mailEnv)} / 池 {sorted(poolEnv)}"
        )
        assert mailEnv == poolEnv, "同一终态在两条旁路上应当逐字段相等"
        for env in (mailEnv, poolEnv):
            assert REPORT_BODY not in json.dumps(env, ensure_ascii=False), (
                "正文不得进旁路——它由主链路与 member 会话承载"
            )
        assert result["member_session_id"] in json.dumps(mailEnv, ensure_ascii=False)
        assert result["agent_id"] in json.dumps(mailEnv, ensure_ascii=False)
        assert result["status"] in json.dumps(mailEnv, ensure_ascii=False)


class TestFailedTerminalStillProjectsKeyInfo:
    @pytest.mark.asyncio
    async def testFailureEnvelopeCarriesCauseNotBody(self, swarm):
        agent = MagicMock()
        agent.config.name = "会失败的子Agent"
        agent.chat = AsyncMock(side_effect=RuntimeError("上游 429 且重试耗尽"))

        initiator = MagicMock()
        captured: list = []
        initiator.context_pool.add_context = MagicMock(
            side_effect=lambda *a, **k: captured.append(a[0] if a else k.get("context"))
        )

        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(
                task="注定失败", session_id=PARENT_SESSION, initiator_agent=initiator
            )

        mails = get_agent_mailbox().drain(PARENT_SESSION)
        assert mails, "失败终态也要回灌，否则主 Agent 只看到沉默"
        env = _parseSideChannel(mails[0])
        assert "429" in json.dumps(env, ensure_ascii=False), "成因属关键信息，须留在信封里"
        assert env["status"] == "failed" or "failed" in json.dumps(env, ensure_ascii=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
