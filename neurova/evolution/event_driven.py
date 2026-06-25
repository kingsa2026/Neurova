"""
进化系统事件驱动闭环 — 连接 EventBus 与进化系统

实现 EvolutionEventBridge 深度模块：
- 小接口：start, stop, get_statistics
- 深实现：事件订阅、发布、过滤、链式触发
- 向后兼容：不修改现有 EvolutionOrchestrator

事件流：
  tool.execution.completed → EvolutionEventBridge → EvolutionOrchestrator → evolution.tool.weight_updated
  experience.recorded → EvolutionEventBridge → EvolutionOrchestrator → evolution.cycle.completed
"""

from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from neurova.core.event_bus import Event, EventBus, Subscription
from neurova.core.event_bus_enhanced import EventBusEnhanced

logger = get_logger(__name__)


@dataclass
class EvolutionEvent:
    """进化事件数据"""
    tool_name: str
    success: bool = True
    latency: float = 0.0
    context: str = ""
    weight_before: float = 1.0
    weight_after: float = 1.0
    lifecycle_state: str = "active"


class EvolutionEventBridge:
    """
    进化系统事件桥接器 — 连接 EventBus 与进化系统

    深度模块设计：
    - 小接口：3个方法（start, stop, get_statistics）
    - 深实现：事件订阅、发布、过滤、链式触发
    - 向后兼容：不修改现有 EvolutionOrchestrator
    """

    # 事件名称常量
    EVT_TOOL_EXECUTED = "evolution.tool.executed"
    EVT_TOOL_WEIGHT_UPDATED = "evolution.tool.weight_updated"
    EVT_TOOL_LIFECYCLE_CHANGED = "evolution.tool.lifecycle_changed"
    EVT_EXPERIENCE_RECORDED = "evolution.experience.recorded"
    EVT_EVOLUTION_CYCLE_COMPLETED = "evolution.cycle.completed"

    def __init__(self, event_bus: Optional[EventBusEnhanced] = None):
        self._event_bus = event_bus
        self._orchestrator = None
        self._subscriptions: List[Subscription] = []
        self._running = False
        self._stats = {
            "events_published": 0,
            "events_received": 0,
            "weight_updates": 0,
            "lifecycle_changes": 0,
            "cycles_completed": 0,
        }

    def set_orchestrator(self, orchestrator) -> None:
        """注入进化编排器"""
        self._orchestrator = orchestrator

    def start(self) -> None:
        """启动事件桥接"""
        if self._running:
            return

        if not self._event_bus:
            return

        # 订阅工具执行完成事件
        sub1 = self._event_bus.subscribe(
            "tool.execution.completed",
            self._on_tool_execution_completed,
        )
        self._subscriptions.append(sub1)

        # 订阅经验记录事件
        sub2 = self._event_bus.subscribe(
            "experience.recorded",
            self._on_experience_recorded,
        )
        self._subscriptions.append(sub2)

        self._running = True
        logger.info("EvolutionEventBridge started")

    def stop(self) -> None:
        """停止事件桥接"""
        if not self._running:
            return

        if self._event_bus:
            for sub in self._subscriptions:
                self._event_bus.unsubscribe(sub.event_name, sub.handler)

        self._subscriptions.clear()
        self._running = False
        logger.info("EvolutionEventBridge stopped")

    def _on_tool_execution_completed(self, event: Event) -> None:
        """处理工具执行完成事件"""
        self._stats["events_received"] += 1

        if not self._orchestrator:
            return

        data = event.data or {}
        tool_name = data.get("tool_name", "")
        success = data.get("success", True)
        latency = data.get("latency", 0.0)
        context = data.get("context", "")

        if not tool_name:
            return

        # 获取更新前的权重
        weight_before = self._orchestrator.tool_weights.get_effective_weight(tool_name)

        # 调用编排器
        self._orchestrator.on_after_tool_execution(
            tool_name=tool_name,
            success=success,
            context=context,
            latency=latency,
        )

        # 获取更新后的权重
        weight_after = self._orchestrator.tool_weights.get_effective_weight(tool_name)

        self._stats["weight_updates"] += 1

        # 发布权重更新事件
        self._publish_event(
            self.EVT_TOOL_WEIGHT_UPDATED,
            EvolutionEvent(
                tool_name=tool_name,
                success=success,
                latency=latency,
                context=context,
                weight_before=weight_before,
                weight_after=weight_after,
            ),
        )

    def _on_experience_recorded(self, event: Event) -> None:
        """处理经验记录事件"""
        self._stats["events_received"] += 1

        if not self._orchestrator:
            return

        data = event.data or {}
        text = data.get("text", "")
        task = data.get("task", "")
        tools = data.get("tools", [])
        success = data.get("success", True)

        # 调用编排器
        result = self._orchestrator.on_experience_recorded(
            text=text,
            task=task,
            tools=tools,
            success=success,
        )

        self._stats["cycles_completed"] += 1

        # 发布进化周期完成事件
        self._publish_event(
            self.EVT_EVOLUTION_CYCLE_COMPLETED,
            {
                "task": task,
                "tools": tools,
                "success": success,
                "result": result,
            },
        )

    def _publish_event(self, event_name: str, data: Any) -> None:
        """发布进化事件"""
        if not self._event_bus:
            return

        self._event_bus.publish(event_name, data=data, source="EvolutionEventBridge")
        self._stats["events_published"] += 1

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "running": self._running,
            "subscriptions": len(self._subscriptions),
        }


# 单例管理
_evolution_event_bridge: Optional[EvolutionEventBridge] = None
_bridge_lock = threading.Lock()


def get_evolution_event_bridge() -> EvolutionEventBridge:
    """
    获取 EvolutionEventBridge 单例

    Returns:
        EvolutionEventBridge 实例
    """
    global _evolution_event_bridge
    if _evolution_event_bridge is None:
        with _bridge_lock:
            if _evolution_event_bridge is None:
                _evolution_event_bridge = EvolutionEventBridge()
    return _evolution_event_bridge


def reset_evolution_event_bridge() -> None:
    """
    重置 EvolutionEventBridge 单例（用于测试）
    """
    global _evolution_event_bridge
    with _bridge_lock:
        if _evolution_event_bridge is not None:
            _evolution_event_bridge.stop()
        _evolution_event_bridge = None
