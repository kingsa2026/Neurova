"""
ToolLifecycleManager v1.0.0 — 工具遗忘曲线与生命周期管理

Phase 2 P2-3: 管理工具从活跃到归档的完整生命周期。

生命周期:
  ACTIVE → DEGRADED → ARCHIVED → FROZEN
  （可通过 revive 回退到 ACTIVE）
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from neurova.evolution.persistence import PersistedStateMixin

logger = get_logger(__name__)


class ToolLifecycleState(Enum):
    """工具生命周期状态枚举。"""

    ACTIVE = "active"
    DEGRADED = "degraded"
    ARCHIVED = "archived"
    FROZEN = "frozen"


@dataclass
class ToolLifecycleEntry:
    """工具生命周期条目。"""

    tool_name: str
    state: ToolLifecycleState = ToolLifecycleState.ACTIVE
    total_calls: int = 0
    success_calls: int = 0
    failure_calls: int = 0
    last_used: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    state_changed_at: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls

    @property
    def inactive_seconds(self) -> float:
        return time.time() - self.last_used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "state": self.state.value,
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failure_calls": self.failure_calls,
            "success_rate": self.success_rate,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "inactive_seconds": self.inactive_seconds,
        }


class ToolLifecycleManager(PersistedStateMixin):
    """
    工具生命周期管理器：管理工具从活跃到归档的完整生命周期。
    """

    # 默认阈值（秒）
    DEGRADED_AFTER_SECONDS = 7 * 24 * 3600  # 7 天不活跃
    ARCHIVED_AFTER_SECONDS = 30 * 24 * 3600  # 30 天不活跃
    FROZEN_AFTER_SECONDS = 90 * 24 * 3600  # 90 天不活跃

    def __init__(
        self,
        degraded_after_seconds: Optional[float] = None,
        archived_after_seconds: Optional[float] = None,
        frozen_after_seconds: Optional[float] = None,
    ):
        # H7 修复: 使用 RLock（不是 Lock），因为 evaluate 调用 _transition、
        # get_lifecycle_report 调用 get_tools_by_state 等可重入场景
        self._lock = threading.RLock()
        self._entries: Dict[str, ToolLifecycleEntry] = {}
        # Bug 修复: 用 `or` 回退会把合法的 0.0（立即降级/归档）当作缺省值
        # 静默替换为默认阈值。改为显式 None 判断。
        self._degraded_after = (
            self.DEGRADED_AFTER_SECONDS if degraded_after_seconds is None else degraded_after_seconds
        )
        self._archived_after = (
            self.ARCHIVED_AFTER_SECONDS if archived_after_seconds is None else archived_after_seconds
        )
        self._frozen_after = (
            self.FROZEN_AFTER_SECONDS if frozen_after_seconds is None else frozen_after_seconds
        )
        # 持久化挂载（未挂载=纯内存/测试语义，零 IO）
        self._init_state_persistence()
        logger.debug("ToolLifecycleManager initialized")

    def register_tool(self, tool_name: str) -> ToolLifecycleEntry:
        """注册一个工具到生命周期管理。"""
        with self._lock:
            if tool_name not in self._entries:
                self._entries[tool_name] = ToolLifecycleEntry(tool_name=tool_name)
                logger.debug("Registered tool: %s", tool_name)
            return self._entries[tool_name]

    def touch(self, tool_name: str, success: bool = True) -> None:
        """记录工具被调用（H1: 接受 success 参数）。"""
        with self._lock:
            if tool_name not in self._entries:
                self.register_tool(tool_name)

            entry = self._entries[tool_name]
            entry.total_calls += 1
            if success:
                entry.success_calls += 1
            else:
                entry.failure_calls += 1
            entry.last_used = self._now()

            # 如果工具已降级或归档，重新激活
            if entry.state in (ToolLifecycleState.DEGRADED, ToolLifecycleState.ARCHIVED):
                self._transition(tool_name, ToolLifecycleState.ACTIVE)
        # C-15 教义：落盘在锁外执行（磁盘 IO 不串行化读路径）
        self._maybe_persist()

    def get_usage_count(self, tool_name: str) -> int:
        """获取工具总使用次数（兼容 Version A API）。"""
        with self._lock:
            entry = self._entries.get(tool_name)
            return entry.total_calls if entry else 0

    def evaluate(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """评估工具生命周期状态。"""
        with self._lock:
            if tool_name:
                if tool_name not in self._entries:
                    return {"error": f"Tool {tool_name} not found"}
                entry = self._entries[tool_name]
                return entry.to_dict()

            # 评估所有工具
            results = {}
            mutated = False
            for name, entry in self._entries.items():
                # 根据不活跃时间自动转换状态
                inactive = entry.inactive_seconds
                if inactive >= self._frozen_after and entry.state != ToolLifecycleState.FROZEN:
                    self._transition(name, ToolLifecycleState.FROZEN)
                    mutated = True
                elif inactive >= self._archived_after and entry.state not in (
                    ToolLifecycleState.ARCHIVED,
                    ToolLifecycleState.FROZEN,
                ):
                    self._transition(name, ToolLifecycleState.ARCHIVED)
                    mutated = True
                elif inactive >= self._degraded_after and entry.state == ToolLifecycleState.ACTIVE:
                    self._transition(name, ToolLifecycleState.DEGRADED)
                    mutated = True

                results[name] = entry.to_dict()

        # 仅状态迁移过才落盘（单工具查询分支是纯读，不触发 IO）
        if mutated:
            self._maybe_persist()
        return results

    def revive(self, tool_name: str) -> bool:
        """将工具恢复到 ACTIVE 状态。"""
        with self._lock:
            if tool_name not in self._entries:
                return False

            self._transition(tool_name, ToolLifecycleState.ACTIVE)
        self._maybe_persist()
        return True

    def delete_tool(self, tool_name: str) -> bool:
        """删除工具。

        安全守卫：ACTIVE 状态的工具不可直接删除（防止误删正在使用的
        工具记录）；需先归档（ARCHIVED/FROZEN）或显式 revive 流程。
        """
        with self._lock:
            entry = self._entries.get(tool_name)
            if entry is None:
                return False
            if entry.state == ToolLifecycleState.ACTIVE:
                raise ValueError(
                    f"cannot delete ACTIVE tool '{tool_name}'; archive it first"
                )
            del self._entries[tool_name]
        self._maybe_persist()
        return True

    def get_state(self, tool_name: str) -> Optional[ToolLifecycleState]:
        """获取工具的生命周期状态（H6: 返回枚举而非字符串）。"""
        with self._lock:
            if tool_name in self._entries:
                return self._entries[tool_name].state
            return None

    def apply_decay(self) -> Dict[str, int]:
        """应用遗忘衰减，返回各状态变更计数。"""
        with self._lock:
            changes: Dict[str, int] = {"degraded": 0, "archived": 0, "frozen": 0}

            for name, entry in self._entries.items():
                inactive = entry.inactive_seconds
                old_state = entry.state

                if inactive >= self._frozen_after and old_state != ToolLifecycleState.FROZEN:
                    self._transition(name, ToolLifecycleState.FROZEN)
                    changes["frozen"] += 1
                elif inactive >= self._archived_after and old_state not in (
                    ToolLifecycleState.ARCHIVED,
                    ToolLifecycleState.FROZEN,
                ):
                    self._transition(name, ToolLifecycleState.ARCHIVED)
                    changes["archived"] += 1
                elif inactive >= self._degraded_after and old_state == ToolLifecycleState.ACTIVE:
                    self._transition(name, ToolLifecycleState.DEGRADED)
                    changes["degraded"] += 1

        self._maybe_persist()
        return changes

    def get_tools_by_state(self, state: ToolLifecycleState) -> List[str]:
        """获取指定状态的工具列表。"""
        with self._lock:
            return [name for name, entry in self._entries.items() if entry.state == state]

    def get_lifecycle_report(self) -> Dict[str, int]:
        """获取生命周期报告。"""
        with self._lock:
            report = {"total": len(self._entries)}
            for state in ToolLifecycleState:
                report[state.value] = len(self.get_tools_by_state(state))
            return report

    def _transition(self, tool_name: str, new_state: ToolLifecycleState) -> None:
        """转换工具状态。"""
        with self._lock:
            if tool_name not in self._entries:
                return

            entry = self._entries[tool_name]
            old_state = entry.state
            entry.state = new_state
            entry.state_changed_at = self._now()

            logger.debug("Tool %s: %s → %s", tool_name, old_state.value, new_state.value)

    def _now(self) -> float:
        """获取当前时间。"""
        return time.time()

    def _snapshot_payload(self) -> Dict[str, Any]:
        """四态快照（锁内取数，写盘由 mixin 在锁外完成）。"""
        with self._lock:
            return {
                "version": 1,
                "tools": {
                    name: {
                        "state": entry.state.value,
                        "total_calls": entry.total_calls,
                        "success_calls": entry.success_calls,
                        "failure_calls": entry.failure_calls,
                        "last_used": entry.last_used,
                        "created_at": entry.created_at,
                        "state_changed_at": entry.state_changed_at,
                    }
                    for name, entry in self._entries.items()
                },
            }

    def _restore_payload(self, data: Dict[str, Any]) -> None:
        tools = data.get("tools", {})
        entries: Dict[str, ToolLifecycleEntry] = {}
        for name, payload in tools.items():
            try:
                state = ToolLifecycleState(payload.get("state", "active"))
            except ValueError:
                # 未知状态串 → 回退 ACTIVE（工具重新挣生命周期）
                state = ToolLifecycleState.ACTIVE
            entries[name] = ToolLifecycleEntry(
                tool_name=name,
                state=state,
                total_calls=int(payload.get("total_calls", 0)),
                success_calls=int(payload.get("success_calls", 0)),
                failure_calls=int(payload.get("failure_calls", 0)),
                last_used=float(payload.get("last_used", time.time())),
                created_at=float(payload.get("created_at", time.time())),
                state_changed_at=float(payload.get("state_changed_at", time.time())),
            )
        with self._lock:
            self._entries = entries

    def _advance_time(self, seconds: float) -> None:
        """测试辅助：将所有工具的 last_used 向前推进。"""
        for entry in self._entries.values():
            entry.last_used -= seconds
