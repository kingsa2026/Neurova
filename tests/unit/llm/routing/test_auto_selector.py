# -*- coding: utf-8 -*-
"""R3（参照系 ad 追平批一）：auto 请求的能力驱动选型进主聊天链路。

契约（源自 docs/04-plans/2026-11-22-reference-ad-llm-routing-catchup-
implementation-plan.md R3 卡）：
- 仅未显式钉死模型/服务商的 auto 请求生效；显式指定与视觉轮覆盖行为不变；
- 带工具的请求要求 TOOL_USE 能力，选不出可满足候选时保持既有兜底
  （None → MultiModelLLMClient 自愈链），不凭空造能力；
- 命中时只传模型名、不携带 provider_id（与视觉轮覆盖同理由：钉死
  provider 会禁用 auto-failover，保留跨服务商切换链）。
"""

import pytest

from neurova.llm.llm_router import get_llm_router
from neurova.llm.routing.auto_selector import resolveAutoChatModel


def _register_router_providers():
    """直接注册路由表（admin scope 已在 conftest 复位为已同步态，不再惰性拉取）。"""
    router = get_llm_router()
    router.register_provider(
        "ad-text", "text-only", scope="admin",
        models=[{"name": "text-model", "capabilities": ["text"],
                 "priority": 5, "health_status": "healthy", "weight": 1.0}],
    )
    router.register_provider(
        "ad-tool", "tool-capable", scope="admin",
        models=[{"name": "tool-model", "capabilities": ["text", "tool_use"],
                 "priority": 1, "health_status": "healthy", "weight": 1.0}],
    )


class TestResolveAutoChatModel:
    def test_tools_required_picks_tool_capable(self):
        _register_router_providers()
        picked = resolveAutoChatModel(scope="admin", needs_tools=True)
        assert picked == ("ad-tool", "tool-model")

    def test_no_tools_takes_highest_priority(self):
        _register_router_providers()
        picked = resolveAutoChatModel(scope="admin", needs_tools=False)
        assert picked == ("ad-text", "text-model")

    def test_no_capable_candidate_returns_none(self, monkeypatch):
        """无满足能力的候选 → None（调用方走既有兜底，不凭空造能力）。"""
        import neurova.llm.llm_router as router_mod

        # 隔离：屏蔽「候选空回退全局表」的惰性同步，避免真实目录串入断言
        monkeypatch.setattr(router_mod, "sync_llm_router", lambda *a, **k: None)
        get_llm_router().register_provider(
            "ad-text-only", "text-only", scope="admin",
            models=[{"name": "text-model", "capabilities": ["text"],
                     "priority": 5, "health_status": "healthy", "weight": 1.0}],
        )
        assert resolveAutoChatModel(scope="admin", needs_tools=True) is None

    def test_router_unavailable_returns_none(self, monkeypatch):
        """路由层异常 → None（fail-open 回既有兜底，不炸调用链）。"""
        import neurova.llm.routing.auto_selector as mod

        def _boom(*a, **k):
            raise RuntimeError("router down")

        monkeypatch.setattr(mod, "_selectChatCandidate", _boom)
        assert resolveAutoChatModel(scope="admin", needs_tools=True) is None


class TestResolveCallModelWiring:
    """AgentLLMClient._resolve_call_model 接线：auto 请求走能力选型。"""

    def _client(self):
        from neurova.agent_core import AgentLLMClient

        return AgentLLMClient(model="auto", provider_id="", scope="admin")

    def test_auto_with_tools_picks_tool_capable_model(self):
        _register_router_providers()
        client = self._client()
        kwargs = {"tools": [{"type": "function", "function": {"name": "ping"}}]}
        model, provider_id = client._resolve_call_model(kwargs)
        assert model == "tool-model"
        # 与视觉轮覆盖同理由：不携带 provider_id，保留跨服务商切换链
        assert provider_id is None
        assert "tools" in kwargs  # 不吞调用方参数

    def test_auto_without_tools_keeps_legacy_fallback(self):
        _register_router_providers()
        client = self._client()
        model, provider_id = client._resolve_call_model({})
        # 无能力要求时选最高优先级（ad-text），仍只传模型名
        assert model == "text-model"
        assert provider_id is None

    def test_explicit_model_unchanged(self):
        _register_router_providers()
        client = self._client()
        client.model = "gpt-x"
        model, provider_id = client._resolve_call_model({})
        assert (model, provider_id) == ("gpt-x", None)

    def test_vision_override_still_wins(self):
        from neurova.llm.llm_routing_overlay import vision_routing_overlay

        _register_router_providers()
        client = self._client()
        with vision_routing_overlay("ad-vis", "vis-model"):
            model, provider_id = client._resolve_call_model(
                {"tools": [{"type": "function", "function": {"name": "ping"}}]}
            )
        assert (model, provider_id) == ("vis-model", None)


class TestRegisterProviderCarriesPriority:
    """R3 live-verify 根因：register_provider_from_config 把 priority 硬编码
    为 1，provider 配置的优先级进不了路由表，选型排序退化为插入序。"""

    def test_priority_flows_into_router_registry(self):
        from neurova.llm.llm_router import (
            get_llm_router,
            register_provider_from_config,
        )

        register_provider_from_config("p-low", "low", ["m1"], {}, scope="admin", priority=1)
        register_provider_from_config("p-high", "high", ["m2"], {}, scope="admin", priority=9)
        entries = {p["provider_id"]: p["models"]
                   for p in get_llm_router().list_providers("admin")}
        assert entries["p-high"][0]["priority"] == 9
        assert entries["p-low"][0]["priority"] == 1

    def test_higher_priority_provider_wins_selection(self):
        from neurova.llm.llm_router import (
            get_llm_router,
            register_provider_from_config,
        )
        from neurova.llm.routing.auto_selector import resolveAutoChatModel

        register_provider_from_config("q-low", "low", ["text-model"],
                                      {"text-model": {"capabilities": ["text"]}},
                                      scope="admin", priority=1)
        register_provider_from_config("q-high", "high", ["tool-model"],
                                      {"tool-model": {"capabilities": ["text", "tool_use"]}},
                                      scope="admin", priority=9)
        assert resolveAutoChatModel(scope="admin", needs_tools=True) == ("q-high", "tool-model")
