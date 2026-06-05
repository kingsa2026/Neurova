"""
ToolLifecycleManager v1.0.0 — 工具遗忘曲线与生命周期管理

Phase 2 P2-3: 管理工具从活跃到归档的完整生命周期。

生命周期:
  ACTIVE → DEGRADED → ARCHIVED → FROZEN
  （可通过 revive 回退到 ACTIVE）
"""

from dataclasses import dataclass, field
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


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


class ToolLifecycleManager:
    """
    工具生命周期管理器：管理工具从活跃到归档的完整生命周期。
    """
    
    # 默认阈值（秒）
    DEGRADED_AFTER_SECONDS = 7 * 24 * 3600   # 7 天不活跃
    ARCHIVED_AFTER_SECONDS = 30 * 24 * 3600  # 30 天不活跃
    FROZEN_AFTER_SECONDS = 90 * 24 * 3600    # 90 天不活跃
    
    def __init__(
        self,
        degraded_after_seconds: Optional[float] = None,
        archived_after_seconds: Optional[float] = None,
        frozen_after_seconds: Optional[float] = None,
    ):
        self._entries: Dict[str, ToolLifecycleEntry] = {}
        self._degraded_after = degraded_after_seconds or self.DEGRADED_AFTER_SECONDS
        self._archived_after = archived_after_seconds or self.ARCHIVED_AFTER_SECONDS
        self._frozen_after = frozen_after_seconds or self.FROZEN_AFTER_SECONDS
        logger.debug("ToolLifecycleManager initialized")
    
    def register_tool(self, tool_name: str) -> ToolLifecycleEntry:
        """注册一个工具到生命周期管理。"""
        if tool_name not in self._entries:
            self._entries[tool_name] = ToolLifecycleEntry(tool_name=tool_name)
            logger.debug(f"Registered tool: {tool_name}")
        return self._entries[tool_name]
    
    def touch(self, tool_name: str, success: bool = True) -> None:
        """记录工具被调用。"""
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
    
    def evaluate(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """评估工具生命周期状态。"""
        if tool_name:
            if tool_name not in self._entries:
                return {"error": f"Tool {tool_name} not found"}
            entry = self._entries[tool_name]
            return entry.to_dict()
        
        # 评估所有工具
        results = {}
        for name, entry in self._entries.items():
            # 根据不活跃时间自动转换状态
            inactive = entry.inactive_seconds
            if inactive >= self._frozen_after and entry.state != ToolLifecycleState.FROZEN:
                self._transition(name, ToolLifecycleState.FROZEN)
            elif inactive >= self._archived_after and entry.state not in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.FROZEN):
                self._transition(name, ToolLifecycleState.ARCHIVED)
            elif inactive >= self._degraded_after and entry.state == ToolLifecycleState.ACTIVE:
                self._transition(name, ToolLifecycleState.DEGRADED)
            
            results[name] = entry.to_dict()
        
        return results
    
    def revive(self, tool_name: str) -> bool:
        """将工具恢复到 ACTIVE 状态。"""
        if tool_name not in self._entries:
            return False
        
        self._transition(tool_name, ToolLifecycleState.ACTIVE)
        return True
    
    def delete_tool(self, tool_name: str) -> bool:
        """删除工具。"""
        if tool_name in self._entries:
            del self._entries[tool_name]
            return True
        return False
    
    def get_state(self, tool_name: str) -> Optional[ToolLifecycleState]:
        """获取工具的生命周期状态。"""
        if tool_name in self._entries:
            return self._entries[tool_name].state
        return None
    
    def apply_decay(self) -> Dict[str, int]:
        """应用遗忘衰减，返回各状态变更计数。"""
        changes: Dict[str, int] = {"degraded": 0, "archived": 0, "frozen": 0}
        
        for name, entry in self._entries.items():
            inactive = entry.inactive_seconds
            old_state = entry.state
            
            if inactive >= self._frozen_after and old_state != ToolLifecycleState.FROZEN:
                self._transition(name, ToolLifecycleState.FROZEN)
                changes["frozen"] += 1
            elif inactive >= self._archived_after and old_state not in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.FROZEN):
                self._transition(name, ToolLifecycleState.ARCHIVED)
                changes["archived"] += 1
            elif inactive >= self._degraded_after and old_state == ToolLifecycleState.ACTIVE:
                self._transition(name, ToolLifecycleState.DEGRADED)
                changes["degraded"] += 1
        
        return changes
    
    def get_tools_by_state(self, state: ToolLifecycleState) -> List[str]:
        """获取指定状态的工具列表。"""
        return [name for name, entry in self._entries.items() if entry.state == state]
    
    def get_lifecycle_report(self) -> Dict[str, int]:
        """获取生命周期报告。"""
        report = {"total": len(self._entries)}
        for state in ToolLifecycleState:
            report[state.value] = len(self.get_tools_by_state(state))
        return report
    
    def _transition(self, tool_name: str, new_state: ToolLifecycleState) -> None:
        """转换工具状态。"""
        if tool_name not in self._entries:
            return
        
        entry = self._entries[tool_name]
        old_state = entry.state
        entry.state = new_state
        entry.state_changed_at = self._now()
        
        logger.debug(f"Tool {tool_name}: {old_state.value} → {new_state.value}")
    
    def _now(self) -> float:
        """获取当前时间。"""
        return time.time()
    
    def _advance_time(self, seconds: float) -> None:
        """测试辅助：将所有工具的 last_used 向前推进。"""
        for entry in self._entries.values():
            entry.last_used -= seconds