# -*- coding: utf-8 -*-
"""D-R2（参照系 ad 追平）：同优先级组内加权分流。

契约（2026-11-22 用户拍板落地）：
- 优先级仍主导：weight 只在**同优先级组内**分配流量份额；
- 组内权重不全相等 → 按权重加权抽取；全相等 → 保持既有确定性排序
  （response_time / 注册序），不引入随机性（零回归）；
- weight=0 = 仅兜底：不参与日常分配，failover 链仍可达；
- 配置面：ProviderConfig.weight（默认 1.0）经 provider CRUD API 与
  register_provider_from_config/sync_llm_router 进路由表。
"""

import asyncio
from types import SimpleNamespace

import pytest

from neurova.llm.llm_router import (
    get_llm_router,
    register_provider_from_config,
)


def _register(pid, model, *, priority, weight, caps=("text",)):
    get_llm_router().register_provider(
        pid, pid, scope="admin",
        models=[{"name": model, "capabilities": list(caps), "priority": priority,
                 "health_status": "healthy", "response_time": 0.0, "weight": weight}],
    )


class _ControlledRng:
    """按脚本出牌的随机源（产出 0~1 的数）。"""

    def __init__(self, seq):
        self.seq = list(seq)

    def random(self):
        return self.seq.pop(0) if self.seq else 0.0


@pytest.fixture
def rng(monkeypatch):
    import neurova.llm.llm_router as mod

    ctl = _ControlledRng([0.0])
    monkeypatch.setattr(mod, "_rng", ctl, raising=False)
    return ctl


def _picks(rng, seq, n):
    from neurova.llm.llm_router import RequestType, select_model_for_request

    rng.seq = list(seq)
    out = []
    for _ in range(n):
        picked = select_model_for_request(RequestType.CHAT, scope="admin")
        out.append(picked.provider_id)
    return out


class TestWeightedSplit:
    def test_weight_split_within_same_priority(self, rng):
        """同优先级 A3:B1 → 累积 [0,0.75) 命中 A、[0.75,1) 命中 B。"""
        _register("wa", "ma", priority=5, weight=3.0)
        _register("wb", "mb", priority=5, weight=1.0)
        assert _picks(rng, [0.2, 0.8, 0.2, 0.8], 4) == ["wa", "wb", "wa", "wb"]

    def test_weight_zero_is_fallback_only(self, rng):
        """weight=0 的同优先级候选不参与日常分配。"""
        _register("wz", "mz", priority=5, weight=0.0)
        _register("wn", "mn", priority=5, weight=1.0)
        assert _picks(rng, [0.0, 0.5, 0.99], 3) == ["wn", "wn", "wn"]

    def test_equal_weights_keep_legacy_deterministic(self, rng):
        """权重全相等 → 保持既有确定性排序（不进随机分支）。"""
        _register("ea", "ma", priority=5, weight=1.0)
        _register("eb", "mb", priority=5, weight=1.0)
        # 若误入随机分支，0.9 会选 eb；旧确定性应恒选注册序首位 ea
        assert _picks(rng, [0.9, 0.9, 0.9], 3) == ["ea", "ea", "ea"]

    def test_priority_dominates_weight(self, rng):
        """优先级不同时 weight 不越级：高优权重再小也先于低优。"""
        _register("hi", "mh", priority=10, weight=0.0)
        _register("lo", "ml", priority=1, weight=100.0)
        assert _picks(rng, [0.99], 1) == ["hi"]

    def test_all_zero_weights_fall_back_deterministic(self, rng):
        """组内全为 0 权重 → 退化确定性（response_time 序），不除零。"""
        _register("z1", "m1", priority=5, weight=0.0)
        _register("z2", "m2", priority=5, weight=0.0)
        assert _picks(rng, [0.1, 0.9], 2) == ["z1", "z1"]


class TestWeightConfigSurface:
    def test_provider_config_weight_default_and_roundtrip(self, tmp_path):
        from neurova.llm.provider_manager import ProviderConfig

        pc = ProviderConfig(id="x", name="x", provider="openai",
                            base_url="https://x.example.com/v1")
        assert pc.weight == 1.0
        data = pc.to_dict()
        assert data["weight"] == 1.0
        pc2 = ProviderConfig.from_dict({**data, "weight": 4.5})
        assert pc2.weight == 4.5

    def test_add_and_update_provider_weight(self, tmp_path):
        from neurova.llm.provider_manager import LLMProviderManager

        mgr = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
        mgr.add_provider(name="w1", provider="openai", base_url="https://w1.example.com/v1",
                         api_key="sk", models=["m"], default_model="m",
                         priority=5, weight=3.0)
        assert mgr.get_provider("w1").weight == 3.0
        assert mgr.update_provider("w1", weight=0.0)
        assert mgr.get_provider("w1").weight == 0.0

    def test_register_and_sync_carry_weight(self, tmp_path, monkeypatch):
        """sync_llm_router 读全局 manager 单例——须把 weight 配置挂到全局再同步。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.llm import provider_manager as pm_mod

        pm_mod.reset_provider_manager()
        from neurova.llm.llm_router import sync_llm_router
        from neurova.llm.provider_manager import get_provider_manager

        mgr = get_provider_manager()
        mgr.add_provider(name="ww", provider="openai", base_url="https://ww.example.com/v1",
                         api_key="sk", models=["m"], default_model="m",
                         priority=5, weight=4.0)
        sync_llm_router()
        rows = [p for p in get_llm_router().list_providers("admin") if p["provider_id"] == "ww"]
        assert rows and rows[0]["models"][0]["weight"] == 4.0
        pm_mod.reset_provider_manager()

    @pytest.mark.asyncio
    async def test_create_provider_api_accepts_weight(self, tmp_path, monkeypatch):
        """CRUD API 透传 weight（管理端配置面）。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.llm import provider_manager as pm_mod

        pm_mod.reset_provider_manager()
        from neurova.api.endpoints.provider import CreateProviderRequest, create_provider
        from neurova.llm.provider_manager import get_provider_manager

        body = CreateProviderRequest(name="w-api", provider_type="openai",
                                     base_url="https://w-api.example.com/v1",
                                     api_key="sk", weight=4.0)
        request = SimpleNamespace(state=SimpleNamespace(request_id="t"))
        info = await create_provider(request=request, body=body,
                                     current_user={"user_id": "u1", "role": "admin"})
        pc = get_provider_manager().get_provider(info.provider_id)
        assert pc.weight == 4.0
        pm_mod.reset_provider_manager()
