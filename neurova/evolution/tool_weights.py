"""
自适应工具权重 (AdaptiveToolWeights)

基于强化学习思想：每个工具有基础权重，根据执行结果的
成功/失败动态调整自适应倍数，并通过时间衰减淘汰长期
不用的工具。

核心公式:
  effective_weight = base_weight × adaptive_multiplier

成功激励 (递减收益):
  multiplier += success_bonus / (1 + success_count)

失败惩罚:
  multiplier *= failure_penalty

时间衰减:
  multiplier *= exp(-decay_rate × hours_since_last_use)
"""

from dataclasses import dataclass, field
import math
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolWeightEntry:
    """工具权重条目"""
    tool_name: str
    base_weight: float = 1.0
    adaptive_multiplier: float = 1.0
    success_count: int = 0
    failure_count: int = 0
    total_uses: int = 0
    last_used: float = field(default_factory=time.time)
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    window: List[Tuple[float, bool]] = field(default_factory=list)  # (timestamp, success)

    @property
    def effective_weight(self) -> float:
        return self.base_weight * self.adaptive_multiplier

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "base_weight": self.base_weight,
            "adaptive_multiplier": self.adaptive_multiplier,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_uses": self.total_uses,
            "last_used": self.last_used,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
        }


class AdaptiveToolWeights:
    """
    自适应工具权重管理器

    根据工具使用结果动态调整权重，实现强化学习式的工具选择优化。
    """

    def __init__(
        self,
        success_bonus: float = 0.1,
        failure_penalty: float = 0.9,
        decay_rate: float = 0.01,
        window_size: int = 100,
        min_multiplier: float = 0.1,
        max_multiplier: float = 5.0,
        default_base_weight: float = 1.0,
    ):
        self._success_bonus = success_bonus
        self._failure_penalty = failure_penalty
        self._decay_rate = decay_rate
        self._window_size = window_size
        self._min_multiplier = min_multiplier
        self._max_multiplier = max_multiplier
        self._default_base_weight = default_base_weight

        self._tools: Dict[str, ToolWeightEntry] = {}
        self._lock = threading.RLock()

    def register_tool(self, tool_name: str, base_weight: Optional[float] = None):
        """注册工具"""
        with self._lock:
            if tool_name not in self._tools:
                self._tools[tool_name] = ToolWeightEntry(
                    tool_name=tool_name,
                    base_weight=base_weight if base_weight is not None else self._default_base_weight,
                )

    def _ensure_registered(self, tool_name: str):
        """确保工具已注册"""
        if tool_name not in self._tools:
            self.register_tool(tool_name)

    def get_weight(self, tool_name: str) -> float:
        """获取基础权重"""
        with self._lock:
            self._ensure_registered(tool_name)
            return self._tools[tool_name].base_weight

    def get_effective_weight(self, tool_name: str) -> float:
        """获取有效权重（考虑自适应乘数和衰减）"""
        with self._lock:
            self._ensure_registered(tool_name)
            entry = self._tools[tool_name]

            # 应用时间衰减
            self._apply_decay(entry)

            return entry.effective_weight

    def get_all_weights(self) -> Dict[str, float]:
        """获取所有工具的有效权重"""
        with self._lock:
            result = {}
            for name, entry in self._tools.items():
                self._apply_decay(entry)
                result[name] = entry.effective_weight
            return result

    def rank_tools(self, tool_names: Optional[List[str]] = None) -> List[Tuple[str, float]]:
        """按有效权重排序工具"""
        with self._lock:
            if tool_names is None:
                tool_names = list(self._tools.keys())

            ranked = []
            for name in tool_names:
                self._ensure_registered(name)
                entry = self._tools[name]
                self._apply_decay(entry)
                ranked.append((name, entry.effective_weight))

            ranked.sort(key=lambda x: x[1], reverse=True)
            return ranked

    def record_success(self, tool_name: str, metadata: Optional[Dict[str, Any]] = None):
        """记录工具使用成功"""
        with self._lock:
            self._ensure_registered(tool_name)
            entry = self._tools[tool_name]
            now = time.time()

            entry.success_count += 1
            entry.total_uses += 1
            entry.last_used = now
            entry.last_success = now

            # 递减收益的成功激励
            bonus = self._success_bonus / (1 + entry.success_count * 0.1)
            entry.adaptive_multiplier = min(
                self._max_multiplier,
                entry.adaptive_multiplier + bonus
            )

            # 更新窗口
            entry.window.append((now, True))
            self._trim_window(entry)

    def record_failure(self, tool_name: str, metadata: Optional[Dict[str, Any]] = None):
        """记录工具使用失败"""
        with self._lock:
            self._ensure_registered(tool_name)
            entry = self._tools[tool_name]
            now = time.time()

            entry.failure_count += 1
            entry.total_uses += 1
            entry.last_used = now
            entry.last_failure = now

            # 失败惩罚
            entry.adaptive_multiplier = max(
                self._min_multiplier,
                entry.adaptive_multiplier * self._failure_penalty
            )

            # 更新窗口
            entry.window.append((now, False))
            self._trim_window(entry)

    def _apply_decay(self, entry: ToolWeightEntry):
        """应用时间衰减"""
        now = time.time()
        hours_since_use = (now - entry.last_used) / 3600.0

        if hours_since_use > 0.1:  # 至少 6 分钟才衰减
            decay = math.exp(-self._decay_rate * hours_since_use)
            entry.adaptive_multiplier = max(
                self._min_multiplier,
                entry.adaptive_multiplier * decay
            )

    def _trim_window(self, entry: ToolWeightEntry):
        """修剪窗口"""
        if len(entry.window) > self._window_size:
            entry.window = entry.window[-self._window_size:]

    def get_tool_entry(self, tool_name: str) -> Optional[ToolWeightEntry]:
        """获取工具条目（只读副本）"""
        with self._lock:
            entry = self._tools.get(tool_name)
            if entry:
                self._apply_decay(entry)
            return entry

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_tools = len(self._tools)
            total_successes = sum(e.success_count for e in self._tools.values())
            total_failures = sum(e.failure_count for e in self._tools.values())
            total_uses = sum(e.total_uses for e in self._tools.values())

            weights = [e.effective_weight for e in self._tools.values()]
            avg_weight = sum(weights) / len(weights) if weights else 0.0

            return {
                "total_tools": total_tools,
                "total_successes": total_successes,
                "total_failures": total_failures,
                "total_uses": total_uses,
                "avg_effective_weight": round(avg_weight, 4),
                "success_rate": round(total_successes / max(1, total_uses), 4),
            }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "tools": {name: entry.to_dict() for name, entry in self._tools.items()},
                "config": {
                    "success_bonus": self._success_bonus,
                    "failure_penalty": self._failure_penalty,
                    "decay_rate": self._decay_rate,
                    "window_size": self._window_size,
                }
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdaptiveToolWeights":
        """从字典反序列化"""
        config = data.get("config", {})
        instance = cls(**config)

        for name, tool_data in data.get("tools", {}).items():
            entry = ToolWeightEntry(
                tool_name=tool_data["tool_name"],
                base_weight=tool_data.get("base_weight", 1.0),
                adaptive_multiplier=tool_data.get("adaptive_multiplier", 1.0),
                success_count=tool_data.get("success_count", 0),
                failure_count=tool_data.get("failure_count", 0),
                total_uses=tool_data.get("total_uses", 0),
                last_used=tool_data.get("last_used", time.time()),
                last_success=tool_data.get("last_success"),
                last_failure=tool_data.get("last_failure"),
            )
            instance._tools[name] = entry

        return instance


# ────── 单例管理 ──────

_weights_instance: Optional[AdaptiveToolWeights] = None
_instance_lock = threading.Lock()


def get_adaptive_tool_weights(**kwargs) -> AdaptiveToolWeights:
    """获取自适应工具权重单例"""
    global _weights_instance
    if _weights_instance is None:
        with _instance_lock:
            if _weights_instance is None:
                _weights_instance = AdaptiveToolWeights(**kwargs)
    return _weights_instance


def reset_adaptive_tool_weights():
    """重置自适应工具权重单例"""
    global _weights_instance
    with _instance_lock:
        _weights_instance = None