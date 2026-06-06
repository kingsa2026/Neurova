from __future__ import annotations

"""
MemoryBus — 记忆子系统的注册中心与事件路由器
==============================================

取代 MemoryManager 的"直接管理 15+ 子系统"模式：
  - 只做三件事：register() / get() / emit()
  - 不吞异常：每个模块独立汇报健康状态
  - 不需要 loop.run_until_complete hack
"""

import logging
import time
import threading
import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ModuleHealth:
    """模块健康状态"""
    module_name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_count: int = 0
    last_error: Optional[str] = None
    response_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BusEvent:
    """总线事件"""
    event_type: str
    source_module: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = ""


# 类型别名
EventHandler = Callable[[BusEvent], None]
HealthChecker = Callable[[], ModuleHealth]


class MemoryBus:
    """
    记忆总线 - 注册中心与事件路由器
    
    只做三件事：
    1. register() - 注册模块
    2. get() - 获取模块
    3. emit() - 发射事件
    """
    
    def __init__(self, max_event_history: int = 1000):
        """
        初始化记忆总线
        
        Args:
            max_event_history: 最大事件历史记录数
        """
        self._lock = threading.RLock()
        
        # 模块注册表
        self._modules: Dict[str, Any] = {}
        self._module_types: Dict[str, str] = {}
        
        # 事件处理
        self._event_handlers: Dict[str, List[EventHandler]] = {}
        self._global_handlers: List[EventHandler] = []
        self._event_history: List[BusEvent] = []
        self._max_event_history = max_event_history
        
        # 健康检查
        self._health_checkers: Dict[str, HealthChecker] = {}
        self._health_status: Dict[str, ModuleHealth] = {}
        self._health_history: List[Dict[str, ModuleHealth]] = []
        self._max_health_history = 100
        
        # 统计
        self._event_counts: Dict[str, int] = {}
        self._module_access_counts: Dict[str, int] = {}
        
        # 事件ID计数器
        self._event_id_counter = 0
        
        logger.info("MemoryBus initialized")
    
    @property
    def events(self) -> List[BusEvent]:
        """获取事件历史"""
        with self._lock:
            return list(self._event_history)
    
    @property
    def module_names(self) -> List[str]:
        """获取所有注册的模块名称"""
        with self._lock:
            return list(self._modules.keys())
    
    def register(
        self,
        name: str,
        module: Any,
        module_type: str = "unknown",
        health_checker: Optional[HealthChecker] = None,
    ) -> None:
        """
        注册模块
        
        Args:
            name: 模块名称
            module: 模块实例
            module_type: 模块类型
            health_checker: 健康检查函数
        """
        with self._lock:
            if name in self._modules:
                logger.warning(f"Module '{name}' already registered, overwriting")
            
            self._modules[name] = module
            self._module_types[name] = module_type
            
            if health_checker:
                self._health_checkers[name] = health_checker
                # 立即执行一次健康检查
                try:
                    health = health_checker()
                    self._health_status[name] = health
                except Exception as e:
                    self._health_status[name] = ModuleHealth(
                        module_name=name,
                        status=HealthStatus.UNKNOWN,
                        last_error=str(e),
                    )
            else:
                self._health_status[name] = ModuleHealth(
                    module_name=name,
                    status=HealthStatus.HEALTHY,
                )
            
            logger.info(f"Module registered: {name} (type={module_type})")
    
    def get(self, name: str) -> Optional[Any]:
        """
        获取模块
        
        Args:
            name: 模块名称
            
        Returns:
            模块实例，如果不存在返回None
        """
        with self._lock:
            module = self._modules.get(name)
            if module:
                self._module_access_counts[name] = self._module_access_counts.get(name, 0) + 1
            return module
    
    def get_healthy(self, module_type: Optional[str] = None) -> List[Any]:
        """
        获取健康的模块
        
        Args:
            module_type: 模块类型过滤
            
        Returns:
            健康模块列表
        """
        with self._lock:
            healthy_modules = []
            for name, module in self._modules.items():
                # 检查类型过滤
                if module_type and self._module_types.get(name) != module_type:
                    continue
                
                # 检查健康状态
                health = self._health_status.get(name)
                if health and health.status == HealthStatus.HEALTHY:
                    healthy_modules.append(module)
            
            return healthy_modules
    
    def emit(self, event_type: str, source_module: str, data: Optional[Dict[str, Any]] = None) -> BusEvent:
        """
        发射事件（同步）
        
        Args:
            event_type: 事件类型
            source_module: 源模块名称
            data: 事件数据
            
        Returns:
            创建的事件对象
        """
        with self._lock:
            # 创建事件
            self._event_id_counter += 1
            event = BusEvent(
                event_type=event_type,
                source_module=source_module,
                data=data or {},
                event_id=f"evt_{self._event_id_counter}",
            )
            
            # 记录事件历史
            self._event_history.append(event)
            if len(self._event_history) > self._max_event_history:
                self._event_history = self._event_history[-self._max_event_history:]
            
            # 更新统计
            self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1
            
            # 获取处理器
            handlers = list(self._event_handlers.get(event_type, []))
            handlers.extend(self._global_handlers)
        
        # 在锁外执行处理器，避免死锁
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler failed for {event_type}: {e}")
        
        return event
    
    async def aemit(self, event_type: str, source_module: str, data: Optional[Dict[str, Any]] = None) -> BusEvent:
        """
        发射事件（异步）
        
        Args:
            event_type: 事件类型
            source_module: 源模块名称
            data: 事件数据
            
        Returns:
            创建的事件对象
        """
        # 异步版本目前只是同步版本的包装
        # 未来可以扩展为真正的异步处理
        return self.emit(event_type, source_module, data)
    
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        with self._lock:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            if handler not in self._event_handlers[event_type]:
                self._event_handlers[event_type].append(handler)
    
    def subscribe_all(self, handler: EventHandler) -> None:
        """
        订阅所有事件
        
        Args:
            handler: 事件处理函数
        """
        with self._lock:
            if handler not in self._global_handlers:
                self._global_handlers.append(handler)
    
    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        取消订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        with self._lock:
            if event_type in self._event_handlers:
                try:
                    self._event_handlers[event_type].remove(handler)
                except ValueError:
                    pass
    
    def unsubscribe_all(self, handler: EventHandler) -> None:
        """
        取消订阅所有事件
        
        Args:
            handler: 事件处理函数
        """
        with self._lock:
            try:
                self._global_handlers.remove(handler)
            except ValueError:
                pass
    
    def health_report(self) -> Dict[str, Any]:
        """
        获取健康报告
        
        Returns:
            健康报告字典
        """
        with self._lock:
            # 刷新所有健康状态
            self._refresh_health_status()
            
            report = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_modules": len(self._modules),
                "healthy_modules": 0,
                "degraded_modules": 0,
                "unhealthy_modules": 0,
                "unknown_modules": 0,
                "modules": {},
            }
            
            for name, health in self._health_status.items():
                report["modules"][name] = {
                    "status": health.status.value,
                    "last_check": health.last_check.isoformat(),
                    "error_count": health.error_count,
                    "last_error": health.last_error,
                    "response_time_ms": health.response_time_ms,
                    "module_type": self._module_types.get(name, "unknown"),
                }
                
                if health.status == HealthStatus.HEALTHY:
                    report["healthy_modules"] += 1
                elif health.status == HealthStatus.DEGRADED:
                    report["degraded_modules"] += 1
                elif health.status == HealthStatus.UNHEALTHY:
                    report["unhealthy_modules"] += 1
                else:
                    report["unknown_modules"] += 1
            
            return report
    
    def health_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取健康历史
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            健康历史记录列表
        """
        with self._lock:
            return list(self._health_history[-limit:])
    
    def refresh_health(self, module_name: Optional[str] = None) -> None:
        """
        刷新健康状态
        
        Args:
            module_name: 模块名称，如果为None则刷新所有
        """
        with self._lock:
            if module_name:
                self._refresh_module_health(module_name)
            else:
                self._refresh_health_status()
    
    def shutdown_all(self) -> None:
        """关闭所有模块"""
        with self._lock:
            modules = list(self._modules.items())
        
        # 在锁外执行关闭操作
        for name, module in modules:
            try:
                if hasattr(module, 'shutdown'):
                    module.shutdown()
                elif hasattr(module, 'close'):
                    module.close()
                elif hasattr(module, 'stop'):
                    module.stop()
                logger.info(f"Module shutdown: {name}")
            except Exception as e:
                logger.error(f"Failed to shutdown module {name}: {e}")
        
        with self._lock:
            self._modules.clear()
            self._module_types.clear()
            self._health_checkers.clear()
            self._health_status.clear()
            self._event_handlers.clear()
            self._global_handlers.clear()
        
        logger.info("All modules shutdown")
    
    def _refresh_health_status(self) -> None:
        """刷新所有模块的健康状态"""
        for name in self._modules:
            self._refresh_module_health(name)
        
        # 保存健康快照
        snapshot = {}
        for name, health in self._health_status.items():
            snapshot[name] = ModuleHealth(
                module_name=health.module_name,
                status=health.status,
                last_check=health.last_check,
                error_count=health.error_count,
                last_error=health.last_error,
                response_time_ms=health.response_time_ms,
                metadata=health.metadata.copy(),
            )
        
        self._health_history.append(snapshot)
        if len(self._health_history) > self._max_health_history:
            self._health_history = self._health_history[-self._max_health_history:]
    
    def _refresh_module_health(self, module_name: str) -> None:
        """刷新单个模块的健康状态"""
        if module_name not in self._health_checkers:
            return
        
        checker = self._health_checkers[module_name]
        try:
            start_time = time.time()
            health = checker()
            health.last_check = datetime.now(timezone.utc)
            health.response_time_ms = (time.time() - start_time) * 1000
            self._health_status[module_name] = health
        except Exception as e:
            # 更新错误状态
            current_health = self._health_status.get(module_name)
            if current_health:
                current_health.error_count += 1
                current_health.last_error = str(e)
                current_health.last_check = datetime.now(timezone.utc)
                # 如果错误过多，标记为不健康
                if current_health.error_count > 5:
                    current_health.status = HealthStatus.UNHEALTHY
                elif current_health.error_count > 2:
                    current_health.status = HealthStatus.DEGRADED
    
    def _record_health(self, module_name: str, health: ModuleHealth) -> None:
        """记录健康状态"""
        with self._lock:
            self._health_status[module_name] = health
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取总线统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "total_modules": len(self._modules),
                "total_events": len(self._event_history),
                "event_counts": dict(self._event_counts),
                "module_access_counts": dict(self._module_access_counts),
                "event_handlers": {
                    event_type: len(handlers)
                    for event_type, handlers in self._event_handlers.items()
                },
                "global_handlers": len(self._global_handlers),
                "health_checkers": len(self._health_checkers),
            }
    
    def __repr__(self) -> str:
        return f"MemoryBus(modules={len(self._modules)}, events={len(self._event_history)})"


# 全局单例
_memory_bus: Optional[MemoryBus] = None
_bus_lock = threading.Lock()


def get_memory_bus(max_event_history: int = 1000) -> MemoryBus:
    """
    获取全局记忆总线单例
    
    Args:
        max_event_history: 最大事件历史记录数
        
    Returns:
        MemoryBus实例
    """
    global _memory_bus
    if _memory_bus is None:
        with _bus_lock:
            if _memory_bus is None:
                _memory_bus = MemoryBus(max_event_history=max_event_history)
    return _memory_bus


def reset_memory_bus() -> None:
    """重置全局记忆总线（用于测试）"""
    global _memory_bus
    with _bus_lock:
        if _memory_bus:
            _memory_bus.shutdown_all()
        _memory_bus = None