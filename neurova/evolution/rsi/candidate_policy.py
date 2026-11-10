# -*- coding: utf-8 -*-
"""候选生成策略对象（A2，survey §10.2）——改进过程 I_t 的可版本化载体。

为什么抽对象而不是留在编排器内联：综述口径里"改进器更新"是递归的定义性核心，
而改进器要能升级、能配对比较、能冻结对照，前提是"候选怎么产生"是一个**可指认、
可版本化、可换入换出**的对象——散在编排器方法里的内联逻辑没有这个形态。
三个自由度收进本类：步进选择（STEP_RATIOS＋整数语义）、剪枝次序（三回调构造）、
打分公式（启发式/快评/方向+密封校验）。

`I_0` 是当前内联行为的**冻结复刻**：同输入下与抽取前的编排器逐值相等（判据
test_candidatePolicyI0 独立推导期望值钉住）。它一经注册进 `ImproverVersionLedger`
就是回归基线——"改着改着基线漂了"由逐值相等格拦住。

版本台账（improverVersionLedger）：I 版本号、变更摘要、生效时间，落盘可读回；
伪造版本号（requireKnown 未注册号）与同版本号改摘要一律被拒——升级要留证据链，
不留证据的"升级"不许入账（A5 的前置纪律）。
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate

logger = get_logger(__name__)

#: I_0 的版本号与变更摘要——冻结复刻的注册口径（同版本号改摘要会被台账拒绝）。
I_0_VERSION = "I_0"
I_0_SUMMARY = (
    "内联行为冻结复刻：setpoint 分级步进 [5/10/15/20%]＋整数语义，"
    "剪枝次序 粗筛(启发式)→中筛(快评)→细筛(方向+密封校验)，"
    "打分=expected_improvement-complexity/2、direction+sealed fail-closed"
)

#: 改进器版本台账的落盘路径 env（与负债账本 NEUROVA_RSI_RECEIPTS 同款约定）。
IMPROVER_LEDGER_ENV = "NEUROVA_RSI_IMPROVER_LEDGER"

_LEDGER_LOCK = threading.Lock()


class CandidatePolicy:
    """候选生成策略：步进选择 / 剪枝次序 / 打分公式 三个自由度的载体。

    依赖注入而非自取：setpoint 表、性能提取、密封校验都由装配方（编排器）传入——
    策略对象保持纯函数形态（同输入逐值相等可判），不背编排器的系统依赖。
    """

    def __init__(
        self,
        *,
        version: str,
        summary: str,
        setpoint_lookup: Callable[[str, str], Any],
        performance_extractor: Callable[[Dict[str, Any]], Optional[float]],
        sealed_validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]],
        excluded_ratios: Optional[List[float]] = None,
    ):
        self.version = str(version)
        self.summary = str(summary)
        self._setpointLookup = setpoint_lookup
        self._performanceExtractor = performance_extractor
        self._sealedValidator = sealed_validator
        # A5：本策略相对 I_0 剔除的步进档位（派生画像的证据随台账条目走）
        self._excludedRatios: List[float] = list(excluded_ratios or [])

    @classmethod
    def I_0(
        cls,
        *,
        setpoint_lookup: Callable[[str, str], Any],
        performance_extractor: Callable[[Dict[str, Any]], Optional[float]],
        sealed_validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]],
    ) -> "CandidatePolicy":
        """I_0 冻结复刻：与抽取前编排器内联行为逐值相等（判据钉住，不许漂）。"""
        return cls(
            version=I_0_VERSION,
            summary=I_0_SUMMARY,
            setpoint_lookup=setpoint_lookup,
            performance_extractor=performance_extractor,
            sealed_validator=sealed_validator,
        )

    # ── 自由度一：步进选择 ──

    def stepCandidates(self, system_name: str, param_name: str, current_value: Any,
                       signals: Dict[str, Any]) -> List[Candidate]:
        """为单个参数生成朝 setpoint 分级步进的候选（I_0＝原内联语义逐值复刻）。

        原语义逐条保留：非数值现值/未知 setpoint/已在 setpoint ⇒ 空列表；
        整数型参数保持整数语义；步进后与现值相等的档位剔除。
        """
        if current_value is None or not isinstance(current_value, (int, float)):
            return []

        setpoint = self._setpointLookup(system_name, param_name)
        if setpoint is None or not isinstance(setpoint, (int, float)):
            return []

        try:
            current_f = float(current_value)
            setpoint_f = float(setpoint)
        except (TypeError, ValueError):
            return []

        delta = setpoint_f - current_f
        if abs(delta) < 1e-9:
            return []  # 已在 setpoint

        performance = self._performanceExtractor(signals)

        candidates: List[Candidate] = []
        for ratio in self.STEP_RATIOS:
            new_value = current_f + delta * ratio
            # 整数型参数保持整数语义
            if isinstance(current_value, int):
                new_value = int(round(new_value))
            if new_value == current_f:
                continue

            optimization = {
                "system": system_name,
                "parameter": f"{system_name}.{param_name}",
                "current_value": current_value,
                "new_value": new_value,
                "performance": performance,
                "setpoint": setpoint_f,
                "reason": (
                    f"{param_name} 偏离 setpoint {setpoint_f}，"
                    f"调整 {current_f} → {new_value}（步进 {ratio*100:.0f}%）"
                ),
            }

            candidate = Candidate(
                id=f"{system_name}.{param_name}.{ratio}",
                name=f"{param_name}_toward_setpoint_{int(ratio*100)}pct",
                parameters={
                    "parameter": f"{system_name}.{param_name}",
                    "new_value": new_value,
                    "adjustment_ratio": ratio,
                },
                complexity=abs(new_value - current_f) / max(abs(current_f), 0.001),
                heuristic_score=1.0 - abs(ratio - 0.10) * 5,
                metadata={"optimization": optimization, "performance": performance},
            )
            candidates.append(candidate)

        return candidates

    #: 步进档位（I_0 冻结）：5/10/15/20%。I_t 升级时这里是第一个自由度。
    STEP_RATIOS: Tuple[float, ...] = (0.05, 0.10, 0.15, 0.20)

    @classmethod
    def derived(cls, *, base: "CandidatePolicy", excluded_ratios: List[float],
                failure_counts: Dict[str, int]) -> "CandidatePolicy":
        """A5 派生策略：I_{t+1}＝基线剔除占多数淘汰档（依赖注入同基线）。"""
        kept = tuple(r for r in base.STEP_RATIOS
                     if not any(abs(r - x) < 1e-9 for x in excluded_ratios))
        if not kept:
            raise ValueError("剔除后步进档位为空——不允许派生出无候选可产的策略")
        # 版本号内容式命名（T2）：同档数不同集合会碰撞（剔 {0.05} 与剔 {0.10}
        # 都曾是 "I_1drop"）——档位编进版本号，确定性且防伪（同号即同剔除集）。
        tier_tag = "_".join(str(int(round(r * 100))) for r in sorted(excluded_ratios))
        derived = cls(
            version=f"I_drop{tier_tag}",
            summary=(f"派生自 {base.version}：剔除淘汰占多数档 {excluded_ratios}"
                     f"（被拒分布 {failure_counts}）"),
            setpoint_lookup=base._setpointLookup,
            performance_extractor=base._performanceExtractor,
            sealed_validator=base._sealedValidator,
            excluded_ratios=list(excluded_ratios),
        )
        derived.STEP_RATIOS = kept  # 实例级覆盖：派生档位随画像走
        return derived

    def excludedRatios(self) -> List[float]:
        """本策略相对 I_0 剔除的档位（派生证据，随台账条目落账）。"""
        return list(self._excludedRatios)

    @classmethod
    def fromLedgerEntry(cls, entry: Dict[str, Any],
                        deps: Dict[str, Any]) -> "CandidatePolicy":
        """A5：按台账换版条目重建 I_t（台账即 policy_t 的事实源）。"""
        derivation = entry.get("derivation") or {}
        excluded = [float(r) for r in (derivation.get("ratios_excluded") or [])]
        policy = cls(
            version=str(entry["version"]),
            summary=str(entry.get("summary") or ""),
            setpoint_lookup=deps["setpoint_lookup"],
            performance_extractor=deps["performance_extractor"],
            sealed_validator=deps.get("sealed_validator"),
            excluded_ratios=excluded,
        )
        policy.STEP_RATIOS = tuple(
            r for r in cls.STEP_RATIOS
            if not any(abs(r - x) < 1e-9 for x in excluded)) or cls.STEP_RATIOS
        return policy

    # ── 自由度二＋三：剪枝次序与打分公式 ──

    def heuristicScore(self, candidate: Candidate) -> float:
        """粗筛打分（I_0＝候选自带的启发式分，原内联透传）。"""
        return candidate.heuristic_score

    def quickEvalScore(self, candidate: Candidate) -> float:
        """中筛快评（I_0＝原内联公式逐值复刻）：性能越低越值得动，扣复杂度代价。"""
        perf = candidate.metadata.get("performance", 0.5)
        adjustment = candidate.parameters.get("adjustment_ratio", 0.1)
        expected_improvement = (1.0 - perf) * adjustment * 10
        return expected_improvement - candidate.complexity * 0.5

    def validationResult(self, candidate: Candidate) -> Dict[str, Any]:
        """细筛校验（I_0＝方向门＋G1 密封档实跑，逐值复刻）。

        sealed_validator 未注入（直接构造/测试形态）时诚实降级为方向单源，
        sealed 格按 unevidenced 说出原因——不冒充完整校验。
        """
        opt = candidate.metadata.get("optimization", {})
        new_value = opt.get("new_value", 0)
        current = opt.get("current_value", 0)
        setpoint = opt.get("setpoint", None)
        # 候选由 stepCandidates 生成，已保证向 setpoint 方向步进。
        # 验证语义：值确实改变，且若已知 setpoint，调整方向必须朝 setpoint 靠近。
        # （此前用性能分 0.7/0.9 带宽做硬门，导致 0.7~0.9 死区里所有候选被拒，
        #   表现为"该优化的参数永远不被优化"。真正的棘轮门是应用后的实测增益 +
        #   回滚，此处的方向校验只负责排除反向调整。）
        direction_ok = new_value != current
        if (
            direction_ok
            and isinstance(setpoint, (int, float))
            and isinstance(new_value, (int, float))
            and isinstance(current, (int, float))
        ):
            toward = abs(float(setpoint) - float(new_value)) < abs(float(setpoint) - float(current))
            direction_ok = toward
        if not direction_ok:
            return {
                "valid": False,
                "score": 0.0,
                "details": f"current={current}, new={new_value}, setpoint={setpoint}",
            }
        if self._sealedValidator is None:
            return {
                "valid": True,
                "score": 1.0,
                "sealed": {"state": "unevidenced",
                           "reason": "策略对象未注入密封校验器（编排器装配外形态）"},
                "details": "direction ok, sealed=unevidenced（无校验器注入，降级方向单源）",
            }
        # G1 补实装：细筛的"完整验证"接 D1 密封档实跑——候选值代入活值快照
        # 推演（真实系统只读），塌方例（低于当前态）即 fail-closed 拒绝；
        # 密封档量不出时诚实降级为方向单源，原因随 details 出街。
        # 这是 A5 元优化候选在应用前的最后一道网：非数值等病值能漏过方向校验
        # （isinstance 门跳过 toward 检查），密封档实跑当场抓住。
        sealed = self._sealedValidator(opt)
        if sealed.get("state") == "measured":
            if sealed.get("regressions"):
                return {
                    "valid": False,
                    "score": 0.0,
                    "sealed": sealed,
                    "details": (
                        "direction ok but sealed regressions="
                        f"{sealed.get('regressions')} (score={sealed.get('score')}, "
                        f"baseline={sealed.get('baseline')})"
                    ),
                }
            return {
                "valid": True,
                "score": 1.0,
                "sealed": sealed,
                "details": f"direction ok, sealed score={sealed.get('score')}，无塌方例",
            }
        reason = sealed.get("reason") or ""
        return {
            "valid": True,
            "score": 1.0,
            "sealed": sealed,
            "details": (
                f"direction ok, sealed={sealed.get('state')}（密封档量不出，"
                "降级方向单源）" + (f": {reason}" if reason else "")
            ),
        }


class ImproverVersionLedger:
    """改进器版本台账（A2）：I 版本号 / 变更摘要 / 生效时间。

    - `register(version, summary)`：同版本号同摘要＝幂等；同版本号不同摘要＝拒
      （升级要留证据链，改摘要不换号就是伪造）；
    - `requireKnown(version)`：未注册的版本号一律被拒——换版入账的前置纪律（A5）；
    - path=None ⇒ 进程内账（单测零 IO 约定；env 未配置时注册/查询照常可用）。
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._memory: List[Dict[str, Any]] = []

    def register(self, version: str, summary: str) -> None:
        with _LEDGER_LOCK:
            existing = {e["version"]: e for e in self.readAll()}
            prior = existing.get(str(version))
            if prior is not None:
                if prior["summary"] != str(summary):
                    raise ValueError(
                        f"改进器版本 {version!r} 已以另一份摘要入账"
                        f"（旧: {prior['summary']!r} / 新: {summary!r}）——"
                        "同版本号改摘要即伪造，换版请起新版本号")
                return  # 幂等重注册
            entry = {
                "version": str(version),
                "summary": str(summary),
                "registered_at": datetime.now(UTC).isoformat(),
            }
            if self._path is None:
                self._memory.append(entry)
                return
            self._memory = list(existing.values()) + [entry]
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
            logger.warning("改进器版本台账读取失败: %s", e)
            return []

    def requireKnown(self, version: str) -> None:
        """未注册的版本号一律被拒（伪造版本号防线，A5 换版入账的前置）。"""
        known = {e["version"] for e in self.readAll()}
        if str(version) not in known:
            raise KeyError(
                f"改进器版本 {version!r} 未在台账注册——伪造版本号不许入账"
                f"（已注册：{sorted(known) or '无'}）")

    def register_upgraded_version(self, *, version: str, summary: str,
                                  derived_from: str, derivation: Dict[str, Any],
                                  probe_readout: Optional[Dict[str, Any]]) -> None:
        """A5 换版入账（提案 gate 的登记半）：无探针读数的换版**被拒**。

        - derived_from 必须是已注册版本（伪造派生来源被拒）；
        - probe_readout 必须是 measured 且带数值 Γ（insufficient_data/缺席
          ＝"升级了但没证据"，不许入账）；
        - 入账条目带 derived_from/derivation/probe_gamma/probe_state/approved_at
          ——"改进器变强"从此有据可查，构造期按最新条目重建 policy_t。
        """
        self.requireKnown(derived_from)
        if not isinstance(probe_readout, dict) or probe_readout.get("state") != "measured":
            raise ValueError(
                f"换版 {version!r} 无配对探针证据（probe_readout={probe_readout!r}）"
                "——'升级了但没证据'不许入账")
        gamma = probe_readout.get("score")
        if not isinstance(gamma, (int, float)):
            raise ValueError(f"配对探针 Γ 非数值（{gamma!r}）——无证据不许入账")
        with _LEDGER_LOCK:
            entry = {
                "version": str(version),
                "summary": str(summary),
                "registered_at": datetime.now(UTC).isoformat(),
                "derived_from": str(derived_from),
                "derivation": dict(derivation or {}),
                "probe_gamma": float(gamma),
                "probe_state": str(probe_readout.get("state")),
            }
            existing = {e["version"] for e in self.readAll()}
            self._memory = [e for e in self.readAll() if e["version"] != str(version)]
            self._memory.append(entry)
            if str(version) in existing:
                # 同版本重入账（重放形态）：覆盖旧条目，证据以最新一次为准
                pass
            if self._path is None:
                return
            self._write(self._memory)

    def latestUpgradedEntry(self) -> Optional[Dict[str, Any]]:
        """最新一条换版条目（构造期重建 policy_t 的事实源）；无则 None。"""
        upgraded = [e for e in self.readAll() if e.get("derived_from")]
        if not upgraded:
            return None
        return sorted(upgraded, key=lambda e: e.get("registered_at") or "")[-1]

    def _write(self, entries: List[Dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"versions": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def resolve_improver_ledger() -> ImproverVersionLedger:
    """按 env 解析改进器版本台账（与负债账本同款约定）。

    env 未配置 ⇒ 进程内账（注册/查询可用、不落盘）——装配注册 I_0 因此在任何
    进程都不缺席；env 配置 ⇒ 落盘账（跨进程可读回，判据走这一态）。
    """
    import os as _os

    env_path = _os.environ.get(IMPROVER_LEDGER_ENV)
    return ImproverVersionLedger(Path(env_path)) if env_path else ImproverVersionLedger()
