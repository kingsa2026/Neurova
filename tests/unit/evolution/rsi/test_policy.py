# -*- coding: utf-8 -*-
"""P3-1：EvolutionPolicy 参数化 + 版本台账（计划书 §3.7 / §6 P3-1）。

判据结构（红→绿）：
- 红灯：``neurova/evolution/rsi/policy.py`` 缺席时本文件收集即红（import 失败）；
- 域校验：来源权重和≠1 拒、预算越界拒、并发越界拒（``PolicyBoundsError``）；
- 台账（沿 ImproverVersionLedger 范式）：同号异摘要拒、requireKnown 未注册拒、
  落盘读回一致、env 未配置零 IO；
- 边界纪律：区间边界是常量（forbidden 语义），不提供运行时改边界接口；
- 默认策略与文档口径一致（来源均分 / 预算保守）。
"""

from __future__ import annotations

import json

import pytest

import neurova.evolution.rsi.policy as policy_module
from neurova.evolution.rsi.policy import (
    MAX_MAX_TOKENS_PER_GENERATION,
    MAX_MAX_WALL_MS,
    MAX_SHADOW_CONCURRENCY,
    MIN_MAX_TOKENS_PER_GENERATION,
    MIN_MAX_WALL_MS,
    MIN_SHADOW_CONCURRENCY,
    POLICY_LEDGER_ENV,
    EvolutionPolicy,
    EvolutionPolicyLedger,
    PolicyBoundsError,
    resolve_policy_ledger,
)


def _policy(**overrides) -> EvolutionPolicy:
    """构造一个合法策略（默认并发 2，其余取文档默认），供越界反例逐字段改。"""
    fields = dict(
        sourceWeights={"rsi": 1 / 3, "eval": 1 / 3, "external": 1 / 3},
        maxTokensPerGeneration=100_000,
        maxWallMs=60_000,
        shadowConcurrency=2,
    )
    fields.update(overrides)
    return EvolutionPolicy(**fields)


class TestPolicyDomain:
    """策略域校验：允许区间外的取值一律 PolicyBoundsError（fail-closed）。"""

    def test_default_policy_matches_plan(self):
        """默认策略与文档口径一致：来源均分、预算保守（区间下半段）、覆盖全空。"""
        policy = EvolutionPolicy.default()
        assert policy.sourceWeights == {"rsi": 1 / 3, "eval": 1 / 3, "external": 1 / 3}
        assert abs(sum(policy.sourceWeights.values()) - 1.0) < 1e-9
        # 预算保守 = 取在允许区间的下半段（宁可少花，不可失控）
        assert (
            MIN_MAX_TOKENS_PER_GENERATION
            <= policy.maxTokensPerGeneration
            <= (MIN_MAX_TOKENS_PER_GENERATION + MAX_MAX_TOKENS_PER_GENERATION) / 2
        )
        assert (
            MIN_MAX_WALL_MS
            <= policy.maxWallMs
            <= (MIN_MAX_WALL_MS + MAX_MAX_WALL_MS) / 2
        )
        assert policy.shadowConcurrency == 1
        # 覆盖缺省 = 交给治理设置（None 语义）
        assert policy.canaryWindow is None
        assert policy.gateThresholds is None

    def test_weight_sum_not_one_rejected(self):
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": 0.5, "eval": 0.5, "external": 0.5})
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": 0.9, "eval": 0.1, "external": 0.1})

    def test_weight_domain_violations_rejected(self):
        # 缺一路 / 多一路
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": 1.0, "eval": 0.0})
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={
                "rsi": 0.4, "eval": 0.3, "external": 0.2, "neuacp": 0.1})
        # 负权重 / 超 1 / 非数值
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": -0.1, "eval": 0.6, "external": 0.5})
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": 1.2, "eval": -0.1, "external": -0.1})
        with pytest.raises(PolicyBoundsError):
            _policy(sourceWeights={"rsi": "0.5", "eval": 0.25, "external": 0.25})

    def test_budget_out_of_bounds_rejected(self):
        for bad_tokens in (0, MIN_MAX_TOKENS_PER_GENERATION - 1,
                           MAX_MAX_TOKENS_PER_GENERATION + 1, -100):
            with pytest.raises(PolicyBoundsError):
                _policy(maxTokensPerGeneration=bad_tokens)
        for bad_wall in (0, MIN_MAX_WALL_MS - 1, MAX_MAX_WALL_MS + 1):
            with pytest.raises(PolicyBoundsError):
                _policy(maxWallMs=bad_wall)

    def test_concurrency_out_of_bounds_rejected(self):
        for bad in (0, -1, MAX_SHADOW_CONCURRENCY + 1, 100):
            with pytest.raises(PolicyBoundsError):
                _policy(shadowConcurrency=bad)
        # 区间内合法：1..4
        for good in range(MIN_SHADOW_CONCURRENCY, MAX_SHADOW_CONCURRENCY + 1):
            assert _policy(shadowConcurrency=good).shadowConcurrency == good

    def test_optional_overrides_domain_rejected(self):
        # 金丝雀窗：给值必须落在区间内；None = 用治理设置
        with pytest.raises(PolicyBoundsError):
            _policy(canaryWindow=30)
        with pytest.raises(PolicyBoundsError):
            _policy(canaryWindow=10 * 86_400)
        assert _policy(canaryWindow=600).canaryWindow == 600
        # 门禁阈值覆盖：值必须落在 [0, 1]
        with pytest.raises(PolicyBoundsError):
            _policy(gateThresholds={"g2": 1.5})
        with pytest.raises(PolicyBoundsError):
            _policy(gateThresholds={"g2": -0.1})
        assert _policy(gateThresholds={"g2": 0.8}).gateThresholds == {"g2": 0.8}


class TestPolicyBoundsDiscipline:
    """边界纪律（裁判件不可达）：边界是常量，不提供运行时改边界接口。"""

    def test_bounds_are_ordered_constants(self):
        assert 0 < MIN_MAX_TOKENS_PER_GENERATION < MAX_MAX_TOKENS_PER_GENERATION
        assert 0 < MIN_MAX_WALL_MS < MAX_MAX_WALL_MS
        assert 1 <= MIN_SHADOW_CONCURRENCY <= MAX_SHADOW_CONCURRENCY <= 4

    def test_no_runtime_bounds_mutation_api(self):
        """改边界=改规则，只能走人工 PR——模块/类上不存在任何改边界接口。"""
        for name in ("setBounds", "updateBounds", "relaxBounds",
                     "overrideBounds", "setPolicyBounds", "widenBounds"):
            assert not hasattr(policy_module, name), name
            assert not hasattr(EvolutionPolicy, name), name
            assert not hasattr(EvolutionPolicyLedger, name), name

    def test_policy_instance_is_frozen(self):
        """策略值不可被运行时悄悄改（frozen dataclass）。"""
        policy = _policy()
        with pytest.raises(Exception):
            policy.shadowConcurrency = 4  # type: ignore[misc]


class TestPolicyLedger:
    """版本台账：同号异摘要拒 / 未注册拒 / 落盘读回一致 / env 未配置零 IO。"""

    def test_register_latest_and_require_known_in_memory(self):
        ledger = EvolutionPolicyLedger()
        ledger.register("P_0", "初始策略：来源均分+保守预算", _policy())
        entry = ledger.latest()
        assert entry["version"] == "P_0"
        assert entry["policy"]["shadowConcurrency"] == 2
        ledger.requireKnown("P_0")  # 已注册 → 不抛

    def test_same_version_different_summary_rejected(self):
        ledger = EvolutionPolicyLedger()
        ledger.register("P_1", "放宽并发到 3", _policy(shadowConcurrency=3))
        with pytest.raises(ValueError):
            ledger.register("P_1", "另一份摘要（伪造）", _policy(shadowConcurrency=3))

    def test_same_version_same_summary_different_policy_rejected(self):
        ledger = EvolutionPolicyLedger()
        ledger.register("P_1", "摘要一致", _policy(shadowConcurrency=2))
        with pytest.raises(ValueError):
            ledger.register("P_1", "摘要一致", _policy(shadowConcurrency=3))

    def test_idempotent_reregister_same_content(self):
        ledger = EvolutionPolicyLedger()
        ledger.register("P_1", "摘要", _policy())
        ledger.register("P_1", "摘要", _policy())  # 幂等
        assert len(ledger.readAll()) == 1

    def test_require_known_rejects_unregistered(self):
        ledger = EvolutionPolicyLedger()
        with pytest.raises(KeyError):
            ledger.requireKnown("P_404")

    def test_register_rejects_non_policy(self):
        ledger = EvolutionPolicyLedger()
        with pytest.raises(TypeError):
            ledger.register("P_1", "摘要", {"shadowConcurrency": 2})

    def test_persist_and_readback_consistent(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "policies" / "evolution_policy.json"
        monkeypatch.setenv(POLICY_LEDGER_ENV, str(ledger_path))
        ledger = resolve_policy_ledger()
        policy_v0 = _policy(shadowConcurrency=1)
        policy_v1 = _policy(
            shadowConcurrency=3,
            canaryWindow=600,
            gateThresholds={"g2": 0.8},
        )
        ledger.register("P_0", "初始策略", policy_v0)
        ledger.register("P_1", "放宽并发+显式金丝雀窗", policy_v1)

        # 新实例（模拟重启）从落盘文件读回，逐字段一致
        reopened = resolve_policy_ledger()
        assert reopened._path == ledger_path
        entries = reopened.readAll()
        assert [e["version"] for e in entries] == ["P_0", "P_1"]
        assert entries[1]["policy"] == policy_v1.toDict()
        assert EvolutionPolicy.fromDict(entries[0]["policy"]) == policy_v0
        assert reopened.latest()["version"] == "P_1"
        reopened.requireKnown("P_0")

    def test_unconfigured_env_is_pure_memory_zero_io(self, tmp_path, monkeypatch):
        monkeypatch.delenv(POLICY_LEDGER_ENV, raising=False)
        monkeypatch.chdir(tmp_path)  # 即使误写也会落到 tmp，便于断言
        ledger = resolve_policy_ledger()
        assert ledger._path is None  # 未配置 env ⇒ 无落盘目标
        ledger.register("P_0", "内存账", _policy())
        ledger.requireKnown("P_0")
        assert ledger.latest()["version"] == "P_0"
        # 零 IO 证据：进程工作目录里没有冒出任何台账文件
        assert list(tmp_path.rglob("*.json")) == []

    def test_corrupt_file_falls_back_to_empty_then_rewrites(self, tmp_path, monkeypatch):
        ledger_path = tmp_path / "evolution_policy.json"
        ledger_path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv(POLICY_LEDGER_ENV, str(ledger_path))
        ledger = resolve_policy_ledger()
        assert ledger.readAll() == []  # 损坏文件：回退空态，不崩
        ledger.register("P_0", "损坏后重建", _policy())
        reopened = resolve_policy_ledger()
        assert [e["version"] for e in reopened.readAll()] == ["P_0"]

    def test_env_name_is_documented(self):
        assert POLICY_LEDGER_ENV == "NEUROVA_EVOLUTION_POLICY"
