"""
Skill Registry - 中央注册表

提供Skill的集中注册与管理功能。
实现Singleton模式，确保全局唯一的注册表实例。

主要功能:
- Skill的注册与取消注册
- 启动/关闭Hook管理
- 控制命令注册
- 线程安全的操作
"""

import asyncio
from dataclasses import dataclass
import datetime
import inspect
import logging
from pathlib import Path
import threading
import typing

from neurova.skills.models import Skill

# skills imports
import neurova.skills.manifest

@dataclass
class HookRegistration:
    """Hook注册记录"""
    skill_id: str
    hook_name: str
    callback: typing.Callable
    priority: int = 100

@dataclass
class ControlCommandRegistration:
    """控制命令注册记录"""
    skill_id: str
    handler: typing.Callable
    priority_level: int = 10

class SkillRegistry:
    """
    SkillRegistry - 中央注册表
    
    实现Singleton模式，确保全局唯一的注册表实例。
    线程安全的技能注册与管理。
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化注册表（仅执行一次）"""
        if self._initialized:
            return
        
        self._skills: typing.Dict[str, typing.Tuple[Skill, Path]] = {}
        self._startup_hooks: typing.List[HookRegistration] = []
        self._shutdown_hooks: typing.List[HookRegistration] = []
        self._control_commands: typing.List[ControlCommandRegistration] = []
        self._event_callbacks: typing.Dict[str, typing.List[typing.Callable]] = {}
        self._runtime_helpers: typing.Dict[str, typing.Any] = {}
        self._initialized = True
        self._logger = logging.getLogger(__name__)
    
    @property
    def skills(self) -> typing.Dict[str, typing.Tuple[Skill, Path]]:
        """获取所有注册的技能"""
        return self._skills.copy()
    
    def register_skill(self, manifest: Skill, path: Path) -> bool:
        """注册技能
        
        Args:
            manifest: 技能清单
            path: 技能路径
            
        Returns:
            bool: 注册是否成功
        """
        with self._lock:
            if manifest.id in self._skills:
                self._logger.warning(f"技能 {manifest.id} 已注册")
                return False
            
            self._skills[manifest.id] = (manifest, path)
            self._trigger_event("skill_registered", {"skill_id": manifest.id})
            return True
    
    def register(self, manifest: Skill, path: Path) -> bool:
        """注册技能（别名）"""
        return self.register_skill(manifest, path)
    
    def register_event_callback(self, event_name: str, callback: typing.Callable) -> None:
        """注册事件回调
        
        Args:
            event_name: 事件名称
            callback: 回调函数
        """
        if event_name not in self._event_callbacks:
            self._event_callbacks[event_name] = []
        self._event_callbacks[event_name].append(callback)
    
    def _trigger_event(self, event_name: str, data: typing.Dict[str, typing.Any]) -> None:
        """触发事件
        
        Args:
            event_name: 事件名称
            data: 事件数据
        """
        if event_name in self._event_callbacks:
            for callback in self._event_callbacks[event_name]:
                try:
                    if inspect.iscoroutinefunction(callback):
                        asyncio.create_task(callback(data))
                    else:
                        callback(data)
                except Exception as e:
                    self._logger.error(f"事件回调执行失败: {e}")
    
    def execute_skill(self, skill_id: str, *args, **kwargs) -> typing.Any:
        """执行技能
        
        Args:
            skill_id: 技能ID
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            执行结果
        """
        skill_info = self.get_skill(skill_id)
        if skill_info is None:
            raise ValueError(f"技能 {skill_id} 未注册")
        
        manifest, path = skill_info
        self._trigger_event("skill_executing", {"skill_id": skill_id})
        
        # 这里可以添加实际的技能执行逻辑
        # 目前返回一个模拟结果
        return {"skill_id": skill_id, "status": "executed"}
    
    def unregister_skill(self, skill_id: str) -> bool:
        """取消注册技能
        
        Args:
            skill_id: 技能ID
            
        Returns:
            bool: 取消注册是否成功
        """
        with self._lock:
            if skill_id not in self._skills:
                return False
            
            del self._skills[skill_id]
            self.unregister_hooks_for_skill(skill_id)
            self.unregister_control_command(skill_id)
            self._trigger_event("skill_unregistered", {"skill_id": skill_id})
            return True
    
    def get_skill(self, skill_id: str) -> typing.Optional[typing.Tuple[Skill, Path]]:
        """获取技能信息
        
        Args:
            skill_id: 技能ID
            
        Returns:
            技能信息元组，不存在返回None
        """
        return self._skills.get(skill_id)
    
    def get_all_skills(self) -> typing.List[typing.Tuple[Skill, Path]]:
        """获取所有技能
        
        Returns:
            技能信息列表
        """
        return list(self._skills.values())
    
    def register_startup_hook(self, skill_id: str, hook_name: str, 
                            callback: typing.Callable, priority: int = 100) -> None:
        """注册启动Hook
        
        Args:
            skill_id: 技能ID
            hook_name: Hook名称
            callback: 回调函数
            priority: 优先级（数值越小优先级越高）
        """
        hook = HookRegistration(
            skill_id=skill_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority
        )
        with self._lock:
            self._startup_hooks.append(hook)
            self._startup_hooks.sort(key=lambda x: x.priority)
    
    def register_shutdown_hook(self, skill_id: str, hook_name: str,
                             callback: typing.Callable, priority: int = 100) -> None:
        """注册关闭Hook
        
        Args:
            skill_id: 技能ID
            hook_name: Hook名称
            callback: 回调函数
            priority: 优先级（数值越小优先级越高）
        """
        hook = HookRegistration(
            skill_id=skill_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority
        )
        with self._lock:
            self._shutdown_hooks.append(hook)
            self._shutdown_hooks.sort(key=lambda x: x.priority)
    
    async def execute_startup_hooks(self) -> None:
        """执行启动Hook（按优先级排序）"""
        hooks = self._startup_hooks.copy()
        for hook in hooks:
            try:
                if inspect.iscoroutinefunction(hook.callback):
                    await hook.callback()
                else:
                    hook.callback()
            except Exception as e:
                self._logger.error(f"启动Hook执行失败: {e}")
    
    async def execute_shutdown_hooks(self) -> None:
        """执行关闭Hook（按优先级排序）"""
        hooks = self._shutdown_hooks.copy()
        for hook in hooks:
            try:
                if inspect.iscoroutinefunction(hook.callback):
                    await hook.callback()
                else:
                    hook.callback()
            except Exception as e:
                self._logger.error(f"关闭Hook执行失败: {e}")
    
    def register_control_command(self, skill_id: str, handler: typing.Callable,
                               priority_level: int = 10) -> None:
        """注册控制命令
        
        Args:
            skill_id: 技能ID
            handler: 命令处理器
            priority_level: 优先级级别
        """
        command = ControlCommandRegistration(
            skill_id=skill_id,
            handler=handler,
            priority_level=priority_level
        )
        with self._lock:
            self._control_commands.append(command)
            self._control_commands.sort(key=lambda x: x.priority_level)
    
    def get_control_commands(self) -> typing.List[ControlCommandRegistration]:
        """获取所有控制命令
        
        Returns:
            控制命令列表
        """
        return self._control_commands.copy()
    
    def get_startup_hooks(self) -> typing.List[HookRegistration]:
        """获取所有启动Hook
        
        Returns:
            启动Hook列表
        """
        return self._startup_hooks.copy()
    
    def get_shutdown_hooks(self) -> typing.List[HookRegistration]:
        """获取所有关闭Hook
        
        Returns:
            关闭Hook列表
        """
        return self._shutdown_hooks.copy()
    
    def set_runtime_helpers(self, helpers: typing.Dict[str, typing.Any]) -> None:
        """设置运行时辅助函数
        
        Args:
            helpers: 辅助函数字典
        """
        self._runtime_helpers.update(helpers)
    
    def get_runtime_helpers(self) -> typing.Dict[str, typing.Any]:
        """获取运行时辅助函数
        
        Returns:
            辅助函数字典
        """
        return self._runtime_helpers.copy()
    
    def unregister_hooks_for_skill(self, skill_id: str) -> None:
        """取消注册指定技能的所有Hook
        
        Args:
            skill_id: 技能ID
        """
        with self._lock:
            self._startup_hooks = [h for h in self._startup_hooks if h.skill_id != skill_id]
            self._shutdown_hooks = [h for h in self._shutdown_hooks if h.skill_id != skill_id]
    
    def unregister_control_command(self, skill_id: str) -> bool:
        """取消注册控制命令
        
        Args:
            skill_id: 技能ID
            
        Returns:
            bool: 取消注册是否成功
        """
        with self._lock:
            original_count = len(self._control_commands)
            self._control_commands = [c for c in self._control_commands if c.skill_id != skill_id]
            return len(self._control_commands) < original_count
    
    async def execute_control_command(self, skill_id: str, args: typing.Dict[str, typing.Any]) -> typing.Any:
        """执行控制命令
        
        Args:
            skill_id: 技能ID
            args: 命令参数
            
        Returns:
            执行结果
        """
        command = next((c for c in self._control_commands if c.skill_id == skill_id), None)
        if command is None:
            return None
        
        try:
            if inspect.iscoroutinefunction(command.handler):
                return await command.handler(args)
            else:
                return command.handler(args)
        except Exception as e:
            self._logger.error(f"控制命令执行失败: {e}")
            return None
    
    def clear(self) -> None:
        """清空注册表"""
        with self._lock:
            self._skills.clear()
            self._startup_hooks.clear()
            self._shutdown_hooks.clear()
            self._control_commands.clear()
            self._event_callbacks.clear()
            self._runtime_helpers.clear()
    
    def __len__(self) -> int:
        """获取注册的技能数量"""
        return len(self._skills)
    
    def __contains__(self, skill_id: str) -> bool:
        """检查技能是否已注册
        
        Args:
            skill_id: 技能ID
            
        Returns:
            bool: 是否已注册
        """
        return skill_id in self._skills
