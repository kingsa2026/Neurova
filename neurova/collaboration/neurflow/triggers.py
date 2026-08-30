"""
Cron 触发绑定管理（P1 Step 5）

TriggerManager：apscheduler-like scheduler 的注入式薄管理器。
- register_cron：把 WorkflowTrigger(cron) 注册为 scheduler job
- unregister：移除 job
- restore_enabled：应用启动时从 loader 恢复全部启用的 cron 触发器
- fire：经注入的 dispatch 回调派发（本类不直接依赖存储/引擎）
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from .models import TriggerType, WorkflowTrigger

logger = logging.getLogger(__name__)

# 全局单例（应用启动时由装配方 set_scheduler 注入 APScheduler 实例）
_manager: Optional["TriggerManager"] = None
_bootstrapped = False


def get_trigger_manager() -> "TriggerManager":
    """全局 TriggerManager 单例（惰性创建，scheduler 可后置注入）。"""
    global _manager
    if _manager is None:
        _manager = TriggerManager()
    return _manager


def set_trigger_scheduler(scheduler: Any) -> None:
    """应用启动装配：把 APScheduler 实例挂到全局 TriggerManager。"""
    get_trigger_manager()._scheduler = scheduler


async def setup_workflow_triggers(
    loader: Optional[Callable[[], list]] = None,
    scheduler: Optional[Any] = None,
) -> int:
    """应用启动装配（幂等）：启动调度器并恢复启用的 cron 触发器。

    loader 返回启用触发器列表（通常 storage.list_enabled_triggers(CRON)）；
    scheduler 可注入（默认新建 AsyncIOScheduler 并 start）。
    返回本次恢复的触发器数（已装配过则返回 0）。
    """
    global _bootstrapped
    if _bootstrapped:
        return 0

    manager = get_trigger_manager()
    if scheduler is None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        scheduler.start()
    set_trigger_scheduler(scheduler)

    restored = await manager.restore_enabled(loader)
    _bootstrapped = True
    logger.info("workflow triggers bootstrapped: %s restored", restored)
    return restored


async def shutdown_workflow_triggers() -> None:
    """应用关闭装配：停掉触发器调度器（若在运行）。"""
    manager = get_trigger_manager()
    scheduler = manager._scheduler
    if scheduler is not None and getattr(scheduler, "running", False):
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            logger.info("trigger scheduler shutdown ignored error", exc_info=True)


class TriggerManager:
    """Cron 触发器生命周期管理（注入 scheduler 与 dispatch）。"""

    def __init__(
        self,
        scheduler: Optional[Any] = None,
        dispatch: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    ):
        self._scheduler = scheduler
        self._dispatch = dispatch
        self._jobs: Dict[str, Any] = {}

    async def register_cron(self, trigger: WorkflowTrigger) -> Optional[str]:
        """把 cron 触发器注册为 scheduler job；返回 job id。

        校验：type 必须为 cron；config 必须含 cron 表达式。
        """
        if trigger.type != TriggerType.CRON:
            raise ValueError("only cron triggers can be registered as cron jobs")
        cron_expr = (trigger.config or {}).get("cron")
        if not cron_expr:
            raise ValueError("cron trigger requires config['cron'] expression")

        job_id = trigger.id
        if self._scheduler is None:
            logger.warning("TriggerManager scheduler not configured; job %s skipped", job_id)
            self._jobs[job_id] = None
            return job_id

        from apscheduler.triggers.cron import CronTrigger

        job = self._scheduler.add_job(
            self._scheduled_fire,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=job_id,
            args=[job_id],
        )
        self._jobs[job_id] = job
        logger.info("cron trigger registered: %s -> workflow %s", job_id, trigger.workflow_id)
        return job_id

    async def unregister(self, trigger_id: str) -> None:
        """移除 job；未注册时静默。"""
        if trigger_id not in self._jobs:
            return
        if self._scheduler is not None:
            try:
                self._scheduler.remove_job(trigger_id)
            except Exception:
                logger.info("job %s already gone from scheduler", trigger_id)
        del self._jobs[trigger_id]

    async def restore_enabled(self, loader: Optional[Callable[[], list]]) -> int:
        """从 loader 恢复全部启用的 cron 触发器；返回恢复数量。"""
        if loader is None:
            return 0
        triggers = loader() or []
        restored = 0
        for tr in triggers:
            if tr.type != TriggerType.CRON or not tr.enabled:
                continue
            try:
                await self.register_cron(tr)
                restored += 1
            except Exception:
                logger.exception("restore cron trigger failed: %s", tr.id)
        return restored

    async def fire(
        self, trigger: WorkflowTrigger, inputs: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """手动/定时触发：经注入的 dispatch 派发。"""
        if self._dispatch is None:
            logger.warning("TriggerManager dispatch not configured; fire skipped")
            return None
        return await self._dispatch(trigger.workflow_id, inputs or {})

    def _scheduled_fire(self, trigger_id: str) -> None:
        """scheduler 到期回调入口（同步壳，内部起 task 驱动 fire）。

        job 注册时以 args=[trigger_id] 绑定；触发时经 trigger_loader
        取回 WorkflowDefinition 所需上下文由 dispatch 闭包持有。
        """
        import asyncio

        loader = getattr(self, "_trigger_loader", None)
        if loader is None or self._dispatch is None:
            logger.warning("scheduled fire without loader/dispatch: %s", trigger_id)
            return
        tr = loader(trigger_id)
        if tr is None or not tr.enabled:
            return
        asyncio.get_event_loop().create_task(self.fire(tr))
