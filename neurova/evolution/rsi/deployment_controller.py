"""
RSI 部署控制器

RSI 风险较高，必须采用渐进式部署，从被动观察到完全自动化
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, List

from .gate_verdict import GateVerdict

logger = get_logger(__name__)


class RSIDeploymentController:
    """RSI 部署控制器"""

    # 部署阶段常量
    PHASE_0_OBSERVATION = 0
    PHASE_1_MANUAL = 1
    PHASE_2_SEMI_AUTO = 2
    PHASE_3_CONDITIONAL_AUTO = 3
    PHASE_4_FULL_AUTO = 4

    def __init__(self, initial_phase: int = 0):
        """
        初始化部署控制器

        Args:
            initial_phase: 初始阶段
        """
        # 验证初始阶段
        if initial_phase < 0 or initial_phase > 4:
            raise ValueError("Initial phase must be between 0 and 4")

        self._current_phase = initial_phase

        # 阶段描述
        self._phase_descriptions = {
            0: "观察阶段 - 只收集数据，不执行优化",
            1: "手动阶段 - 生成优化建议，人工审批",
            2: "半自动阶段 - 低风险优化自动执行",
            3: "有条件自动阶段 - 中风险优化自动执行",
            4: "完全自动阶段 - 所有优化自动执行",
        }

        # 风险级别对应的最低自动执行阶段
        self._risk_phase_mapping = {
            "low": 2,  # Phase 2 可以自动执行低风险
            "medium": 3,  # Phase 3 可以自动执行中风险
            "high": 4,  # Phase 4 可以自动执行高风险
        }

        logger.info("RSIDeploymentController initialized at phase %s", initial_phase)

    def get_current_phase(self) -> int:
        """
        获取当前部署阶段

        Returns:
            int: 当前阶段
        """
        return self._current_phase

    def can_auto_execute(self, risk_level: str) -> bool:
        """
        判断是否可以自动执行

        Args:
            risk_level: 风险级别 ('low', 'medium', 'high')

        Returns:
            bool: 是否可以自动执行
        """
        # 获取风险级别对应的最低自动执行阶段
        min_phase = self._risk_phase_mapping.get(risk_level, 4)

        # 当前阶段必须大于等于最低阶段
        return self._current_phase >= min_phase

    # 各阶段晋升所要求的"无回滚天数"门槛（phase 0 → 1 无要求）
    _REQUIRED_DAYS_WITHOUT_ROLLBACK = {0: 0, 1: 7, 2: 7, 3: 30, 4: 0}

    # 收敛读数中**可以作为晋升依据**的那些。判据用白名单而不是黑名单：
    # 黑名单会把"没被列举到的失稳态"（oscillating、分析器将来新增的状态）
    # 默认读成"没发散 ⇒ 可以推进"，与工单 003 要消灭的兜底同病。
    _PROMOTABLE_CONVERGENCE = ("converging", "converged")
    # 有读数且结论为否：无论本阶段是否"要求"该读数，一律硬否决
    _VETOING_CONVERGENCE = ("diverging", "measurement_blind")

    # 各阶段**必须具备**的读数（工单 008）。缺席即 `unevidenced`。
    #
    # 这张表按"走到这一步之前，系统有没有可能已经产生过该读数"来填，
    # 而不是每个阶段一律要三份 —— 后者会把晋升链锁成循环依赖（工单 006 移交本单的裁决）：
    # `roi` 与收敛结论只在**自动执行过参数之后**才存在，而自动执行要求先晋升到 phase 2。
    #
    # - phase 0 → 1：观察期只收数据，无风险可证，不要求；
    # - phase 1 → 2：本阶段仍未自动执行过任何东西，只有"装配以来的无回滚天数"可查，即卡口；
    # - phase 2 → 3：低风险自动执行已跑过，成本收益与收敛结论都应在盘上，转为必需；
    # - phase 3 → 4：同上，另需 30 天无回滚。
    _REQUIRED_EVIDENCE = {
        0: frozenset(),
        1: frozenset({"days_without_rollback"}),
        2: frozenset({"days_without_rollback", "roi", "convergence_status"}),
        3: frozenset({"days_without_rollback", "roi", "convergence_status"}),
    }

    def evaluate_phase_transition(self, metrics: Dict[str, Any]) -> GateVerdict:
        """评估是否应该进入下一阶段（三态判据，工单 003/008）。

        返回 `GateVerdict`：`bool(verdict)` 只在 `passed` 时为真，
        因此调用方 `if controller.evaluate_phase_transition(m):` 的旧写法无需改动，
        就不会再把"取不到数据"读成"判据通过"。

        两类判据分开处理：
        - **硬否决**（有读数且结论为否）：发散、度量失明、不可晋升的收敛读数、
          负 ROI、无回滚天数未达标
          —— 只要读数存在就生效，不因"此阶段不要求"而豁免；
        - **必需性**（该阶段必须有读数）：缺席才判 `unevidenced`。

        `measurement_blind` 是"有读数但读数是量不出来的"，由收敛分析器给出，
        在这里按硬否决处理（零证据不得当作已收敛）。
        """
        if self._current_phase >= 4:
            return GateVerdict.failed("已处于最高阶段 4，不再晋升")

        unevidenced: List[str] = []
        required = self._REQUIRED_EVIDENCE.get(self._current_phase, frozenset())

        status = metrics.get("convergence_status")
        if status in self._VETOING_CONVERGENCE:
            logger.warning("Convergence vetoes promotion: %s", status)
            return GateVerdict.failed(f"convergence_status={status}，否决晋升", status)
        if status is None or str(status).strip() == "":
            if "convergence_status" in required:
                unevidenced.append("convergence_status 缺失：无法判断是否发散")
        elif status not in self._PROMOTABLE_CONVERGENCE:
            # 有读数但不是可晋升的结论。insufficient_data 只是样本没攒够，
            # 在低阶段不阻塞（高阶段才转为必需）；其余读数（oscillating 等）一律硬否决。
            if status == "insufficient_data":
                if "convergence_status" in required:
                    unevidenced.append("convergence_status=insufficient_data：收敛分析样本不足")
            else:
                logger.warning("Non-promotable convergence reading: %s", status)
                return GateVerdict.failed(
                    f"convergence_status={status} 不是可晋升的收敛结论", status
                )

        roi = metrics.get("roi")
        if roi is None:
            if "roi" in required:
                unevidenced.append("roi 缺失：无投资回报证据可判")
        elif roi < 0:
            logger.warning("Negative ROI, not advancing phase")
            return GateVerdict.failed(f"roi={roi} 为负", roi)

        required_days = self._required_days_without_rollback()
        if required_days > 0:
            days = metrics.get("days_without_rollback")
            if days is None:
                unevidenced.append(
                    f"days_without_rollback 缺失（phase {self._current_phase} 需 ≥{required_days} 天）"
                )
            elif days < required_days:
                logger.info(
                    "Not enough days without rollback: %s < %s", days, required_days
                )
                return GateVerdict.failed(
                    f"days_without_rollback={days} 未达 phase {self._current_phase} "
                    f"要求的 {required_days} 天",
                    days,
                )

        if unevidenced:
            return GateVerdict.unevidenced("；".join(unevidenced), dict(metrics))

        return GateVerdict.passed(
            f"phase {self._current_phase} 晋升判据全部有证据且满足", dict(metrics)
        )

    def _required_days_without_rollback(self) -> int:
        return self._REQUIRED_DAYS_WITHOUT_ROLLBACK.get(self._current_phase, 0)

    def advance_phase(self) -> int:
        """
        进入下一阶段

        Returns:
            int: 新的阶段
        """
        # 如果已经在最高阶段，不能继续
        if self._current_phase >= 4:
            logger.warning("Already at maximum phase (4)")
            return self._current_phase

        # 进入下一阶段
        self._current_phase += 1

        logger.info("Advanced to phase %s: %s", self._current_phase, self._phase_descriptions[self._current_phase])
        return self._current_phase


def create_deployment_controller(initial_phase: int = 0) -> RSIDeploymentController:
    """
    创建 RSI 部署控制器实例

    Args:
        initial_phase: 初始阶段

    Returns:
        RSIDeploymentController: RSI 部署控制器实例
    """
    return RSIDeploymentController(initial_phase)


def create_deployment_controller_with_settings(settings) -> RSIDeploymentController:
    """按治理设置创建部署控制器（治理遗留收口 2026-09-05）。

    settings 里带 rsi_phase（0..4）则以之为初始阶段（管理员在设置页配置的
    部署阶段），否则维持 phase=0 观察期。非法值回退 0。
    """
    phase = 0
    try:
        raw = (settings or {}).get("rsi_phase")
        if raw is not None:
            phase = int(raw)
    except (TypeError, ValueError):
        phase = 0
    if phase < 0 or phase > 4:
        phase = 0
    return RSIDeploymentController(initial_phase=phase)
