# -*- coding: utf-8 -*-
"""A4（对照改进追问批）：按缓存画像自适应折叠目标。

数据依据（data/usage_history.db 实测，2026-11-15）：
- deepseek-v4-flash-vision（39 calls）：cache 命中 38% —— 前缀缓存真实生效；
- qiniu/conatus-free（632 calls）：命中 1.2%、nex-n2.6（122 calls）：0% ——
  两个主力模型**没有有效前缀缓存**。

契约：
1. `UsageHistoryStore.cache_profile_for_model(model)`：按模型聚合
   {calls, prompt_tokens, cache_read_tokens, hit_rate, sufficient}；
   sufficient = calls ≥ 20（样本门槛）；
2. 折叠目标自适应：无有效缓存（sufficient 且 hit < 5%）的模型，预算击穿
   折叠目标从 0.5 加深到 0.35（视图更小 = 非缓存链路的直接账单节省）；
   缓存生效模型维持 0.5（保前缀）；样本不足维持 0.5（证据门槛）；
3. 开关 NEUROVA_CACHE_ADAPTIVE_FOLD=0 关闭（默认开，证据门槛内生效）；
4. 健康读数：fold_resolution 旁挂 cache_adaptive 面。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.core.usage_history import UsageHistoryStore


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.core.usage_history import reset_usage_history

    reset_usage_history()
    yield
    reset_usage_history()


def _seed(db_path: str, model: str, calls: int, hit_ratio: float):
    """往指定库播样本：calls 条记录，cache_read = prompt×hit_ratio。"""
    import sqlite3

    conn = sqlite3.connect(db_path)
    store = UsageHistoryStore(db_path=db_path)
    for i in range(calls):
        store.record(
            model=model,
            provider="p-seed",
            prompt_tokens=1000,
            completion_tokens=10,
            user_id="u-seed",
            cache_read_tokens=int(1000 * hit_ratio),
        )
    conn.close()


def _mk_agent(model="test-model"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = model
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "s"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-a4"
    agent.agent_id = "a-a4"
    return agent


class TestCacheProfile:
    def test_profile_aggregation(self, tmp_path):
        db = str(tmp_path / "u.db")
        _seed(db, "m-prof", calls=25, hit_ratio=0.4)
        store = UsageHistoryStore(db_path=db)
        profile = store.cache_profile_for_model("m-prof")
        assert profile["calls"] == 25
        assert profile["hit_rate"] == pytest.approx(0.4)
        assert profile["sufficient"] is True

    def test_profile_insufficient_calls(self, tmp_path):
        db = str(tmp_path / "u.db")
        _seed(db, "m-few", calls=3, hit_ratio=0.0)
        store = UsageHistoryStore(db_path=db)
        profile = store.cache_profile_for_model("m-few")
        assert profile["sufficient"] is False

    def test_profile_unknown_model(self, tmp_path):
        store = UsageHistoryStore(db_path=str(tmp_path / "u.db"))
        profile = store.cache_profile_for_model("never-seen")
        assert profile["calls"] == 0 and profile["sufficient"] is False


class TestCacheAdaptiveFoldTarget:
    def _orch(self, model="test-model"):
        return ContextOrchestrator(_mk_agent(model), use_pool=False, auto_tag=False)

    def _seed_global(self, tmp_path, monkeypatch, hit: float, calls: int = 25):
        """把全局单例指到 tmp 库并播样本（不依赖 data-root 的解析时机）。"""
        import neurova.core.usage_history as uh

        db = str(tmp_path / "usage_history.db")
        _seed(db, "test-model", calls=calls, hit_ratio=hit)
        store = UsageHistoryStore(db_path=db)
        monkeypatch.setattr(uh, "get_usage_history", lambda: store)

    def test_no_cache_model_folds_deeper(self, tmp_path, monkeypatch):
        """无有效缓存（样本足、命中<5%）：折叠目标加深到 0.35。"""
        monkeypatch.delenv("NEUROVA_CACHE_ADAPTIVE_FOLD", raising=False)
        self._seed_global(tmp_path, monkeypatch, hit=0.0)
        orch = self._orch()
        target, profile = orch._cacheAdaptiveFoldTarget()
        assert target == 0.35, f"无缓存模型应加深折叠目标：{profile}"
        assert profile["hit_rate"] < 0.05 and profile["sufficient"]

    def test_cached_model_keeps_half(self, tmp_path, monkeypatch):
        """缓存生效（命中 38%）：维持 0.5（保前缀）。"""
        monkeypatch.delenv("NEUROVA_CACHE_ADAPTIVE_FOLD", raising=False)
        self._seed_global(tmp_path, monkeypatch, hit=0.38)
        orch = self._orch()
        target, _ = orch._cacheAdaptiveFoldTarget()
        assert target == 0.5

    def test_insufficient_samples_keeps_half(self, tmp_path, monkeypatch):
        """样本不足（<20 calls）：证据门槛，维持 0.5。"""
        monkeypatch.delenv("NEUROVA_CACHE_ADAPTIVE_FOLD", raising=False)
        self._seed_global(tmp_path, monkeypatch, hit=0.0, calls=5)
        orch = self._orch()
        target, _ = orch._cacheAdaptiveFoldTarget()
        assert target == 0.5

    def test_kill_switch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
        self._seed_global(tmp_path, monkeypatch, hit=0.0)
        orch = self._orch()
        target, _ = orch._cacheAdaptiveFoldTarget()
        assert target == 0.5
