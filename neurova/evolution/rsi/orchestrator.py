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
from .rollback_manager import create_rollback_manager, resolve_rollback_state_path
from .self_improvement_proposer import SelfImprovementProposer, ProposalType
from .system_performance import get_setpoint
from neurova.security.governance_settings import save_governance_settings

logger = get_logger(__name__)


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
        # 创建集成管理器
        self.integration_manager = create_rsi_integration_manager(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
        )

        # 创建收敛性分析器
        self.convergence_analyzer = create_convergence_analyzer()

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

        # 创建部署控制器（治理遗留收口：rsi_phase 来自治理设置，默认 0 观察期）
        try:
            from neurova.security.governance_settings import load_governance_settings

            self.deployment_controller = create_deployment_controller_with_settings(
                load_governance_settings()
            )
        except Exception as e:  # noqa: BLE001 - 设置不可用时维持默认观察期
            logger.warning("部署控制器按治理设置初始化失败，回退默认: %s", e)
            self.deployment_controller = create_deployment_controller()

        # 阶段推进/不晋升的证据时间线（回滚历史 + 装配时刻）由 rollback_manager
        # 唯一持有并持久化，此处不再留第二份起算点。

        # 创建递归棘轮剪枝器（P0-A1 修复：接入核心算法）
        # 用于在多个候选优化方案中通过"粗筛→中筛→细筛"选出最优
        self.pruner = RecursiveRatchetPruner(
            rounds=3,
            candidates_per_round=[50, 10, 3],
        )

        # P0-A3 修复：接入 SelfImprovementProposer
        # 当自动参数调整失效（convergence=diverging/oscillating with negative trend）时，
        # 升级到人工评审提案路径（skill_manifest/action_definition/pr_patch）。
        # 这是"渐进式自我改进"的中高风险通道，所有提案保持 PENDING 等待人工 approve_and_apply。
        # 工单 005：阶段与回滚历史必须与编排器同一份。此前这里裸构造，proposer 自带
        # 一个 phase=0 的控制器 ⇒ medium/high 提案的门禁看的是那个私有阶段，
        # 管理员在前端调 `rsi_phase` 对这条通道完全无效。
        # 归属先定：proposer 的台账与"批准即生效"都按它落到正确的技能库（工单 010）
        self.agent_id = str(agent_id or "default")
        self.self_improvement_proposer = SelfImprovementProposer(
            agent_id=self.agent_id,
            deployment_controller=self.deployment_controller,
            rollback_manager=self.rollback_manager,
        )

        # 迭代计数器
        self._iteration_count = 0
        # 工单 012：`RSI_GATE_FAILURES` 吃的是"连续被硬否决"的轮数（通过即归零），
        # 而 `get_status()` 要能答"最近一轮晋升判据说了什么"，故把最近结论留在实例上。
        self._consecutive_gate_failures = 0
        self._last_phase_outcome: Dict[str, Any] = {}
        # 工单 009：升级通道走没走过、为什么没走，也要能从状态面读到
        self._last_escalation: Dict[str, Any] = {}

        # 端到端评测集（Auto Harness：gain 的统一度量，懒加载）
        self._eval_harness: Optional[Any] = None
        self._last_eval_outcome: Optional[Dict[str, Any]] = None

        logger.info("RSIOrchestrator initialized")

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
            live_params = {
                system: {
                    p.name: p.current_value
                    for p in params
                    if p.current_value is not None
                }
                for system, params in self.integration_manager.get_optimizable_parameters().items()
            }
            outcome = harness.run(live_params)
        except Exception as e:  # noqa: BLE001 - 评测故障不阻断迭代
            logger.debug("端到端评测失败，回退信号估算: %s", e)
            self._last_eval_outcome = None
            return self._measure_performance_from_signals()

        self._last_eval_outcome = {
            "score": outcome.get("score"),
            "state": outcome.get("state"),
            "evidenced_cases": outcome.get("evidenced_cases"),
            "blind_cases": outcome.get("blind_cases"),
            "cases": outcome["cases"],
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
        # 回滚判据要读 roi：取**本轮记数之前**的成本核算读数（本轮增益还没进
        # 历史，判的是"走到这一步为止"的累积读数）。没有成本记录 → None，
        # 判据按"没测到"处理，不塞 0。
        roi_before_apply = (
            self.convergence_analyzer.compute_roi()
            if self.convergence_analyzer.cost_history else None
        )

        if optimizations and self.deployment_controller.can_auto_execute("low"):
            perf_before = self._measure_performance()
            eval_before = self._last_eval_outcome
            snapshot = self._snapshot_optimizable()

            applied_results = self.apply_optimizations(optimizations)
            applied_count = sum(1 for r in applied_results if r.get("applied"))

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
                # 回滚判据的单一事实源是 `rollback_manager.should_rollback`：
                # 编排器只负责把本轮读数喂进去，不自己另写一套比较。
                if self.rollback_manager.should_rollback({
                    "convergence_status": convergence.get("status", ""),
                    "roi": roi_before_apply,
                    "gain": gain,
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
                    applied_count = 0
                    gain = 0.0
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
                gain=gain, cost=1.0, evidenced=gain_evidenced
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
            "convergence": convergence,
            "optimizations": optimizations,
            "applied_results": applied_results,
            "applied_count": applied_count,
            "gain": gain,
            "eval": {"before": eval_before, "after": eval_after},
            "escalation": escalation,
            "phase_advanced": phase_advanced,
            "phase_persisted": phase_persisted,
            "phase_verdict": phase_verdict,
            "metrics": self.metrics.get_dashboard_data(),
        }

    def _persist_rsi_phase(self, new_phase: int) -> bool:
        """把自动晋升的结论写回治理设置（工单 005）。

        不回写 ⇒ 重启即归零，而编排器每次都以盘上值重建 ⇒ 阶段永远停在人工设定的那个，
        "自动晋升"在跨重启的部署里从未真的发生过。

        写失败不推翻本轮判据（判据吃的是已发生的证据），但 `False` 必须一路带到观测面：
        "内存已晋升、盘上没晋升"是一等读数，不是静默两态。

        治理设置是**进程级单文件、多 agent 共享一个 phase**（口径见
        `neurova/security/governance_settings.py` 模块文档串）：多个 agent 的编排器
        各自晋升时按后写者胜，多 agent 隔离属本单"明确不做"的范围。
        """
        if save_governance_settings({"rsi_phase": new_phase}):
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
        """为单个参数生成候选方案（朝 setpoint 方向的分级步进）。

        真正闭环修复：此前按 performance 高低做无脑单调增减（失控漂移
        的本质）。现改为以 setpoint 为目标，生成 5%/10%/15%/20% 步进
        靠近的候选；已在 setpoint 的参数不产生候选。
        """
        param_name = param_info.name
        current_value = param_info.current_value
        if current_value is None or not isinstance(current_value, (int, float)):
            return []

        setpoint = get_setpoint(system_name, param_name)
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

        performance = self._extract_performance(signals)

        candidates = []
        for ratio in [0.05, 0.10, 0.15, 0.20]:
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

    def _prune_candidates(self, candidates: List[Candidate], signals: Dict[str, Any]) -> Optional[Candidate]:
        """用 RecursiveRatchetPruner 剪枝候选方案，选出最优"""

        # 启发式函数：基于参数复杂度和启发式分数
        def heuristic_fn(candidate: Candidate) -> float:
            return candidate.heuristic_score

        # 快速评估函数：基于性能改善预期
        def quick_eval_fn(candidate: Candidate) -> float:
            perf = candidate.metadata.get("performance", 0.5)
            # 性能越低，越需要激进调整（但激进调整复杂度高）
            adjustment = candidate.parameters.get("adjustment_ratio", 0.1)
            expected_improvement = (1.0 - perf) * adjustment * 10
            return expected_improvement - candidate.complexity * 0.5

        # 验证函数：基于调整方向是否正确
        def validation_fn(candidate: Candidate) -> Dict[str, Any]:
            opt = candidate.metadata.get("optimization", {})
            new_value = opt.get("new_value", 0)
            current = opt.get("current_value", 0)
            setpoint = opt.get("setpoint", None)
            # 候选由 _generate_candidates_for_param 生成，已保证向 setpoint 方向步进。
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
            return {
                "valid": direction_ok,
                "score": 1.0 if direction_ok else 0.0,
                "details": f"current={current}, new={new_value}, setpoint={setpoint}",
            }

        try:
            return self.pruner.recursive_prune(
                candidates=candidates,
                validation_fn=validation_fn,
                quick_eval_fn=quick_eval_fn,
                heuristic_fn=heuristic_fn,
            )
        except Exception as e:
            logger.warning("RecursiveRatchetPruner 剪枝失败: %s，回退到首个候选", e)
            return candidates[0] if candidates else None

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

            if parameter and new_value is not None:
                success = self.integration_manager.apply_optimization(parameter, new_value)
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
            "phase_advanced": bool(self._last_phase_outcome.get("phase_advanced")),
            "phase_persisted": bool(self._last_phase_outcome.get("phase_persisted")),
            "phase_verdict": self._last_phase_outcome.get("phase_verdict") or {},
            "candidates": {
                "generated": generated,
                "pruned": pruned,
                "pass_rate": ((generated - pruned) / generated) if generated else 0.0,
            },
            "rollback_history": self.rollback_manager.get_rollback_history(),
            "escalation": self._last_escalation,
            "experience_channel": experience_channel,
            "metrics": self.metrics.get_dashboard_data(),
            # 能力缺口读数（T-03 的读侧）：写侧在 `agent/capability_gap` →
            # `agent/gap_metric_channel`，读侧在此 —— 只写不读是断点
            # （AGENTS §2），故写进同一个状态面的字段里。
            "capability_gap": _readGapMetrics(),
        }


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
