"""
NeurFlow P1 Step 5 — Cron 触发绑定测试（TriggerManager）

契约（neurova/collaboration/neurflow/triggers.py）：
- TriggerManager 注入 scheduler（apscheduler-like）与 fire 回调
- register_cron(trigger) → scheduler.add_job 被调用（cron 表达式来自 trigger.config）
- unregister(trigger_id) → scheduler.remove_job
- restore_enabled(loader) → 从 loader 恢复全部启用 cron trigger
- fire 语义：经注入的 dispatch 回调派发（manager 不直接碰存储/引擎）

TDD：先红后绿。mock scheduler，不真实 apscheduler。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger
from neurova.collaboration.neurflow.triggers import TriggerManager


def _cron_trigger(**overrides):
    fields = dict(
        id="trg_c1",
        workflow_id="wf_1",
        type=TriggerType.CRON,
        config={"cron": "0 9 * * 1-5"},
        enabled=True,
    )
    fields.update(overrides)
    return WorkflowTrigger(**fields)


class TestTriggerManagerContract:
    def test_manager_importable(self):
        assert TriggerManager is not None

    def test_defaults(self):
        m = TriggerManager()
        assert m._scheduler is None
        assert m._jobs == {}

    def test_accepts_scheduler_and_dispatch(self):
        sched = MagicMock()
        dispatch = AsyncMock()
        m = TriggerManager(scheduler=sched, dispatch=dispatch)
        assert m._scheduler is sched
        assert m._dispatch is dispatch


class TestRegisterCron:
    @pytest.mark.asyncio
    async def test_register_creates_apscheduler_job(self):
        sched = MagicMock()
        sched.add_job.return_value = MagicMock(id="job_x")
        m = TriggerManager(scheduler=scheduler_stub(sched))

        tr = _cron_trigger()
        job_id = await m.register_cron(tr)

        sched.add_job.assert_called_once()
        call_kwargs = sched.add_job.call_args.kwargs
        # trigger 参数应为 CronTrigger 实例（from_crontab 解析 config["cron"]）
        from apscheduler.triggers.cron import CronTrigger

        assert isinstance(call_kwargs.get("trigger"), CronTrigger)
        assert call_kwargs.get("id") == "trg_c1" or job_id == "trg_c1"
        assert m._jobs["trg_c1"] is not None

    @pytest.mark.asyncio
    async def test_register_non_cron_rejected(self):
        m = TriggerManager()
        tr = _cron_trigger(type=TriggerType.WEBHOOK)
        with pytest.raises(ValueError):
            await m.register_cron(tr)

    @pytest.mark.asyncio
    async def test_register_missing_cron_expr_rejected(self):
        m = TriggerManager()
        tr = _cron_trigger(config={})
        with pytest.raises(ValueError):
            await m.register_cron(tr)


class TestUnregister:
    @pytest.mark.asyncio
    async def test_unregister_removes_job(self):
        sched = MagicMock()
        m = TriggerManager(scheduler=scheduler_stub(sched))
        await m.register_cron(_cron_trigger())

        await m.unregister("trg_c1")
        sched.remove_job.assert_called_once_with("trg_c1")
        assert "trg_c1" not in m._jobs

    @pytest.mark.asyncio
    async def test_unregister_unknown_id_is_noop(self):
        m = TriggerManager()
        await m.unregister("never_registered")  # 不抛异常


class TestRestoreEnabled:
    @pytest.mark.asyncio
    async def test_restore_registers_all_enabled_cron_triggers(self):
        sched = MagicMock()
        m = TriggerManager(scheduler=scheduler_stub(sched))

        loader = MagicMock(
            return_value=[
                _cron_trigger(id="trg_a"),
                _cron_trigger(id="trg_b", config={"cron": "*/5 * * * *"}),
            ]
        )
        restored = await m.restore_enabled(loader)

        assert restored == 2
        assert "trg_a" in m._jobs
        assert "trg_b" in m._jobs

    @pytest.mark.asyncio
    async def test_restore_with_no_loader_is_zero(self):
        m = TriggerManager()
        assert await m.restore_enabled(None) == 0


class TestFire:
    @pytest.mark.asyncio
    async def test_fire_calls_dispatch(self):
        dispatch = AsyncMock(return_value={"success": True})
        m = TriggerManager(dispatch=dispatch)

        tr = _cron_trigger()
        await m.fire(tr, {"k": "v"})
        dispatch.assert_awaited_once_with("wf_1", {"k": "v"})

    @pytest.mark.asyncio
    async def test_fire_without_dispatch_is_safe(self):
        m = TriggerManager()
        await m.fire(_cron_trigger(), {})  # 不抛异常


def scheduler_stub(mock_sched):
    """包一层以满足构造器类型宽容度（测试用 mock 直传亦可）。"""
    return mock_sched
