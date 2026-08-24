from __future__ import annotations

"""
Neurova 自动化任务调度器核心模块

提供任务调度、执行、依赖管理等核心功能。
支持 Cron 表达式、间隔触发、条件触发等多种调度方式。
"""

import asyncio
from neurova.core.logger import get_logger
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = get_logger(__name__)

# ============================================================
# 枚举定义
# ============================================================


class TaskType(str, Enum):
    """任务类型"""

    AGENT = "agent"
    WORKFLOW = "workflow"
    SCRIPT = "script"
    WEBHOOK = "webhook"


class TriggerType(str, Enum):
    """触发类型"""

    CRON = "cron"
    INTERVAL = "interval"
    MANUAL = "manual"
    CONDITION = "condition"
    EVENT = "event"


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(str, Enum):
    """任务优先级"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# 数据模型
# ============================================================


@dataclass
class ScheduleConfig:
    """调度配置"""

    type: TriggerType = TriggerType.CRON
    cron: Optional[str] = None
    interval_seconds: Optional[int] = None
    timezone: str = "Asia/Shanghai"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "cron": self.cron,
            "interval_seconds": self.interval_seconds,
            "timezone": self.timezone,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleConfig":
        return cls(
            type=TriggerType(data.get("type", "cron")),
            cron=data.get("cron"),
            interval_seconds=data.get("interval_seconds"),
            timezone=data.get("timezone", "Asia/Shanghai"),
            start_date=datetime.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
        )


@dataclass
class TaskRequest:
    """任务请求配置"""

    type: TaskType = TaskType.AGENT
    agent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    script: Optional[str] = None
    webhook_url: Optional[str] = None
    input: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 300
    retry_on_failure: bool = False
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "agent_id": self.agent_id,
            "workflow_id": self.workflow_id,
            "script": self.script,
            "webhook_url": self.webhook_url,
            "input": self.input,
            "timeout": self.timeout,
            "retry_on_failure": self.retry_on_failure,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRequest":
        return cls(
            type=TaskType(data.get("type", "agent")),
            agent_id=data.get("agent_id"),
            workflow_id=data.get("workflow_id"),
            script=data.get("script"),
            webhook_url=data.get("webhook_url"),
            input=data.get("input", {}),
            timeout=data.get("timeout", 300),
            retry_on_failure=data.get("retry_on_failure", False),
            max_retries=data.get("max_retries", 3),
        )


@dataclass
class TaskDependency:
    """任务依赖"""

    task_id: str
    type: str = "blocks"  # blocks, waits_for, runs_after

    def to_dict(self) -> Dict[str, str]:
        return {"task_id": self.task_id, "type": self.type}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "TaskDependency":
        return cls(task_id=data["task_id"], type=data.get("type", "blocks"))


@dataclass
class RetryPolicy:
    """重试策略"""

    enabled: bool = False
    max_attempts: int = 3
    retry_delay_seconds: int = 60
    exponential_backoff: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryPolicy":
        return cls(**data) if data else cls()


@dataclass
class NotificationConfig:
    """通知配置"""

    on_success: bool = False
    on_failure: bool = True
    channels: List[str] = field(default_factory=lambda: ["in_app"])
    webhook_url: Optional[str] = None
    email_recipients: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationConfig":
        return cls(**data) if data else cls()


@dataclass
class AutomationTask:
    """自动化任务"""

    id: str
    name: str
    description: Optional[str] = None
    type: TaskType = TaskType.AGENT
    enabled: bool = True
    priority: TaskPriority = TaskPriority.NORMAL
    schedule: Optional[ScheduleConfig] = None
    request: Optional[TaskRequest] = None
    dependencies: List[TaskDependency] = field(default_factory=list)
    retry_policy: Optional[RetryPolicy] = None
    notifications: Optional[NotificationConfig] = None
    max_execution_time: int = 3600
    tags: List[str] = field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "enabled": self.enabled,
            "priority": self.priority.value if isinstance(self.priority, Enum) else self.priority,
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "request": self.request.to_dict() if self.request else None,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "retry_policy": self.retry_policy.to_dict() if self.retry_policy else None,
            "notifications": self.notifications.to_dict() if self.notifications else None,
            "max_execution_time": self.max_execution_time,
            "tags": self.tags,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutomationTask":
        schedule = ScheduleConfig.from_dict(data["schedule"]) if data.get("schedule") else None
        request = TaskRequest.from_dict(data["request"]) if data.get("request") else None
        dependencies = [TaskDependency.from_dict(d) for d in data.get("dependencies", [])]
        retry_policy = RetryPolicy.from_dict(data.get("retry_policy")) if data.get("retry_policy") else None
        notifications = NotificationConfig.from_dict(data.get("notifications")) if data.get("notifications") else None

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            type=TaskType(data.get("type", "agent")),
            enabled=data.get("enabled", True),
            priority=TaskPriority(data.get("priority", "normal")),
            schedule=schedule,
            request=request,
            dependencies=dependencies,
            retry_policy=retry_policy,
            notifications=notifications,
            max_execution_time=data.get("max_execution_time", 3600),
            tags=data.get("tags", []),
            created_by=data.get("created_by"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            last_run_at=datetime.fromisoformat(data["last_run_at"]) if data.get("last_run_at") else None,
            next_run_at=datetime.fromisoformat(data["next_run_at"]) if data.get("next_run_at") else None,
            run_count=data.get("run_count", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
        )


@dataclass
class TaskExecution:
    """任务执行记录"""

    id: str
    task_id: str
    task_name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    triggered_by: str = "manual"
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "triggered_by": self.triggered_by,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "logs": self.logs,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskExecution":
        return cls(
            id=data["id"],
            task_id=data["task_id"],
            task_name=data.get("task_name", ""),
            status=TaskStatus(data.get("status", "pending")),
            triggered_by=data.get("triggered_by", "manual"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.now(),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            duration_ms=data.get("duration_ms"),
            result=data.get("result"),
            error=data.get("error"),
            logs=data.get("logs", []),
            metadata=data.get("metadata", {}),
        )


# ============================================================
# 任务执行器接口
# ============================================================


class TaskExecutor(ABC):
    """任务执行器抽象基类"""

    @abstractmethod
    async def execute(self, task: AutomationTask, execution: TaskExecution) -> Dict[str, Any]:
        """执行任务并返回结果"""

    @abstractmethod
    async def validate(self, task: AutomationTask) -> tuple[bool, Optional[str]]:
        """验证任务配置是否有效"""


class AgentTaskExecutor(TaskExecutor):
    """Agent 任务执行器"""

    def __init__(self, agent_manager=None):
        self.agent_manager = agent_manager

    async def execute(self, task: AutomationTask, execution: TaskExecution) -> Dict[str, Any]:
        """通过 Agent 执行任务"""
        try:
            from neurova.api.app import app_state

            agent_id = task.request.agent_id if task.request else None
            if not agent_id and hasattr(app_state, "default_agent"):
                agent = app_state.default_agent
                agent_id = getattr(agent.config, "agent_id", None)
            elif agent_id and hasattr(app_state, "agents"):
                agent = app_state.agents.get(agent_id)
            else:
                return {"success": False, "error": "Agent not found"}

            if not agent:
                return {"success": False, "error": f"Agent {agent_id} not found"}

            input_data = task.request.input if task.request else {}
            message = input_data.get("message", "")
            if not message:
                return {"success": False, "error": "No message provided"}

            # 执行 Agent
            # S7 修复 (B-2 #10): 不注入 {"history": []},让 agent.chat() 从 session 恢复历史.
            result = agent.chat(message, stream=False)

            return {
                "success": True,
                "result": result,
                "agent_id": agent_id,
            }
        except Exception as e:
            logger.exception("Agent task execution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def validate(self, task: AutomationTask) -> tuple[bool, Optional[str]]:
        """验证 Agent 任务"""
        if not task.request or not task.request.agent_id:
            return False, "Agent ID is required"
        return True, None


class WorkflowTaskExecutor(TaskExecutor):
    """工作流任务执行器"""

    def __init__(self, workflow_runner=None):
        self.workflow_runner = workflow_runner

    async def execute(self, task: AutomationTask, execution: TaskExecution) -> Dict[str, Any]:
        """执行工作流任务"""
        try:
            workflow_id = task.request.workflow_id if task.request else None
            if not workflow_id:
                return {"success": False, "error": "Workflow ID is required"}

            # 获取工作流运行器
            from neurova.api.app import app_state

            workflow_runner = getattr(app_state, "workflow_runner", None)

            if not workflow_runner:
                # 如果没有工作流运行器，尝试导入
                try:
                    from neurova.workflow.runner import WorkflowRunner

                    workflow_runner = WorkflowRunner()
                except ImportError:
                    return {"success": False, "error": "Workflow runner not available"}

            # 执行工作流
            input_data = task.request.input if task.request else {}
            result = await workflow_runner.run_workflow(workflow_id, context=input_data)

            return {
                "success": True,
                "result": result,
                "workflow_id": workflow_id,
            }
        except Exception as e:
            logger.exception("Workflow task execution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def validate(self, task: AutomationTask) -> tuple[bool, Optional[str]]:
        """验证工作流任务"""
        if not task.request or not task.request.workflow_id:
            return False, "Workflow ID is required"
        return True, None


class WebhookTaskExecutor(TaskExecutor):
    """Webhook 任务执行器"""

    async def execute(self, task: AutomationTask, execution: TaskExecution) -> Dict[str, Any]:
        """执行 Webhook 任务"""
        try:
            import aiohttp

            webhook_url = task.request.webhook_url if task.request else None
            if not webhook_url:
                return {"success": False, "error": "Webhook URL is required"}

            input_data = task.request.input if task.request else {}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url, json=input_data, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    result = (
                        await response.json() if response.content_type == "application/json" else await response.text()
                    )

                    return {
                        "success": response.status < 400,
                        "status_code": response.status,
                        "result": result,
                    }
        except Exception as e:
            logger.exception("Webhook task execution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def validate(self, task: AutomationTask) -> tuple[bool, Optional[str]]:
        """验证 Webhook 任务"""
        if not task.request or not task.request.webhook_url:
            return False, "Webhook URL is required"
        if not task.request.webhook_url.startswith(("http://", "https://")):
            return False, "Invalid webhook URL"
        return True, None


class ScriptTaskExecutor(TaskExecutor):
    """脚本任务执行器"""

    def __init__(self):
        self._script_globals: Dict[str, Any] = {}
        self._script_locals: Dict[str, Any] = {}

    async def execute(self, task: AutomationTask, execution: TaskExecution) -> Dict[str, Any]:
        """执行脚本任务"""
        try:
            script = task.request.script if task.request else None
            if not script:
                return {"success": False, "error": "Script is required"}

            input_data = task.request.input if task.request else {}

            # 创建安全的执行环境
            safe_globals = {
                "__builtins__": __builtins__,
                "input": input_data,
                "task": task.to_dict(),
                "execution": execution.to_dict(),
            }
            safe_locals: Dict[str, Any] = {"result": None, "error": None}

            # 执行脚本
            exec(script, safe_globals, safe_locals)

            return {
                "success": safe_locals.get("error") is None,
                "result": safe_locals.get("result"),
                "output": safe_locals.get("output"),
                "error": safe_locals.get("error"),
            }
        except Exception as e:
            logger.exception("Script task execution failed: %s", e)
            return {"success": False, "error": str(e)}

    async def validate(self, task: AutomationTask) -> tuple[bool, Optional[str]]:
        """验证脚本任务"""
        if not task.request or not task.request.script:
            return False, "Script is required"
        return True, None


# ============================================================
# 任务调度器核心
# ============================================================


class TaskScheduler:
    """
    任务调度器核心类

    负责:
    - 任务的注册、启停
    - 调度器的启动和关闭
    - 任务的执行和监控
    - 执行历史的记录
    """

    _instance: Optional["TaskScheduler"] = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self._tasks: Dict[str, AutomationTask] = {}
        self._executions: Dict[str, List[TaskExecution]] = {}
        self._running_executions: Dict[str, TaskExecution] = {}
        self._executors: Dict[TaskType, TaskExecutor] = {}
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._apscheduler: Optional[BackgroundScheduler] = None
        self._task_lock = Lock()
        self._event_handlers: List[Callable] = []
        self._dependency_graph: Dict[str, Set[str]] = {}  # task_id -> depends_on

        # 注册默认执行器
        self._register_default_executors()

        logger.info("TaskScheduler initialized")

    def _register_default_executors(self):
        """注册默认任务执行器"""
        self._executors[TaskType.AGENT] = AgentTaskExecutor()
        self._executors[TaskType.WORKFLOW] = WorkflowTaskExecutor()
        self._executors[TaskType.WEBHOOK] = WebhookTaskExecutor()
        self._executors[TaskType.SCRIPT] = ScriptTaskExecutor()

    def register_executor(self, task_type: TaskType, executor: TaskExecutor):
        """注册自定义执行器"""
        self._executors[task_type] = executor
        logger.info("Registered executor for task type: %s", task_type.value)

    # ============================================================
    # 任务管理
    # ============================================================

    def add_task(self, task: AutomationTask) -> bool:
        """添加任务"""
        with self._task_lock:
            try:
                # 验证任务
                if not self._validate_task(task):
                    return False

                self._tasks[task.id] = task
                self._executions[task.id] = []
                self._dependency_graph[task.id] = set()

                # 添加依赖关系
                for dep in task.dependencies:
                    if dep.task_id in self._dependency_graph:
                        self._dependency_graph[dep.task_id].add(task.id)

                # 如果调度器已启动且任务启用,添加到调度器
                if task.enabled and self._apscheduler and task.schedule:
                    self._add_to_scheduler(task)

                logger.info("Task added: %s (%s)", task.id, task.name)
                self._emit_event("task_added", task)
                return True
            except Exception as e:
                logger.exception("Failed to add task: %s", e)
                return False

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[AutomationTask]:
        """更新任务"""
        with self._task_lock:
            if task_id not in self._tasks:
                return None

            try:
                old_task = self._tasks[task_id]

                # 移除旧的调度器任务
                if self._apscheduler and task_id in self._apscheduler.get_jobs():
                    self._apscheduler.remove_job(task_id)

                # 更新任务
                updated_data = old_task.to_dict()
                updated_data.update(updates)
                new_task = AutomationTask.from_dict(updated_data)
                new_task.updated_at = datetime.now()

                self._tasks[task_id] = new_task

                # 如果启用且有调度配置,重新添加
                if new_task.enabled and new_task.schedule:
                    self._add_to_scheduler(new_task)

                logger.info("Task updated: %s", task_id)
                self._emit_event("task_updated", new_task)
                return new_task
            except Exception as e:
                logger.exception("Failed to update task: %s", e)
                return None

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        with self._task_lock:
            if task_id not in self._tasks:
                return False

            try:
                # 移除调度器任务
                if self._apscheduler and task_id in self._apscheduler.get_jobs():
                    self._apscheduler.remove_job(task_id)

                # 移除依赖关系
                for other_id in self._dependency_graph:
                    self._dependency_graph[other_id].discard(task_id)

                del self._dependency_graph[task_id]
                del self._tasks[task_id]
                del self._executions[task_id]

                logger.info("Task deleted: %s", task_id)
                self._emit_event("task_deleted", {"task_id": task_id})
                return True
            except Exception as e:
                logger.exception("Failed to delete task: %s", e)
                return False

    def get_task(self, task_id: str) -> Optional[AutomationTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, filters: Optional[Dict[str, Any]] = None) -> List[AutomationTask]:
        """列出任务"""
        tasks = list(self._tasks.values())

        if filters:
            if "enabled" in filters:
                tasks = [t for t in tasks if t.enabled == filters["enabled"]]
            if "type" in filters:
                tasks = [t for t in tasks if t.type.value == filters["type"] or t.type == filters["type"]]
            if "search" in filters:
                search = filters["search"].lower()
                tasks = [t for t in tasks if search in t.name.lower() or search in (t.description or "").lower()]
            if "tags" in filters:
                tasks = [t for t in tasks if any(tag in t.tags for tag in filters["tags"])]

        return tasks

    def enable_task(self, task_id: str) -> Optional[AutomationTask]:
        """启用任务"""
        return self.update_task(task_id, {"enabled": True})

    def disable_task(self, task_id: str) -> Optional[AutomationTask]:
        """禁用任务"""
        with self._task_lock:
            if task_id not in self._tasks:
                return None

            # 移除调度器任务
            if self._apscheduler and task_id in self._apscheduler.get_jobs():
                self._apscheduler.remove_job(task_id)

            task = self._tasks[task_id]
            task.enabled = False
            task.updated_at = datetime.now()

            self._emit_event("task_disabled", task)
            return task

    # ============================================================
    # 调度器控制
    # ============================================================

    def start(self):
        """启动调度器"""
        if self._apscheduler and self._apscheduler.running:
            logger.warning("Scheduler already running")
            return

        try:
            jobstores = {"default": MemoryJobStore()}
            executors = {"default": ThreadPoolExecutor(10), "processpool": ProcessPoolExecutor(5)}
            job_defaults = {"coalesce": True, "max_instances": 3, "misfire_grace_time": 60}

            self._apscheduler = BackgroundScheduler(
                jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone="Asia/Shanghai"
            )

            # 添加事件监听器
            self._apscheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
            self._apscheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)

            # 添加所有启用的任务
            for task in self._tasks.values():
                if task.enabled and task.schedule:
                    self._add_to_scheduler(task)

            self._apscheduler.start()
            logger.info("TaskScheduler started")

        except Exception as e:
            logger.exception("Failed to start scheduler: %s", e)
            raise

    def stop(self):
        """停止调度器"""
        if self._apscheduler and self._apscheduler.running:
            self._apscheduler.shutdown(wait=True)
            logger.info("TaskScheduler stopped")

    def _add_to_scheduler(self, task: AutomationTask):
        """添加任务到 APScheduler"""
        if not task.schedule or not self._apscheduler:
            return

        try:
            schedule = task.schedule

            if schedule.type == TriggerType.CRON and schedule.cron:
                # Cron 触发器
                parts = schedule.cron.split()
                if len(parts) >= 5:
                    trigger = CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4],
                        timezone=schedule.timezone,
                        start_date=schedule.start_date,
                        end_date=schedule.end_date,
                    )
                else:
                    logger.warning("Invalid cron expression: %s", schedule.cron)
                    return
            elif schedule.type == TriggerType.INTERVAL and schedule.interval_seconds:
                # 间隔触发器
                trigger = IntervalTrigger(
                    seconds=schedule.interval_seconds,
                    start_date=schedule.start_date,
                    end_date=schedule.end_date,
                )
            else:
                logger.warning("Unsupported schedule type: %s", schedule.type)
                return

            self._apscheduler.add_job(
                func=self._execute_task_wrapper,
                trigger=trigger,
                id=task.id,
                args=[task.id],
                replace_existing=True,
                misfire_grace_time=60,
            )

            # 计算下次执行时间
            next_run_time = self._apscheduler.get_job(task.id).next_run_time
            if next_run_time:
                task.next_run_at = next_run_time

            logger.info("Task %s added to scheduler, next run: %s", task.id, task.next_run_at)

        except Exception as e:
            logger.exception("Failed to add task to scheduler: %s", e)

    # ============================================================
    # 任务执行
    # ============================================================

    async def execute_task(
        self, task_id: str, input_override: Optional[Dict[str, Any]] = None, triggered_by: str = "manual"
    ) -> Optional[TaskExecution]:
        """执行任务"""
        task = self._tasks.get(task_id)
        if not task:
            logger.error("Task not found: %s", task_id)
            return None

        # 检查依赖
        if not self._check_dependencies(task_id):
            logger.warning("Task %s dependencies not satisfied", task_id)
            return None

        # 创建执行记录
        execution = TaskExecution(
            id=str(uuid.uuid4()),
            task_id=task_id,
            task_name=task.name,
            status=TaskStatus.PENDING,
            triggered_by=triggered_by,
        )

        self._running_executions[execution.id] = execution
        task.run_count += 1
        task.last_run_at = datetime.now()

        self._emit_event("execution_started", execution)

        try:
            # 获取执行器
            executor = self._executors.get(task.type)
            if not executor:
                raise ValueError(f"No executor for task type: {task.type}")

            # 验证任务
            valid, error = await executor.validate(task)
            if not valid:
                raise ValueError(f"Task validation failed: {error}")

            # 合并输入
            if input_override and task.request:
                task.request.input.update(input_override)

            # 执行任务
            execution.status = TaskStatus.RUNNING
            result = await executor.execute(task, execution)

            # 处理结果
            if result.get("success"):
                execution.status = TaskStatus.SUCCESS
                execution.result = result
                task.success_count += 1
            else:
                execution.status = TaskStatus.FAILED
                execution.error = result.get("error", "Unknown error")
                task.failure_count += 1

                # 重试逻辑
                if task.retry_policy and task.retry_policy.enabled:
                    await self._handle_retry(task, execution)

        except asyncio.TimeoutError:
            execution.status = TaskStatus.TIMEOUT
            execution.error = "Task execution timed out"
            task.failure_count += 1
        except Exception as e:
            execution.status = TaskStatus.FAILED
            execution.error = str(e)
            task.failure_count += 1
            logger.exception("Task execution failed: %s", e)

        finally:
            execution.ended_at = datetime.now()
            execution.duration_ms = int((execution.ended_at - execution.started_at).total_seconds() * 1000)

            # 记录执行历史
            if task_id in self._executions:
                self._executions[task_id].append(execution)

            # 限制历史记录数量
            if len(self._executions[task_id]) > 100:
                self._executions[task_id] = self._executions[task_id][-100:]

            # 清理运行中的执行
            if execution.id in self._running_executions:
                del self._running_executions[execution.id]

            self._emit_event("execution_completed", execution)

        return execution

    def _execute_task_wrapper(self, task_id: str):
        """任务执行包装器 (用于 APScheduler)"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.execute_task(task_id, triggered_by="scheduler"))
            finally:
                loop.close()
        except Exception as e:
            logger.exception("Task execution wrapper failed: %s", e)

    async def _handle_retry(self, task: AutomationTask, execution: TaskExecution):
        """处理任务重试"""
        if not task.retry_policy or not task.retry_policy.enabled:
            return

        max_attempts = task.retry_policy.max_attempts
        if execution.metadata.get("_retry_count", 0) >= max_attempts:
            return

        delay = task.retry_policy.retry_delay_seconds
        if task.retry_policy.exponential_backoff:
            delay *= 2 ** execution.metadata.get("_retry_count", 0)

        execution.metadata["_retry_count"] = execution.metadata.get("_retry_count", 0) + 1
        logger.info("Scheduling retry for task %s in %s seconds", task.id, delay)

        # 延迟重试
        await asyncio.sleep(delay)
        await self.execute_task(task.id, triggered_by="retry")

    def _check_dependencies(self, task_id: str) -> bool:
        """检查任务依赖是否满足"""
        dependents = self._dependency_graph.get(task_id, set())
        for dep_id in dependents:
            dep_task = self._tasks.get(dep_id)
            if not dep_task:
                continue

            # 检查是否有依赖任务正在运行
            if dep_id in self._running_executions:
                return False

            # 检查依赖任务的最后执行状态
            executions = self._executions.get(dep_id, [])
            if executions:
                last_execution = executions[-1]
                if last_execution.status == TaskStatus.FAILED:
                    return False

        return True

    # ============================================================
    # 执行历史
    # ============================================================

    def get_execution_history(self, task_id: str, limit: int = 50) -> List[TaskExecution]:
        """获取执行历史"""
        return self._executions.get(task_id, [])[-limit:]

    def get_execution(self, execution_id: str) -> Optional[TaskExecution]:
        """获取执行记录"""
        for executions in self._executions.values():
            for exec in executions:
                if exec.id == execution_id:
                    return exec
        return self._running_executions.get(execution_id)

    def get_all_executions(self, limit: int = 100) -> List[TaskExecution]:
        """获取所有执行记录"""
        all_executions = []
        for executions in self._executions.values():
            all_executions.extend(executions)

        all_executions.sort(key=lambda x: x.started_at, reverse=True)
        return all_executions[:limit]

    # ============================================================
    # 事件处理
    # ============================================================

    def add_event_handler(self, handler: Callable):
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable):
        """移除事件处理器"""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_type: str, data: Any):
        """触发事件"""
        for handler in self._event_handlers:
            try:
                handler(event_type, data)
            except Exception as e:
                logger.exception("Event handler error: %s", e)

    def _on_job_executed(self, event):
        """任务执行完成回调"""
        if event.exception:
            logger.error("Job %s executed with exception: %s", event.job_id, event.exception)

    def _on_job_error(self, event):
        """任务执行错误回调"""
        logger.error("Job %s error: %s", event.job_id, event.exception)

    # ============================================================
    # 验证
    # ============================================================

    def _validate_task(self, task: AutomationTask) -> bool:
        """验证任务配置"""
        if not task.name:
            logger.error("Task name is required")
            return False

        if task.schedule and task.schedule.type not in [TriggerType.MANUAL, TriggerType.CONDITION, TriggerType.EVENT]:
            if task.schedule.type == TriggerType.CRON and not task.schedule.cron:
                logger.error("Cron expression is required for CRON trigger")
                return False
            if task.schedule.type == TriggerType.INTERVAL and not task.schedule.interval_seconds:
                logger.error("Interval seconds is required for INTERVAL trigger")
                return False

        return True

    # ============================================================
    # 依赖图
    # ============================================================

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """获取依赖图"""
        return {k: list(v) for k, v in self._dependency_graph.items()}

    def get_dependent_tasks(self, task_id: str) -> List[str]:
        """获取依赖指定任务的所有任务"""
        return list(self._dependency_graph.get(task_id, set()))

    def get_task_dependencies(self, task_id: str) -> List[TaskDependency]:
        """获取任务的依赖列表"""
        task = self._tasks.get(task_id)
        return task.dependencies if task else []

    # ============================================================
    # 统计
    # ============================================================

    def get_task_stats(self, task_id: str) -> Dict[str, Any]:
        """获取任务统计"""
        task = self._tasks.get(task_id)
        if not task:
            return {}

        executions = self._executions.get(task_id, [])
        today = datetime.now().date()

        today_executions = [e for e in executions if e.started_at.date() == today]
        today_success = sum(1 for e in today_executions if e.status == TaskStatus.SUCCESS)
        today_total = len(today_executions)

        return {
            "task_id": task_id,
            "total_runs": task.run_count,
            "success_count": task.success_count,
            "failure_count": task.failure_count,
            "success_rate": task.success_count / task.run_count if task.run_count > 0 else 0,
            "avg_duration_ms": sum(e.duration_ms or 0 for e in executions) / len(executions) if executions else 0,
            "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
            "today_runs": today_total,
            "today_success": today_success,
            "today_success_rate": today_success / today_total if today_total > 0 else 0,
        }

    def get_overview_stats(self) -> Dict[str, Any]:
        """获取概览统计"""
        total_tasks = len(self._tasks)
        active_tasks = sum(1 for t in self._tasks.values() if t.enabled)

        today = datetime.now().date()
        today_total = 0
        today_success = 0
        running = len(self._running_executions)

        for executions in self._executions.values():
            for e in executions:
                if e.started_at.date() == today:
                    today_total += 1
                    if e.status == TaskStatus.SUCCESS:
                        today_success += 1

        return {
            "total_tasks": total_tasks,
            "active_tasks": active_tasks,
            "total_executions_today": today_total,
            "success_rate_today": today_success / today_total if today_total > 0 else 0,
            "running_tasks": running,
        }


# ============================================================
# 全局实例
# ============================================================

_scheduler_instance: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """获取任务调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = TaskScheduler()
    return _scheduler_instance


def init_scheduler() -> TaskScheduler:
    """初始化任务调度器"""
    scheduler = get_scheduler()
    scheduler.start()
    return scheduler
