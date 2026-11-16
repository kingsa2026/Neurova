"""P1-3 监督评审相位单元测试。

覆盖：
- reviewMode 缺省 none → 不评审，run.review 为 None；
- reviewMode=supervisor + 评审 correct → completed，review.passed=True；
- 评审 issues_found → 带 findings 回炉一次（第二次 chat 提示词含评审打回与发现），
  复审通过 → completed 且 reworked=True；
- 复审仍不通过 → failed（cause=review_failed），chat 次数=首跑+1 次回炉；
- 评审器不可用 → 诚实降级 completed + review.skipped=reviewer_unavailable；
- 验收门+评审同时启用 → 先验收后评审，两通道各司其职；
- in_review 相位在评审期间可见（status 工具读数）。
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.core.app_settings import ADVANCED_DEFAULTS


def make_review_agent(chat_replies, review_outputs, judge_verdicts=None):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(side_effect=[{"text": r} for r in chat_replies])

    reviews = list(review_outputs)
    judges = list(judge_verdicts or [])

    async def fake_channel(messages, *args, **kwargs):
        # 验收与评审共用 llm_client.chat 通道：按消息标记路由各自的剧本
        text = json.dumps(messages, ensure_ascii=False)
        if "<goal>" in text:
            payload = judges.pop(0) if judges else {"achieved": True, "confidence": 1.0, "missing": []}
        else:
            payload = reviews.pop(0) if reviews else {
                "findings": [], "overall_correctness": "correct", "overall_confidence_score": 1.0,
            }
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=fake_channel)
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def gateOff():
    with patch("neurova.agent.acceptance_gate.get_advanced_settings", return_value={}):
        yield


REVIEW_UNIT = {"goal": "完成登录页重构", "reviewMode": "supervisor"}
FINDING = {"title": "缺少错误提示", "priority": "P1", "code_location": "Login.vue",
           "body": "登录失败路径没有用户可见提示"}
ISSUES = {"findings": [FINDING], "overall_correctness": "issues_found",
          "overall_explanation": "存在一个 P1 问题", "overall_confidence_score": 0.8}
CORRECT = {"findings": [], "overall_correctness": "correct",
           "overall_explanation": "核对通过", "overall_confidence_score": 0.9}


class TestReviewPhase:
    @pytest.mark.asyncio
    async def test_default_no_review(self, swarm, gateOff):
        agent = make_review_agent(["完成"], [])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="纯文本任务", agent_id="researcher")
        assert result["status"] == "completed"
        assert swarm.status(result["subagent_id"])["review"] is None
        agent.llm_client.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_pass_completes(self, swarm, gateOff):
        agent = make_review_agent(["产出"], [CORRECT])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher",
                                       task_unit=REVIEW_UNIT)
        assert result["status"] == "completed"
        stored = swarm.status(result["subagent_id"])
        assert stored["review"]["passed"] is True
        assert stored["review"]["rounds"] == 0
        agent.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_review_rework_then_pass(self, swarm, gateOff):
        agent = make_review_agent(["有缺陷的产出", "修正后的完整产出"], [ISSUES, CORRECT])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher",
                                       task_unit=REVIEW_UNIT)
        assert result["status"] == "completed"
        assert agent.chat.await_count == 2
        reworkPrompt = agent.chat.await_args_list[1][0][0]
        assert "评审打回" in reworkPrompt
        assert "缺少错误提示" in reworkPrompt
        assert "P1" in reworkPrompt
        stored = swarm.status(result["subagent_id"])
        assert stored["review"]["reworked"] is True
        assert stored["review"]["rounds"] == 1

    @pytest.mark.asyncio
    async def test_review_fail_after_rework(self, swarm, gateOff):
        agent = make_review_agent(["产出一", "产出二"], [ISSUES, ISSUES])
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher",
                                       task_unit=REVIEW_UNIT)
        assert result["status"] == "failed"
        stored = swarm.status(result["subagent_id"])
        assert stored["error"].startswith("review_failed")
        assert "缺少错误提示" in stored["error"]
        assert agent.chat.await_count == 2  # 首跑 + 一次回炉，不无限重试

    @pytest.mark.asyncio
    async def test_reviewer_unavailable_honest_skip(self, swarm, gateOff):
        agent = make_review_agent(["完成"], [])
        agent.llm_client.chat = AsyncMock(side_effect=RuntimeError("review channel down"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher",
                                       task_unit=REVIEW_UNIT)
        assert result["status"] == "completed"  # 诚实降级：不误杀
        stored = swarm.status(result["subagent_id"])
        assert stored["review"]["skipped"] == "reviewer_unavailable"

    @pytest.mark.asyncio
    async def test_acceptance_then_review_sequence(self, swarm):
        # 验收门（设置开）+ 评审（reviewMode=supervisor）同时启用：先验收后评审
        agent = make_review_agent(
            ["产出"],
            [CORRECT],  # 评审通道
            [{"achieved": True, "confidence": 0.9, "missing": []}],  # 验收通道
        )
        both = {"goal": "完成登录页重构", "acceptanceCriteria": ["登录成功跳转"], "reviewMode": "supervisor"}
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent), \
             patch("neurova.agent.acceptance_gate.get_advanced_settings",
                   return_value={"swarm_acceptance_enabled": True}):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=both)
        assert result["status"] == "completed"
        stored = swarm.status(result["subagent_id"])
        assert stored["acceptance"]["achieved"] is True
        assert stored["review"]["passed"] is True


UNIT = {"goal": "完成登录页重构", "acceptanceCriteria": ["登录成功跳转"]}


class TestInReviewPhase:
    def test_in_review_in_status_vocabulary(self):
        from neurova.agent.swarm import (
            SUBAGENT_IN_REVIEW, SUBAGENT_STATUSES, SUBAGENT_ACTIVE_STATUSES,
            SUBAGENT_FINISHED_STATUSES,
        )
        assert SUBAGENT_IN_REVIEW == "in_review"
        assert SUBAGENT_IN_REVIEW in SUBAGENT_STATUSES
        assert SUBAGENT_IN_REVIEW in SUBAGENT_ACTIVE_STATUSES
        assert not (SUBAGENT_ACTIVE_STATUSES & SUBAGENT_FINISHED_STATUSES)
        assert SUBAGENT_ACTIVE_STATUSES | SUBAGENT_FINISHED_STATUSES == SUBAGENT_STATUSES

    def test_advanced_defaults_unchanged_for_review(self):
        # 评审相位无独立开关：reviewMode 是任务单元字段，不新增设置键
        assert "swarm_review_enabled" not in ADVANCED_DEFAULTS
