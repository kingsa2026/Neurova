"""
RSI 回滚管理器

RSI 风险较高，必须具备自动回滚机制；同时它是阶段晋升判据
"距上次回滚多少天"的**唯一真实数据来源**（工单 004）。

此前该类在生产里只被读不被写：`orchestrator.run_iteration` 的 gain<0 分支
绕过本类直接改内存（旧 :228），于是 `get_rollback_history()` 恒空 →
`days_without_rollback` 恒 0 → phase 1→2 的 7 天要求永不可满足。
"""

from neurova.core.logger import get_logger
from neurova.evolution.persistence import PersistedStateMixin
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import uuid

logger = get_logger(__name__)

_PAYLOAD_VERSION = 2

# 回滚时间线落盘路径开关。未显式设置时**不做任何 IO** ——
# 与 `NEUROVA_RSI_RECEIPTS` 同款约定：几十个单测各自构造 RSIOrchestrator，
# 隐式写仓库 data/ 会把测试变成状态污染源。生产由 start_server/部署环境设定。
ROLLBACK_STATE_ENV = "NEUROVA_EVOLUTION_ROLLBACK"


def resolve_rollback_state_path() -> Optional[Path]:
    """回滚历史与装配时刻的落盘路径；未配置环境变量时返回 None。"""
    env_path = os.environ.get(ROLLBACK_STATE_ENV)
    return Path(env_path) if env_path else None


def _aware(value: datetime) -> datetime:
    """统一成带时区的 UTC，避免与历史 naive 时间戳相减时抛 TypeError。"""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class RSIRollbackManager(PersistedStateMixin):
    """RSI 回滚管理器"""

    def __init__(self, max_rollback_history: int = 100):
        """
        初始化回滚管理器

        Args:
            max_rollback_history: 最大回滚历史记录数
        """
        self.max_rollback_history = max_rollback_history

        # 快照存储: {snapshot_id: system_state}
        self._snapshots: Dict[str, Dict[str, Any]] = {}

        # 回滚历史
        self._rollback_history: List[Dict[str, Any]] = []

        # 装配时刻：无回滚记录时"距上次回滚多少天"的起算点。
        # 可经持久化跨重启存活；置 None 表示"起算点未知"，
        # 此时 days_since_last_rollback() 返回 None 而不是编造 0。
        self._installed_at: Optional[datetime] = datetime.now(timezone.utc)

        self._init_state_persistence()

        logger.info("RSIRollbackManager initialized with max_history=%s", max_rollback_history)

    # ── 装配时刻 ────────────────────────────────────────────────

    @property
    def installed_at(self) -> Optional[datetime]:
        return self._installed_at

    @installed_at.setter
    def installed_at(self, value: Optional[datetime]) -> None:
        self._installed_at = _aware(value) if value is not None else None
        self._maybe_persist()

    def days_since_last_rollback(self) -> Optional[float]:
        """距最近一次回滚的天数；从未回滚则距装配时刻。

        Returns:
            Optional[float]: None 表示**无任何起算证据** —— 调用方必须据此
            把该读数从判据里摘掉（`GateVerdict.unevidenced`），
            不得兜底成 0.0（那正是把"没证据"伪装成"今天刚回滚过"）。
        """
        anchor = self._installed_at
        if self._rollback_history:
            last = self._rollback_history[-1].get("timestamp")
            try:
                anchor = _aware(datetime.fromisoformat(str(last)))
            except (TypeError, ValueError):
                logger.warning("回滚记录时间戳不可解析: %r（回退装配时刻）", last)
        if anchor is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - anchor).total_seconds() / 86400.0)

    # ── 快照与回滚 ──────────────────────────────────────────────

    def create_snapshot(self, system_state: Dict[str, Any]) -> str:
        """
        创建系统状态快照

        Args:
            system_state: 系统状态

        Returns:
            str: 快照 ID
        """
        # 生成唯一 ID
        snapshot_id = str(uuid.uuid4())

        # 存储快照
        self._snapshots[snapshot_id] = system_state.copy()

        logger.debug("Created snapshot: %s", snapshot_id)
        return snapshot_id

    def should_rollback(self, metrics: Dict[str, Any]) -> bool:
        """
        判断是否应该回滚

        Args:
            metrics: 当前指标

        Returns:
            bool: 是否应该回滚
        """
        # 检查收敛状态
        convergence_status = metrics.get("convergence_status", "")
        if convergence_status == "diverging":
            logger.warning("Divergence detected, should rollback")
            return True

        # 检查 ROI
        roi = metrics.get("roi", 0)
        if roi < 0:
            logger.warning("Negative ROI detected: %s, should rollback", roi)
            return True

        return False

    def execute_rollback(self, snapshot_id: str) -> bool:
        """
        执行回滚到指定快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            bool: 是否成功回滚
        """
        # 检查快照是否存在
        if snapshot_id not in self._snapshots:
            logger.error("Snapshot not found: %s", snapshot_id)
            return False

        # 获取快照
        system_state = self._snapshots[snapshot_id]

        # 记录回滚历史
        rollback_record = {
            "snapshot_id": snapshot_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_state": system_state,
        }
        self._rollback_history.append(rollback_record)

        # 清理旧历史记录
        if len(self._rollback_history) > self.max_rollback_history:
            self._rollback_history = self._rollback_history[-self.max_rollback_history:]

        # 回滚留痕即治理事件：即时落盘，不走 `_maybe_persist` 的 10s 节流。
        # 一次回滚可能决定阶段晋升能否发生；若在节流窗口内进程退出，
        # 判据就永久看不到它 —— 这恰是工单 004 要消灭的"证据静默丢失"。
        # 回滚本身低频（仅在实测增益为负时发生），即时写的开销可忽略。
        self.save()

        logger.info("Executed rollback to snapshot: %s", snapshot_id)
        return True

    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """
        获取回滚历史

        Returns:
            List[Dict[str, Any]]: 回滚历史记录
        """
        return self._rollback_history.copy()

    # ── PersistedStateMixin 钩子 ────────────────────────────────

    def _snapshot_payload(self) -> Dict[str, Any]:
        return {
            "version": _PAYLOAD_VERSION,
            "installed_at": self._installed_at.isoformat() if self._installed_at else None,
            "history": self._rollback_history[-self.max_rollback_history:],
        }

    def _restore_payload(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        installed_at = data.get("installed_at")
        if isinstance(installed_at, str):
            try:
                self._installed_at = _aware(datetime.fromisoformat(installed_at))
            except ValueError:
                logger.warning("installed_at 不可解析，保留现值: %r", installed_at)
        history = data.get("history")
        if isinstance(history, list):
            self._rollback_history = [r for r in history if isinstance(r, dict)]


def create_rollback_manager(max_rollback_history: int = 100) -> RSIRollbackManager:
    """
    创建 RSI 回滚管理器实例
    """
    return RSIRollbackManager(max_rollback_history)
