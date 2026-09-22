# -*- coding: utf-8 -*-
"""B6-8：静默降级收敛——能力被关掉必须有读数与恢复路径（Issue #90 · P2-5）。

红灯依据（改前实证，审计 §2.1 P2-5）：

- 驱逐台账初始化失败：只 `logger.warning` 后回退内存台账，**此后不再尝试**；
- 摘要压缩器初始化失败：`pool._summarizer = None`，而 `_build_window_summarizer`
  的闭包恒返回 None —— 全链路再无 LLM 摘要，且**没有任何读数**说明它被关掉了。
- 两处都属"能力永久关闭 + 只留一行 warning"：审计的判据是"有可观测读数与
  重试/恢复路径，不以 warning 代替"。

契约（修复后）：

1. 每个降级部件在**读数面**上有名有姓：`attempts` / `enabled` / `last_error`；
2. 降级**不粘死**：下一轮构建会再尝试装配，成功后能力自动恢复（读数转 enabled）；
3. 降级状态只有一处登记（编排器持有），池侧读的是同一份——不新造第二份健康表。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.orchestrator import ContextOrchestrator


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    agent.question_queue_manager = None
    return agent


async def _build(orch):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        await orch.build_context(
            user_input="问题", session_context=[{"role": "user", "content": "短历史"}]
        )


def _failingSummarizerImport():
    """只让摘要器那一个 import 抛错（其余依赖保持真实）。"""
    realImport = __import__

    def failingImport(name, *args, **kwargs):
        if name == "neurova.context.summarizing_compressor":
            raise ImportError("模拟摘要器依赖缺失")
        return realImport(name, *args, **kwargs)

    return patch("builtins.__import__", side_effect=failingImport)


def _orchestratorWithFailingSummarizer():
    """摘要器装配失败：真构造面（真 ContextOrchestrator，只让 import 抛错）。"""
    with _failingSummarizerImport():
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    return orch


class TestDegradationReadout:
    def test_summarizer_failure_is_named_in_readout(self):
        """摘要器装配失败必须在读数面上有名有姓（改前只有一行 warning）。"""
        orch = _orchestratorWithFailingSummarizer()

        health = orch.get_context_health()
        assert health["summarizer"]["enabled"] is False
        assert health["summarizer"]["attempts"] >= 1
        assert "ImportError" in (health["summarizer"]["last_error"] or ""), (
            f"降级原因未点名：{health['summarizer']}"
        )

    def test_healthy_state_reports_enabled(self):
        """健康态读数不得把"没降级"写成"不可观测"。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)

        health = orch.get_context_health()
        assert health["summarizer"]["enabled"] is True
        assert health["ledger"]["enabled"] is True
        assert health["summarizer"]["last_error"] is None

    def test_readout_is_single_source(self):
        """池侧读的是编排器同一份降级登记（不新造第二份健康表）。"""
        orch = _orchestratorWithFailingSummarizer()

        assert orch.context_pool._summarizer is None
        assert orch.get_context_health()["summarizer"]["enabled"] is False


class TestDegradationRecovery:
    @pytest.mark.asyncio
    async def test_next_turn_retries_and_recovers(self):
        """降级不粘死：下一轮构建再装一次，成功后能力恢复（改前恒 None）。"""
        orch = _orchestratorWithFailingSummarizer()
        assert orch.get_context_health()["summarizer"]["enabled"] is False

        with _failingSummarizerImport():
            await _build(orch)  # 依赖仍缺：本轮重试并如实记账，状态不变
        health = orch.get_context_health()
        assert health["summarizer"]["enabled"] is False
        assert health["summarizer"]["attempts"] >= 2, (
            "本轮没有重试装配 —— 降级被粘死（改前正是这种'关掉就不再试'的形态）"
        )

        await _build(orch)  # 依赖恢复：下一轮构建即自动接回

        recovered = orch.get_context_health()
        assert recovered["summarizer"]["enabled"] is True
        assert recovered["summarizer"]["last_error"] is None
        assert orch.context_pool._summarizer is not None, "恢复后池侧未接上摘要器"

    @pytest.mark.asyncio
    async def test_healthy_turn_does_not_rebuild(self):
        """健康态不做无谓重建：attempts 不随轮次增长（避免每轮造摘要器）。"""
        orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
        before = orch.get_context_health()["summarizer"]["attempts"]

        await _build(orch)

        assert orch.get_context_health()["summarizer"]["attempts"] == before
