"""
Agent 自我管理模块 - 提供核心指令、心跳任务等功能
基于数据库存储，不使用 Markdown 文件
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import Memory

logger = logging.getLogger(__name__)


# ────── Enums ──────

class CommandType(Enum):
    """指令类型"""
    SYSTEM = "system"           # 系统指令
    BEHAVIOR = "behavior"       # 行为指令
    SAFETY = "safety"           # 安全指令
    PERSONALITY = "personality" # 个性指令
    GOAL = "goal"               # 目标指令


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"         # 待执行
    RUNNING = "running"         # 执行中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 已失败
    SKIPPED = "skipped"         # 已跳过
    PAUSED = "paused"           # 已暂停


# ────── Data Models ──────

@dataclass
class CoreCommand:
    """核心指令"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    command_type: CommandType = CommandType.SYSTEM
    content: str = ""
    priority: int = 0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "command_type": self.command_type.value,
            "content": self.content,
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreCommand":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            command_type=CommandType(data.get("command_type", "system")),
            content=data.get("content", ""),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )


@dataclass
class HeartbeatTask:
    """心跳任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    task_type: str = "periodic"
    interval_seconds: int = 3600  # 默认1小时
    last_run_at: Optional[datetime.datetime] = None
    next_run_at: Optional[datetime.datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    run_count: int = 0
    last_result: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type,
            "interval_seconds": self.interval_seconds,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "status": self.status.value,
            "run_count": self.run_count,
            "last_result": self.last_result,
            "enabled": self.enabled,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeartbeatTask":
        def _parse_dt(val: Any) -> Optional[datetime.datetime]:
            if isinstance(val, datetime.datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.datetime.fromisoformat(val)
                except ValueError:
                    return None
            return None

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            task_type=data.get("task_type", "periodic"),
            interval_seconds=data.get("interval_seconds", 3600),
            last_run_at=_parse_dt(data.get("last_run_at")),
            next_run_at=_parse_dt(data.get("next_run_at")),
            status=TaskStatus(data.get("status", "pending")),
            run_count=data.get("run_count", 0),
            last_result=data.get("last_result"),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )


# ────── Main Manager ──────

class AgentSelfManager:
    """
    Agent 自我管理器
    
    提供核心指令、心跳任务等功能。
    基于数据库存储，不使用 Markdown 文件。
    """
    
    def __init__(self, agent_id: str, storage_path: Optional[str] = None):
        """
        初始化自我管理器
        
        Args:
            agent_id: Agent ID
            storage_path: 存储路径
        """
        self.agent_id = agent_id
        self.storage_path = storage_path or f"data/agent_self_{agent_id}.json"
        
        self._commands: Dict[str, CoreCommand] = {}
        self._heartbeat_tasks: Dict[str, HeartbeatTask] = {}
        self._initialized = False
        
        logger.info(f"AgentSelfManager 初始化: {agent_id}")
    
    def initialize(self) -> None:
        """初始化管理器"""
        if self._initialized:
            return
        
        # 加载数据
        self._load_commands()
        self._load_heartbeat_tasks()
        
        # 确保默认值
        self._ensure_defaults()
        
        self._initialized = True
        logger.info(f"AgentSelfManager 初始化完成: {self.agent_id}")
    
    def _load_commands(self) -> None:
        """加载指令"""
        try:
            # 从存储加载指令
            # 这里简化实现，实际应该从数据库或文件加载
            logger.debug(f"加载指令: {self.agent_id}")
        except Exception as e:
            logger.error(f"加载指令失败: {e}")
    
    def _save_commands(self) -> None:
        """保存指令"""
        try:
            # 保存指令到存储
            # 这里简化实现，实际应该保存到数据库或文件
            logger.debug(f"保存指令: {len(self._commands)} 个")
        except Exception as e:
            logger.error(f"保存指令失败: {e}")
    
    def _load_heartbeat_tasks(self) -> None:
        """加载心跳任务"""
        try:
            # 从存储加载心跳任务
            logger.debug(f"加载心跳任务: {self.agent_id}")
        except Exception as e:
            logger.error(f"加载心跳任务失败: {e}")
    
    def _save_heartbeat_tasks(self) -> None:
        """保存心跳任务"""
        try:
            # 保存心跳任务到存储
            logger.debug(f"保存心跳任务: {len(self._heartbeat_tasks)} 个")
        except Exception as e:
            logger.error(f"保存心跳任务失败: {e}")
    
    def _ensure_defaults(self) -> None:
        """确保默认值"""
        # 如果没有指令，添加默认指令
        if not self._commands:
            default_commands = [
                CoreCommand(
                    name="核心指令",
                    command_type=CommandType.SYSTEM,
                    content="你是一个智能助手，需要帮助用户解决问题。",
                    priority=100,
                ),
                CoreCommand(
                    name="安全指令",
                    command_type=CommandType.SAFETY,
                    content="不要执行任何可能造成伤害的操作。",
                    priority=90,
                ),
            ]
            
            for cmd in default_commands:
                self._commands[cmd.id] = cmd
            
            self._save_commands()
        
        # 如果没有心跳任务，添加默认任务
        if not self._heartbeat_tasks:
            default_tasks = [
                HeartbeatTask(
                    name="状态检查",
                    description="定期检查系统状态",
                    interval_seconds=300,  # 5分钟
                ),
            ]
            
            for task in default_tasks:
                self._heartbeat_tasks[task.id] = task
            
            self._save_heartbeat_tasks()
    
    def get_commands(self, command_type: Optional[CommandType] = None) -> List[CoreCommand]:
        """
        获取指令
        
        Args:
            command_type: 按类型过滤
            
        Returns:
            指令列表
        """
        commands = list(self._commands.values())
        
        if command_type:
            commands = [c for c in commands if c.command_type == command_type]
        
        # 按优先级排序
        commands.sort(key=lambda x: x.priority, reverse=True)
        
        return commands
    
    def add_command(self, command: CoreCommand) -> CoreCommand:
        """
        添加指令
        
        Args:
            command: 指令
            
        Returns:
            添加的指令
        """
        self._commands[command.id] = command
        self._save_commands()
        
        logger.debug(f"添加指令: {command.name}")
        return command
    
    def update_command(self, command_id: str, **kwargs) -> Optional[CoreCommand]:
        """
        更新指令
        
        Args:
            command_id: 指令ID
            **kwargs: 更新的字段
            
        Returns:
            更新后的指令
        """
        command = self._commands.get(command_id)
        if not command:
            return None
        
        for key, value in kwargs.items():
            if hasattr(command, key):
                setattr(command, key, value)
        
        command.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self._save_commands()
        
        logger.debug(f"更新指令: {command.name}")
        return command
    
    def delete_command(self, command_id: str) -> bool:
        """
        删除指令
        
        Args:
            command_id: 指令ID
            
        Returns:
            是否删除成功
        """
        if command_id in self._commands:
            del self._commands[command_id]
            self._save_commands()
            logger.debug(f"删除指令: {command_id}")
            return True
        return False
    
    def get_heartbeat_tasks(self, enabled_only: bool = False) -> List[HeartbeatTask]:
        """
        获取心跳任务
        
        Args:
            enabled_only: 是否只返回启用的任务
            
        Returns:
            心跳任务列表
        """
        tasks = list(self._heartbeat_tasks.values())
        
        if enabled_only:
            tasks = [t for t in tasks if t.enabled]
        
        return tasks
    
    def get_due_tasks(self) -> List[HeartbeatTask]:
        """
        获取到期的任务
        
        Returns:
            到期的任务列表
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        due_tasks = []
        
        for task in self._heartbeat_tasks.values():
            if not task.enabled:
                continue
            
            if task.next_run_at is None or task.next_run_at <= now:
                due_tasks.append(task)
        
        return due_tasks
    
    def add_heartbeat_task(self, task: HeartbeatTask) -> HeartbeatTask:
        """
        添加心跳任务
        
        Args:
            task: 心跳任务
            
        Returns:
            添加的任务
        """
        # 计算下次运行时间
        if task.next_run_at is None:
            task.next_run_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=task.interval_seconds)
        
        self._heartbeat_tasks[task.id] = task
        self._save_heartbeat_tasks()
        
        logger.debug(f"添加心跳任务: {task.name}")
        return task
    
    def update_heartbeat_task(self, task_id: str, **kwargs) -> Optional[HeartbeatTask]:
        """
        更新心跳任务
        
        Args:
            task_id: 任务ID
            **kwargs: 更新的字段
            
        Returns:
            更新后的任务
        """
        task = self._heartbeat_tasks.get(task_id)
        if not task:
            return None
        
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        task.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self._save_heartbeat_tasks()
        
        logger.debug(f"更新心跳任务: {task.name}")
        return task
    
    def record_task_run(self, task_id: str, success: bool, result: Optional[str] = None) -> Optional[HeartbeatTask]:
        """
        记录任务运行
        
        Args:
            task_id: 任务ID
            success: 是否成功
            result: 运行结果
            
        Returns:
            更新后的任务
        """
        task = self._heartbeat_tasks.get(task_id)
        if not task:
            return None
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        task.last_run_at = now
        task.next_run_at = now + datetime.timedelta(seconds=task.interval_seconds)
        task.run_count += 1
        task.last_result = result
        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.updated_at = now
        
        self._save_heartbeat_tasks()
        
        logger.debug(f"记录任务运行: {task.name} (成功: {success})")
        return task
    
    def delete_heartbeat_task(self, task_id: str) -> bool:
        """
        删除心跳任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否删除成功
        """
        if task_id in self._heartbeat_tasks:
            del self._heartbeat_tasks[task_id]
            self._save_heartbeat_tasks()
            logger.debug(f"删除心跳任务: {task_id}")
            return True
        return False
    
    def get_system_prompt_context(self) -> str:
        """
        获取系统提示上下文
        
        Returns:
            系统提示上下文
        """
        context_parts = []
        
        # 添加核心指令
        commands = self.get_commands()
        if commands:
            context_parts.append("## 核心指令")
            for cmd in commands:
                if cmd.enabled:
                    context_parts.append(f"- {cmd.name}: {cmd.content}")
        
        # 添加心跳任务状态
        tasks = self.get_heartbeat_tasks(enabled_only=True)
        if tasks:
            context_parts.append("\n## 心跳任务")
            for task in tasks:
                status = "✓" if task.status == TaskStatus.COMPLETED else "⏳"
                context_parts.append(f"- {status} {task.name}: {task.description}")
        
        return "\n".join(context_parts)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取状态信息
        
        Returns:
            状态信息字典
        """
        commands = list(self._commands.values())
        tasks = list(self._heartbeat_tasks.values())
        
        return {
            "agent_id": self.agent_id,
            "initialized": self._initialized,
            "commands_count": len(commands),
            "enabled_commands_count": sum(1 for c in commands if c.enabled),
            "tasks_count": len(tasks),
            "enabled_tasks_count": sum(1 for t in tasks if t.enabled),
            "due_tasks_count": len(self.get_due_tasks()),
            "last_activity": max(
                [c.updated_at for c in commands] + 
                [t.updated_at for t in tasks] + 
                [datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)]
            ).isoformat(),
        }