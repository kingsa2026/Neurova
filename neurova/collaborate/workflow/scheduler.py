# -*- coding: utf-8 -*-
"""
Agent 调度器

提供 Agent 任务调度和执行管理功能。
"""

from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .models import FlowContext, ScheduledTask

logger = get_logger(__name__)


class AgentScheduler:
    """Agent 调度器

    负责管理和执行计划任务。
    """

    _instance: Optional["AgentScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, storage_path: str = None):
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self._tasks: Dict[str, ScheduledTask] = {}
        self._task_handlers: Dict[str, Callable] = {}  # action -> handler
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        # RLock: persist 在持锁路径(add_task/remove_task/_execute_task)内可安全调用
        self._task_lock = threading.RLock()
        self._event_handlers: List[Callable] = []
        # 任务持久化: 重启不丢(内存态是遗留缺陷)
        import os
        self.storage_path = str(
            storage_path or os.environ.get("NEUROVA_SCHEDULER_STORE") or "data/scheduler_tasks.json"
        )
        self._load_from_storage()

        logger.info("AgentScheduler initialized (storage=%s)", self.storage_path)

    # ── 任务持久化 ──
    def _load_from_storage(self) -> None:
        """启动加载: 从 JSON 重建任务(内存态 → 持久化修复)"""
        try:
            import json
            from pathlib import Path as _P

            p = _P(self.storage_path)
            if not p.exists():
                return
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, list):
                return
            for item in raw:
                try:
                    task = ScheduledTask(**item)
                    if task.task_id:
                        self._tasks[task.task_id] = task
                except Exception:  # noqa: BLE001 — 单条损坏不阻断整体加载
                    logger.warning("skip corrupted schedule entry: %s", str(item)[:80])
            logger.info("loaded %d scheduled task(s) from storage", len(self._tasks))
        except Exception as e:  # noqa: BLE001
            logger.warning("load scheduler storage failed: %s", e)

    def _persist(self) -> None:
        """快照落盘(RLock 允许多次进入)"""
        try:
            import json
            from dataclasses import asdict
            from pathlib import Path as _P

            with self._task_lock:
                snapshot = [asdict(t) for t in self._tasks.values()]
            p = _P(self.storage_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:  # noqa: BLE001
            logger.warning("persist scheduler storage failed: %s", e)

    def register_handler(self, action: str, handler: Callable) -> None:
        """注册任务处理器

        Args:
            action: 动作名称
            handler: 处理函数，签名: (task: ScheduledTask, context: FlowContext) -> Any
        """
        self._task_handlers[action] = handler
        logger.info("Registered handler for action: %s", action)

    def add_task(self, task: ScheduledTask) -> bool:
        """添加任务

        Args:
            task: 计划任务

        Returns:
            是否添加成功
        """
        with self._task_lock:
            if task.task_id in self._tasks:
                logger.warning("Task already exists: %s", task.task_id)
                return False

            self._tasks[task.task_id] = task
            logger.info("Task added: %s (%s)", task.task_id, task.name)
            self._emit_event("task_added", task)
            self._persist()
            return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务

        Args:
            task_id: 任务ID

        Returns:
            是否移除成功
        """
        with self._task_lock:
            if task_id not in self._tasks:
                return False

            task = self._tasks.pop(task_id)
            logger.info("Task removed: %s (%s)", task_id, task.name)
            self._emit_event("task_removed", task)
            self._persist()
            return True

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, status: str = None) -> List[ScheduledTask]:
        """列出任务

        Args:
            status: 按状态过滤

        Returns:
            任务列表
        """
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def schedule_task(
        self,
        name: str,
        action: str,
        agent_id: str = "",
        scheduled_at: float = None,
        interval_seconds: int = None,
        parameters: Dict[str, Any] = None,
        cron_expression: str = None,
    ) -> ScheduledTask:
        """创建并添加任务

        Args:
            name: 任务名称
            action: 执行的动作
            agent_id: 执行的 Agent ID
            scheduled_at: 计划执行时间
            interval_seconds: 重复间隔（秒）
            parameters: 动作参数
            cron_expression: Cron 表达式(5 段 分时日月周)

        Returns:
            创建的任务
        """
        task = ScheduledTask(
            name=name,
            action=action,
            agent_id=agent_id,
            scheduled_at=scheduled_at,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            parameters=parameters or {},
        )
        # 初始排程: interval/cron 预置 next_run_at, 否则首轮 is_due 恒 False 永不触发
        from .models import compute_next_run

        if task.cron_expression or interval_seconds:
            task.next_run_at = compute_next_run(
                cron_expression=task.cron_expression,
                interval_seconds=interval_seconds,
            )
        self.add_task(task)
        return task

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None
        logger.info("Scheduler stopped")

    def _scheduler_loop(self) -> None:
        """调度器主循环"""
        while self._running:
            try:
                self._check_and_execute_tasks()
                time.sleep(1)  # 每秒检查一次
            except Exception as e:
                logger.exception("Error in scheduler loop: %s", e)
                time.sleep(5)  # 出错后等待更长时间

    def _check_and_execute_tasks(self) -> None:
        """检查并执行到期任务"""
        with self._task_lock:
            due_tasks = [task for task in self._tasks.values() if task.is_due()]

        for task in due_tasks:
            self._execute_task(task)

    def _execute_task(self, task: ScheduledTask) -> None:
        """执行任务"""
        handler = self._task_handlers.get(task.action)
        if not handler:
            logger.error("No handler registered for action: %s", task.action)
            task.mark_failed(f"No handler for action: {task.action}")
            return

        task.mark_running()
        self._persist()
        self._emit_event("task_started", task)

        try:
            # 创建执行上下文
            context = FlowContext()

            # 执行处理器
            result = handler(task, context)

            task.mark_completed(result)
            self._persist()
            self._emit_event("task_completed", task)
            logger.info("Task completed: %s (%s)", task.task_id, task.name)

        except Exception as e:
            task.mark_failed(str(e))
            self._persist()
            self._emit_event("task_failed", task, {"error": str(e)})
            logger.exception("Task failed: %s (%s): %s", task.task_id, task.name, e)

    def add_event_handler(self, handler: Callable) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def _emit_event(self, event_type: str, task: ScheduledTask, data: Dict[str, Any] = None) -> None:
        """触发事件"""
        event_data = {
            "event_type": event_type,
            "task_id": task.task_id,
            "task_name": task.name,
            "timestamp": time.time(),
            **(data or {}),
        }

        for handler in self._event_handlers:
            try:
                handler(event_data)
            except Exception as e:
                logger.exception("Error in event handler: %s", e)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        tasks = list(self._tasks.values())
        return {
            "total_tasks": len(tasks),
            "pending_tasks": len([t for t in tasks if t.status == "pending"]),
            "running_tasks": len([t for t in tasks if t.status == "running"]),
            "completed_tasks": len([t for t in tasks if t.status == "completed"]),
            "failed_tasks": len([t for t in tasks if t.status == "failed"]),
            "cancelled_tasks": len([t for t in tasks if t.status == "cancelled"]),
            "is_running": self._running,
        }


# 全局调度器实例
_global_scheduler: Optional[AgentScheduler] = None


def get_scheduler() -> AgentScheduler:
    """获取全局调度器"""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = AgentScheduler()
    return _global_scheduler


def register_action_handlers(scheduler: "AgentScheduler", agent_resolver=None) -> None:
    """注册调度动作处理器(断点修复: 此前全仓零注册, 任务触发即失败)。

    handler 签名: (task: ScheduledTask, context: FlowContext) -> Any
    同步执行; agent 交互(chat/execute_skill/run_workflow 均 async)经
    asyncio.run 桥接(调度线程无运行中事件循环)。

    agent_resolver(task) -> agent 对象; 缺省从 app state.agents 按
    task.agent_id(兜底 default)解析。
    """

    def _resolve(task):
        if agent_resolver is not None:
            return agent_resolver(task)
        try:
            from neurova.api.endpoints import get_app_state

            state = get_app_state() or {}
            agents = (state.get("agents") or {}) or {}
        except Exception:
            agents = {}
        return agents.get(task.agent_id or "default") or agents.get("default")

    def _send_message(task, ctx):
        agent = _resolve(task)
        if agent is None:
            raise RuntimeError(f"agent not found: {task.agent_id or 'default'}")
        message = (task.parameters or {}).get("message", "")
        import asyncio

        return asyncio.run(agent.chat(message))

    def _execute_skill(task, ctx):
        agent = _resolve(task)
        skill_id = (task.parameters or {}).get("skill_id", "") or ""
        if not skill_id:
            raise RuntimeError("execute_skill requires parameters.skill_id")
        registry = getattr(agent, "_skill_registry", None)
        if registry is None:
            raise RuntimeError("agent skill registry not available")
        import asyncio

        return asyncio.run(registry.execute_skill(skill_id, dict(task.parameters or {})))

    def _run_workflow(task, ctx):
        workflow_id = (task.parameters or {}).get("workflow_id", "") or ""
        if not workflow_id:
            raise RuntimeError("run_workflow requires parameters.workflow_id")
        from neurova.api.endpoints.neurflow_api import get_workflow_agent_deps

        deps = get_workflow_agent_deps()
        workflow = deps["load_published_workflow"](workflow_id)
        if workflow is None:
            raise RuntimeError(f"workflow not found or not published: {workflow_id}")
        inputs = (task.parameters or {}).get("inputs") or {}
        import asyncio

        return asyncio.run(deps["run_workflow"](workflow, inputs))

    scheduler.register_handler("send_message", _send_message)
    scheduler.register_handler("execute_skill", _execute_skill)
    scheduler.register_handler("run_workflow", _run_workflow)
    logger.info("registered scheduler action handlers: send_message / execute_skill / run_workflow")
