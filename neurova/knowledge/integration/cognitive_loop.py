"""
认知闭环协调器

实现记忆系统 ↔ 心流知识库 ↔ 成长系统的三角闭环

闭环模式:
- KNOWLEDGE_DRIVEN: 知识驱动闭环（被动学习）
- PROBLEM_DRIVEN: 问题驱动闭环（主动学习）
- REFLECTION_DRIVEN: 反思驱动闭环（元认知）
- FULL_LOOP: 完整闭环（所有模式）
"""

import asyncio
from dataclasses import dataclass, field
import datetime
import enum
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.mem_core import Memory

logger = logging.getLogger(__name__)


class LoopMode(str, Enum):
    """闭环模式"""
    KNOWLEDGE_DRIVEN = "knowledge_driven"  # 知识驱动闭环
    PROBLEM_DRIVEN = "problem_driven"  # 问题驱动闭环
    REFLECTION_DRIVEN = "reflection_driven"  # 反思驱动闭环
    FULL_LOOP = "full_loop"  # 完整闭环


class TriggerType(str, Enum):
    """触发类型"""
    QUERY = "query"  # 查询触发
    MEMORY_MISS = "memory_miss"  # 记忆缺失触发
    GAP_DISCOVERY = "gap_discovery"  # 知识缺口发现
    REFLECTION = "reflection"  # 反思触发
    SCHEDULED = "scheduled"  # 定时触发
    MANUAL = "manual"  # 手动触发


@dataclass
class LoopEvent:
    """闭环事件"""
    event_id: str = field(default_factory=lambda: f"event_{int(time.time() * 1000)}")
    event_type: str = ""
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LoopEvent':
        """从字典创建"""
        return cls(
            event_id=data.get("event_id", f"event_{int(time.time() * 1000)}"),
            event_type=data.get("event_type", ""),
            source=data.get("source", ""),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )


@dataclass
class LoopConfig:
    """闭环配置"""
    mode: LoopMode = LoopMode.FULL_LOOP
    enabled: bool = True
    auto_trigger: bool = True
    trigger_interval_seconds: int = 3600
    max_events_per_loop: int = 100
    timeout_seconds: int = 300
    retry_count: int = 3
    retry_delay_seconds: int = 5
    
    # 记忆系统配置
    memory_retrieval_limit: int = 10
    memory_confidence_threshold: float = 0.7
    
    # 知识库配置
    knowledge_search_limit: int = 20
    knowledge_confidence_threshold: float = 0.6
    
    # 成长系统配置
    evolution_enabled: bool = True
    evolution_threshold: float = 0.5
    reflection_interval_hours: int = 24
    
    # 日志配置
    logging_enabled: bool = True
    log_level: str = "INFO"
    
    # 扩展配置
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "mode": self.mode.value,
            "enabled": self.enabled,
            "auto_trigger": self.auto_trigger,
            "trigger_interval_seconds": self.trigger_interval_seconds,
            "max_events_per_loop": self.max_events_per_loop,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
            "memory_retrieval_limit": self.memory_retrieval_limit,
            "memory_confidence_threshold": self.memory_confidence_threshold,
            "knowledge_search_limit": self.knowledge_search_limit,
            "knowledge_confidence_threshold": self.knowledge_confidence_threshold,
            "evolution_enabled": self.evolution_enabled,
            "evolution_threshold": self.evolution_threshold,
            "reflection_interval_hours": self.reflection_interval_hours,
            "logging_enabled": self.logging_enabled,
            "log_level": self.log_level,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LoopConfig':
        """从字典创建"""
        return cls(
            mode=LoopMode(data.get("mode", "full_loop")),
            enabled=data.get("enabled", True),
            auto_trigger=data.get("auto_trigger", True),
            trigger_interval_seconds=data.get("trigger_interval_seconds", 3600),
            max_events_per_loop=data.get("max_events_per_loop", 100),
            timeout_seconds=data.get("timeout_seconds", 300),
            retry_count=data.get("retry_count", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 5),
            memory_retrieval_limit=data.get("memory_retrieval_limit", 10),
            memory_confidence_threshold=data.get("memory_confidence_threshold", 0.7),
            knowledge_search_limit=data.get("knowledge_search_limit", 20),
            knowledge_confidence_threshold=data.get("knowledge_confidence_threshold", 0.6),
            evolution_enabled=data.get("evolution_enabled", True),
            evolution_threshold=data.get("evolution_threshold", 0.5),
            reflection_interval_hours=data.get("reflection_interval_hours", 24),
            logging_enabled=data.get("logging_enabled", True),
            log_level=data.get("log_level", "INFO"),
            metadata=data.get("metadata", {})
        )


@dataclass
class LoopStats:
    """闭环统计"""
    total_loops: int = 0
    successful_loops: int = 0
    failed_loops: int = 0
    total_events: int = 0
    knowledge_driven_loops: int = 0
    problem_driven_loops: int = 0
    reflection_driven_loops: int = 0
    avg_loop_duration_ms: float = 0.0
    last_loop_time: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_loops": self.total_loops,
            "successful_loops": self.successful_loops,
            "failed_loops": self.failed_loops,
            "total_events": self.total_events,
            "knowledge_driven_loops": self.knowledge_driven_loops,
            "problem_driven_loops": self.problem_driven_loops,
            "reflection_driven_loops": self.reflection_driven_loops,
            "avg_loop_duration_ms": self.avg_loop_duration_ms,
            "last_loop_time": self.last_loop_time
        }


class CognitiveLoopCoordinator:
    """
    认知闭环协调器
    
    功能：
    1. 协调记忆系统、知识库和成长系统
    2. 实现不同模式的闭环
    3. 管理闭环事件和统计
    """
    
    def __init__(self, config: Optional[LoopConfig] = None):
        """
        初始化认知闭环协调器
        
        Args:
            config: 闭环配置
        """
        self.config = config or LoopConfig()
        
        # 统计信息
        self.stats = LoopStats()
        
        # 事件队列
        self._event_queue: asyncio.Queue = asyncio.Queue()
        
        # 回调函数
        self._callbacks: Dict[str, List[Callable]] = {
            "on_loop_start": [],
            "on_loop_end": [],
            "on_knowledge_driven": [],
            "on_problem_driven": [],
            "on_reflection_driven": [],
            "on_error": []
        }
        
        # 运行状态
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 依赖组件（延迟初始化）
        self._memory_system = None
        self._knowledge_base = None
        self._evolution_hub = None
        
        logger.info(f"CognitiveLoopCoordinator initialized: mode={self.config.mode.value}")
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """注册回调函数"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def trigger(self, trigger_type: TriggerType, 
               data: Optional[Dict[str, Any]] = None) -> str:
        """
        触发闭环
        
        Args:
            trigger_type: 触发类型
            data: 触发数据
            
        Returns:
            事件ID
        """
        event = LoopEvent(
            event_type=trigger_type.value,
            source="manual",
            data=data or {}
        )
        
        # 添加到队列
        self._event_queue.put_nowait(event)
        
        logger.info(f"Triggered loop: {trigger_type.value}, event_id={event.event_id}")
        return event.event_id
    
    async def start(self) -> None:
        """启动闭环协调器"""
        if self._running:
            logger.warning("CognitiveLoopCoordinator is already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._loop_runner())
        
        logger.info("CognitiveLoopCoordinator started")
    
    async def stop(self) -> None:
        """停止闭环协调器"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("CognitiveLoopCoordinator stopped")
    
    async def _loop_runner(self) -> None:
        """闭环运行器"""
        logger.info("Loop runner started")
        
        while self._running:
            try:
                # 等待事件
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(),
                        timeout=self.config.trigger_interval_seconds
                    )
                except asyncio.TimeoutError:
                    # 定时触发
                    if self.config.auto_trigger:
                        event = LoopEvent(
                            event_type=TriggerType.SCHEDULED.value,
                            source="auto"
                        )
                    else:
                        continue
                
                # 执行闭环
                await self._execute_loop(event)
                
                # 更新统计
                self.stats.total_events += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Loop runner error: {e}")
                await asyncio.sleep(1)
        
        logger.info("Loop runner stopped")
    
    async def _execute_loop(self, event: LoopEvent) -> None:
        """执行闭环"""
        start_time = time.time()
        
        try:
            # 触发开始回调
            await self._safe_callback("on_loop_start", event)
            
            # 根据模式执行
            if self.config.mode == LoopMode.KNOWLEDGE_DRIVEN:
                await self._knowledge_to_memory(event)
                self.stats.knowledge_driven_loops += 1
                
            elif self.config.mode == LoopMode.PROBLEM_DRIVEN:
                await self._handle_memory_miss(event)
                self.stats.problem_driven_loops += 1
                
            elif self.config.mode == LoopMode.REFLECTION_DRIVEN:
                await self._execute_reflection(event)
                self.stats.reflection_driven_loops += 1
                
            elif self.config.mode == LoopMode.FULL_LOOP:
                # 执行完整闭环
                await self._knowledge_to_memory(event)
                await self._knowledge_to_evolution(event)
                await self._check_gap_discovery(event)
                await self._evolution_feedback(event)
            
            # 更新统计
            self.stats.successful_loops += 1
            self.stats.total_loops += 1
            
            # 计算平均时长
            duration_ms = (time.time() - start_time) * 1000
            if self.stats.avg_loop_duration_ms == 0:
                self.stats.avg_loop_duration_ms = duration_ms
            else:
                self.stats.avg_loop_duration_ms = (
                    self.stats.avg_loop_duration_ms * 0.9 + duration_ms * 0.1
                )
            
            self.stats.last_loop_time = time.time()
            
            # 触发结束回调
            await self._safe_callback("on_loop_end", event, duration_ms)
            
            logger.info(f"Loop executed: {event.event_type}, duration={duration_ms:.2f}ms")
            
        except Exception as e:
            self.stats.failed_loops += 1
            self.stats.total_loops += 1
            
            logger.error(f"Loop execution failed: {e}")
            
            # 触发错误回调
            await self._safe_callback("on_error", event, str(e))
    
    async def _knowledge_to_memory(self, event: LoopEvent) -> None:
        """知识到记忆的闭环"""
        logger.debug("Executing knowledge_to_memory loop")
        
        # 这里应该调用知识库和记忆系统的接口
        # 简化实现：记录日志
        pass
    
    async def _knowledge_to_evolution(self, event: LoopEvent) -> None:
        """知识到成长的闭环"""
        logger.debug("Executing knowledge_to_evolution loop")
        
        # 这里应该调用知识库和成长系统的接口
        # 简化实现：记录日志
        pass
    
    async def _handle_memory_miss(self, event: LoopEvent) -> None:
        """处理记忆缺失"""
        logger.debug("Handling memory miss")
        
        # 这里应该调用记忆系统和知识库的接口
        # 简化实现：记录日志
        pass
    
    async def _check_gap_discovery(self, event: LoopEvent) -> None:
        """检查知识缺口"""
        logger.debug("Checking knowledge gaps")
        
        # 这里应该调用知识库的接口
        # 简化实现：记录日志
        pass
    
    async def _execute_reflection(self, event: LoopEvent) -> None:
        """执行反思"""
        logger.debug("Executing reflection")
        
        # 这里应该调用成长系统的接口
        # 简化实现：记录日志
        pass
    
    async def _evolution_feedback(self, event: LoopEvent) -> None:
        """成长反馈"""
        logger.debug("Executing evolution feedback")
        
        # 这里应该调用成长系统的接口
        # 简化实现：记录日志
        pass
    
    async def _safe_callback(self, event_name: str, *args) -> None:
        """安全执行回调"""
        for callback in self._callbacks.get(event_name, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args)
                else:
                    callback(*args)
            except Exception as e:
                logger.error(f"Callback {event_name} failed: {e}")
    
    def get_loop_stats(self) -> Dict[str, Any]:
        """获取闭环统计"""
        return self.stats.to_dict()
    
    def reset_stats(self) -> None:
        """重置统计"""
        self.stats = LoopStats()
        logger.info("Loop stats reset")


# 全局实例
_cognitive_loop: Optional[CognitiveLoopCoordinator] = None


def create_cognitive_loop(config: Optional[LoopConfig] = None,
                         mode: Optional[LoopMode] = None) -> CognitiveLoopCoordinator:
    """
    创建认知闭环协调器
    
    Args:
        config: 闭环配置
        mode: 闭环模式（覆盖配置中的模式）
        
    Returns:
        CognitiveLoopCoordinator 实例
    """
    global _cognitive_loop
    
    if config is None:
        config = LoopConfig()
    
    if mode:
        config.mode = mode
    
    _cognitive_loop = CognitiveLoopCoordinator(config=config)
    return _cognitive_loop


def create_scenario_loop(scenario: str) -> CognitiveLoopCoordinator:
    """
    创建预定义场景的闭环
    
    Args:
        scenario: 场景名称
        
    Returns:
        CognitiveLoopCoordinator 实例
    """
    # 预定义场景配置
    scenarios = {
        "learning": LoopConfig(
            mode=LoopMode.KNOWLEDGE_DRIVEN,
            auto_trigger=True,
            trigger_interval_seconds=1800,
            memory_confidence_threshold=0.8,
            knowledge_confidence_threshold=0.7
        ),
        "problem_solving": LoopConfig(
            mode=LoopMode.PROBLEM_DRIVEN,
            auto_trigger=False,
            memory_confidence_threshold=0.6,
            knowledge_confidence_threshold=0.5
        ),
        "reflection": LoopConfig(
            mode=LoopMode.REFLECTION_DRIVEN,
            auto_trigger=True,
            trigger_interval_seconds=86400,  # 每天
            reflection_interval_hours=24
        ),
        "full": LoopConfig(
            mode=LoopMode.FULL_LOOP,
            auto_trigger=True,
            trigger_interval_seconds=3600,
            evolution_enabled=True
        )
    }
    
    config = scenarios.get(scenario, scenarios["full"])
    return create_cognitive_loop(config=config)


def get_cognitive_loop() -> Optional[CognitiveLoopCoordinator]:
    """获取全局认知闭环协调器实例"""
    return _cognitive_loop


def reset_cognitive_loop() -> None:
    """重置全局认知闭环协调器实例（用于测试）"""
    global _cognitive_loop
    _cognitive_loop = None