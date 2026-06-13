"""
LoopManager 深度模块 - Agent Loop 生命周期管理

提供统一的 Loop 管理接口，包括：
1. 初始化和重建 Loop
2. 状态机管理 (INITIALIZING, READY, DEGRADED, FAILED)
3. 智能降级（保留功能子集）
4. 状态变更回调

设计原则：
- 深度模块：小接口，深实现
- 状态机：清晰的状态转换
- 可测试：接口清晰，易于 mock
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, List, Optional

from neurova.agent.loops.registry import find_agent_loop

logger = logging.getLogger(__name__)


class LoopState(Enum):
    """Loop 状态枚举"""

    INITIALIZING = "initializing"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class LoopEvent:
    """Loop 状态变更事件"""

    old_state: LoopState
    new_state: LoopState
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "old_state": self.old_state.value,
            "new_state": self.new_state.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class LoopManager:
    """
    Agent Loop 生命周期管理器

    封装 Loop 的初始化、重建、状态管理等功能，
    提供统一的接口和智能降级策略。

    使用示例：
        manager = LoopManager(agent)
        await manager.initialize()

        # 获取 Loop
        loop = manager.get_loop()
        if loop:
            response = await loop.predict_step(messages)

        # 状态变更回调
        manager.on_state_change(lambda event: print(f"State changed: {event}"))
    """

    def __init__(self, agent: Any):
        """
        初始化 LoopManager

        参数:
            agent: Agent 实例，提供对配置和其他系统的访问
        """
        self._agent = agent
        self._loop = None
        self._state = LoopState.INITIALIZING
        self._state_callbacks: List[Callable[[LoopEvent], None]] = []
        self._start_time = time.time()
        self._last_model: Optional[str] = None

        logger.debug("LoopManager initialized for agent: %s", getattr(agent.config, 'name', 'unknown'))

    @property
    def agent(self) -> Any:
        """获取 Agent 实例"""
        return self._agent

    def get_loop(self) -> Optional[Any]:
        """
        获取当前 Loop 实例

        返回:
            BaseAgentLoop 实例，如果未初始化或失败则返回 None
        """
        return self._loop

    def get_state(self) -> LoopState:
        """
        获取当前状态

        返回:
            LoopState 枚举值
        """
        return self._state

    def get_health(self) -> dict:
        """
        获取健康信息

        返回:
            包含状态、Loop类型、模型、运行时间等信息的字典
        """
        loop_type = type(self._loop).__name__ if self._loop else None
        model = getattr(self._agent.config.llm_config, "model", None)
        uptime = time.time() - self._start_time

        return {
            "state": self._state.value,
            "loop_type": loop_type,
            "model": model,
            "last_model": self._last_model,
            "uptime_seconds": uptime,
            "has_loop": self._loop is not None,
        }

    def initialize_sync(self) -> bool:
        """
        同步初始化 Loop（供 __init__ 调用）

        根据配置的模型自动选择合适的 Loop 类型。

        返回:
            True 表示初始化成功，False 表示失败
        """
        if self._state == LoopState.READY and self._loop is not None:
            logger.warning("Loop already initialized, use force_reinitialize() to reinitialize")
            return True

        self._set_state(LoopState.INITIALIZING, "Starting loop initialization")

        try:
            # 获取模型名称
            model_name = getattr(self._agent.config.llm_config, "model", None)
            if not model_name:
                logger.error("No model configured")
                self._set_state(LoopState.FAILED, "No model configured")
                return False

            self._last_model = model_name

            # 查找合适的 Loop 类
            loop_class = find_agent_loop(model_name)

            if not loop_class:
                logger.warning("No suitable Loop found for model: %s", model_name)
                self._set_state(LoopState.FAILED, f"No Loop found for model: {model_name}")
                return False

            # 实例化 Loop
            loop_instance = loop_class(self._agent)

            # 检查 Loop 功能
            if not self._check_loop_functionality(loop_instance):
                logger.warning("Loop %s has limited functionality", loop_class.__name__)
                self._loop = loop_instance
                self._set_state(LoopState.DEGRADED, f"Loop {loop_class.__name__} has limited functionality")
                return True

            self._loop = loop_instance
            self._set_state(LoopState.READY, f"Loop {loop_class.__name__} initialized successfully")

            logger.info("Agent Loop initialized: %s " f"(model=%s)", loop_class.__name__, model_name)
            return True

        except Exception as e:
            logger.error("Agent Loop initialization failed: %s", e)
            self._set_state(LoopState.FAILED, f"Initialization failed: {str(e)}")
            return False

    async def initialize(self) -> bool:
        """
        异步初始化 Loop

        根据配置的模型自动选择合适的 Loop 类型。

        返回:
            True 表示初始化成功，False 表示失败
        """
        return self.initialize_sync()

    async def rebuild(self, model_name: str) -> bool:
        """
        重建 Loop（模型热切换时调用）

        当模型切换后，需要重新选择合适的 Loop 类型。

        参数:
            model_name: 新的模型名称

        返回:
            True 表示重建成功，False 表示失败
        """
        if not model_name:
            logger.error("No model name provided for rebuild")
            return False

        # 如果是相同模型，直接返回成功
        if model_name == self._last_model and self._loop is not None:
            logger.debug("Same model %s, no rebuild needed", model_name)
            return True

        old_loop_name = type(self._loop).__name__ if self._loop else "None"
        old_loop = self._loop
        loop_class_name = None

        try:
            # 更新配置中的模型名
            self._agent.config.llm_config.model = model_name
            self._last_model = model_name

            # 查找新模型对应的 Loop 类
            loop_class = find_agent_loop(model_name)
            loop_class_name = loop_class.__name__ if loop_class else None

            if not loop_class:
                logger.warning("No suitable Loop found for model: %s", model_name)
                return False

            # 实例化新 Loop
            new_loop = loop_class(self._agent)

            # 检查新 Loop 功能
            if not self._check_loop_functionality(new_loop):
                logger.warning("New Loop %s has limited functionality", loop_class.__name__)
                self._loop = new_loop
                self._set_state(LoopState.DEGRADED, f"Rebuilt to {loop_class.__name__} with limited functionality")
                return True

            # 替换 Loop
            self._loop = new_loop
            self._set_state(LoopState.READY, f"Loop rebuilt: {old_loop_name} → {loop_class.__name__}")

            logger.info("Agent Loop rebuilt: %s → %s " f"(model=%s)", old_loop_name, loop_class.__name__, model_name)
            return True

        except Exception as e:
            logger.error("Agent Loop rebuild failed: %s → %s: %s", old_loop_name, loop_class_name or 'None', e)
            # 保留旧 Loop
            self._loop = old_loop
            return False

    async def force_reinitialize(self) -> bool:
        """
        强制重新初始化 Loop

        无论当前状态如何，都会重新初始化。

        返回:
            True 表示初始化成功，False 表示失败
        """
        # 重置状态
        self._loop = None
        self._state = LoopState.INITIALIZING

        return await self.initialize()

    def on_state_change(self, callback: Callable[[LoopEvent], None]) -> None:
        """
        注册状态变更回调

        参数:
            callback: 回调函数，接收 LoopEvent 参数
        """
        if callback not in self._state_callbacks:
            self._state_callbacks.append(callback)

    def remove_state_change_callback(self, callback: Callable[[LoopEvent], None]) -> None:
        """
        移除状态变更回调

        参数:
            callback: 要移除的回调函数
        """
        if callback in self._state_callbacks:
            self._state_callbacks.remove(callback)

    def clear_state_change_callbacks(self) -> None:
        """清除所有状态变更回调"""
        self._state_callbacks.clear()

    def _set_state(self, new_state: LoopState, message: str = "") -> None:
        """
        设置新状态并触发回调

        参数:
            new_state: 新状态
            message: 状态变更消息
        """
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state

        # 创建事件
        event = LoopEvent(
            old_state=old_state,
            new_state=new_state,
            message=message,
        )

        # 触发回调
        for callback in self._state_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error("State change callback error: %s", e)

    def _check_loop_functionality(self, loop: Any) -> bool:
        """
        检查 Loop 功能是否完整

        参数:
            loop: Loop 实例

        返回:
            True 表示功能完整，False 表示功能受限
        """
        # 检查基本功能
        if not hasattr(loop, "predict_step"):
            return False

        # 检查是否支持工具调用
        if not hasattr(loop, "handle_tool_calls"):
            logger.debug("Loop does not have handle_tool_calls method")
            # 这不是致命错误，只是功能受限

        # 检查是否标记为功能受限
        if hasattr(loop, "_tools_supported") and not loop._tools_supported:
            logger.debug("Loop has tools support disabled")
            return False

        return True

    def __repr__(self) -> str:
        """字符串表示"""
        loop_type = type(self._loop).__name__ if self._loop else "None"
        return f"LoopManager(state={self._state.value}, loop={loop_type})"
