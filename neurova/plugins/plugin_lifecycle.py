from __future__ import annotations

"""
插件生命周期钩子 - 插件安装/启用/禁用/卸载各阶段回调

功能:
- 生命周期事件定义
- 生命周期钩子注册与执行
- 前置/后置钩子
- 钩子错误处理
- 通过事件总线触发所有生命周期事件
"""

import asyncio
from dataclasses import dataclass, field
import enum
import logging
import typing
from typing import Awaitable, Callable, Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class LifecycleEvent(str, Enum):
    """
    生命周期事件枚举
    """
    # 安装相关
    BEFORE_INSTALL = "before_install"
    AFTER_INSTALL = "after_install"
    
    # 卸载相关
    BEFORE_UNINSTALL = "before_uninstall"
    AFTER_UNINSTALL = "after_uninstall"
    
    # 启用相关
    BEFORE_ENABLE = "before_enable"
    AFTER_ENABLE = "after_enable"
    
    # 禁用相关
    BEFORE_DISABLE = "before_disable"
    AFTER_DISABLE = "after_disable"
    
    # 加载相关
    BEFORE_LOAD = "before_load"
    AFTER_LOAD = "after_load"
    
    # 卸载相关
    BEFORE_UNLOAD = "before_unload"
    AFTER_UNLOAD = "after_unload"
    
    # 更新相关
    BEFORE_UPDATE = "before_update"
    AFTER_UPDATE = "after_update"


@dataclass
class LifecycleHook:
    """
    生命周期钩子数据类
    """
    event: LifecycleEvent
    callback: Callable[[], None]
    priority: int = 0
    plugin_name: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event": self.event.value,
            "priority": self.priority,
            "plugin_name": self.plugin_name,
            "description": self.description,
            "metadata": self.metadata
        }
    
    def execute(self):
        """执行钩子"""
        try:
            self.callback()
        except Exception as e:
            logger.error(f"Failed to execute lifecycle hook for {self.plugin_name}: {e}")
            raise


class PluginLifecycleManager:
    """
    插件生命周期管理器
    
    管理插件的生命周期钩子，支持前置/后置钩子和事件总线集成。
    """
    
    def __init__(self):
        """初始化生命周期管理器"""
        self._hooks: Dict[str, List[LifecycleHook]] = {}
        self._plugin_states: Dict[str, str] = {}
        self._event_listeners: Dict[str, List[Callable]] = {}
        
        logger.info("PluginLifecycleManager initialized")
    
    def register_hook(self, hook: LifecycleHook):
        """
        注册生命周期钩子
        
        Args:
            hook: 生命周期钩子
        """
        key = self._make_key(hook.event, hook.plugin_name)
        
        if key not in self._hooks:
            self._hooks[key] = []
        
        self._hooks[key].append(hook)
        
        # 按优先级排序
        self._hooks[key].sort(key=lambda h: h.priority, reverse=True)
        
        logger.debug(f"Registered lifecycle hook: {hook.event.value} for {hook.plugin_name}")
    
    def unregister_hooks(self, plugin_name: str):
        """
        注销指定插件的所有钩子
        
        Args:
            plugin_name: 插件名称
        """
        keys_to_remove = []
        for key in self._hooks:
            if key.endswith(f":{plugin_name}") or key.startswith(f"{plugin_name}:"):
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._hooks[key]
        
        logger.debug(f"Unregistered all hooks for plugin: {plugin_name}")
    
    def execute_lifecycle(self, event: LifecycleEvent, plugin_name: str, **kwargs):
        """
        执行生命周期事件
        
        Args:
            event: 生命周期事件
            plugin_name: 插件名称
            **kwargs: 额外参数
        """
        key = self._make_key(event, plugin_name)
        
        # 执行钩子
        hooks = self._hooks.get(key, [])
        for hook in hooks:
            try:
                hook.execute()
            except Exception as e:
                logger.error(f"Failed to execute hook for {event.value} on {plugin_name}: {e}")
                # 可以选择是否继续执行其他钩子
                continue
        
        # 触发事件监听器
        self._trigger_event_listeners(event, plugin_name, **kwargs)
        
        logger.debug(f"Executed lifecycle event: {event.value} for {plugin_name}")
    
    def _collect_hooks(self, event: LifecycleEvent, plugin_name: str) -> List[LifecycleHook]:
        """
        收集指定事件和插件的钩子
        
        Args:
            event: 生命周期事件
            plugin_name: 插件名称
            
        Returns:
            List[LifecycleHook]: 钩子列表
        """
        key = self._make_key(event, plugin_name)
        return self._hooks.get(key, [])
    
    def _make_key(self, event: LifecycleEvent, plugin_name: str) -> str:
        """
        生成钩子键
        
        Args:
            event: 生命周期事件
            plugin_name: 插件名称
            
        Returns:
            str: 钩子键
        """
        return f"{event.value}:{plugin_name}"
    
    def set_plugin_state(self, plugin_name: str, state: str):
        """
        设置插件状态
        
        Args:
            plugin_name: 插件名称
            state: 状态
        """
        self._plugin_states[plugin_name] = state
        logger.debug(f"Set plugin state: {plugin_name} -> {state}")
    
    def get_plugin_state(self, plugin_name: str) -> Optional[str]:
        """
        获取插件状态
        
        Args:
            plugin_name: 插件名称
            
        Returns:
            Optional[str]: 插件状态
        """
        return self._plugin_states.get(plugin_name)
    
    def get_all_states(self) -> Dict[str, str]:
        """
        获取所有插件状态
        
        Returns:
            Dict[str, str]: 状态字典
        """
        return self._plugin_states.copy()
    
    def add_event_listener(self, event: LifecycleEvent, callback: Callable):
        """
        添加事件监听器
        
        Args:
            event: 生命周期事件
            callback: 回调函数
        """
        if event.value not in self._event_listeners:
            self._event_listeners[event.value] = []
        
        self._event_listeners[event.value].append(callback)
        logger.debug(f"Added event listener for {event.value}")
    
    def remove_event_listener(self, event: LifecycleEvent, callback: Callable):
        """
        移除事件监听器
        
        Args:
            event: 生命周期事件
            callback: 回调函数
        """
        if event.value in self._event_listeners:
            try:
                self._event_listeners[event.value].remove(callback)
                logger.debug(f"Removed event listener for {event.value}")
            except ValueError:
                logger.warning(f"Event listener not found for {event.value}")
    
    def _trigger_event_listeners(self, event: LifecycleEvent, plugin_name: str, **kwargs):
        """
        触发事件监听器
        
        Args:
            event: 生命周期事件
            plugin_name: 插件名称
            **kwargs: 额外参数
        """
        listeners = self._event_listeners.get(event.value, [])
        
        for listener in listeners:
            try:
                # 尝试调用监听器
                if asyncio.iscoroutinefunction(listener):
                    # 异步监听器
                    asyncio.create_task(listener(plugin_name, **kwargs))
                else:
                    # 同步监听器
                    listener(plugin_name, **kwargs)
            except Exception as e:
                logger.error(f"Failed to trigger event listener for {event.value}: {e}")
    
    def clear_all_hooks(self):
        """清除所有钩子"""
        self._hooks.clear()
        logger.info("Cleared all lifecycle hooks")
    
    def clear_plugin_hooks(self, plugin_name: str):
        """
        清除指定插件的钩子
        
        Args:
            plugin_name: 插件名称
        """
        self.unregister_hooks(plugin_name)
        logger.info(f"Cleared hooks for plugin: {plugin_name}")
    
    def get_hook_count(self, event: Optional[LifecycleEvent] = None, 
                      plugin_name: Optional[str] = None) -> int:
        """
        获取钩子数量
        
        Args:
            event: 生命周期事件（可选）
            plugin_name: 插件名称（可选）
            
        Returns:
            int: 钩子数量
        """
        if event and plugin_name:
            key = self._make_key(event, plugin_name)
            return len(self._hooks.get(key, []))
        elif event:
            count = 0
            for key, hooks in self._hooks.items():
                if key.startswith(f"{event.value}:"):
                    count += len(hooks)
            return count
        elif plugin_name:
            count = 0
            for key, hooks in self._hooks.items():
                if key.endswith(f":{plugin_name}"):
                    count += len(hooks)
            return count
        else:
            return sum(len(hooks) for hooks in self._hooks.values())
    
    def list_hooks(self, event: Optional[LifecycleEvent] = None,
                  plugin_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出钩子
        
        Args:
            event: 生命周期事件（可选）
            plugin_name: 插件名称（可选）
            
        Returns:
            List[Dict[str, Any]]: 钩子列表
        """
        hooks_list = []
        
        for key, hooks in self._hooks.items():
            for hook in hooks:
                # 过滤条件
                if event and hook.event != event:
                    continue
                if plugin_name and hook.plugin_name != plugin_name:
                    continue
                
                hooks_list.append(hook.to_dict())
        
        return hooks_list
    
    def _log(self, level: str, message: str):
        """
        记录日志
        
        Args:
            level: 日志级别
            message: 日志消息
        """
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "debug":
            logger.debug(message)


# 全局生命周期管理器实例
_global_lifecycle_manager: Optional[PluginLifecycleManager] = None


def get_lifecycle_manager() -> PluginLifecycleManager:
    """
    获取全局生命周期管理器
    
    Returns:
        PluginLifecycleManager: 全局生命周期管理器实例
    """
    global _global_lifecycle_manager
    if _global_lifecycle_manager is None:
        _global_lifecycle_manager = PluginLifecycleManager()
    return _global_lifecycle_manager


def reset_lifecycle_manager():
    """
    重置全局生命周期管理器 (主要用于测试)
    """
    global _global_lifecycle_manager
    _global_lifecycle_manager = None


# 便捷函数
def register_lifecycle_hook(event: LifecycleEvent, callback: Callable, 
                           plugin_name: str = "", priority: int = 0,
                           description: str = "") -> LifecycleHook:
    """
    注册生命周期钩子（便捷函数）
    
    Args:
        event: 生命周期事件
        callback: 回调函数
        plugin_name: 插件名称
        priority: 优先级
        description: 描述
        
    Returns:
        LifecycleHook: 注册的钩子
    """
    hook = LifecycleHook(
        event=event,
        callback=callback,
        priority=priority,
        plugin_name=plugin_name,
        description=description
    )
    
    manager = get_lifecycle_manager()
    manager.register_hook(hook)
    
    return hook


def execute_lifecycle_event(event: LifecycleEvent, plugin_name: str, **kwargs):
    """
    执行生命周期事件（便捷函数）
    
    Args:
        event: 生命周期事件
        plugin_name: 插件名称
        **kwargs: 额外参数
    """
    manager = get_lifecycle_manager()
    manager.execute_lifecycle(event, plugin_name, **kwargs)
