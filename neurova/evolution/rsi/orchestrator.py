"""
RSI 编排器

协调 RSI 迭代的执行，包括：
- 从四大闭环系统收集反馈信号
- 生成优化建议
- 应用优化
- 监控收敛性
- 管理回滚和部署
"""

from neurova.core.logger import get_logger
from neurova.skills.library_service import agentLibrary
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .convergence_analyzer import (
    STATE_CONVERGED,
    STATE_MEASUREMENT_BLIND,
    create_convergence_analyzer,
)
from .gate_verdict import GateVerdict

from .deployment_controller import (
    create_deployment_controller,
    create_deployment_controller_with_settings,
)
from .integration_manager import create_rsi_integration_manager
from .metrics import RSIMetrics, create_rsi_metrics
from .recursive_ratchet_pruner import RecursiveRatchetPruner, Candidate
from .debt_ledger import DebtVerdict, resolve_debt_ledger
from .rollback_manager import create_rollback_manager, resolve_rollback_state_path
from .self_improvement_proposer import SelfImprovementProposer, ProposalType
from .system_performance import get_setpoint
from neurova.security.governance_settings import rsiPhaseSourceFor

logger = get_logger(__name__)


def usageTokensDelta(before: int, after: int) -> int:
    """E1：usage 单源的 token 差分（iterative 期间的真实消耗）。

    负差分（记账面被清/换进程）不出负数——按 0 处理，不产假成本；
    计数取自 `usage_accounting.snapshot()`（身份上下文按 sender 计的那套），
    不新建第二套 token 计数（教义第 6 条）。
    """
    try:
        delta = int(after) - int(before)
    except (TypeError, ValueError):
        return 0
    return delta if delta > 0 else 0

#: 一次参数动作的代价（与 `convergence_analyzer.record_iteration(cost=1.0)`
#: 同一计量单位，单源引用，不新造第二个尺度）。
_PARAM_ACTION_COST = 1


@dataclass(frozen=True)
class IterationCadence:
    """派发层的速度指令：`mode` 决定跑不跑，`basis`/`evidence` 说明凭什么。

    工单 008：裸字符串 "backoff" 说不清"卡在哪个判据、依据什么读数"，
    SKIPPED 措辞就只能写"降频了"——与它要取代的静默降级只差一层表述。
    降频是"这一阵少跑"，不是"进化结束"，所以每次跳过都得带着可核对的依据。
    """

    mode: str
    basis: str
    evidence: str


def _carries_no_evidence(signals: Dict[str, Any]) -> bool:
    """该系统反馈是否被标为无证据（缺席闭环系统的占位替身，工单 018）。

    无证据者一律不参与读数与判据 —— 兜底性能均值、人工升级通道都按此排除，
    否则"对不存在的系统算出一个性能分"会换个入口继续存在。
    """
    verdict = signals.get("verdict")
    return isinstance(verdict, dict) and verdict.get("state") == GateVerdict.STATE_UNEVIDENCED


def assertRsiOptimizationIdentity(optimizations: List[Dict[str, Any]]) -> None:
    """参数轮账实前置：每条优化必须有唯一参数名。"""
    parameters = [str(item.get("parameter") or "") for item in optimizations]
    missing = [index for index, name in enumerate(parameters) if not name]
    if missing:
        raise AssertionError(f"RSI 优化项缺参数名，位置={missing}")
    duplicates = sorted({name for name in parameters if parameters.count(name) > 1})
    if duplicates:
        raise AssertionError(f"RSI 同一参数出现多条优化，参数={duplicates}")


def assertRsiRoundIdentity(
    optimizations: List[Dict[str, Any]], applied_results: List[Dict[str, Any]]
) -> None:
    """参数轮账实后置：一参数一结果的条数必须相等。"""
    if len(applied_results) != len(optimizations):
        raise AssertionError(
            "RSI 参数账实不符："
            f"optimizations={len(optimizations)}, applied_results={len(applied_results)}"
        )


def _e2e_gain_from_evals(eval_before: Any, eval_after: Any) -> Optional[float]:
    """P1-2:e2e 标尺的并列增益读数。

    两侧都 ``measured`` 才有值;任一侧缺读数/未量出 → None —— 诚实三态,
    不得兜底 0.0(与 gain 的 evidence 门同一口径)。
    """
    before = eval_before.get("e2e") if isinstance(eval_before, dict) else None
    after = eval_after.get("e2e") if isinstance(eval_after, dict) else None
    if not (isinstance(before, dict) and isinstance(after, dict)):
        return None
    if before.get("state") != "measured" or after.get("state") != "measured":
        return None
    b, a = before.get("score"), after.get("score")
    if b is None or a is None:
        return None
    return round(float(a) - float(b), 6)


#: 族级归因的状态词汇——四态不可折叠（与 `parameter_activity` 的
#: `never_proposed ≠ sparse ≠ no_data` 同族纪律：折叠会把相反的事读成同一件事）。
_FAMILY_ACTED = "acted"
_FAMILY_PROPOSED_NOT_APPLIED = "proposed_not_applied"
_FAMILY_NO_CANDIDATE = "no_candidate"
_FAMILY_PLACEHOLDER_HOST = "placeholder_host"


def familyAttribution(
    optimizations: List[Dict[str, Any]],
    appliedResults: List[Dict[str, Any]],
    *,
    tableFamilies: List[str],
    placeholderSystems: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """把"这一轮到底动了哪几族"按参数族拆开，随观测面同行——**只拆账，不拆增益**。

    为什么要这格：一轮 RSI 是**联合动作**——`generate_optimizations()` 对每个参数各选
    1 个候选，`apply_optimizations()` 全量应用，然后**一次** `perf_after - perf_before`、
    **一次**整轮回滚（见 `run_iteration` 的应用段）。提名按参数、判定与回滚按整轮，
    于是"这轮涨了/跌了"永远回答不了"是哪一族动的"，而返回体里只留着
    `optimizations` 与 `applied_results` 两个平铺列表，要靠人现场对表。

    为什么**不**按族拆 gain：本仓一轮只有一次读数，按族摊就是造归因。
    `gain_scope` 因此恒为 `"round"`，这一格是写给后来人的边界，不是待办。

    为什么不拆轮（拆成每族一轮才是外部论据里的"模块化演化"）：真账里 11 个参数只有
    7 个出现过、4 个 `never_proposed`（`parameter_activity` 的实测），拆轮会让多数轮次
    在无数据上空转，且每轮都要再付一次评测成本。读数先立住，拆不拆轮是读数稳定之后的事。

    参数表之外的 `system` 不会进本读数：候选只从 `get_optimizable_parameters()` 生成
    （`generate_optimizations` 逐族逐参遍历），所以这里不另立第二份族清单。
    """
    placeholders = set(placeholderSystems or [])
    byFamily: Dict[str, Dict[str, Any]] = {
        family: {"proposed": 0, "applied": 0, "params": []} for family in tableFamilies
    }
    appliedByParam = {
        str(item.get("parameter")): bool(item.get("applied"))
        for item in (appliedResults or [])
        if item.get("parameter")
    }

    for optimization in optimizations or []:
        family = optimization.get("system")
        row = byFamily.get(family)
        if row is None:
            continue
        parameter = optimization.get("parameter")
        applied = bool(appliedByParam.get(str(parameter), False))
        row["proposed"] += 1
        row["applied"] += 1 if applied else 0
        row["params"].append({
            "parameter": parameter,
            "from": optimization.get("current_value"),
            "to": optimization.get("new_value"),
            "applied": applied,
        })

    for family, row in byFamily.items():
        if row["applied"]:
            row["status"] = _FAMILY_ACTED
        elif row["proposed"]:
            # 有提名却一件没落地：被反向闸/阶段闸拦下，或应用本身失败——
            # 与"这族压根没候选"是相反的事，不许折叠。
            row["status"] = _FAMILY_PROPOSED_NOT_APPLIED
        elif family in placeholders:
            row["status"] = _FAMILY_PLACEHOLDER_HOST
        else:
            row["status"] = _FAMILY_NO_CANDIDATE

    return {"by_family": byFamily, "gain_scope": "round"}


def _ratchet_candidates_from_settings() -> list:
    """棘轮每轮候选数从 evolution_settings 读(§6-3 收口 2026-10-06)。

    原为硬编码 [50,10,3];合法性(正整数、非空、有界)由 load_settings 的
    类型收敛统一保证,这里不再兜第二层默认(单一事实源)。
    """
    from neurova.evolution.evolution_settings import load_settings

    return list(load_settings().rsi_ratchet_candidates)


class RSIOrchestrator:
    """
    RSI 编排器 - 协调递归自我改进的完整流程

    职责：
    1. 协调四大闭环系统（睡眠、情感、经验、工具记忆）
    2. 执行 RSI 迭代
    3. 监控收敛性
    4. 管理回滚和部署
    """

    def __init__(
        self,
        sleep_system: Any,
        emotion_system: Any,
        experience_system: Any,
        tool_memory_system: Any,
        agent_id: str = "default",
        **kwargs,
    ):
        """
        初始化 RSI 编排器

        Args:
            agent_id: 本编排器服务的 agent。提案台账与"批准即生效"都按它落到
                正确的技能库上（工单 010）；单 agent 部署沿用 "default" 这个
                既有约定，多 agent 部署必须显式传，否则各 agent 的提案共一桶。
            sleep_system: 睡眠闭环系统
            emotion_system: 情感闭环系统
            experience_system: 经验闭环系统
            tool_memory_system: 工具记忆闭环系统
        """
        # 归属先定（G2）：部署控制器按本 agent 的相位解析装配，agent_id 必须
        # 先于控制器存在——覆写条目按 agent_id 命中，顺序颠倒就是全员吃全局。
        self.agent_id = str(agent_id or "default")
        # 创建集成管理器
        # 上下文经济性宿主（004 M2）：预算对象在生产由 `TokenBudget()` 默认构造
        # （`context/orchestrator.py` 两处装配点亦如此），故此处同源取默认构造；
        # 宿主缺席时 `context` 族在源头返回空参数列表。
        context_system = kwargs.pop("context_system", None)
        if context_system is None:
            try:
                from neurova.context.models import TokenBudget

                context_system = TokenBudget()
            except Exception as e:  # noqa: BLE001 - 宿主不可用即缺席，不猜
                logger.debug("上下文经济性宿主不可用: %s", e)
        self.integration_manager = create_rsi_integration_manager(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
            context_system=context_system,
        )

        # 创建收敛性分析器
        self.convergence_analyzer = create_convergence_analyzer()

        # 候选生成策略（A2）：三个自由度（步进/剪枝次序/打分）收进 CandidatePolicy，
        # I_0＝内联行为冻结复刻（同输入逐值相等）；构造即注册进版本台账——
        # "改进器"从此是可版本化对象，A5 换版与 A3 配对探针的地基。
        # A5：台账即 policy_t 的事实源——最新已批准+有证据的换版条目在构造期
        # 重建 I_t（步进档位剔除形），无换版条目回退 I_0。
        from .candidate_policy import I_0_SUMMARY, I_0_VERSION, CandidatePolicy
        from .system_performance import get_setpoint

        _policy_deps = dict(
            setpoint_lookup=get_setpoint,
            performance_extractor=self._extract_performance,
            sealed_validator=self._sealedCandidateValidation,
        )
        self._candidate_policy = CandidatePolicy.I_0(**_policy_deps)
        try:
            from .candidate_policy import resolve_improver_ledger

            _ledger = resolve_improver_ledger()
            _ledger.register(I_0_VERSION, I_0_SUMMARY)
            _upgraded = _ledger.latestUpgradedEntry()
            if _upgraded is not None:
                self._candidate_policy = CandidatePolicy.fromLedgerEntry(
                    _upgraded, _policy_deps)
                logger.info(
                    "I_t 按台账重建：%s（derived_from=%s，probe_gamma=%s）",
                    _upgraded["version"], _upgraded.get("derived_from"),
                    _upgraded.get("probe_gamma"),
                )
        except Exception as e:  # noqa: BLE001 - 台账故障不阻断装配，读数如实告警
            logger.warning("改进器版本台账装配失败（回退 I_0）: %s", e)

        # Eq8 配对探针（A3）：I_t 与 I_0 同起始态同预算配对比较，纯读数与主轨迹隔离。
        # policy_0 恒为独立 I_0 复刻（A5 换版后它是冻结对照臂）；policy_t 即当前策略。
        from .improver_paired_probe import ImproverPairedProbe

        def _i0Replica() -> CandidatePolicy:
            return CandidatePolicy.I_0(
                setpoint_lookup=get_setpoint,
                performance_extractor=self._extract_performance,
                sealed_validator=self._sealedCandidateValidation,
            )

        self._candidate_policy_i0_factory = _i0Replica
        self._paired_probe = ImproverPairedProbe(
            policy_t=self._candidate_policy,
            policy_0=_i0Replica(),
            starting_states=self._probeStartingStates,
            outcome_evaluator=self._probeOutcome,
        )

        # 创建监控指标管理器
        self.metrics = create_rsi_metrics()

        # 创建回滚管理器
        self.rollback_manager = create_rollback_manager()
        # 工单 004：晋升判据看的是真实日历时间，回滚历史与装配时刻必须跨重启存活。
        # 未配置 NEUROVA_EVOLUTION_ROLLBACK 时零 IO 副作用（挂载点在此而非
        # bootstrap_evolution_persistence —— bootstrap 早于 per-agent 构造）。
        rollback_state_path = resolve_rollback_state_path()
        if rollback_state_path is not None:
            self.rollback_manager.attach_persistence(rollback_state_path)
            if not self.rollback_manager.load(rollback_state_path):
                # 首次启动：立刻把装配时刻钉到盘上。否则每次重启都重置成"现在"，
                # "7 天无回滚"这条判据在任何跨重启的部署里永远累计不满。
                self.rollback_manager.save()

        # 负债账本（Issue #289 · 003）：长在**同一份** `rsi_receipts.jsonl` 上 ——
        # 单一事实源，不新增第二份账本文件。未配置 env 时零 IO（与回执同款约定）。
        self.debt_ledger = resolve_debt_ledger()

        # 创建部署控制器（治理遗留收口：rsi_phase 来自治理设置，默认 0 观察期）
        try:
            from neurova.security.governance_settings import load_governance_settings

            # G2 覆写路线：相位按本 agent 解析（overrides 命中即覆写值，否则全局）
            self.deployment_controller = create_deployment_controller_with_settings(
                load_governance_settings(), agent_id=self.agent_id
            )
        except Exception as e:  # noqa: BLE001 - 设置不可用时维持默认观察期
            logger.warning("部署控制器按治理设置初始化失败，回退默认: %s", e)
            self.deployment_controller = create_deployment_controller()

        # 阶段推进/不晋升的证据时间线（回滚历史 + 装配时刻）由 rollback_manager
        # 唯一持有并持久化，此处不再留第二份起算点。

        # 创建递归棘轮剪枝器（P0-A1 修复：接入核心算法）
        # 用于在多个候选优化方案中通过"粗筛→中筛→细筛"选出最优
        # §6-3：候选数/轮数来自 evolution_settings（rsi_ratchet_candidates，
        # 默认 [50,10,3] 与原硬编码一致）
        candidates = _ratchet_candidates_from_settings()
        self.pruner = RecursiveRatchetPruner(
            rounds=len(candidates),
            candidates_per_round=candidates,
        )

        # P0-A3 修复：接入 SelfImprovementProposer
        # 当自动参数调整失效（convergence=diverging/oscillating with negative trend）时，
        # 升级到人工评审提案路径（skill_manifest/action_definition/pr_patch）。
        # 这是"渐进式自我改进"的中高风险通道，所有提案保持 PENDING 等待人工 approve_and_apply。
        # 工单 005：阶段与回滚历史必须与编排器同一份。此前这里裸构造，proposer 自带
        # 一个 phase=0 的控制器 ⇒ medium/high 提案的门禁看的是那个私有阶段，
        # 管理员在前端调 `rsi_phase` 对这条通道完全无效。
        # 归属先定：proposer 的台账与"批准即生效"都按它落到正确的技能库（工单 010）；
        # agent_id 已在装配最前定好（G2 相位覆写按它命中）。
        self.self_improvement_proposer = SelfImprovementProposer(
            agent_id=self.agent_id,
            deployment_controller=self.deployment_controller,
            rollback_manager=self.rollback_manager,
        )

        # 迭代计数器
        self._iteration_count = 0
        # D2 审计预定表：序列启动前预定（步长固定落盘），事后审计只读预定时刻
        from .audit_schedule import resolve_audit_schedule

        self._audit_schedule = resolve_audit_schedule()
        # 工单 012：`RSI_GATE_FAILURES` 吃的是"连续被硬否决"的轮数（通过即归零），
        # 而 `get_status()` 要能答"最近一轮晋升判据说了什么"，故把最近结论留在实例上。
        self._consecutive_gate_failures = 0
        self._last_phase_outcome: Dict[str, Any] = {}
        # 工单 009：升级通道走没走过、为什么没走，也要能从状态面读到
        self._last_escalation: Dict[str, Any] = {}
        # 003：反向闸最近一轮拦没拦、为什么拦（同一条"没做也要说得出为什么"的纪律）
        self._last_debt_gate: Dict[str, Any] = {}
        # E1/E2：最近一轮的资源向量（None=本轮未进应用段，无成本可记）
        self._last_cost_vector: Optional[Dict[str, Any]] = None
        # C5 纵报四格：最近一次回滚的恢复成本（None=无回滚）＋滚动接受统计
        self._last_recovery: Optional[Dict[str, Any]] = None
        self._attempts_total = 0
        self._applied_total = 0
        # F1 外部对照：逐轮成对采集（代理分, e2e 参考分）——setpoint 贴近度
        # 代理的滚动相关性呈报（观测档：参考=e2e 对齐；golden 臂评分属升判据档）
        self._proxyReferencePairs: List[Dict[str, Any]] = []

        # 端到端评测集（Auto Harness：gain 的统一度量，懒加载）
        self._eval_harness: Optional[Any] = None
        self._last_eval_outcome: Optional[Dict[str, Any]] = None
        # 密封档验收证据（D1）：决策（应用/回滚）落定后读一次，随 get_status 呈报。
        self._last_sealed_evidence: Optional[Dict[str, Any]] = None

        logger.info("RSIOrchestrator initialized")

    #: RSI gain 置信区间的 z 值（B3）：≈97.5% 单侧置信，口径镜像
    #: eval/config.EvolutionConfig.noise_z 的出厂值（两侧机器各自独立调参，
    #: 不互相引用——文本侧校准带与 RSI 例级 CI 是两种噪声形态）。
    RSI_GAIN_CI_Z = 2.0

    def _pairedGainCI(self, eval_before: Any, eval_after: Any) -> Optional[Dict[str, Any]]:
        """应用前后决策档的**配对例级 CI**（B3）：gain 的抽样不确定度。

        决策档 6 例是行为空间的样本——例级差分（after−before 逐例配对）的
        均值±z·se 就是本轮 gain 的置信区间。确定性 harness 的诚实退化：
        无差异 ⇒ sd=0 ⇒ 带宽 0（CI 退化为点值，如实报窄带）。
        任一侧非 measured 或用例失配 ⇒ None（CI 缺席，回滚判据回退点规则）。
        """
        import statistics as _st

        try:
            if not isinstance(eval_before, dict) or not isinstance(eval_after, dict):
                return None
            if eval_before.get("state") != "measured" or eval_after.get("state") != "measured":
                return None
            before_by_id = {c.get("id"): c.get("score")
                            for c in (eval_before.get("cases") or [])}
            deltas: List[float] = []
            for c in (eval_after.get("cases") or []):
                base = before_by_id.get(c.get("id"))
                score = c.get("score")
                if base is None or score is None:
                    continue
                deltas.append(float(score) - float(base))
            if not deltas:
                return None
            n = len(deltas)
            mean = sum(deltas) / n
            sd = _st.stdev(deltas) if n > 1 else 0.0
            se = sd / (n ** 0.5) if n > 1 else 0.0
            half = self.RSI_GAIN_CI_Z * se
            return {
                "mean": round(mean, 6),
                "sd": round(sd, 6),
                "n": n,
                "lower": round(mean - half, 6),
                "upper": round(mean + half, 6),
                "z": self.RSI_GAIN_CI_Z,
            }
        except Exception as e:  # noqa: BLE001 - CI 现算失败＝缺席，不阻断主链
            logger.debug("gain 配对 CI 现算失败: %s", e)
            return None

    def _caseRegressionMetrics(self, eval_before: Any, eval_after: Any) -> Dict[str, Any]:
        """跨轮回放门的例级读数（C1）：经文本侧共享判据机器出退化清单。

        判据机器**接线不并造**（教义第 6 条）：`eval.runner._caseRegressionReadout`
        是 P1-A 成果、probeCaseLevelGate 的同一判据形态——RSI 侧只做形状适配
        （决策档 {id, score} → 判据机器的 {baseline, candidate, failed} 形状）。
        任一侧非 measured ⇒ 空清单（例级门无量不出形态，不冒充通过）。
        """
        try:
            from neurova.evolution.eval.runner import _caseRegressionReadout

            if (not isinstance(eval_before, dict) or not isinstance(eval_after, dict)
                    or eval_before.get("state") != "measured"
                    or eval_after.get("state") != "measured"):
                return {"case_regressions": [], "case_unevidenced": []}
            before_by_id = {c.get("id"): c.get("score")
                            for c in (eval_before.get("cases") or [])}
            case_scores = {}
            for c in (eval_after.get("cases") or []):
                base = before_by_id.get(c.get("id"))
                score = c.get("score")
                if base is None or score is None:
                    continue
                case_scores[c["id"]] = {
                    "baseline": base, "candidate": score,
                    "baseline_failed": False, "candidate_failed": False,
                }
            regressions, unevidenced = _caseRegressionReadout(case_scores)
            return {"case_regressions": regressions, "case_unevidenced": unevidenced}
        except Exception as e:  # noqa: BLE001 - 例级门故障＝缺席，不阻断主链
            logger.debug("跨轮回放门例级读数失败: %s", e)
            return {"case_regressions": [], "case_unevidenced": []}

    def _pairedE2EGain(self, eval_before: Any, eval_after: Any) -> Optional[float]:
        """真实结局对齐差分（B1）：前后两次 yardstick 读数的差。

        双方都 measured ⇒ after − before（带符号，确定性重放无采样噪声）；
        任一侧缺席（insufficient_data/未暴露窗口）⇒ None（读数缺省不参与判据）。
        """
        try:
            if not isinstance(eval_before, dict) or not isinstance(eval_after, dict):
                return None
            e2e_before = eval_before.get("e2e")
            e2e_after = eval_after.get("e2e")
            if not isinstance(e2e_before, dict) or not isinstance(e2e_after, dict):
                return None
            if e2e_before.get("state") != "measured" or e2e_after.get("state") != "measured":
                return None
            before_score = e2e_before.get("score")
            after_score = e2e_after.get("score")
            if not isinstance(before_score, (int, float)) or not isinstance(after_score, (int, float)):
                return None
            return round(float(after_score) - float(before_score), 6)
        except Exception as e:  # noqa: BLE001 - 差分失败＝缺席，不阻断主链
            logger.debug("e2e 对齐差分现算失败: %s", e)
            return None

    def _recordProxyReferencePair(self, proxy: float, reference: float) -> None:
        """F1 成对采集：代理分 × 外部参考分（观测档参考=e2e 对齐分）。

        窗口封顶（rollingCorrelation.WINDOW）——相关性是滚动读数不是全史账。
        """
        from .proxy_reference import WINDOW

        self._proxyReferencePairs.append(
            {"proxy": float(proxy), "reference": float(reference)})
        if len(self._proxyReferencePairs) > WINDOW:
            self._proxyReferencePairs = self._proxyReferencePairs[-WINDOW:]

    def _transferReadout(self) -> Dict[str, Any]:
        """C4 迁移读数（观测档）：结局窗口时间分半当两域（旧域 vs 近域）重放差值。

        golden 臂域待 B2 通道出真结局后接入（完整两轴随真臂机器挂载）。
        """
        try:
            from .transfer_readout import splitWindowDomains, transferReadout

            weights = self.integration_manager._systems.get("tool_memory")
            inner = getattr(weights, "tool_weights", weights)
            streams_fn = getattr(inner, "outcome_streams", None)
            if not callable(streams_fn):
                return {"state": "unevidenced", "reason": "权重对象未暴露结局窗口"}
            split = splitWindowDomains(streams_fn())
            if split is None:
                return {"state": "insufficient_data", "score": None,
                        "detail": "结局窗口不足以分半"}
            return transferReadout(split["a"], split["b"],
                                   label_a="older", label_b="recent")
        except Exception as e:  # noqa: BLE001 - 迁移读侧故障不阻断状态面
            logger.debug("迁移读侧失败: %s", e)
            return {"state": "unevidenced", "reason": str(e)}

    def _coverageReadout(self) -> Dict[str, Any]:
        """H1 覆盖矩阵：近期评测实际触达的族（eval outcome 的 case family 列）。"""
        try:
            from .coverage import coverageReadout

            outcome = self._last_eval_outcome
            families = []
            if isinstance(outcome, dict):
                families = [c.get("family") for c in (outcome.get("cases") or [])
                            if c.get("family")]
            return coverageReadout(families)
        except Exception as e:  # noqa: BLE001 - 覆盖读侧故障不阻断状态面
            logger.debug("覆盖读侧失败: %s", e)
            return {"state": "unevidenced", "reason": str(e)}

    def _proxyReferenceReadout(self) -> Dict[str, Any]:
        """F1 读数：滚动相关性（代理独自粉饰在这里现形）。"""
        from .proxy_reference import rollingCorrelation

        pairs = self._proxyReferencePairs
        proxy_series = [p["proxy"] for p in pairs]
        reference_series = [p["reference"] for p in pairs]
        readout = rollingCorrelation(proxy_series, reference_series)
        readout["channel"] = "e2e_alignment（观测档）"
        return readout

    def _checkpointColumns(self) -> Dict[str, Any]:
        """C5 纵报四格：接受率/新成功/回归/恢复成本（D2 预定时刻进台账）。

        缺格如实点名（recovery None = 无回滚发生，不是 0 成本）。
        """
        case_metrics = (self._last_eval_outcome or {}) if isinstance(
            self._last_eval_outcome, dict) else {}
        regressions = case_metrics.get("case_regressions")
        new_successes = case_metrics.get("case_unevidenced")
        acceptance_rate = (self._applied_total / self._attempts_total
                           if self._attempts_total else None)
        return {
            "acceptance_rate": (round(acceptance_rate, 4)
                                if acceptance_rate is not None else None),
            "new_successes": new_successes,
            "regressions": regressions,
            "recovery_cost": self._last_recovery,
            "missing": [k for k, v in {
                "acceptance_rate": acceptance_rate,
                "recovery_cost": self._last_recovery,
            }.items() if v is None],
        }

    def _iterationCostVector(self, *, wall_ms: int, tokens_delta: int) -> Dict[str, Any]:
        """E2 每轮资源向量：{turns, tokens, wall_ms}——逐维呈报不相加（Eq10 口径）。

        turns=1（本轮迭代自身）；tokens=usage 单源差分（确定性 harness 不发
        LLM ⇒ 诚实为 0，不冒领真 token 计数）；wall_ms=应用/度量段墙钟。
        """
        return {"turns": 1, "tokens": int(max(0, tokens_delta)), "wall_ms": int(wall_ms)}

    def _probeOutcome(self, state: Dict[str, Any], candidate: Any) -> Optional[float]:
        """Eq8 配对探针的下游结局评估（观测档）：候选值代入活值快照推演决策档。

        candidate=None（A4 无更新臂）＝**留在原地**的基线质量——活值快照原样
        推演，不做任何替换；这不是"量不出"，把基线态读成 None 会把对照臂
        记成零证据（活体实测抓到过：no_update 臂 evidenced=0 的误读）。
        密封档永不进本探针——探针读数经 A5 会变成升级证据链的一环，把密封喂进
        选择过程就是自适应污染（D1 纪律的探针侧延伸）。
        """
        try:
            harness = self._eval_harness
            if harness is None:
                from .eval_harness import RSIEvalHarness

                harness = RSIEvalHarness()
                self._eval_harness = harness
            base_params = self._current_live_params()
            if candidate is None:
                outcome = harness.run(base_params)
                return outcome.get("score")
            live_params = self._substituteCandidateValue(base_params, {
                "system": state["system"],
                "parameter": f"{state['system']}.{state['param']}",
                "new_value": candidate.metadata["optimization"]["new_value"],
            })
            if live_params is None:
                return None
            outcome = harness.run(live_params)
            return outcome.get("score")
        except Exception as e:  # noqa: BLE001 - 探针故障＝该配对无证据，不阻断
            logger.debug("配对探针下游评估失败: %s", e)
            return None

    def _probeStartingStates(self) -> List[Dict[str, Any]]:
        """确定性起始态网格：可优化数值参数（排序固定）× 固定扰动档。

        同输入同网格（重放纪律）；命中 setpoint 的组合剔除（无候选可产）；
        封顶 MAX_STARTING_STATES（get_status 每次轮询都跑探针，成本钉在
        几十次 harness 推演内）。
        """
        from .improver_paired_probe import MAX_STARTING_STATES, STARTING_STATE_OFFSETS

        from .system_performance import get_setpoint as _get_setpoint

        states: List[Dict[str, Any]] = []
        params = self.integration_manager.get_optimizable_parameters()
        for system_name in sorted(params.keys()):
            for param_info in sorted(params[system_name], key=lambda p: p.name):
                current = getattr(param_info, "current_value", None)
                if current is None or not isinstance(current, (int, float)):
                    continue
                setpoint = _get_setpoint(system_name, param_info.name)
                if setpoint is None or not isinstance(setpoint, (int, float)):
                    continue
                for offset in STARTING_STATE_OFFSETS:
                    probed = round(float(current) * (1.0 + offset), 6)
                    if abs(probed - float(setpoint)) < 1e-9:
                        continue
                    states.append({
                        "system": system_name,
                        "param": param_info.name,
                        "current": probed,
                        "setpoint": float(setpoint),
                    })
                    if len(states) >= MAX_STARTING_STATES:
                        return states
        return states

    def _current_live_params(self) -> Dict[str, Dict[str, Any]]:
        """当下可优化参数的活值快照（主度量与密封档证据共用同一份派生，教义第 6 条）。"""
        return {
            system: {
                p.name: p.current_value
                for p in params
                if p.current_value is not None
            }
            for system, params in self.integration_manager.get_optimizable_parameters().items()
        }

    def _evalOutcomeReadout(self) -> Dict[str, Any]:
        """决策档评测读数（状态面呈报）：最近一次主度量的统一三态形态。"""
        outcome = self._last_eval_outcome
        if not isinstance(outcome, dict):
            return {"state": "unevidenced",
                    "reason": "本进程尚无评测读数（未跑过迭代或评测故障）"}
        return outcome

    def _sealedEvidenceReadout(self) -> Dict[str, Any]:
        """密封档验收证据（状态面呈报）：缺席时按 unevidenced 说出为什么，不冒充证据。"""
        evidence = self._last_sealed_evidence
        if not isinstance(evidence, dict):
            return {"state": "unevidenced",
                    "reason": "尚无参数应用轮次——密封档只作决策后的验收证据，从不参与判定"}
        families = sorted({c.get("family") for c in evidence.get("cases", []) if c.get("family")})
        return {**evidence, "covered_families": families}

    def _run_sealed_evidence(self) -> Optional[Dict[str, Any]]:
        """密封档验收证据（D1）：决策落定后对**最终参数态**跑一次密封用例。

        保留候选后的读数回答"从未被优化过的用例是否也站得住"；回滚后的读数
        应≈基线（回滚把密封证据一并带回来的独立核对）。故障 fail-soft 返回 None，
        状态面按 unevidenced 呈报，不冒充证据。
        """
        try:
            harness = self._eval_harness
            if harness is None:
                from .eval_harness import RSIEvalHarness

                harness = RSIEvalHarness()
                self._eval_harness = harness
            return harness.run_sealed(self._current_live_params())
        except Exception as e:  # noqa: BLE001 - 密封证据故障不阻断迭代主链
            logger.debug("密封档验收证据读取失败: %s", e)
            return None

    def _measure_performance(self) -> float:
        """实测当前整体性能：端到端评测集优先（Auto Harness 统一度量），
        信号估算兜底（评测集不可用时保持旧行为）。

        工单 007：评测集报 `measurement_blind`（全部用例回退 setpoint，等于没在测量）时
        **不得静默退回信号估算并参与 gain 相减** —— 那只是把"参数贴贴度复读"
        从另一个门塞回来。此处仍返回数值以兼容签名，但把 `state` 记进
        `_last_eval_outcome`，由 `run_iteration` 决定该轮 gain 是否有效。
        """
        try:
            harness = self._eval_harness
            if harness is None:
                from .eval_harness import RSIEvalHarness

                harness = RSIEvalHarness()
                self._eval_harness = harness
            outcome = harness.run(self._current_live_params())
        except Exception as e:  # noqa: BLE001 - 评测故障不阻断迭代
            logger.debug("端到端评测失败，回退信号估算: %s", e)
            self._last_eval_outcome = None
            return self._measure_performance_from_signals()

        # P1-2(2026-10-06):端到端任务标尺与 harness 分数**并列呈报**——
        # 重放工具窗口的真实结局流,量"历史成功工具在排名中的对齐度"。
        # 它是观测面不是判据:不参与 gain 计算与回滚判定。
        e2e: Optional[Dict[str, Any]] = None
        try:
            from .task_yardstick import measure_tool_selection

            e2e = measure_tool_selection(
                self.integration_manager._systems.get("tool_memory"))
        except Exception as e2e_err:  # noqa: BLE001 - 标尺故障不影响主度量
            logger.debug("端到端任务标尺测量失败: %s", e2e_err)

        self._last_eval_outcome = {
            "score": outcome.get("score"),
            "state": outcome.get("state"),
            "evidenced_cases": outcome.get("evidenced_cases"),
            "blind_cases": outcome.get("blind_cases"),
            "cases": outcome["cases"],
            "e2e": e2e,
        }
        if outcome.get("score") is None:
            # 度量失明：给出信号估算值供日志与降级读数使用，
            # 但 state 已标记，run_iteration 不会把这轮的差值当真实增益。
            logger.info(
                "RSI 评测集度量失明（%d 个用例全部回退 setpoint），本轮 gain 视为无证据",
                outcome.get("blind_cases"),
            )
            return self._measure_performance_from_signals()
        return float(outcome["score"])

    def _measure_performance_from_signals(self) -> float:
        """信号估算性能：真实闭环系统的 setpoint 梯度估算平均值（评测集兜底路径）。

        工单 018：占位替身被排除在均值之外 —— 对它估出来的分只是"空对象的镜像
        默认值离目标有多像"，正是审计里 +0.111 假增益的读数来源。
        全为替身时没有读数（0.0 = 没得测，不是"性能最差"）。
        """
        from .system_performance import estimate_system_performance

        signals = self.collect_feedback_signals()
        optimizable = self.integration_manager.get_optimizable_parameters()

        scores = []
        for system_name in self.integration_manager._systems:
            feedback = signals.get(system_name, {})
            if not isinstance(feedback, dict) or _carries_no_evidence(feedback):
                continue
            params = {
                p.name: p.current_value
                for p in optimizable.get(system_name, [])
            }
            scores.append(estimate_system_performance(system_name, feedback, params))

        return sum(scores) / len(scores) if scores else 0.0

    def _snapshot_optimizable(self) -> Dict[str, Any]:
        """快照全部可优化参数当前值（用于有害调整回滚）"""
        snapshot = {}
        for system_name, params in self.integration_manager.get_optimizable_parameters().items():
            for p in params:
                snapshot[p.name] = {"system": system_name, "value": p.current_value}
        return snapshot

    def _restore_optimizable(self, snapshot: Dict[str, Any]) -> None:
        """按快照恢复参数（仅恢复应用过的那些）"""
        for param_path, info in snapshot.items():
            self.integration_manager.apply_optimization(
                f"{info['system']}.{param_path}", info["value"]
            )

    def _compute_days_without_rollback(self) -> Optional[float]:
        """距上次回滚多少天（治理遗留 A / 工单 004：phase 评估的真实数据来源）。

        委托给 `rollback_manager`：那里同时握着回滚历史与装配时刻，
        是这条读数的唯一事实源。返回 None 表示**起算点未知** ——
        调用方必须把该键从判据里摘掉，让它落到 `unevidenced`，
        绝不可兜底成 0.0（旧实现正是这么把"没证据"伪装成"今天刚回滚过"，
        于是 phase 1→2 的 7 天永不可达）。
        """
        try:
            return self.rollback_manager.days_since_last_rollback()
        except Exception as e:  # noqa: BLE001 - 读数失败按"无证据"处理，不编造数值
            logger.warning("回滚天数读取失败，本晋升判据按无证据处理: %s", e)
            return None

    def run_iteration(self) -> Dict[str, Any]:
        """
        运行一次 RSI 迭代（真实棘轮：应用 → 实测 → 保留/回滚）

        Returns:
            Dict[str, Any]: 迭代结果，包含：
                - feedback_signals: 反馈信号（占位替身那几路带 `verdict` = unevidenced）
                - placeholder_systems: 由缺席占位替身顶位的系统名（工单 018）
                - convergence: 收敛性分析
                - optimizations: 优化建议
                - applied_results: 实际应用结果
                - applied_count: 成功应用的优化数
                - gain: 应用后的实测性能增益（有害调整回滚后为 0）
                - eval: 本轮前后测量读数（`state` 为 measured / measurement_blind）
                - phase_verdict: 阶段晋升判据（`GateVerdict` 三态）
                - metrics: 监控指标
        """
        # 1. 收集反馈信号
        feedback_signals = self.collect_feedback_signals()

        # 2. 分析收敛状态
        convergence = self.convergence_analyzer.analyze_convergence()

        # 3. 生成优化建议
        optimizations = self.generate_optimizations(feedback_signals)

        # 4. 应用优化（部署控制器允许时）+ 实测增益 + 棘轮保留/回滚
        applied_results: List[Dict[str, Any]] = []
        applied_count = 0
        attempted = False
        gain_evidenced = False
        gain = 0.0
        # eval 读数随分支赋值,但返回体无条件引用——必须在此初始化,
        # 否则"候选过闸却全部应用失败"(applied_count==0)一路 NameError
        # (潜伏崩溃,test_task_yardstick.py 随 P1-2 同批钉住)。
        eval_before: Optional[Dict[str, Any]] = None
        eval_after: Optional[Dict[str, Any]] = None
        # 回滚判据要读 roi：取**本轮记数之前**的成本核算读数（本轮增益还没进
        # 历史，判的是"走到这一步为止"的累积读数）。没有成本记录 → None，
        # 判据按"没测到"处理，不塞 0。
        roi_before_apply = (
            self.convergence_analyzer.compute_roi()
            if self.convergence_analyzer.cost_history else None
        )

        # 反向闸（003 M2）：上一次动作的代价未清 ⇒ 本次不动作 + 记原因。
        # 灰度复用 deployment_controller 的阶段语义（K3）：phase < 2 时不生效，
        # 与"低风险自动执行"同一档位判据，不新造第二个开关。
        debt_verdict = self._debt_gate_verdict()
        if optimizations and debt_verdict.allow is False and self.deployment_controller.can_auto_execute("low"):
            logger.info(
                "RSI 反向闸拦下本轮寻优：%s（未清余额=%s）",
                debt_verdict.reason, debt_verdict.outstanding,
            )
            optimizations = []
            self._last_debt_gate: Dict[str, Any] = {
                "blocked": True,
                "reason": debt_verdict.reason,
                "outstanding": debt_verdict.outstanding,
            }
        else:
            self._last_debt_gate = {
                "blocked": False,
                "reason": debt_verdict.reason,
                "outstanding": debt_verdict.outstanding,
            }

        if optimizations and self.deployment_controller.can_auto_execute("low"):
            self._attempts_total += 1
            # E1/E2 成本计量起点：usage 单源快照＋墙钟（应用/度量段的真实消耗）
            import time as _time

            from neurova.core.usage_accounting import get_usage_accounting

            _cost_t0 = _time.monotonic()
            _tokens_before = get_usage_accounting().snapshot()["total"]["total_tokens"]
            perf_before = self._measure_performance()
            eval_before = self._last_eval_outcome
            snapshot = self._snapshot_optimizable()

            assertRsiOptimizationIdentity(optimizations)
            applied_results = self.apply_optimizations(optimizations)
            assertRsiRoundIdentity(optimizations, applied_results)
            applied_count = sum(1 for r in applied_results if r.get("applied"))
            self._applied_total += applied_count

            if applied_count:
                perf_after = self._measure_performance()
                eval_after = self._last_eval_outcome
                gain = perf_after - perf_before
                # 本轮是否真被量出来：评测集两次都必须报 measured。
                # 度量失明时 gain 恒为 0，喂进历史就会被当成"没有改善空间"（工单 008）。
                attempted = True
                gain_evidenced = bool(
                    isinstance(eval_before, dict) and eval_before.get("state") == "measured"
                    and isinstance(eval_after, dict) and eval_after.get("state") == "measured"
                )
                # B3 配对置信区间：例级差分的抽样不确定度，喂给回滚判据
                # （上界<0 确证危害才回滚；带内噪声不出 gain 轴判据）并随
                # eval_after 出街。CI 缺席（失明/用例失配）时判据回退点规则。
                gain_ci = self._pairedGainCI(eval_before, eval_after)
                if isinstance(eval_after, dict) and gain_ci is not None:
                    eval_after["gain_ci"] = gain_ci
                # B1 真实结局对齐差分：行为分涨而结局对齐崩必判否（e2e 轴
                # 只否决不奖励），随 eval_after 出街。
                e2e_gain = self._pairedE2EGain(eval_before, eval_after)
                if isinstance(eval_after, dict) and e2e_gain is not None:
                    eval_after["e2e_gain"] = e2e_gain
                # C1 跨轮回放门：例级退化清单（共享判据机器出），喂回滚判据。
                case_metrics = self._caseRegressionMetrics(eval_before, eval_after)
                if isinstance(eval_after, dict):
                    eval_after.update(case_metrics)
                # 回滚判据的单一事实源是 `rollback_manager.should_rollback`：
                # 编排器只负责把本轮读数喂进去，不自己另写一套比较。
                _rollback_t0 = _time.monotonic()
                if self.rollback_manager.should_rollback({
                    "convergence_status": convergence.get("status", ""),
                    "roi": roi_before_apply,
                    "gain": gain,
                    "gain_ci": gain_ci,
                    "e2e_gain": e2e_gain,
                    "case_regressions": case_metrics.get("case_regressions"),
                }):
                    # 有害调整：回滚到应用前快照（失控漂移的本质防护）。
                    # 工单 004：回滚必须同时**留痕到 rollback_manager** ——
                    # 阶段晋升判据的"距上次回滚多少天"只有这一个真实数据来源；
                    # 旧实现只改内存不记账，导致该读数恒 0、phase 1→2 永不可达。
                    snapshot_id = self.rollback_manager.create_snapshot(snapshot)
                    self._restore_optimizable(snapshot)
                    if not self.rollback_manager.execute_rollback(snapshot_id):
                        logger.error(
                            "RSI 回滚已执行但留痕失败（snapshot_id=%s）：晋升判据将看不到本次回滚",
                            snapshot_id,
                        )
                    # 回滚处置债务（003 票面"连带必改"）：该笔代价必须结清或
                    # 显式转挂，不许静默消失 —— 否则回滚反而制造"无主欠账"。
                    if self.debt_ledger is not None:
                        self.debt_ledger.settle_on_rollback(reason="rollback_restored_snapshot")
                    applied_count = 0
                    gain = 0.0
                    # C5 恢复成本：回滚耗时（重测成本＝决策落定后的密封档重读，
                    # 与下方 _run_sealed_evidence 同一次调用，此处记时间与次数）。
                    self._last_recovery = {
                        "rollback_ms": int((_time.monotonic() - _rollback_t0) * 1000),
                        "remeasure_evals": 1,
                    }
                # 密封档验收证据（D1）：决策（保留/回滚）落定后对最终参数态读一次——
                # 密封用例从不进 gain/收敛史/候选生成（切分单源 eval_harness.splitSealedCases），
                # 只作验收证据随状态面呈报。
                self._last_sealed_evidence = self._run_sealed_evidence()
                # E1/E2 资源向量：usage 单源差分＋墙钟（确定性 harness 不发 LLM
                # ⇒ tokens 诚实为 0，不冒领真 token 计数）。
                _tokens_after = get_usage_accounting().snapshot()["total"]["total_tokens"]
                self._last_cost_vector = self._iterationCostVector(
                    wall_ms=int((_time.monotonic() - _cost_t0) * 1000),
                    tokens_delta=usageTokensDelta(_tokens_before, _tokens_after),
                )
        else:
            eval_before = None
            eval_after = None

        # 5. 记入收敛历史 —— 尝试过就记，但增益只在"真被量出来"时才记（工单 008）。
        # 两道门各挡一种假象：
        #   a) 本轮什么都没应用 → 不记（挡"什么都没做却被判定收敛"）；
        #   b) 应用了但评测集度量失明 → 记一轮 evidenced=False：成本真花过（进 roi 分母），
        #      增益不进增益史（挡"量不出来"被读成"没有改善空间"，
        #      这是 should_continue() 在零证据下永久关掉进化的真实路径）。
        # 有害调整被回滚后 gain 归 0，但测量有效，故仍记一轮 ——
        # roi 因此能表达"只烧成本不产出"（工单 006 移交本单的裁决：
        # 不引入负增益语义，改用可证伪的零产出门槛）。
        if attempted:
            self.convergence_analyzer.record_iteration(
                gain=gain, cost=1.0, evidenced=gain_evidenced,
                cost_vector=self._last_cost_vector,
            )

        # roi 读数在喂数之后取，保证"本轮的增益/成本"已计入 ——
        # 若在迭代前读，首轮永远是空，指标与守卫都拿不到值（工单 006）。
        # None 表示"还没花过成本"，下游必须摘键落 unevidenced，
        # 不得兜底成 0.0 —— 那正是 roi 守卫空转（幻影守卫）的成因。
        roi_readout = self.convergence_analyzer.compute_roi() \
            if self.convergence_analyzer.cost_history else None

        # 计数先于供值：`rsi_cycles_total` 说的是"到这份读为止一共跑了几轮"，
        # 而第 6 步就在对外报这份读数（工单 012 前它写在第 8 步，于是指标恒比
        # 实际轮次少 1，首轮读数报 0）。
        self._iteration_count += 1

        # D2 审计预定表：命中预定时刻时封存时点快照（sealed evidence＋eval
        # outcome＋cost vector）——事后审计只读预定时刻，表外请求被拒（§7.2
        # 选点污染防线）。表由序列启动前预定（步长固定），运行中不改。
        try:
            if self._audit_schedule.isScheduled(self._iteration_count):
                self._audit_schedule.recordSnapshot(self._iteration_count, {
                    "sealed_evidence": self._last_sealed_evidence,
                    "eval_outcome": self._last_eval_outcome,
                    "cost_vector": self._last_cost_vector,
                    "deployment_phase": self.deployment_controller.get_current_phase(),
                    # C5 纵报四格：接受率/新成功/回归/恢复成本（缺格在
                    # checkpointColumnsReadout 点名，不冒充）。
                    "checkpoint_columns": self._checkpointColumns(),
                })
                # C2 质量三曲线：deployed=现值（决策落定后的状态）、final=本轮
                # 结束读数、archive_best 由流内历史现算（互斥守卫在 record 侧）。
                from .result_summary import record_quality_curves

                _deployed = None
                if isinstance(self._last_eval_outcome, dict):
                    _deployed = self._last_eval_outcome.get("score")
                if isinstance(_deployed, (int, float)):
                    record_quality_curves(
                        self.agent_id, self._iteration_count,
                        deployed=float(_deployed), final=float(_deployed),
                    )
        except Exception as e:  # noqa: BLE001 - 审计封存故障不阻断迭代
            logger.debug("审计预定表封存失败: %s", e)

        # 6. 规范指标供值（工单 012）：写了没人读与定义了没人写同罪，两套键不许并存。
        #    原先这里写的是临时键 `iteration_count/applied_count/…`，而 `RSIMetrics`
        #    声明的 7 个规范常量有 6 个从没被写过 ⇒ `check_alerts()` 与"棘轮门通过率"
        #    吃的是恒 0 的空仪表。被删掉的那几个临时数在本轮返回值里原样可得
        #    （`applied_count`/`optimizations`/`eval`），指标面只留告警与判据要吃的名字。
        self.metrics.record_metric(RSIMetrics.RSI_CYCLES_TOTAL, self._iteration_count)
        self.metrics.record_metric(
            RSIMetrics.RSI_ROLLBACK_COUNT,
            len(self.rollback_manager.get_rollback_history()),
        )
        gains = list(self.convergence_analyzer.gain_history)
        if gains:
            self.metrics.record_metric(
                RSIMetrics.RSI_IMPROVEMENT_RATE,
                sum(1 for g in gains if g > 0) / len(gains),
            )
        # 工单 006：roi 写进规范指标，否则 `metrics.check_alerts()` 的
        # 负 ROI 告警读到的永远是初始 0（该指标此前零写入方）。
        if roi_readout is not None:
            self.metrics.record_metric(RSIMetrics.RSI_CONVERGENCE_ROI, float(roi_readout))
        self._refresh_experience_metrics()
        # §6-4(2026-10-06):规范指标快照追加进观测审计流(时序留痕;
        # 未挂载零 IO,失败只记日志——观测面故障不阻断迭代)
        self._persist_metrics_snapshot()

        # F1 外部对照成对采集：代理分（setpoint 梯度估算，自指面）×外部参考分
        # （e2e 真实结局对齐，观测档）——每轮采集一次，滚动相关性随状态面出街。
        try:
            from .task_yardstick import measure_tool_selection

            proxy_score = self._measure_performance_from_signals()
            e2e_readout = measure_tool_selection(
                self.integration_manager._systems.get("tool_memory"))
            reference_score = (e2e_readout.get("score")
                               if isinstance(e2e_readout, dict) else None)
            if isinstance(proxy_score, (int, float)) and isinstance(reference_score, (int, float)):
                self._recordProxyReferencePair(float(proxy_score), float(reference_score))
        except Exception as e:  # noqa: BLE001 - 对照采集故障不阻断迭代
            logger.debug("F1 外部对照采集失败: %s", e)

        # 7. P0-A3 + 工单 009：自动通道失效（失明/发散/振荡下行/真 ROI 非正）时
        # 升级给 SelfImprovementProposer。roi 一并进判据，否则"花了成本零产出"
        # 这一种失效形态在观测上不存在。
        escalation = self._escalate_to_proposer_if_needed(
            convergence, feedback_signals, roi=roi_readout
        )

        # 8. 阶段自动评估（遗留事项 ① 接线）：evaluate_phase_transition 此前零
        # 调用方——phase 永远停在观察期，can_auto_execute("low") 恒 False。
        # 判据通过后由 advance_phase 真正推进（判据与推进分离是 controller 原设计）。
        # 工单 003/004：判据返回三态 GateVerdict，且结论随迭代结果对外可见 ——
        # "没晋升"必须说得出是没证据还是有否决证据。
        phase_advanced = False
        phase_persisted = False
        phase_verdict: Dict[str, Any] = GateVerdict.unevidenced("本轮未执行阶段评估").to_dict()
        try:
            phase_metrics = {"convergence_status": convergence.get("status", "")}
            if roi_readout is not None:
                phase_metrics["roi"] = float(roi_readout)
            # 真实回滚天数（治理遗留 A / 工单 004）：来自 rollback_manager 的历史与
            # 装配时刻。取不到就不塞键 —— 让判据落 unevidenced，而不是伪装成 0 天。
            days_without_rollback = self._compute_days_without_rollback()
            if days_without_rollback is not None:
                phase_metrics["days_without_rollback"] = days_without_rollback
            # 经验质量读数（工单 016）：只搬运本轮已刷新的规范指标，判据面不另算一套。
            # 与上面两条不同，这里不摘键——空库与"有库但没人采纳过"要能被区分出来，
            # 读数的 None 字段本身就是证据（第 6 步 `_refresh_experience_metrics()` 已写入）。
            phase_metrics["experience_quality"] = self.metrics.experience_quality_readout()

            verdict = self.deployment_controller.evaluate_phase_transition(phase_metrics)
            if not isinstance(verdict, GateVerdict):
                # 兼容返回裸 bool 的第三方/替身控制器，不让类型差异吞掉三态语义
                verdict = (GateVerdict.passed() if verdict
                           else GateVerdict.failed("阶段判据返回假值，未提供理由"))
            phase_verdict = verdict.to_dict()

            if verdict:
                # 工单 012：`RSI_GATE_FAILURES` 的告警文案是"连续失败 N 次"，
                # 所以计数口径就是**连续**被硬否决的轮数：通过即归零。
                self._consecutive_gate_failures = 0
                new_phase = self.deployment_controller.advance_phase()
                phase_advanced = True
                # 工单 005：内存阶段推进对"下一次重启"毫无意义 —— 编排器每次都按
                # 盘上的 rsi_phase 重建。落盘失败仍算晋升发生过的本轮，但必须留下读数。
                phase_persisted = self._persist_rsi_phase(new_phase)
                logger.info(
                    "RSI 部署阶段推进至 %s（治理设置 rsi_phase 落盘=%s）",
                    new_phase,
                    phase_persisted,
                )
            else:
                if verdict.state == GateVerdict.STATE_FAILED:
                    # 有读数且结论为否才算失败；`unevidenced` 是"还没量到"，
                    # 计进"连续失败"会把缺证据读成质量差（工单 003 的三态之分）
                    self._consecutive_gate_failures += 1
                    self.metrics.record_metric(
                        RSIMetrics.RSI_GATE_FAILURES, self._consecutive_gate_failures
                    )
                logger.info("RSI 阶段不晋升 [%s]：%s", verdict.state, verdict.reason)
            self._last_phase_outcome = {
                "phase_advanced": phase_advanced,
                "phase_persisted": phase_persisted,
                "phase_verdict": phase_verdict,
            }
        except Exception as e:  # noqa: BLE001 - 阶段评估故障不影响迭代主流程
            logger.debug("阶段推进评估跳过: %s", e)
            phase_verdict = GateVerdict.unevidenced(f"阶段评估异常: {e}").to_dict()

        return {
            "feedback_signals": feedback_signals,
            # 工单 018：哪几路是占位替身必须随行——否则 `applied_count=0`
            # 在观测面上与"跑过了但没找到改进空间"无法区分
            "placeholder_systems": self.integration_manager.get_placeholder_system_names(),
            # 反向闸读数（003 M2）：拦没拦、为什么拦 —— 拦下必须可归因，
            # 不得表现为"这轮刚好没有候选"（两者在观测上是相反的事）。
            "debt_gate": self._last_debt_gate,
            "convergence": convergence,
            "optimizations": optimizations,
            "applied_results": applied_results,
            "applied_count": applied_count,
            # 族级归因读数：联合轮只有一次 gain，但"哪一族动了、从多少改到多少"
            # 必须随行——否则观测面只剩两个平铺列表，事后无法归因。
            # 只拆账不拆增益（`gain_scope` 恒 "round"），四态不折叠。
            "family_attribution": familyAttribution(
                optimizations,
                applied_results,
                tableFamilies=list(
                    self.integration_manager.get_optimizable_parameters().keys()
                ),
                placeholderSystems=self.integration_manager.get_placeholder_system_names(),
            ),
            "gain": gain,
            "eval": {"before": eval_before, "after": eval_after},
            # P1-2:e2e 标尺增益(并列读数;任一侧未量出即 None,不折算 0)
            "e2e_gain": _e2e_gain_from_evals(eval_before, eval_after),
            "escalation": escalation,
            "phase_advanced": phase_advanced,
            "phase_persisted": phase_persisted,
            "phase_verdict": phase_verdict,
            "metrics": self.metrics.get_dashboard_data(),
        }

    def _persist_metrics_snapshot(self) -> None:
        """§6-4:规范指标快照落盘(挂载点见 result_summary.attach_persistence)。"""
        try:
            from .result_summary import record_metrics_snapshot

            record_metrics_snapshot(
                self.metrics.get_dashboard_data(), agent_id=self.agent_id)
        except Exception as e:  # noqa: BLE001 - 观测面故障不阻断迭代
            logger.debug("指标快照落盘失败: %s", e)

    def _persist_rsi_phase(self, new_phase: int) -> bool:
        """把自动晋升的结论写回治理设置（工单 005；G2 升级为按 agent 分域）。

        不回写 ⇒ 重启即归零，而编排器每次都以盘上值重建 ⇒ 阶段永远停在人工设定的那个，
        "自动晋升"在跨重启的部署里从未真的发生过。

        写失败不推翻本轮判据（判据吃的是已发生的证据），但 `False` 必须一路带到观测面：
        "内存已晋升、盘上没晋升"是一等读数，不是静默两态。

        G2 覆写路线：写回分域收口到 `persistRsiPhaseFor` 单源——本 agent 有覆写
        条目时写覆写条目（a 晋升不许拖着 b 走），无覆写时沿旧语义写全局。
        旧注记"多 agent 共享一个 phase、按后写者胜"随覆写域生效而退役。
        """
        from neurova.security.governance_settings import persistRsiPhaseFor

        if persistRsiPhaseFor(self.agent_id, new_phase):
            return True
        logger.warning(
            "阶段晋升未落盘：rsi_phase=%s 只在内存生效，重启将归零"
            "（治理设置写入失败，看 governance_settings.py 的日志）",
            new_phase,
        )
        return False

    def _refresh_experience_metrics(self) -> None:
        """把经验族质量读数写进规范指标（工单 008 的写入方）。

        算式只有一份，在 `EKB.quality_snapshot()`；这里只做搬运，绝不就地重算
        ——两处算同一个数必然漂移，漂移了就没有人能相信读数。
        库不可用（未初始化/文件被占）时下"本轮没有读数"的结论，而不是留旧值：
        旧值会被读成"质量没变化"，那正是本轮一路在拆的那类假象。
        """
        try:
            from neurova.skills.experience_knowledge_base import (
                get_experience_knowledge_base,
            )

            snap = get_experience_knowledge_base().quality_snapshot()
        except Exception as e:  # noqa: BLE001 - 观测面故障不阻断迭代
            logger.warning("经验质量读数刷新失败（本轮指标记 0）: %s", e)
            snap = {
                "rows": 0,
                "unevidenced_ratio": 0.0,
                "hit_rate": 0.0,
                "adoption_decisions": 0,
                "adoption_success_rate": None,
            }

        self.metrics.record_metric(RSIMetrics.EXPERIENCE_ROWS, snap["rows"])
        self.metrics.record_metric(RSIMetrics.EXPERIENCE_UNEVIDENCED_RATIO, snap["unevidenced_ratio"])
        self.metrics.record_metric(RSIMetrics.EXPERIENCE_HIT_RATE, snap["hit_rate"])
        self.metrics.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, snap["adoption_decisions"])
        # 无采纳决策 ⇒ 成功率不可得：记 0 并由 decisions 让告警保持沉默
        # （告警带最小决策数门槛，正是为了不把"没测到"读成"全失败"）
        self.metrics.record_metric(
            RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE,
            0.0 if snap["adoption_success_rate"] is None else snap["adoption_success_rate"],
        )

    def _escalation_verdict(
        self, convergence: Dict[str, Any], roi: Optional[float]
    ) -> GateVerdict:
        """自动参数调整是否已失效的三态判据（工单 009）。

        `passed` 说的是"失效判据成立 ⇒ 该走人工评审通道"。三种可证伪的失效读数：
        度量失明（应用了调整但量不出增益 —— 007 上抛的形态，这才是"自动调整失效"
        的准确定义，不必等负增益）、发散、振荡下行，外加 006 的真 ROI 非正
        （成本花过而增益为零）。

        为什么原来它是死码：`diverging` 要求 `mean_gain < -0.05`，而有害调整在
        第 4 步就被回滚并把 gain 归 0 ⇒ 增益没有负值来源，实测 80 轮该分支
        一次未触发，`_escalate_to_proposer_if_needed` 恒返回空列表。
        """
        status = str(convergence.get("status") or "").strip()
        if not status:
            return GateVerdict.unevidenced("本轮没有收敛读数，无从判断自动通道是否失效")

        slope = (convergence.get("metrics") or {}).get("trend_slope", 0)
        if status == STATE_MEASUREMENT_BLIND:
            return GateVerdict.passed("评测集度量失明：调整已应用却量不出增益，自动参数调整失效")
        if status == "diverging":
            return GateVerdict.passed("convergence=diverging：实测增益持续为负")
        if status == "oscillating" and isinstance(slope, (int, float)) and slope < 0:
            return GateVerdict.passed(f"convergence=oscillating 且 trend_slope={slope}：振荡且趋势向下")
        # 必须是真读数才参与判据：truthiness 会把 MagicMock 的 roi 当成有效值
        # 直接参与比较（工单 003/018 同一条纪律，`_experience_quality_guard` 同款判型）
        if isinstance(roi, (int, float)) and roi <= 0.0:
            return GateVerdict.passed(f"真 ROI={roi} 非正：成本已花而增益未现")
        return GateVerdict.failed(
            f"convergence={status}"
            + (f"、roi={roi}" if roi is not None else "、roi 无读数")
            + " ⇒ 自动通道未失效，不需人工升级"
        )

    def _escalate_to_proposer_if_needed(
        self,
        convergence: Dict[str, Any],
        feedback_signals: Dict[str, Any],
        roi: Optional[float] = None,
    ) -> Dict[str, Any]:
        """P0-A3 + 工单 009：自动调整失效时升级到 SelfImprovementProposer。

        返回形态（不再是裸 `List[str]`）：
        `{"verdict": 三态判据, "proposals": [提案 id], "skipped": [{system, reason}]}`
        —— 判据为"未触发"时也要给依据，每个被挡下的系统也要点名，
        否则"空列表"仍是黑箱（与本批一路在拆的静默降级同形）。
        提案一律保持 PENDING，本单不开自动 apply 路径。
        """
        verdict = self._escalation_verdict(convergence, roi)
        status = str(convergence.get("status") or "")
        outcome: Dict[str, Any] = {
            "verdict": verdict.to_dict(),
            "proposals": [],
            "skipped": [],
        }
        if not verdict:
            self._last_escalation = outcome
            return outcome

        # 度量失明时，"性能读数不低"不能证明系统没问题 —— 那正是量不出来的意思，
        # 故失明这一轮不按 performance 过滤（工单 007 的三态在此继续生效）。
        blind = status == STATE_MEASUREMENT_BLIND
        # 一个系统在人工队列里只该占一格：待审期间逐轮重问，等于把人工队列
        # 变成自动通道的刷屏出口（实测一次全套跑出 800+ 条同形 pending）。
        # 被拒/已应用的不在 pending 里，下一轮失效仍会重新提案 —— 去重的边界
        # 正是"人还没看过"，不是"这个系统以后都不许再提"。
        pending_targets = {
            proposal.target for proposal in self.self_improvement_proposer.list_pending_proposals()
        }

        for system_name, signals in feedback_signals.items():
            escalation_target = f"rsi_escalation_{system_name}"
            if not isinstance(signals, dict):
                outcome["skipped"].append({
                    "system": system_name,
                    "reason": "反馈信号不是字典，无从定位失效系统",
                })
                continue
            if _carries_no_evidence(signals):
                # 给一个没装配的系统提"请改进它"的人工提案，
                # 等于把自动通道的谎转手交给人工通道（工单 018）。
                outcome["skipped"].append({
                    "system": system_name,
                    "reason": "信号来自缺席闭环系统的占位替身（无证据）",
                })
                continue
            if escalation_target in pending_targets:
                outcome["skipped"].append({
                    "system": system_name,
                    "reason": f"该系统已有待审提案（{escalation_target}），不重复问人工",
                })
                continue
            performance = self._extract_performance(signals)
            if performance is None:
                outcome["skipped"].append({
                    "system": system_name,
                    "reason": "无性能读数（performance_score/success_rate/"
                              "avg_success_rate/stability 皆缺），不凭空提案",
                })
                continue
            if performance >= 0.5 and not blind:
                outcome["skipped"].append({
                    "system": system_name,
                    "reason": f"性能 {performance:.2f} 未低于升级线 0.5，非本系统之过",
                })
                continue

            proposal_id = self._submit_escalation_proposal(
                system_name, escalation_target, performance, status
            )
            if proposal_id:
                outcome["proposals"].append(proposal_id)

        self._last_escalation = outcome
        return outcome

    def _submit_escalation_proposal(
        self, system_name: str, skill_id: str, performance: float, status: str
    ) -> Optional[str]:
        """为一个失效系统落一条低风险 skill_manifest 提案（保持 PENDING）。

        `skill_id` 刻意**不带轮次后缀**：它是去重键，一个系统在人工队列里只该
        占一格（工单 009 落地后实测：带 `_iteration_count` 时每轮每个系统都新起
        一条提案，一次测试套件就刷出 873 个 pending JSON）。
        """
        manifest_yaml = (
            f"# Auto-generated by RSI escalation (system={system_name}, performance={performance:.2f})\n"
            f"skill_id: {skill_id}\n"
            f"description: |\n"
            f"  RSI 检测到 {system_name} 系统性能持续低下 (performance={performance:.2f})，\n"
            f"  自动参数调整已失效 (convergence={status})。\n"
            f"  请评审并设计新的技能/工具/action 来改进此系统。\n"
        )
        description = (
            f"RSI 升级提案：{system_name} 系统性能持续低下 "
            f"(performance={performance:.2f}, convergence={status})"
        )
        try:
            proposal = self.self_improvement_proposer.propose_skill_manifest(
                skill_id=skill_id,
                manifest_yaml=manifest_yaml,
                description=description,
                risk_level="low",
            )
            self.self_improvement_proposer.submit_proposal(proposal)
        except Exception as e:
            logger.warning(
                "RSI 升级失败：系统 %s 提案创建异常: %s", system_name, e, exc_info=True
            )
            return None
        logger.info(
            "RSI 升级：为系统 %s 创建 skill_manifest 提案 %s（performance=%.2f, convergence=%s）",
            system_name,
            proposal.proposal_id,
            performance,
            status,
        )
        return proposal.proposal_id

    def _compute_avg_performance(self, feedback_signals: Dict[str, Any]) -> float:
        """从反馈信号中提取平均性能指标（0.0-1.0）

        用于估算 RSI 迭代的增益。性能指标字段名优先级：
        performance_score > success_rate > avg_success_rate > stability
        """
        performances = []
        for system_name, signals in feedback_signals.items():
            if not isinstance(signals, dict):
                continue
            for key in ("performance_score", "success_rate", "avg_success_rate", "stability"):
                val = signals.get(key)
                if isinstance(val, (int, float)) and 0.0 <= val <= 1.0:
                    performances.append(float(val))
                    break
        if not performances:
            return 0.0
        return sum(performances) / len(performances)

    def collect_feedback_signals(self) -> Dict[str, Any]:
        """
        从四大闭环系统收集反馈信号

        Returns:
            Dict[str, Any]: 反馈信号字典，包含 sleep、emotion、experience、tool_memory 四个键
        """
        return self.integration_manager.collect_feedback_signals()

    def generate_optimizations(self, signals: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        根据反馈信号生成优化建议（P0-A1：使用 RecursiveRatchetPruner 剪枝）

        对每个参数生成多个不同调整幅度的候选方案，用递归棘轮剪枝器
        通过"粗筛→中筛→细筛"选出最优候选。

        Args:
            signals: 反馈信号字典

        Returns:
            List[Dict[str, Any]]: 优化建议列表（每个参数最多 1 个最优候选）
        """
        optimizations = []
        candidates_generated = 0

        # 获取可优化参数
        optimizable_params = self.integration_manager.get_optimizable_parameters()

        # 基于反馈信号生成优化建议
        for system_name, params in optimizable_params.items():
            system_signals = signals.get(system_name, {})

            for param_info in params:
                # 为每个参数生成多个候选方案（不同调整幅度）
                candidates = self._generate_candidates_for_param(system_name, param_info, system_signals)
                if not candidates:
                    continue
                candidates_generated += len(candidates)

                # 用递归棘轮剪枝器选出最优候选
                best_candidate = self._prune_candidates(candidates, system_signals)
                if best_candidate:
                    optimization = best_candidate.metadata.get("optimization")
                    if optimization:
                        # 标记来自剪枝过程
                        optimization["pruned"] = True
                        optimization["prune_rounds"] = self.pruner.rounds
                        optimization["candidate_count"] = len(candidates)
                        optimizations.append(optimization)

        # 候选统计进规范指标（工单 012）：生成数与各参数存活数只在这里同时可得
        # ——`_prune_candidates` 每次只看见一个参数的候选，异常回退那条路径也会
        # 让剪枝器自己的 prune_history 不完整。存活 = 进入 optimizations 的条数。
        self.metrics.record_metric(RSIMetrics.RSI_CANDIDATES_GENERATED, candidates_generated)
        self.metrics.record_metric(
            RSIMetrics.RSI_CANDIDATES_PRUNED, candidates_generated - len(optimizations)
        )
        return optimizations

    def _generate_candidates_for_param(
        self, system_name: str, param_info: Any, signals: Dict[str, Any]
    ) -> List[Candidate]:
        """为单个参数生成候选（A2 起纯委托：步进语义单源在 CandidatePolicy.I_0）。

        真正闭环修复（历史）：此前按 performance 高低做无脑单调增减（失控漂移
        的本质），后改为 setpoint 分级步进。A2 抽取：步进选择/打分公式/剪枝次序
        三自由度收进策略对象，本方法只做形状适配——行为由 I_0 冻结复刻判据钉住。
        """
        return self._candidate_policy.stepCandidates(
            system_name, param_info.name, param_info.current_value, signals
        )

    def _prune_candidates(self, candidates: List[Candidate], signals: Dict[str, Any]) -> Optional[Candidate]:
        """用 RecursiveRatchetPruner 剪枝候选方案，选出最优（A2 起打分/校验单源在策略对象）。

        三回调全部委托 `self._candidate_policy`（I_0＝原内联公式冻结复刻）：
        粗筛启发式 / 中筛快评 / 细筛方向+密封校验。策略未注入密封校验器时
        诚实降级方向单源（形状与 G1 前一致），编排器装配恒注入。
        """
        policy = self._candidate_policy
        try:
            return self.pruner.recursive_prune(
                candidates=candidates,
                validation_fn=policy.validationResult,
                quick_eval_fn=policy.quickEvalScore,
                heuristic_fn=policy.heuristicScore,
            )
        except Exception as e:
            logger.warning("RecursiveRatchetPruner 剪枝失败: %s，回退到首个候选", e)
            return candidates[0] if candidates else None

    def _substituteCandidateValue(self, live_params: Dict[str, Dict[str, Any]],
                                  optimization: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
        """把候选步进值代入活值快照的**深拷贝**（`system.parameter` 形态与候选生成同源）。

        返回 None = 候选缺 system/parameter/new_value 任一关键项（校验按 unevidenced 处理）。
        """
        import copy as _copy

        system = str(optimization.get("system") or "")
        parameter = str(optimization.get("parameter") or "")
        new_value = optimization.get("new_value")
        if not system or not parameter or new_value is None:
            return None
        param_name = parameter.split(".", 1)[1] if "." in parameter else parameter
        if not param_name:
            return None
        snapshot = _copy.deepcopy(live_params)
        snapshot.setdefault(system, {})[param_name] = new_value
        return snapshot

    def _sealedCandidateValidation(self, optimization: Dict[str, Any]) -> Dict[str, Any]:
        """G1 细筛校验步的密封档实跑：候选步进值代入**活值快照副本**推演。

        复用 D1 密封机器（splitSealedCases + run_sealed），不新建第二套校验面；
        例级对照当前态密封读数出 regressions——候选把某个密封用例撞到低于当前态
        即塌方（fail-closed）。真实系统全程只读，校验不改任何活值。
        """
        try:
            harness = self._eval_harness
            if harness is None:
                from .eval_harness import RSIEvalHarness

                harness = RSIEvalHarness()
                self._eval_harness = harness
            live_params = self._current_live_params()
            baseline = harness.run_sealed(live_params)
            candidate_params = self._substituteCandidateValue(live_params, optimization)
            if candidate_params is None:
                return {"state": "unevidenced", "score": None, "baseline": None,
                        "regressions": [],
                        "reason": "候选优化缺 system/parameter/new_value 任一关键项"}
            candidate_readout = harness.run_sealed(candidate_params)
            base_by_id = {c.get("id"): c.get("score")
                          for c in (baseline.get("cases") or [])}
            regressions = [
                c.get("id") for c in (candidate_readout.get("cases") or [])
                if c.get("id") in base_by_id and c.get("score", 1.0) < base_by_id[c.get("id")]
            ]
            return {
                "state": candidate_readout.get("state"),
                "score": candidate_readout.get("score"),
                "baseline": baseline.get("score"),
                "regressions": regressions,
            }
        except Exception as e:  # noqa: BLE001 - 校验故障不阻断剪枝主链，读数如实 unevidenced
            logger.debug("细筛密封档校验失败: %s", e)
            return {"state": "unevidenced", "score": None, "baseline": None,
                    "regressions": [], "reason": str(e)}

    def _extract_performance(self, signals: Dict[str, Any]) -> Optional[float]:
        """从反馈信号中提取性能指标（0.0-1.0）

        优先级：performance_score > success_rate > avg_success_rate > stability
        """
        if not isinstance(signals, dict):
            return None
        for key in ("performance_score", "success_rate", "avg_success_rate", "stability"):
            val = signals.get(key)
            if isinstance(val, (int, float)) and 0.0 <= val <= 1.0:
                return float(val)
        return None

    def _debt_gate_verdict(self) -> DebtVerdict:
        """反向闸判据：欠账未清则本次不动作。

        账本缺席（未配置 env / 未装配）时**放行**并为原因值 `debt_clear`：
        "没有账"与"账上欠着"是两件事，把前者读成后者会让未开账的部署全线停摆。
        """
        if self.debt_ledger is None:
            return DebtVerdict(True, "debt_clear", 0)
        try:
            return self.debt_ledger.evaluate_next_step()
        except Exception as e:  # noqa: BLE001 - 判据不可用按安全侧处理并留读数
            logger.warning("负债闸判据失败，按安全侧（不动作）处置: %s", e)
            return DebtVerdict(False, "ledger_write_failed", -1)

    def _debt_readout(self) -> Dict[str, Any]:
        """负债读数（治理面与状态面共用同一份，不新开第二套观测通道）。"""
        if self.debt_ledger is None:
            return {"available": False, "reason": "ledger_not_configured"}
        try:
            lookup = self.debt_ledger.outstanding_lookup()
            verdict = self._debt_gate_verdict()
            return {
                "available": True,
                **lookup,
                "last_write_failure": self.debt_ledger.last_write_failure_reason(),
                "next_step": {
                    "allow": verdict.allow,
                    "reason": verdict.reason,
                    "outstanding": verdict.outstanding,
                },
            }
        except Exception as e:  # noqa: BLE001 - 读数失败如实暴露，不编造数值
            return {"available": False, "reason": f"{type(e).__name__}: {e}"}

    def apply_optimizations(self, optimizations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        应用优化建议

        Args:
            optimizations: 优化建议列表

        Returns:
            List[Dict[str, Any]]: 应用结果列表
        """
        results = []

        for optimization in optimizations:
            parameter = optimization.get("parameter")
            new_value = optimization.get("new_value")
            # 代价口径（003 M1）：引用 002 的输出字段 `cost`，不另立一份定义。
            # 一次参数动作的成本就是它一轮的实际耗用（`convergence_analyzer`
            # 记成本用的同一计量单位），故取 1.0 —— 与 `record_iteration(cost=1.0)`
            # 同源，不新造第二个尺度。
            cost = int(optimization.get("cost", _PARAM_ACTION_COST))
            repayment = int(optimization.get("repayment", 0))

            if parameter and new_value is not None:
                success = self.integration_manager.apply_optimization(
                    parameter, new_value,
                    debt_ledger=self.debt_ledger, cost=cost, repayment=repayment,
                )
                results.append(
                    {
                        "parameter": parameter,
                        "new_value": new_value,
                        "applied": success,
                    }
                )
            else:
                results.append(
                    {
                        "parameter": parameter,
                        "new_value": new_value,
                        "applied": False,
                        "error": "Invalid optimization format",
                    }
                )

        return results

    def should_continue(self) -> bool:
        """
        判断是否应该继续 RSI 迭代

        Returns:
            bool: 是否继续
        """
        # 检查收敛性
        convergence = self.convergence_analyzer.analyze_convergence()
        status = convergence.get("status", "insufficient_data")

        # 如果已经收敛，可以停止
        if status == "converged":
            return False

        # 如果发散，需要回滚
        if status == "diverging":
            logger.warning("RSI diverging, considering rollback")
            return True  # 继续迭代，但可能需要回滚

        # 默认继续
        return True

    def iteration_cadence(self) -> IterationCadence:
        """本轮该全频跑、还是降频巡检（工单 008 交给派发层的依据）。

        `should_continue()` 的契约是" converged → False"（真实棘轮收益耗尽即停，
        见 tests/unit/evolution/test_rsi_ratchet_effectiveness.py:187）。
        但派发层把它当成"从此再不跑"就是缺陷：参数会漂、代码会变，
        收敛结论只对其产生时的那份证据有效。故这里区分两档：

        - `run`：仍有信息量（发散/振荡/正在收敛/样本不足）→ 每轮跑；
        - `backoff`：已收敛，或评测集度量失明（再跑也量不出新东西）→ 降频巡检；
        - 度量失明**不是**"没事可做"，它意味着测量坏了，必须继续被巡检并暴露，
          所以只降频、不终止。

        Returns:
            IterationCadence: mode ∈ {"run","backoff"}，附判据与读数原文
        """
        report = self.convergence_analyzer.analyze_convergence()
        status = str(report.get("status", ""))
        window = self.convergence_analyzer.window_size
        recent = self.convergence_analyzer.evidence_history[-window:]
        evidenced = sum(1 for ok in recent if ok)
        evidence = (
            f"窗口 {window} 轮内有效测量 {evidenced} 轮"
            f"（已尝试 {len(recent)} 轮）"
        )
        mode = "backoff" if status in (STATE_CONVERGED, STATE_MEASUREMENT_BLIND) else "run"
        return IterationCadence(mode=mode, basis=status, evidence=evidence)

    def get_status(self) -> Dict[str, Any]:
        """RSI 当前状态 —— 全链路唯一一份"人可读的 RSI 现在怎么样"（工单 012）。

        `RSIDashboard` 被删除（生产零实例化，且它读的候选/门控指标当时无人供值，
        于是"棘轮门通过率"恒 0、`get_rollback_history()` 是一句 `return []` 的显式
        stub）。它唯一有价值的两个聚合并到这里，供值方换成已经接电的规范指标；
        经验族视图（工单 008）随 `metrics` 一并可达，不因删 dashboard 而失去读点。

        Returns:
            Dict[str, Any]: 状态信息，包含：
                - iteration_count: 迭代次数
                - convergence_status: 收敛状态
                - deployment_phase: 部署阶段（与控制器逐值相等）
                - phase_advanced / phase_persisted / phase_verdict: 最近一轮晋升的
                  三态结论（"没晋升"要说得出是缺证据还是被否决；落盘失败不得被
                  读成已存活，工单 005 的两态在此收口）
                - candidates: 候选生成/剪枝数与棘轮门通过率
                - rollback_history: 真实回滚留痕（工单 004 的数据源）
                - experience_channel: 改进回流通道判据（工单 016：待审队列有界，
                  溢出丢了改进必须看得见，不得静默）
                - presentation_funnel: 呈现→派发漏斗三态读数（§8 前置 3 的读侧；
                  技能进了 prompt 却没被点名，必须在这一格看得见）
                - metrics: 规范指标 + 告警 + 经验族视图
        """
        convergence = self.convergence_analyzer.analyze_convergence()
        generated = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_GENERATED) or 0
        pruned = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_PRUNED) or 0

        from neurova.evolution.skill_experience import get_skill_experience_store

        experience_channel = get_skill_experience_store().pending_pressure_verdict().to_dict()

        return {
            "iteration_count": self._iteration_count,
            "convergence_status": convergence.get("status", "unknown"),
            "agent_id": self.agent_id,
            "deployment_phase": self.deployment_controller.get_current_phase(),
            # 相位来源（G2）：管理员看得见这 agent 在吃覆写还是全局——
            # 有效性判定与解析同源（governance_settings.rsiPhaseSourceFor）。
            "phase_source": rsiPhaseSourceFor(self.agent_id),
            "phase_advanced": bool(self._last_phase_outcome.get("phase_advanced")),
            "phase_persisted": bool(self._last_phase_outcome.get("phase_persisted")),
            "phase_verdict": self._last_phase_outcome.get("phase_verdict") or {},
            "candidates": {
                "generated": generated,
                "pruned": pruned,
                "pass_rate": ((generated - pruned) / generated) if generated else 0.0,
            },
            "rollback_history": self.rollback_manager.get_rollback_history(),
            # 负债读数（003 M3 的读侧）：只写不读的字段是 AGENTS.md §2 点名的断点。
            "debt": self._debt_readout(),
            # 决策档评测读数（D1 的读侧）：`_last_eval_outcome` 此前只进 gain 内部
            # 计算、状态面从不呈报（只写不读形态）——密封档上呈报面时同批接出。
            "eval_outcome": self._evalOutcomeReadout(),
            # 密封档验收证据（D1）：决策落定后的独立验收读数；
            # 密封用例永不进 gain/候选生成（切分单源 splitSealedCases）。
            "sealed_evidence": self._sealedEvidenceReadout(),
            # Eq8 配对探针读数（A3）：I_t vs I_0 同起始态同预算配对比较——
            # "改进器本身在变好"的直接证据（观测档：确定性 harness 推演，
            # 与主轨迹完全隔离；三态纪律与 task_yardstick 同款）。
            "improver_paired_probe": self._paired_probe.run(),
            # E1/E2 资源向量读数（逐维呈报不相加）＋E3 被拒成本聚合——
            # 成本链写了有人读（漏计费守卫的读侧）。
            "cost_vector": {
                "last": self._last_cost_vector,
                "totals": self.convergence_analyzer.costVectorReadout()["totals"],
            },
            "pruner_failed_cost": self.pruner.failedCostReadout(),
            # F1 外部对照：代理分×外部参考分的滚动相关性（代理独自粉饰在此现形）。
            "proxy_reference_correlation": self._proxyReferenceReadout(),
            # H1 覆盖矩阵：期望族单源（harness 决策档∪任务流形态）×近期触达。
            "coverage": self._coverageReadout(),
            # C4 迁移读数（观测档：窗口时间分半两域重放差值；同域恒等守卫）。
            "transfer": self._transferReadout(),
            # D2 审计预定表读数：预定时刻清单（独立审计只读预定时刻——
            # 表外请求在 readAuditSnapshot 被拒并点名理由）。
            # C2 质量三曲线读数（archive-best/deployed/final 逐 checkpoint 分列，
            # 语义互斥守卫在 record 侧——"历史最好冒充现值"构造态被拒）。
            "quality_curves": _qualityCurvesReadout(self.agent_id),
            # C5 纵报四格滚动读数（缺格点名）。
            "checkpoint_columns": self._checkpointColumns(),
            "audit_schedule": {
                "stride": self._audit_schedule._stride,
                "scheduled_points": self._audit_schedule.scheduledPoints()[:10],
                "snapshots_recorded": sorted(
                    self._audit_schedule._snapshots.keys())[-10:],
            },
            # 参数活性读数（004 M3）：每个在表参数动过几次 / 从未出现，三态不折叠。
            "parameter_activity": _readParameterActivitySurface(),
            "escalation": self._last_escalation,
            "experience_channel": experience_channel,
            # 呈现漏斗读数（§8 前置 3 的读侧）：写侧在技能目录渲染 →
            # 轮次账本 → manifest 漏斗；只写不读是 AGENTS.md §2 点名的断点。
            "presentation_funnel": _readPresentationFunnel(self.agent_id),
            "metrics": self.metrics.get_dashboard_data(),
            # 能力缺口读数（T-03 的读侧）：写侧在 `agent/capability_gap` →
            # `agent/gap_metric_channel`，读侧在此 —— 只写不读是断点
            # （AGENTS §2），故写进同一个状态面的字段里。
            "capability_gap": _readGapMetrics(),
            # 强化口径禁令读数（T-06 的读侧）：写侧在
            # `tool_layers/capability_graph.noteMetaRewardSkip`。与缺口读数同一
            # 状态面，不另起第二套观测通道。
            "meta_reward_guard": _readRewardGuardMetrics(),
        }


def _readParameterActivitySurface() -> Dict[str, Any]:
    """参数活性读数（004 M3）：账本落点与 003 同一枚 env，不新开第二套读数体系。"""
    from neurova.evolution.rsi.parameter_activity import readParameterActivity

    import os as _os

    env_path = _os.environ.get("NEUROVA_RSI_RECEIPTS")
    if not env_path:
        return {
            "states": {},
            "movements": {},
            "vocabulary": ["moving", "sparse", "never_proposed", "no_data"],
            "overall": "no_data",
            "reason": "ledger_not_configured",
        }
    from pathlib import Path as _Path

    return readParameterActivity(_Path(env_path))


def parameter_host_classes() -> Dict[str, type]:
    """参数表各系统的**宿主类**单一事实源（004 M1 的落点解析读它）。

    取真实子系统类，不用探针桩：探针桩上没有 property 别名，
    用它验不出"两个名字落同一物理落点"这条缺陷 —— 守卫会恒绿。
    """
    hosts: Dict[str, type] = {}
    try:
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

        hosts["sleep"] = SleepConsolidation
    except Exception as e:  # noqa: BLE001 - 宿主不可导入即缺席，由守卫如实报
        logger.debug("sleep 宿主类不可导入: %s", e)
    try:
        from neurova.evolution.experience_feedback import ExperienceFeedback

        hosts["experience"] = ExperienceFeedback
    except Exception as e:  # noqa: BLE001
        logger.debug("experience 宿主类不可导入: %s", e)
    try:
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
            ToolMemoryIntegration,
        )

        hosts["tool_memory"] = ToolMemoryIntegration
    except Exception as e:  # noqa: BLE001
        logger.debug("tool_memory 宿主类不可导入: %s", e)
    try:
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

        hosts["emotion"] = EmotionModule
    except Exception as e:  # noqa: BLE001
        logger.debug("emotion 宿主类不可导入: %s", e)
    try:
        from neurova.context.models import TokenBudget

        hosts["context"] = TokenBudget
    except Exception as e:  # noqa: BLE001
        logger.debug("context 宿主类不可导入: %s", e)
    return hosts


def _qualityCurvesReadout(agent_id: str) -> Dict[str, Any]:
    """C2 三曲线读数（模块级：读侧走 result_summary 单一出处）。"""
    try:
        from .result_summary import readQualityCurves

        return readQualityCurves(agent_id)
    except Exception as e:  # noqa: BLE001 - 曲线读侧故障不阻断状态面
        logger.debug("质量曲线读侧失败: %s", e)
        return {"state": "unevidenced", "reason": str(e)}


def _readPresentationFunnel(agent_id: str) -> Dict[str, Any]:
    """呈现→派发漏斗读数（§8 前置 3 的读侧；只搬运读数，判据不在此处另算一套）。

    取数走 `SkillService.get_skill_usage` 这一份规范读数口（它已携带
    presentations），不直读 manifest usage——同一格不得有第二个取数口。
    函数级 import：让"读侧未接线"退化为空读数而不是 ImportError。
    """
    from neurova.evolution.skill_experience import presentationFunnelVerdict

    try:
        service = agentLibrary(agent_id)
        rows = [
            service.get_skill_usage(skill_id)
            for skill_id, _info in service.iter_skills()
        ]
    except Exception as e:  # noqa: BLE001 - 读数不可用如实落 unevidenced，不折叠成 0
        return GateVerdict.unevidenced(f"呈现漏斗读数不可用: {e}").to_dict()
    return presentationFunnelVerdict(rows).to_dict()


def _readRewardGuardMetrics() -> Dict[str, Any]:
    """元检索反哺/发布禁令的命中读数（写侧见 `tool_layers/capability_graph`）。

    与 `_readGapMetrics` 同形：函数级 import，让"读侧未接线"退化为空读数
    而不是 ImportError。
    """
    try:
        from neurova.tool_layers.capability_graph import readRewardGuardSkips

        by_key = readRewardGuardSkips()
        by_channel: Dict[str, int] = {}
        for key, count in by_key.items():
            channel = key.split(":", 1)[0]
            by_channel[channel] = by_channel.get(channel, 0) + count
        return {"by_channel": by_channel, "by_key": by_key, "total": sum(by_key.values())}
    except Exception:  # noqa: BLE001 - 观测面缺失不得让状态面整体失败
        return {"by_channel": {}, "by_key": {}, "total": 0}


def _readGapMetrics() -> Dict[str, Any]:
    """能力缺口指标读侧（写侧见 `agent/gap_metric_channel`）。

    独立函数而非直接 import：`agent` 包与本模块的导入链互相牵连，
    函数级 import 让"读侧未接线"退化为一个空读数而不是 ImportError。
    """
    try:
        from neurova.agent.capability_gap import gapMetricReadout

        return gapMetricReadout()
    except Exception:  # noqa: BLE001 - 观测面缺失不得让状态面整体失败
        return {"by_kind": {}, "total": 0}


def create_rsi_orchestrator(
    sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any, **kwargs
) -> RSIOrchestrator:
    """
    创建 RSI 编排器的工厂函数

    Args:
        sleep_system: 睡眠闭环系统
        emotion_system: 情感闭环系统
        experience_system: 经验闭环系统
        tool_memory_system: 工具记忆闭环系统

    Returns:
        RSIOrchestrator: RSI 编排器实例
    """
    return RSIOrchestrator(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
        **kwargs,
    )
