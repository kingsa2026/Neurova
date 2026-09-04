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
from typing import Any, Dict, List, Optional

from .convergence_analyzer import create_convergence_analyzer
from .deployment_controller import create_deployment_controller
from .integration_manager import create_rsi_integration_manager
from .metrics import create_rsi_metrics
from .recursive_ratchet_pruner import RecursiveRatchetPruner, Candidate
from .rollback_manager import create_rollback_manager
from .self_improvement_proposer import SelfImprovementProposer, ProposalType
from .system_performance import get_setpoint

logger = get_logger(__name__)


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
        self, sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any, **kwargs
    ):
        """
        初始化 RSI 编排器

        Args:
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

        # 创建部署控制器
        self.deployment_controller = create_deployment_controller()

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
        self.self_improvement_proposer = SelfImprovementProposer()

        # 迭代计数器
        self._iteration_count = 0

        logger.info("RSIOrchestrator initialized")

    def _measure_performance(self) -> float:
        """实测当前整体性能：四系统 setpoint 梯度估算的平均值。"""
        from .system_performance import estimate_system_performance

        signals = self.collect_feedback_signals()
        optimizable = self.integration_manager.get_optimizable_parameters()

        scores = []
        for system_name in self.integration_manager._systems:
            feedback = signals.get(system_name, {})
            if not isinstance(feedback, dict):
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

    def run_iteration(self) -> Dict[str, Any]:
        """
        运行一次 RSI 迭代（真实棘轮：应用 → 实测 → 保留/回滚）

        Returns:
            Dict[str, Any]: 迭代结果，包含：
                - feedback_signals: 反馈信号
                - convergence: 收敛性分析
                - optimizations: 优化建议
                - applied_results: 实际应用结果
                - applied_count: 成功应用的优化数
                - gain: 应用后的实测性能增益（有害调整回滚后为 0）
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
        gain = 0.0

        if optimizations and self.deployment_controller.can_auto_execute("low"):
            perf_before = self._measure_performance()
            snapshot = self._snapshot_optimizable()

            applied_results = self.apply_optimizations(optimizations)
            applied_count = sum(1 for r in applied_results if r.get("applied"))

            if applied_count:
                perf_after = self._measure_performance()
                gain = perf_after - perf_before
                if gain < 0:
                    # 有害调整：回滚到应用前快照（失控漂移的本质防护）
                    self._restore_optimizable(snapshot)
                    applied_count = 0
                    gain = 0.0

        # 5. 喂入收敛数据——只喂有意义的迭代。
        # 此前每轮无条件喂 gain=0，导致"什么都没做却被判定收敛"的虚假收敛。
        if applied_count > 0 or gain != 0.0:
            cost = 1.0  # 固定迭代成本
            self.convergence_analyzer.record_iteration(gain=gain, cost=cost)

        # 6. 更新指标
        self.metrics.record_metric("iteration_count", self._iteration_count)
        self.metrics.record_metric("feedback_signals_count", len(feedback_signals))
        self.metrics.record_metric("optimizations_count", len(optimizations))
        self.metrics.record_metric("applied_count", applied_count)

        # 7. P0-A3 修复：检测到发散/振荡时，升级给 SelfImprovementProposer
        escalation_proposals = self._escalate_to_proposer_if_needed(convergence, feedback_signals)

        # 8. 更新迭代计数
        self._iteration_count += 1

        # 9. 阶段自动评估（遗留事项 ① 接线）：evaluate_phase_transition 此前零
        # 调用方——phase 永远停在观察期，can_auto_execute("low") 恒 False。
        # 判据通过后由 advance_phase 真正推进（判据与推进分离是 controller 原设计）。
        phase_advanced = False
        try:
            phase_metrics = {
                "convergence_status": convergence.get("status", ""),
                "roi": float((convergence.get("metrics") or {}).get("roi", 0.0) or 0.0)
                if isinstance(convergence.get("metrics"), dict)
                else 0.0,
                "days_without_rollback": float(
                    self.metrics.get_metric("days_without_rollback") or 0
                ),
            }
            if self.deployment_controller.evaluate_phase_transition(phase_metrics):
                new_phase = self.deployment_controller.advance_phase()
                phase_advanced = True
                logger.info("RSI 部署阶段推进至 %s", new_phase)
        except Exception as e:  # noqa: BLE001 - 阶段评估故障不影响迭代主流程
            logger.debug("阶段推进评估跳过: %s", e)

        return {
            "feedback_signals": feedback_signals,
            "convergence": convergence,
            "optimizations": optimizations,
            "applied_results": applied_results,
            "applied_count": applied_count,
            "gain": gain,
            "escalation_proposals": escalation_proposals,
            "phase_advanced": phase_advanced,
            "metrics": self.metrics.get_dashboard_data(),
        }

    def _escalate_to_proposer_if_needed(
        self, convergence: Dict[str, Any], feedback_signals: Dict[str, Any]
    ) -> List[str]:
        """P0-A3：当自动参数调整失效时升级到 SelfImprovementProposer

        触发条件：convergence status 为 diverging 或 oscillating 且 trend_slope < 0
        动作：根据失效的系统创建 skill_manifest 提案（低风险路径），
              保留所有提案为 PENDING 状态等待人工评审。

        Args:
            convergence: 收敛性分析结果
            feedback_signals: 反馈信号（用于定位失效系统）

        Returns:
            List[str]: 创建的提案 ID 列表（可能为空）
        """
        status = convergence.get("status")
        metrics = convergence.get("metrics", {}) or {}
        trend_slope = metrics.get("trend_slope", 0)

        # 只在发散或振荡+负趋势时升级
        needs_escalation = status == "diverging" or (
            status == "oscillating" and isinstance(trend_slope, (int, float)) and trend_slope < 0
        )
        if not needs_escalation:
            return []

        proposal_ids: List[str] = []
        # 为每个性能低下的系统创建一个 skill_manifest 提案
        # （skill_manifest 是低风险路径，适合作为首次升级手段）
        for system_name, signals in feedback_signals.items():
            if not isinstance(signals, dict):
                continue
            performance = self._extract_performance(signals)
            # 只为性能确实低下的系统提案（避免无的放矢）
            if performance is None or performance >= 0.5:
                continue

            skill_id = f"rsi_escalation_{system_name}_{self._iteration_count}"
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
                proposal_ids.append(proposal.proposal_id)
                logger.info(
                    "RSI 升级：为系统 %s 创建 skill_manifest 提案 %s（performance=%.2f, convergence=%s）",
                    system_name,
                    proposal.proposal_id,
                    performance,
                    status,
                )
            except Exception as e:
                logger.warning(
                    "RSI 升级失败：系统 %s 提案创建异常: %s", system_name, e, exc_info=True
                )

        return proposal_ids

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

    def _compute_ratchet_adjustment_ratio(
        self, param_name: str, current_value: Any, performance: float, ratio: float
    ) -> Optional[Any]:
        """基于指定调整幅度计算棘轮调整值"""
        param_lower = param_name.lower()

        # 阈值类参数：性能低时降低阈值（更激进），性能高时提高阈值（更保守）
        if "threshold" in param_lower:
            if performance < 0.7:
                return current_value * (1 - ratio)
            elif performance > 0.9:
                return current_value * (1 + ratio)
            return None

        # rate/factor/bonus/penalty 类参数
        if any(suffix in param_lower for suffix in ("rate", "factor", "bonus", "penalty")):
            if performance < 0.7:
                return current_value * (1 + ratio)
            elif performance > 0.9:
                return current_value * (1 - ratio)
            return None

        return None

    def _generate_optimization_for_param(
        self, system_name: str, param_info: Any, signals: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        为单个参数生成优化建议（基于反馈信号的棘轮策略）

        优化策略：
        - 提取系统性能指标（performance_score / success_rate / stability）
        - 阈值类参数：性能低 → 降低阈值（更激进）；性能高 → 提高阈值（更保守）
        - rate/factor 类参数：基于性能微调（性能低 → 增大奖励/惩罚）
        - 只生成小幅调整（±10%），避免剧烈变化（棘轮原则：单调小幅改进）

        Args:
            system_name: 系统名称
            param_info: ParameterInfo 对象（含 name/current_value/description/system）
            signals: 系统反馈信号

        Returns:
            Optional[Dict[str, Any]]: 优化建议或 None（无信号/无性能指标时返回 None）
        """
        # 提取系统性能指标（0.0-1.0）
        performance = self._extract_performance(signals)
        if performance is None:
            return None  # 无性能指标，不生成优化（避免无依据调整）

        param_name = param_info.name
        current_value = param_info.current_value
        if current_value is None:
            return None  # 系统未暴露此参数，无法优化

        # 棘轮策略：基于参数名后缀决定调整方向
        new_value = self._compute_ratchet_adjustment(param_name, current_value, performance)
        if new_value is None or new_value == current_value:
            return None

        return {
            "system": system_name,
            "parameter": f"{system_name}.{param_name}",
            "current_value": current_value,
            "new_value": new_value,
            "performance": performance,
            "reason": f"性能={performance:.2f}，调整 {param_name} 从 {current_value} 到 {new_value}",
        }

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

    def _compute_ratchet_adjustment(
        self, param_name: str, current_value: Any, performance: float
    ) -> Optional[Any]:
        """基于参数名后缀和性能计算棘轮调整值

        阈值类（含 threshold）：性能低→降低阈值；性能高→提高阈值
        rate/factor/bonus/penalty 类：性能低→增大；性能高→减小
        其他：不调整

        调整幅度固定 10%（棘轮原则：小幅单调改进）
        """
        if not isinstance(current_value, (int, float)):
            return None

        param_lower = param_name.lower()
        adjustment_ratio = 0.10  # 固定 10% 调整

        # 阈值类参数：性能低时降低阈值（更激进），性能高时提高阈值（更保守）
        if "threshold" in param_lower:
            if performance < 0.7:
                return current_value * (1 - adjustment_ratio)
            elif performance > 0.9:
                return current_value * (1 + adjustment_ratio)
            return None

        # rate/factor/bonus/penalty 类参数：性能低时增大调整力度
        if any(suffix in param_lower for suffix in ("rate", "factor", "bonus", "penalty")):
            if performance < 0.7:
                # 对 penalty 类反向（性能低时增大惩罚）
                if "penalty" in param_lower:
                    return current_value * (1 + adjustment_ratio)
                return current_value * (1 + adjustment_ratio)
            elif performance > 0.9:
                if "penalty" in param_lower:
                    return current_value * (1 - adjustment_ratio)
                return current_value * (1 - adjustment_ratio)
            return None

        # 其他参数类型不自动调整
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

    def get_status(self) -> Dict[str, Any]:
        """
        获取 RSI 状态

        Returns:
            Dict[str, Any]: 状态信息，包含：
                - iteration_count: 迭代次数
                - convergence_status: 收敛状态
                - deployment_phase: 部署阶段
                - metrics: 监控指标
        """
        convergence = self.convergence_analyzer.analyze_convergence()

        return {
            "iteration_count": self._iteration_count,
            "convergence_status": convergence.get("status", "unknown"),
            "deployment_phase": self.deployment_controller.get_current_phase(),
            "metrics": self.metrics.get_dashboard_data(),
        }


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
