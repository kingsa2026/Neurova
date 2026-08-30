"""
NeurFlow 遗留③ — 触发器启动装配测试

契约（triggers.setup_workflow_triggers / shutdown_workflow_triggers）：
- setup_workflow_triggers(loader=None, scheduler=None)：
  - 创建并启动 AsyncIOScheduler（或用注入的）
  - set_trigger_scheduler 挂到全局 TriggerManager
  - restore_enabled(loader) 恢复 cron 触发器，返回恢复数
- 幂等：二次调用返回 0 且不重复注册 job
- shutdown_workflow_triggers()：停 scheduler

TDD：先红后绿。loader/scheduler 均可注入。
"""
import pytest
from unittest.mock import MagicMock

from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger
from neurova.collaboration.neurflow import triggers as trg
from neurova.collaboration.neurflow.triggers import (
    get_trigger_manager,
    setup_workflow_triggers,
    shutdown_workflow_triggers,
)


def _cron_trigger(trigger_id="trg_boot1"):
    return WorkflowTrigger(
        id=trigger_id,
        workflow_id="wf_boot",
        type=TriggerType.CRON,
        enabled=True,
        config={"cron": "0 9 * * 1-5"},
    )


@pytest.fixture(autouse=True)
def _reset_manager():
    """每个用例前后重置全局单例（隔离）。"""
    trg._manager = None
    trg._bootstrapped = False
    yield
    trg._manager = None
    trg._bootstrapped = False


class TestSetupWorkflowTriggers:
    @pytest.mark.asyncio
    async def test_setup_starts_scheduler_and_restores(self, tmp_path):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        loader = MagicMock(return_value=[_cron_trigger()])
        restored = await setup_workflow_triggers(loader=loader)

        assert restored == 1
        manager = get_trigger_manager()
        assert manager._scheduler is not None
        assert isinstance(manager._scheduler, AsyncIOScheduler)
        assert manager._scheduler.running
        assert "trg_boot1" in manager._jobs

        # shutdown 不抛异常即可（AsyncIOScheduler 停止是异步的，running 不即时翻转）
        await shutdown_workflow_triggers()

    @pytest.mark.asyncio
    async def test_idempotent_second_call_restores_zero(self, tmp_path):
        loader = MagicMock(return_value=[_cron_trigger()])
        await setup_workflow_triggers(loader=loader)
        second = await setup_workflow_triggers(loader=loader)
        assert second == 0
        await shutdown_workflow_triggers()

    @pytest.mark.asyncio
    async def test_injected_scheduler_used(self):
        sched = MagicMock()
        sched.running = True
        loader = MagicMock(return_value=[])
        await setup_workflow_triggers(loader=loader, scheduler=sched)
        assert get_trigger_manager()._scheduler is sched
        await shutdown_workflow_triggers()