# -*- coding: utf-8 -*-
"""P0-1 缓存经济学修剪判据（上下文工程十轴 · 轴8）。

契约：
1. 无定价元数据 ⇒ 不拦截（判据诚实走"数据不足"路径，行为与无判据一致）；
2. 收益 > 代价 ⇒ 放行（proceed）；
3. 收益 ≤ 代价 ⇒ defer（ttl>0 归因 warm_within_ttl_deferred；无保证 TTL 归因
   break_even_failed）；
4. 折叠归因：被闸改判的增长门主动折叠记 cache_deferred（读数面看到
   "门想折、被缓存经济学按住"，不谎报"门没触发"）；
5. 预算击穿（安全线）不受闸管辖——容量优先，与卡住抑制同序；
6. env `NEUROVA_CACHE_PRICING_JSON` 可覆盖/追加计价表；坏 JSON 回退内置表。
"""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.compression_economics import (
    CACHE_BREAK_EVEN_REASONS,
    CachePricing,
    evaluateCacheBreakEven,
    getProviderCachePricing,
)
from neurova.context.fold_trigger import (
    REASON_BUDGET_BREACH,
    REASON_CACHE_DEFERRED,
    REASON_GROWTH_GATE,
)
from neurova.context.window_compactor import estimate_window_tokens


def _pricing(**kw) -> CachePricing:
    base = dict(
        ttl_seconds=300,
        cached_read_price_per_token=0.3e-6,
        write_price_per_token=3.75e-6,
    )
    base.update(kw)
    return CachePricing(**base)


class TestProviderCachePricing:
    def test_unknown_provider_returns_none(self):
        """未知 provider 一律 None = 无元数据（判据走数据不足路径，不编数）。"""
        assert getProviderCachePricing("no-such-provider") is None
        assert getProviderCachePricing("") is None
        assert getProviderCachePricing(None) is None

    def test_anthropic_family_pricing_present(self):
        p = getProviderCachePricing("anthropic")
        assert p is not None
        assert p.ttl_seconds > 0, "anthropic 有官方 TTL 界（5 分钟档）"
        assert 0 < p.cached_read_price_per_token < p.write_price_per_token

    def test_openai_family_pricing_present(self):
        p = getProviderCachePricing("openai")
        assert p is not None
        assert 0 < p.cached_read_price_per_token < p.write_price_per_token

    def test_model_name_family_fallback(self):
        """注册表查无此模型时以模型名兜底：claude-/gpt- 前缀映射到家族定价
        （镜像 agent/loops/registry 的家族规则，不另造第二份映射语义）。"""
        assert getProviderCachePricing("claude-sonnet-4-test") is not None
        assert getProviderCachePricing("gpt-4o-test") is not None

    def test_env_override_appends_and_replaces(self, monkeypatch):
        override = [
            {
                "provider": "deepseek-test",
                "ttl_seconds": 60,
                "cached_read_price_per_token": 1e-7,
                "write_price_per_token": 2e-7,
            }
        ]
        monkeypatch.setenv("NEUROVA_CACHE_PRICING_JSON", json.dumps(override))
        appended = getProviderCachePricing("deepseek-test")
        assert appended is not None and appended.ttl_seconds == 60

        monkeypatch.setenv(
            "NEUROVA_CACHE_PRICING_JSON",
            json.dumps(
                [
                    {
                        "provider": "anthropic",
                        "ttl_seconds": 111,
                        "cached_read_price_per_token": 1e-7,
                        "write_price_per_token": 2e-7,
                    }
                ]
            ),
        )
        replaced = getProviderCachePricing("anthropic")
        assert replaced is not None and replaced.ttl_seconds == 111, "env 同名键应覆盖内置表"

    def test_env_malformed_falls_back_to_builtin(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CACHE_PRICING_JSON", "not-json")
        assert getProviderCachePricing("anthropic") is not None


class TestCacheBreakEven:
    def test_reason_set_is_closed(self):
        assert CACHE_BREAK_EVEN_REASONS == frozenset(
            {"no_pricing", "warm_within_ttl_deferred", "break_even_failed", "proceed"}
        )

    def test_no_pricing_does_not_defer(self):
        """无定价 ⇒ 不拦截（默认行为不变）。"""
        v = evaluateCacheBreakEven(
            remaining_steps=10,
            tokens_saved_per_call=5000,
            invalidation_tokens=50000,
            pricing=None,
        )
        assert v.defer is False
        assert v.reason == "no_pricing"

    def test_profit_over_cost_proceeds(self):
        """收益 10×10000×0.3e-6=0.03 > 代价 1000×3.45e-6×1.5≈0.0052 ⇒ 放行。"""
        v = evaluateCacheBreakEven(
            remaining_steps=10,
            tokens_saved_per_call=10000,
            invalidation_tokens=1000,
            pricing=_pricing(),
        )
        assert v.defer is False
        assert v.reason == "proceed"
        assert v.savings > v.rewrite_cost > 0

    def test_savings_below_cost_defers(self):
        """收益 2×1000×0.3e-6=6e-4 ≤ 代价 50000×3.45e-6×1.5≈0.259 ⇒ defer。"""
        v = evaluateCacheBreakEven(
            remaining_steps=2,
            tokens_saved_per_call=1000,
            invalidation_tokens=50000,
            pricing=_pricing(),
        )
        assert v.defer is True
        assert v.reason in {"warm_within_ttl_deferred", "break_even_failed"}

    def test_ttl_bounded_defer_attribution(self):
        """有 TTL 界的暖缓存归因 warm_within_ttl_deferred；无保证 TTL 归因 break_even_failed。"""
        warm = evaluateCacheBreakEven(
            remaining_steps=2,
            tokens_saved_per_call=1000,
            invalidation_tokens=50000,
            pricing=_pricing(ttl_seconds=300),
        )
        cold = evaluateCacheBreakEven(
            remaining_steps=2,
            tokens_saved_per_call=1000,
            invalidation_tokens=50000,
            pricing=_pricing(ttl_seconds=0),
        )
        assert warm.defer and warm.reason == "warm_within_ttl_deferred"
        assert cold.defer and cold.reason == "break_even_failed"

    def test_no_invalidation_never_defers(self):
        """无可失效前缀（首次折叠）：缓存维度没有要保护的东西 ⇒ 不拦。"""
        v = evaluateCacheBreakEven(
            remaining_steps=10,
            tokens_saved_per_call=1000,
            invalidation_tokens=0,
            pricing=_pricing(),
        )
        assert v.defer is False and v.reason == "proceed"

    def test_safety_factor_scales_rewrite_cost(self):
        base = evaluateCacheBreakEven(
            remaining_steps=3,
            tokens_saved_per_call=2000,
            invalidation_tokens=20000,
            pricing=_pricing(),
            safety_factor=1.0,
        )
        safe = evaluateCacheBreakEven(
            remaining_steps=3,
            tokens_saved_per_call=2000,
            invalidation_tokens=20000,
            pricing=_pricing(),
            safety_factor=3.0,
        )
        assert safe.rewrite_cost == pytest.approx(base.rewrite_cost * 3.0)


# ── 编排层接线（真实编排器 + 真实判据，不 mock 判据对象） ──────────────────


def _mk_agent(model: str = "test-model"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-cache-gate"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = model
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-cache-gate"
    agent.agent_id = "a-cache-gate"
    return agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _summary_rows(view):
    return [
        m
        for m in view
        if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))
    ]


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import (
        reset_self_model_engine,
    )

    reset_meta_ledger()
    reset_self_model_engine()
    yield
    reset_meta_ledger()
    reset_self_model_engine()


def _mk_orchestrator(model: str):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(_mk_agent(model), use_pool=True, auto_tag=False)
    orch._window_hard_limit = 10**9
    return orch


def _warmSlotScenario(orch, key: str, occupancy: float):
    """增长门 + 暖缓存场景： seeding 摘要覆盖/冻结头/增量基线。

    占用钉在 `occupancy`；增量 0.6×total（过增长门 token 门槛）；
    冻结头 ≈8000 token（大而暖——重渲染即失效的前缀）。
    """
    msgs = [_long_msg(i) for i in range(24)]
    total = estimate_window_tokens(msgs)
    budget = orch._effectiveWindowBudget(int(total / occupancy))
    head_rows = [{"role": "system", "content": "[早期对话摘要] " + "史" * 8000}]
    cache = orch._window_cache_slot(key)
    cache.update(
        {
            "summary": "旧摘要：早期经历已提炼。",
            "covered": {orch._windowChunkHash(m) for m in msgs[:4]},
            "frozen_head_rows": head_rows,
            "last_fold_tokens": int(total * 0.4),
            "last_fold_msgs": 4,
            "last_count": len(msgs) - 2,
        }
    )
    return msgs, budget, head_rows


class TestCacheGateWiring:
    @pytest.mark.asyncio
    async def test_growth_gate_fold_deferred_as_cache_deferred(self, monkeypatch):
        """增长门想折、缓存盈亏不合算 ⇒ 改判 cache_deferred，不折。"""
        # 剩余步数取工具轮预算单源：env 钉小值（轮末尾的诚实剩余量）。
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", "4")
        orch = _mk_orchestrator("claude-sonnet-4-test")
        msgs, budget, head_rows = _warmSlotScenario(orch, "sess-cache-gate", 0.8)

        # 前置（用同一判据复算，防"没触发所以没拦"的假红/假绿）：
        # 增长门确实会触发，且缓存闸确实落在 defer 区。
        from neurova.context.compression_economics import (
            evaluateCacheBreakEven,
            getProviderCachePricing,
        )

        total = estimate_window_tokens(msgs)
        growth = total - int(total * 0.4)
        verdict = evaluateCacheBreakEven(
            remaining_steps=4,
            tokens_saved_per_call=growth,
            invalidation_tokens=estimate_window_tokens(head_rows),
            pricing=getProviderCachePricing("claude-sonnet-4-test"),
        )
        assert verdict.defer is True, f"测试前置不成立（应落在 defer 区）：{verdict}"

        view = await orch._apply_window_budget(msgs, budget, cache_key="sess-cache-gate")

        health = orch.get_context_health()
        ft = health["fold_trigger"]
        assert ft["last_reason"] == REASON_CACHE_DEFERRED, (
            f"折叠归因应改判 cache_deferred，实得 {ft['last_reason']}"
        )
        assert ft["should_fold"] is False
        gate = health["cache_break_even"]
        assert gate["defer"] is True
        assert gate["reason"] == "warm_within_ttl_deferred"
        assert gate["invalidation_tokens"] > 0
        assert health["fold_suppression"]["cache_hits"] >= 1, "抑制必须进读数面，不留静默"
        assert _summary_rows(view), "零折叠轮视图 = 冻结头 + 未覆盖尾部（冻结头在场）"
        assert not _summary_rows(view)[0] is None

    @pytest.mark.asyncio
    async def test_budget_breach_bypasses_cache_gate(self, monkeypatch):
        """预算击穿（安全线）不受缓存闸管辖：即便闸会 defer 也必折。"""
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", "4")
        orch = _mk_orchestrator("claude-sonnet-4-test")

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：早期经历已提炼。"

        orch._window_summarizer = fake_summarize
        msgs, budget, _head = _warmSlotScenario(orch, "sess-breach", 1.15)
        total = estimate_window_tokens(msgs)
        assert total > budget, "前置：必须真的击穿"

        view = await orch._apply_window_budget(msgs, budget, cache_key="sess-breach")

        health = orch.get_context_health()
        assert health["fold_trigger"]["last_reason"] == REASON_BUDGET_BREACH, (
            f"击穿归因不得被缓存闸改判，实得 {health['fold_trigger']['last_reason']}"
        )
        assert _summary_rows(view), "击穿必折：安全线优先于缓存经济学"

    @pytest.mark.asyncio
    async def test_no_pricing_keeps_default_behavior(self, monkeypatch):
        """无定价元数据（未知模型）：闸不拦，增长门照常按原判据走。"""
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", "4")
        orch = _mk_orchestrator("test-model")
        msgs, budget, _head = _warmSlotScenario(orch, "sess-nopricing", 0.8)

        await orch._apply_window_budget(msgs, budget, cache_key="sess-nopricing")

        health = orch.get_context_health()
        assert health["cache_break_even"]["reason"] == "no_pricing"
        assert health["cache_break_even"]["defer"] is False
        assert health["fold_trigger"]["last_reason"] == REASON_GROWTH_GATE, (
            f"无定价不得改判折叠归因，实得 {health['fold_trigger']['last_reason']}"
        )
