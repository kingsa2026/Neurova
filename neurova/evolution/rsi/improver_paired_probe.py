# -*- coding: utf-8 -*-
"""Eq8 配对探针 ImproverPairedProbe（A3，survey §10.2）——改进器质量的直接证据。

综述口径：改进器本身在变好（Eq8）需要配对证据——把 I_t 与 I_0 作用于**同一批
留出起始态**、**同预算**跑下游、比后继质量差 Γ_t(B)。这是"改进器变强"与
"任务系统变好"两个不同命题的分界线：本探针只量前者。

**隔离纪律**：探针是纯读数——不进 gain、不进回滚、不进收敛史、不进任何判定；
下游评估走**决策档**（harness.run），密封档永不进本探针（密封是最终验收证据，
探针读数经 A5 会变成升级证据链的一环——把密封喂进选择过程就是自适应污染）。

**两步走（学 task_yardstick 先例）**：本探针先做**观测档**——确定性、零 LLM、
重放式（同输入逐字节相等），下游评估用 harness 合成推演；真轨迹臂（A1 的
real_agent 面）与预算镜像（planRealArmTurns）属升判据档，等 A5 产出真实
I_t≠I_0 再挂载——现在就烧真回合只会给恒等策略配对出 Γ=0 的假证据。

**三态纪律**（与 task_yardstick 同款）：measured（score ∈ ℝ，Γ 带符号）/
insufficient_data（起始态或配对证据不足，score=None）/ unevidenced（双版本
缺席，说原因不空转）。
"""

from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.candidate_policy import CandidatePolicy
from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate
from neurova.evolution.rsi.task_yardstick import MIN_ENTRIES

logger = get_logger(__name__)

#: 起始态网格的确定性扰动档（I_0 冻结）：每个可优化数值参数 × 4 个相对偏移。
#: 命中 setpoint 的组合剔除（无候选可产），排序与档位固定 ⇒ 同输入同网格。
STARTING_STATE_OFFSETS = (-0.10, -0.05, 0.05, 0.10)

#: 单次探针的起始态上限（deterministic 切片，前 MIN_ENTRIES×2 个）——
#: get_status 每次轮询都会跑探针，网格封顶把读数成本钉在几十次 harness 推演内。
MAX_STARTING_STATES = MIN_ENTRIES * 2


class ImproverPairedProbe:
    """I_t vs I_0 的配对比较（纯读数，与主轨迹隔离）。"""

    def __init__(
        self,
        *,
        policy_t: Optional[CandidatePolicy],
        policy_0: Optional[CandidatePolicy],
        starting_states: Callable[[], List[Dict[str, Any]]],
        outcome_evaluator: Callable[[Dict[str, Any], Candidate], Optional[float]],
    ):
        """依赖注入：双版本策略、起始态供给（确定性）、下游结局评估（合成可控）。

        outcome_evaluator(state, candidate) → score 或 None（量不出＝该配对无证据）。
        """
        self._policyT = policy_t
        self._policy0 = policy_0
        self._startingStatesFn = starting_states
        self._outcomeEvaluator = outcome_evaluator

    #: E4 共同里程碑轴（评估序位）：两臂在同一序位上比质量。
    MILESTONES = (5, 10)

    def _qualityAtMilestones(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """共同里程碑轴上的质量读数（逐臂；缺臂点名，不空线冒充）。

        第 k 个里程碑 = 前 k 个配对的逐臂质量均值（评估按配对序累积，
        三臂各自 realized cost 即其里程碑轴）。
        """
        readout: Dict[str, Any] = {"axis": list(self.MILESTONES)}
        for name, keys in (("full", "quality_t"), ("frozen_I_0", "quality_0"),
                           ("no_update", "quality_no_update")):
            series = [p.get(keys) for p in pairs]
            at = {}
            for milestone in self.MILESTONES:
                prefix = [v for v in series[:milestone] if v is not None]
                if len(prefix) < milestone:
                    at[str(milestone)] = {
                        "state": "unevidenced",
                        "reason": f"{name} 臂在里程碑 {milestone} 缺样本"
                                  f"（有证据 {len(prefix)}/{milestone}）——不空线冒充",
                    }
                else:
                    at[str(milestone)] = {
                        "state": "measured",
                        "quality_mean": round(sum(prefix) / len(prefix), 6),
                    }
            readout[name] = at
        return readout

    def _startingStates(self) -> List[Dict[str, Any]]:
        return list(self._startingStatesFn() or [])

    def _bestCandidate(self, policy: CandidatePolicy,
                       state: Dict[str, Any]) -> Optional[Candidate]:
        """该策略在此起始态的自评最优候选（quickEvalScore 排序取首，确定性）。

        配对比较用各策略**自己的**偏好——比较的是"策略会怎么选"，不是统一裁判；
        完整剪枝序（粗→中→细）的臂扩展属 A4 双对照臂。
        排序计分异常按 0.0 参与排序——与剪枝中筛的异常计分同款纪律（快评公式对
        metadata 缺失/None 形态会抛，I_0 原样语义，计分侧兜住）。
        """
        candidates = policy.stepCandidates(
            state["system"], state["param"], state["current"], signals={})
        if not candidates:
            return None

        def _rankScore(candidate: Candidate) -> float:
            try:
                return policy.quickEvalScore(candidate)
            except Exception:  # noqa: BLE001 - 计分异常＝0 分参与排序（中筛同款）
                return 0.0

        return max(candidates, key=_rankScore)

    def run(self) -> Dict[str, Any]:
        """跑一次配对比较，返回三态读数（纯函数：同输入逐字节相等）。"""
        if self._policyT is None or self._policy0 is None:
            missing = []
            if self._policyT is None:
                missing.append("I_t")
            if self._policy0 is None:
                missing.append("I_0")
            return {
                "state": "unevidenced",
                "score": None,
                "reason": f"配对双版本缺席：{'/'.join(missing)} 未装配——探针不空转",
                "pairs": [],
                "arms": {},
                "realized_evaluations": 0,
            }

        states = self._startingStates()
        if len(states) < MIN_ENTRIES:
            return {
                "state": "insufficient_data",
                "score": None,
                "states": len(states),
                "detail": f"起始态 {len(states)} < {MIN_ENTRIES}（task_yardstick 先例），不产出读数",
                "pairs": [],
                "arms": {},
                "realized_evaluations": 0,
                "policy_versions": {
                    "t": self._policyT.version, "baseline": self._policy0.version},
            }

        pairs: List[Dict[str, Any]] = []
        gammas: List[float] = []
        evaluations = 0
        # A4 双对照臂的逐臂计账：全循环（I_t 候选）/ 冻结 I_0（基线候选）/
        # 无持久更新（推理时搜索不落盘——基线质量，candidate=None 形态）。
        # 三臂同起始态同评估器，帽＝起始态数，隔离的变量只有"改进器贡献"。
        arm_counts = {"full": 0, "frozen_I_0": 0, "no_update": 0}
        arm_qualities: Dict[str, List[float]] = {"full": [], "frozen_I_0": [], "no_update": []}
        for state in states:
            best_t = self._bestCandidate(self._policyT, state)
            best_0 = self._bestCandidate(self._policy0, state)
            # 无更新臂恒评一次（candidate=None → 基线质量），与候选有无无关——
            # 这是它作为对照的形态：策略怎么换它都不动（变异格钉住）。
            evaluations += 1
            arm_counts["no_update"] += 1
            quality_none = self._outcomeEvaluator(state, None)
            if quality_none is not None:
                arm_qualities["no_update"].append(quality_none)
            if best_t is None and best_0 is None:
                pairs.append({
                    "state": f"{state['system']}.{state['param']}@{state['current']}",
                    "candidate_t": None,
                    "candidate_0": None,
                    "quality_t": None,
                    "quality_0": None,
                    "quality_no_update": quality_none,
                    "gamma": None,
                })
                continue  # 双方都无候选：配对无比较意义，无更新臂已计账
            quality_t: Optional[float] = None
            quality_0: Optional[float] = None
            if best_t is not None:
                evaluations += 1
                arm_counts["full"] += 1
                quality_t = self._outcomeEvaluator(state, best_t)
                if quality_t is not None:
                    arm_qualities["full"].append(quality_t)
            if best_0 is not None:
                evaluations += 1
                arm_counts["frozen_I_0"] += 1
                quality_0 = self._outcomeEvaluator(state, best_0)
                if quality_0 is not None:
                    arm_qualities["frozen_I_0"].append(quality_0)
            pair_gamma: Optional[float] = None
            if quality_t is not None and quality_0 is not None:
                pair_gamma = quality_t - quality_0
                gammas.append(pair_gamma)
            pairs.append({
                "state": f"{state['system']}.{state['param']}@{state['current']}",
                "candidate_t": best_t.metadata["optimization"]["new_value"] if best_t else None,
                "candidate_0": best_0.metadata["optimization"]["new_value"] if best_0 else None,
                "quality_t": quality_t,
                "quality_0": quality_0,
                "quality_no_update": quality_none,
                "gamma": pair_gamma,
            })

        arms = {
            name: {
                "realized": arm_counts[name],
                "quality_mean": (
                    round(sum(qs) / len(qs), 6) if qs else None),
                "evidenced": len(qs),
            }
            for name, qs in arm_qualities.items()
        }
        # C3 净接线：逐对分类走 ab_library 共享聚合（improved/regressed 与
        # 冷热 A/B 的 fixed/broken 同判据同机器，不自带第二套）。
        from neurova.evolution.eval.ab_library import classifyPairwise

        classification = classifyPairwise(
            [p["quality_0"] for p in pairs],
            [p["quality_t"] for p in pairs],
            [p["state"] for p in pairs],
        )
        arms["full"]["improved"] = classification["improved"]
        arms["full"]["regressed"] = classification["regressed"]
        # E4 质量@成本里程碑：共同里程碑轴（评估序位 5/10）上的逐臂质量均值——
        # 替代"只看终点分"；里程碑超出容量时点名缺哪个臂（不得空线冒充）。
        # 同级读数（非臂键——A4 的 arms 键集语义不变）。
        milestones = self._qualityAtMilestones(pairs)

        if not gammas:
            return {
                "state": "insufficient_data",
                "score": None,
                "states": len(states),
                "detail": "全部配对无下游证据（候选缺席或结局量不出），不产出 Γ",
                "pairs": pairs,
                "arms": arms,
                "quality_at_milestones": milestones,
                "realized_evaluations": evaluations,
                "policy_versions": {
                    "t": self._policyT.version, "baseline": self._policy0.version},
            }

        gamma = sum(gammas) / len(gammas)
        return {
            "state": "measured",
            "score": round(gamma, 6),
            "states": len(states),
            "evidenced_pairs": len(gammas),
            "pairs": pairs,
            "arms": arms,
            "quality_at_milestones": milestones,
            "realized_evaluations": evaluations,
            "policy_versions": {
                "t": self._policyT.version, "baseline": self._policy0.version},
            "detail": (
                f"Γ_t(B)={gamma:.4f}（{len(gammas)} 对下游质量差均值，带符号；"
                "观测档：harness 合成推演，真轨迹臂属升判据档）"
            ),
        }
