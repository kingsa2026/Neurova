# -*- coding: utf-8 -*-
"""EvolutionPolicy 参数化 + 版本台账 —— 元层（L3）地基（P3-1）。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§2.0（自动只发生在判据与边界之内）、§2.1 原则 3（裁判在演化集合之外）、
§3.7（policy.py 设计）、§6 P3 批 P3-1。

``EvolutionPolicy`` 是世代编排器的元层参数载体：候选来源权重（rsi/eval/external
三路）、每代预算上限（token / 墙钟）、影子验证并发度、金丝雀窗与各门禁阈值的
覆盖值（None = 交给治理设置，本模块不复制治理默认值——单一事实源不搬家）。

边界纪律（裁判件不可达，§2.1 原则 3）：

- 策略只能在"允许区间"内取值：各字段在构造期做 domain/区间校验，越界抛
  ``PolicyBoundsError``——不存在"悄悄收敛到非法值"的路径；
- **区间边界本身是常量（forbidden 语义）**：本模块不提供任何运行时修改边界的
  接口（无 setBounds / 无配置键 / 无 env 覆盖）。改边界 = 改规则，只走人工 PR
  + 守卫测试红绿。自动演化可以在边界内调参数，永远碰不到边界本身。

版本台账 ``EvolutionPolicyLedger`` 沿 ``candidate_policy.ImproverVersionLedger``
范式：同版本号改摘要（或改策略）= 伪造，拒；``requireKnown`` 未注册号拒；
落盘路径由 env ``NEUROVA_EVOLUTION_POLICY`` 指定，未配置时纯内存零 IO
（与 NEUROVA_EVOLUTION_GENERATIONS / NEUROVA_RSI_IMPROVER_LEDGER 同款约定，
防止单测把仓库 data/ 变成状态污染源）。写入原子（tmp + os.replace）。
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "POLICY_LEDGER_ENV",
    "VALID_SOURCE_KEYS",
    "MIN_MAX_TOKENS_PER_GENERATION",
    "MAX_MAX_TOKENS_PER_GENERATION",
    "MIN_MAX_WALL_MS",
    "MAX_MAX_WALL_MS",
    "MIN_SHADOW_CONCURRENCY",
    "MAX_SHADOW_CONCURRENCY",
    "MIN_CANARY_WINDOW_SECONDS",
    "MAX_CANARY_WINDOW_SECONDS",
    "EvolutionPolicy",
    "EvolutionPolicyLedger",
    "PolicyBoundsError",
    "resolve_policy_ledger",
]

#: 策略版本台账的落盘路径 env（未配置 = 纯内存零 IO）。
POLICY_LEDGER_ENV = "NEUROVA_EVOLUTION_POLICY"

#: 候选来源三路（§2.2：RSI 参数臂 / evolution_eval 文本技能臂 / neuacp 代码臂）。
VALID_SOURCE_KEYS = ("rsi", "eval", "external")

#: 权重和判据容差（浮点三等分 1/3+1/3+1/3 在 IEEE754 下恰好为 1.0，容差仅防手输小数）。
_WEIGHT_SUM_TOLERANCE = 1e-9

# ---------------------------------------------------------------------------
# 允许区间（forbidden 常量）：只准在这里读，不准有任何运行时改写通道。
# ---------------------------------------------------------------------------
MIN_MAX_TOKENS_PER_GENERATION = 1_000
MAX_MAX_TOKENS_PER_GENERATION = 5_000_000
MIN_MAX_WALL_MS = 1_000
MAX_MAX_WALL_MS = 3_600_000
MIN_SHADOW_CONCURRENCY = 1
MAX_SHADOW_CONCURRENCY = 4
MIN_CANARY_WINDOW_SECONDS = 60
MAX_CANARY_WINDOW_SECONDS = 86_400
MIN_GATE_THRESHOLD = 0.0
MAX_GATE_THRESHOLD = 1.0


class PolicyBoundsError(ValueError):
    """策略取值越出允许区间（fail-closed）。

    区间边界是 forbidden 常量：收到本异常时应当修正策略取值，
    而不是试图放宽边界——边界修改只走人工 PR。
    """


def _fail(field_name: str, reason: str) -> "PolicyBoundsError":
    return PolicyBoundsError(f"EvolutionPolicy.{field_name}: {reason}")


def _isNumber(value: Any) -> bool:
    """bool 是 int 子类，先排除；只收有限数值。"""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _validateSourceWeights(weights: Any) -> None:
    if not isinstance(weights, dict):
        raise _fail("sourceWeights", f"必须是 dict，实为 {type(weights).__name__}")
    missing = [k for k in VALID_SOURCE_KEYS if k not in weights]
    if missing:
        raise _fail("sourceWeights", f"缺来源路 {missing}（三路 rsi/eval/external 必须齐）")
    extra = sorted(k for k in weights if k not in VALID_SOURCE_KEYS)
    if extra:
        raise _fail("sourceWeights", f"未知来源路 {extra}（合法 {list(VALID_SOURCE_KEYS)}）")
    total = 0.0
    for key in VALID_SOURCE_KEYS:
        value = weights[key]
        if not _isNumber(value):
            raise _fail("sourceWeights", f"{key} 权重必须是有限数值，实为 {value!r}")
        if value < 0.0 or value > 1.0:
            raise _fail("sourceWeights", f"{key} 权重越界 [0,1]：{value!r}")
        total += float(value)
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise _fail(
            "sourceWeights",
            f"三路权重和必须为 1，实为 {total!r}（各路 {dict(weights)}）",
        )


def _validateIntInRange(field_name: str, value: Any,
                        low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(field_name, f"必须是 int，实为 {value!r}")
    if value < low or value > high:
        raise _fail(field_name, f"越界 [{low}, {high}]：{value!r}")


def _validateGateThresholds(thresholds: Any) -> None:
    if thresholds is None:
        return
    if not isinstance(thresholds, dict):
        raise _fail("gateThresholds", f"必须是 dict 或 None，实为 {type(thresholds).__name__}")
    for gate, threshold in thresholds.items():
        if not isinstance(gate, str) or not gate:
            raise _fail("gateThresholds", f"门禁名必须是非空字符串，实为 {gate!r}")
        if not _isNumber(threshold):
            raise _fail("gateThresholds", f"{gate} 阈值必须是有限数值，实为 {threshold!r}")
        if threshold < MIN_GATE_THRESHOLD or threshold > MAX_GATE_THRESHOLD:
            raise _fail(
                "gateThresholds",
                f"{gate} 阈值越界 [{MIN_GATE_THRESHOLD}, {MAX_GATE_THRESHOLD}]：{threshold!r}",
            )


@dataclass(frozen=True)
class EvolutionPolicy:
    """一代演化的元层参数（可版本化、构造期域校验、实例不可变）。

    允许区间由模块级常量圈定（forbidden 语义）：越界在构造期即抛
    ``PolicyBoundsError``；``canaryWindow`` / ``gateThresholds`` 传 None
    表示"用治理设置"（覆盖语义，缺省不搬家）。
    """

    #: 候选来源权重：rsi / eval / external 三路，和为 1。
    sourceWeights: Dict[str, float] = field(
        default_factory=lambda: {k: 1 / 3 for k in VALID_SOURCE_KEYS})
    #: 每代 token 预算上限。
    maxTokensPerGeneration: int = 100_000
    #: 每代墙钟上限（毫秒）。
    maxWallMs: int = 60_000
    #: 影子验证并发度（1..4）。
    shadowConcurrency: int = 1
    #: 金丝雀观测窗（秒）；None = 用治理设置。
    canaryWindow: Optional[int] = None
    #: 各门禁阈值覆盖（门禁名 → 阈值，值域 [0,1]）；None = 用治理设置。
    gateThresholds: Optional[Dict[str, float]] = None

    def __post_init__(self):
        _validateSourceWeights(self.sourceWeights)
        _validateIntInRange(
            "maxTokensPerGeneration", self.maxTokensPerGeneration,
            MIN_MAX_TOKENS_PER_GENERATION, MAX_MAX_TOKENS_PER_GENERATION)
        _validateIntInRange("maxWallMs", self.maxWallMs,
                            MIN_MAX_WALL_MS, MAX_MAX_WALL_MS)
        _validateIntInRange("shadowConcurrency", self.shadowConcurrency,
                            MIN_SHADOW_CONCURRENCY, MAX_SHADOW_CONCURRENCY)
        if self.canaryWindow is not None:
            _validateIntInRange("canaryWindow", self.canaryWindow,
                                MIN_CANARY_WINDOW_SECONDS, MAX_CANARY_WINDOW_SECONDS)
        _validateGateThresholds(self.gateThresholds)
        # 冻结防御：dict 字段存副本，外部别名改不动已构造的策略。
        object.__setattr__(self, "sourceWeights", dict(self.sourceWeights))
        if self.gateThresholds is not None:
            object.__setattr__(self, "gateThresholds", dict(self.gateThresholds))

    @classmethod
    def default(cls) -> "EvolutionPolicy":
        """文档默认档（§3.7 / §6 P3-1 口径）：来源均分、预算保守、覆盖全交治理。"""
        return cls()

    def toDict(self) -> Dict[str, Any]:
        """可序列化载荷（台账落盘 / 读回的最小契约）。"""
        return {
            "sourceWeights": dict(self.sourceWeights),
            "maxTokensPerGeneration": int(self.maxTokensPerGeneration),
            "maxWallMs": int(self.maxWallMs),
            "shadowConcurrency": int(self.shadowConcurrency),
            "canaryWindow": None if self.canaryWindow is None else int(self.canaryWindow),
            "gateThresholds": None if self.gateThresholds is None else dict(self.gateThresholds),
        }

    @classmethod
    def fromDict(cls, payload: Dict[str, Any]) -> "EvolutionPolicy":
        """按台账载荷重建策略；缺键即拒（fail-closed，不猜默认）。"""
        if not isinstance(payload, dict):
            raise _fail("fromDict", f"载荷必须是 dict，实为 {type(payload).__name__}")
        required = (
            "sourceWeights", "maxTokensPerGeneration", "maxWallMs",
            "shadowConcurrency", "canaryWindow", "gateThresholds",
        )
        missing = [k for k in required if k not in payload]
        if missing:
            raise _fail("fromDict", f"载荷缺键 {missing}")
        return cls(
            sourceWeights=dict(payload["sourceWeights"]),
            maxTokensPerGeneration=payload["maxTokensPerGeneration"],
            maxWallMs=payload["maxWallMs"],
            shadowConcurrency=payload["shadowConcurrency"],
            canaryWindow=payload["canaryWindow"],
            gateThresholds=(
                None if payload["gateThresholds"] is None
                else dict(payload["gateThresholds"])
            ),
        )


class EvolutionPolicyLedger:
    """策略版本台账（沿 ImproverVersionLedger 范式）。

    - ``register(version, summary, policy)``：同号同摘要同策略 = 幂等；
      同号异摘要（或同号同摘要异策略）= 伪造，拒——调参入账要留证据链；
    - ``requireKnown(version)``：未注册版本号一律 KeyError——引用前先验真；
    - path=None ⇒ 纯内存账（env 未配置时零 IO）；配置后原子写、重启可读回。
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._memory: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def register(self, version: str, summary: str, policy: EvolutionPolicy) -> None:
        if not isinstance(policy, EvolutionPolicy):
            raise TypeError(
                f"policy 必须是 EvolutionPolicy，实为 {type(policy).__name__}"
                "——裸 dict 不许入账（域校验必须先过）")
        entry = {
            "version": str(version),
            "summary": str(summary),
            "policy": policy.toDict(),
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            existing = {e["version"]: e for e in self.readAll()}
            prior = existing.get(entry["version"])
            if prior is not None:
                if prior["summary"] != entry["summary"]:
                    raise ValueError(
                        f"策略版本 {entry['version']!r} 已以另一份摘要入账"
                        f"（旧: {prior['summary']!r} / 新: {entry['summary']!r}）——"
                        "同版本号改摘要即伪造，换版请起新版本号")
                if prior.get("policy") != entry["policy"]:
                    raise ValueError(
                        f"策略版本 {entry['version']!r} 摘要未变但参数变了"
                        "——同版本号改策略即伪造，换版请起新版本号")
                return  # 幂等重注册
            self._memory = list(existing.values()) + [entry]
            if self._path is None:
                return
            self._write(self._memory)

    def readAll(self) -> List[Dict[str, Any]]:
        if self._path is None:
            return list(self._memory)
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            versions = data.get("versions") if isinstance(data, dict) else None
            return list(versions) if isinstance(versions, list) else []
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("策略版本台账读取失败: %s", e)
            return []

    def requireKnown(self, version: str) -> None:
        """未注册的版本号一律被拒（引用伪造版本号的前置防线）。"""
        known = {e["version"] for e in self.readAll()}
        if str(version) not in known:
            raise KeyError(
                f"策略版本 {version!r} 未在台账注册——伪造版本号不许引用"
                f"（已注册：{sorted(known) or '无'}）")

    def latest(self) -> Optional[Dict[str, Any]]:
        """最新一条策略条目（按入账时间）；空账返回 None。"""
        entries = self.readAll()
        if not entries:
            return None
        return sorted(entries, key=lambda e: e.get("registered_at") or "")[-1]

    def _write(self, entries: List[Dict[str, Any]]) -> None:
        """原子写（tmp + os.replace），损坏配置不能污染已落盘账本。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"versions": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)


def resolve_policy_ledger() -> EvolutionPolicyLedger:
    """按 env 解析策略版本台账（与 ImproverVersionLedger 同款约定）。

    env ``NEUROVA_EVOLUTION_POLICY`` 未配置 ⇒ 纯内存账（注册/查询可用、零 IO）；
    配置 ⇒ 落盘账（原子写、跨进程可读回）。
    """
    env_path = os.environ.get(POLICY_LEDGER_ENV)
    return EvolutionPolicyLedger(Path(env_path)) if env_path else EvolutionPolicyLedger()
