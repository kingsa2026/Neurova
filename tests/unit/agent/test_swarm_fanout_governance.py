"""蜂群 fan-out 治理测试（把防踩踏/预算/冷却能力吸收进 SwarmManager.spawn）

设计约束（放大视角、不断点、fail-open、不造平行岛）：
- 全部拒绝走既有 _rejection()（携带 swarm_rejection 键 → is_policy_denial 归类为"决策非故障"）。
- 预算闸复用 cost_budget.get_budget_service（record_llm_cost 写的同一对象），不建第二套。
- 模型冷却读 model_rate_limiter.get_shared_limiter（只读 pause_remaining，不 acquire，避免与
  multi_model_client 的双重计数/泄漏）。
- 每模型并发帽与派生间隔默认关闭（0），不改变既有 MAX_ACTIVE_CHILDREN 突发语义与既有测试；
  仅在显式配置时生效。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import SwarmManager, get_swarm_manager, reset_swarm_manager
from neurova.models.cost_budget import (
    BudgetConfig,
    BudgetScope,
    get_budget_service,
    reset_budget_service,
)


def make_agent(name="子Agent", reply="报告", model=None):
    """model=None → llm_client.config.model 非字符串，模拟模型不可解析（门控优雅跳过）。"""
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    if model is not None:
        agent.llm_client.config.model = model
    return agent


def slow_agent(model=None, hold=30):
    agent = make_agent(model=model)

    async def _chat(*a, **k):
        await asyncio.sleep(hold)
        return {"text": "x"}

    agent.chat = AsyncMock(side_effect=_chat)
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    reset_budget_service()
    yield get_swarm_manager()
    reset_swarm_manager()
    reset_budget_service()


def _over_agent_budget(identifier="default", amount="1", used="2"):
    mgr = get_budget_service().manager
    now = datetime.now()
    mgr.register_budget(
        BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier=identifier,
            amount=Decimal(amount),
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
        )
    )
    mgr.record_usage(BudgetScope.HOURLY, identifier, Decimal(used))


# ── P3 预算闸（默认开，fail-open）────────────────────────────────
class TestBudgetGate:
    @pytest.mark.asyncio
    async def test_over_budget_rejects(self, swarm):
        """HOURLY 预算超支：结构化拒绝，不派生。"""
        _over_agent_budget("default")
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="贵任务")
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "BUDGET_EXCEEDED"
        agent.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_budget_configured_allows(self, swarm):
        """未注册预算 → fail-open 放行（零回归保护）。"""
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="正常")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_budget_rejection_is_policy_denial(self, swarm):
        from neurova.security.governance import is_policy_denial

        _over_agent_budget("default")
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="贵任务")
        assert is_policy_denial(result) is True


# ── P4 模型冷却预检（复用 model_rate_limiter，只读）───────────────
class TestModelCooldown:
    @pytest.mark.asyncio
    async def test_model_in_cooldown_rejects(self, swarm):
        agent = make_agent(model="gpt-slow")
        fake_limiter = MagicMock()
        fake_limiter.pause_remaining.return_value = 12.5
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent), patch(
            "neurova.llm.model_rate_limiter.get_shared_limiter", return_value=fake_limiter
        ):
            result = await swarm.spawn(task="t")
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "MODEL_COOLDOWN"
        assert result.get("retry_after_ms", 0) >= 12000
        fake_limiter.pause_remaining.assert_any_call("gpt-slow")

    @pytest.mark.asyncio
    async def test_no_cooldown_allows(self, swarm):
        agent = make_agent(model="gpt-fast")
        fake_limiter = MagicMock()
        fake_limiter.pause_remaining.return_value = 0.0
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent), patch(
            "neurova.llm.model_rate_limiter.get_shared_limiter", return_value=fake_limiter
        ):
            result = await swarm.spawn(task="t")
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_unresolvable_model_skips_cooldown(self, swarm):
        """模型不可解析（None）→ 冷却/并发模型键检查优雅跳过，不报错。"""
        agent = make_agent(model=None)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="t")
        assert result["status"] == "completed"


# ── P1 每模型并发帽（默认关，显式配置生效）────────────────────────
class TestPerModelConcurrencyCap:
    @pytest.mark.asyncio
    async def test_cap_one_serializes_same_model(self, swarm, monkeypatch):
        monkeypatch.setattr(SwarmManager, "MAX_CONCURRENT_PER_MODEL", 1)
        agent = slow_agent(model="big-model")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            first = await swarm.spawn(task="a", background=True)
            assert first.get("background") is True
            second = await swarm.spawn(task="b", background=True)
        assert second.get("rejected") is True
        assert second["rejection"]["code"] == "MODEL_CONCURRENCY"

    @pytest.mark.asyncio
    async def test_different_models_not_gated_together(self, swarm, monkeypatch):
        monkeypatch.setattr(SwarmManager, "MAX_CONCURRENT_PER_MODEL", 1)
        a1 = slow_agent(model="model-a")
        a2 = slow_agent(model="model-b")
        agents = {"ma": a1, "mb": a2}
        with patch(
            "neurova.api.endpoints.get_agent_instance",
            side_effect=lambda aid: agents.get(aid),
        ):
            r1 = await swarm.spawn(task="a", agent_id="ma", background=True)
            r2 = await swarm.spawn(task="b", agent_id="mb", background=True)
        assert r1.get("background") and r2.get("background")

    @pytest.mark.asyncio
    async def test_slot_released_after_completion(self, swarm, monkeypatch):
        monkeypatch.setattr(SwarmManager, "MAX_CONCURRENT_PER_MODEL", 1)
        agent = make_agent(model="m")  # fast reply completes
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            r1 = await swarm.spawn(task="a")  # foreground, completes & releases
            r2 = await swarm.spawn(task="b")
        assert r1["status"] == "completed" and r2["status"] == "completed"


# ── P2 派生间隔（默认关，显式配置生效）────────────────────────────
class TestSpawnSpacing:
    @pytest.mark.asyncio
    async def test_too_fast_rejected_with_retry_after(self, swarm, monkeypatch):
        monkeypatch.setattr(SwarmManager, "MIN_SPAWN_INTERVAL_MS", 10_000)
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            r1 = await swarm.spawn(task="a")
            r2 = await swarm.spawn(task="b")
        assert r1["status"] == "completed"
        assert r2.get("rejected") is True
        assert r2["rejection"]["code"] == "SPAWN_TOO_FAST"
        assert r2.get("retry_after_ms", 0) > 0

    @pytest.mark.asyncio
    async def test_default_spacing_disabled_allows_burst(self, swarm):
        """默认 0=关：连续派生不受限（保护既有突发语义）。"""
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            r1 = await swarm.spawn(task="a")
            r2 = await swarm.spawn(task="b")
        assert r1["status"] == "completed" and r2["status"] == "completed"


# ── kill-switch ────────────────────────────────────────────────
class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_governance_off_skips_budget(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_GOVERNANCE", "off")
        _over_agent_budget("default")
        agent = make_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="t")
        assert result["status"] == "completed"
