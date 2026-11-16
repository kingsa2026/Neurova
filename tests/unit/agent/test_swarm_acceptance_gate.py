"""P1-2 蜂群终态验收门单元测试。

覆盖：
- 开关关（默认）且无显式验收条件 → 不设门，行为与旧链路一致；
- 开关开 + 判定达标 → completed，acceptance 记录在 run；
- 判定不达标 → 带 missing 回炉一次（第二次 chat 提示词含验收打回与逐条缺项）；
- 回炉后仍不达标 → failed（cause=acceptance_failed），产出不作合格结果回流；
- 判定器不可用 → 诚实降级 completed + acceptance.skipped=judge_unavailable；
- 显式 acceptanceCriteria 绕过开关单独生效；
- 设置默认值落在 ADVANCED_DEFAULTS（单源）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.core.app_settings import ADVANCED_DEFAULTS


def make_gate_agent(chat_replies, judge_verdicts):
    """chat_replies: 首跑与回炉的正文列表；judge_verdicts: 判定 JSON 列表（逐次）。"""
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(side_effect=[{"text": r} for r in chat_replies])
    verdicts = list(judge_verdicts)

    async def fake_verify(messages, *args, **kwargs):
        payload = verdicts.pop(0) if verdicts else {"achieved": True, "confidence": 1.0, "missing": []}
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=fake_verify)
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def gateOff():
    with patch("neurova.agent.acceptance_gate.get_advanced_settings", return_value={}):
        yield


@pytest.fixture
def gateOn():
    with patch("neurova.agent.acceptance_gate.get_advanced_settings",
               return_value={"swarm_acceptance_enabled": True}):
        yield


UNIT = {"goal": "完成登录页重构", "acceptanceCriteria": ["登录成功跳转", "错误提示可见"]}


class TestGateOff:
    @pytest.mark.asyncio
    async def test_default_off_no_gate(self, swarm, gateOff):
        agent = make_gate_agent(["完成"], [])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="纯文本任务", agent_id="researcher")
        assert result["status"] == "completed"
        assert swarm.status(result["subagent_id"])["acceptance"] is None
        agent.llm_client.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_value_is_off_in_settings_single_source(self, gateOff):
        assert ADVANCED_DEFAULTS["swarm_acceptance_enabled"] is False


class TestGateOn:
    @pytest.mark.asyncio
    async def test_judge_achieved_completes(self, swarm, gateOn):
        agent = make_gate_agent(["完整产出"], [{"achieved": True, "confidence": 0.9, "missing": []}])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=UNIT)
        assert result["status"] == "completed"
        stored = swarm.status(result["subagent_id"])
        assert stored["acceptance"]["achieved"] is True
        assert stored["acceptance"]["rounds"] == 0
        agent.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rework_then_pass(self, swarm, gateOn):
        agent = make_gate_agent(
            ["缺跳转的半成品", "补齐跳转的完整产出"],
            [
                {"achieved": False, "confidence": 0.8, "missing": ["登录成功跳转"], "explanation": "证据未覆盖"},
                {"achieved": True, "confidence": 0.9, "missing": []},
            ],
        )
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=UNIT)
        assert result["status"] == "completed"
        assert agent.chat.await_count == 2
        reworkPrompt = agent.chat.await_args_list[1][0][0]
        assert "验收打回" in reworkPrompt
        assert "登录成功跳转" in reworkPrompt
        stored = swarm.status(result["subagent_id"])
        assert stored["acceptance"]["reworked"] is True
        assert stored["acceptance"]["rounds"] == 1

    @pytest.mark.asyncio
    async def test_fail_after_rework(self, swarm, gateOn):
        agent = make_gate_agent(
            ["半成品一", "半成品二"],
            [
                {"achieved": False, "confidence": 0.8, "missing": ["登录成功跳转"]},
                {"achieved": False, "confidence": 0.8, "missing": ["登录成功跳转", "错误提示可见"]},
            ],
        )
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=UNIT)
        assert result["status"] == "failed"
        stored = swarm.status(result["subagent_id"])
        assert stored["error"].startswith("acceptance_failed")
        assert "登录成功跳转" in stored["error"]
        assert agent.chat.await_count == 2  # 首跑 + 一次回炉，不无限重试

    @pytest.mark.asyncio
    async def test_judge_unavailable_honest_skip(self, swarm, gateOn):
        agent = make_gate_agent(["完成"], [])
        agent.llm_client.chat = AsyncMock(side_effect=RuntimeError("channel down"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=UNIT)
        assert result["status"] == "completed"  # 诚实降级：不误杀
        stored = swarm.status(result["subagent_id"])
        assert stored["acceptance"]["skipped"] == "judge_unavailable"

    @pytest.mark.asyncio
    async def test_explicit_criteria_bypass_switch(self, swarm, gateOff):
        # 开关关，但任务显式带验收条件 → 数据齐备即验收
        agent = make_gate_agent(["完整产出"], [{"achieved": True, "confidence": 1.0, "missing": []}])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=UNIT)
        assert result["status"] == "completed"
        agent.llm_client.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_gate_on_without_unit_judges_task_text(self, swarm, gateOn):
        # 开关开 → 所有蜂群任务过门（goal=task 文本，无显式条目）
        agent = make_gate_agent(["完成"], [{"achieved": True, "confidence": 0.7, "missing": []}])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="整理会议纪要", agent_id="researcher")
        assert result["status"] == "completed"
        agent.llm_client.chat.assert_awaited_once()
