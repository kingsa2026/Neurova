"""负一屏推送链路残留修复回归（2026-09-12 用户指定「修复残留」）。

根因两处：
1. 生产 get_notification_manager() 从不传 negative_screen_config_manager
   → _schedule_negative_screen_push 永不触发（推送链路整体休眠）；
2. task_completed 通知类型全仓无生产者——AgentScheduler._emit_event
   ("task_completed") 只走 _event_handlers，而 add_event_handler 无调用方，
   任务完成从不镜像为站内通知。

修复契约：
1. 单例缺省注入 create_negative_screen_config_manager()（与负一屏设置页
   同源目录 data/negative_screen，用户配置即时生效）；
2. get_scheduler() 创建时注册通知桥：task_completed → task_completed 通知
   （触发负一屏推送判定）；task_failed → task_failed 通知（普通站内，不推送）；
   接收人=notify_admins（无注册管理员兜底 default，与门面语义一致）；
3. 桥注册幂等（重复 get_scheduler 不叠加 handler）。
"""
import os

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_nsg_bridge_012345")

import neurova.collaborate.workflow.scheduler as sched_mod
from neurova.collaborate.workflow.models import ScheduledTask
from neurova.api.endpoints import notifications as api_ep
from neurova.notifications import manager as mem


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    monkeypatch.setenv("NEUROVA_SCHEDULER_STORE", str(tmp_path / "scheduler_tasks.json"))
    mem.reset_notification_manager()
    # 重置调度器单例（类级 __new__ 单例 + 模块级 _global_scheduler）
    saved_inst = sched_mod.AgentScheduler._instance
    saved_global = sched_mod._global_scheduler
    sched_mod.AgentScheduler._instance = None
    sched_mod._global_scheduler = None
    yield tmp_path
    sched_mod.AgentScheduler._instance = saved_inst
    sched_mod._global_scheduler = saved_global
    mem.reset_notification_manager()


class TestConfigManagerInjection:
    def test_singleton_has_default_config_manager(self, isolated):
        nm = mem.get_notification_manager()
        assert nm._negative_screen_config_manager is not None, (
            "生产单例未注入负一屏配置管理器，推送链路休眠"
        )

    def test_endpoint_facade_shares_same_singleton(self, isolated):
        assert api_ep.get_notification_manager() is mem.get_notification_manager()


class TestSchedulerNotificationBridge:
    def _emit(self, event_type, task_name="每日摘要", error=None):
        sched = sched_mod.get_scheduler()
        task = ScheduledTask(name=task_name, agent_id="a1")
        data = {"error": error} if error else None
        sched._emit_event(event_type, task, data)

    def test_task_completed_mirrors_notification_and_push_decision(self, isolated):
        nm = mem.get_notification_manager()
        calls = []
        nm._schedule_negative_screen_push = (
            lambda user_id, notification: calls.append(user_id)
        )
        self._emit("task_completed")
        items = nm.get_user_notifications("default", limit=50)
        assert any(n.notification_type == "task_completed" for n in items), (
            "调度任务完成未镜像为站内通知"
        )
        assert calls, "task_completed 应触发负一屏推送判定"

    def test_task_failed_mirrors_notification_without_push(self, isolated):
        nm = mem.get_notification_manager()
        calls = []
        nm._schedule_negative_screen_push = (
            lambda user_id, notification: calls.append(user_id)
        )
        self._emit("task_failed", error="boom")
        items = nm.get_user_notifications("default", limit=50)
        failed = [n for n in items if n.notification_type == "task_failed"]
        assert failed, "任务失败未镜像为站内通知"
        assert "boom" in failed[0].message
        assert not calls, "task_failed 不触发负一屏推送（仅完成推送）"

    def test_bridge_registration_is_idempotent(self, isolated):
        sched_mod.get_scheduler()
        sched = sched_mod.get_scheduler()  # 第二次不得叠加桥
        before = len(sched._event_handlers)
        nm = mem.get_notification_manager()
        self._emit("task_completed", task_name="once")
        items = nm.get_user_notifications("default", limit=50)
        mine = [n for n in items if n.notification_type == "task_completed"]
        assert len(mine) == 1, f"桥重复注册：{len(mine)} 条"
        assert len(sched._event_handlers) == before

    def test_bridge_notification_persisted(self, isolated):
        self._emit("task_completed")
        mem.reset_notification_manager()
        nm = mem.get_notification_manager()
        assert any(
            n.notification_type == "task_completed"
            for n in nm.get_user_notifications("default", limit=50)
        ), "桥通知未落盘"


class TestPushFullChain:
    """全链集成钉：真 config manager + 假 pusher → 后台推送 → 状态回写并落盘。

    证明注入点打通后 task_completed 通知确实走完
    add_notification → _schedule_negative_screen_push → push_task → 状态持久化。
    """

    def test_task_completed_pushes_and_persists_state(self, isolated, tmp_path):
        import time as _t

        from neurova.notifications.negative_screen import (
            NegativeScreenConfig,
            NegativeScreenConfigManager,
            PushResult,
        )

        config_manager = NegativeScreenConfigManager(data_dir=str(tmp_path / "ns"))
        config_manager.save_config(NegativeScreenConfig(
            user_id="alice", auth_code="test-auth", enabled=True,
        ))

        class _FakePusher:
            async def push_task(self, **kwargs):
                return PushResult(success=True, task_id="tk-live")

        nm = mem.NotificationManager(
            negative_screen_config_manager=config_manager,
            negative_screen_pusher=_FakePusher(),
            storage_path=str(tmp_path / "ns_notifications.json"),
        )
        n = nm.add_notification(
            user_id="alice", title="任务完成", message="报表已生成",
            notification_type="task_completed",
        )
        # 后台线程推送：轮询回写完成（上限 5s）
        deadline = _t.time() + 5
        while _t.time() < deadline and not n.negative_screen_pushed:
            _t.sleep(0.05)
        assert n.negative_screen_pushed is True, "假推送未回写状态"
        assert n.negative_screen_task_id == "tk-live"
        # 状态随通知落盘：新实例读同文件可回读
        nm2 = mem.NotificationManager(
            storage_path=str(tmp_path / "ns_notifications.json"),
        )
        got = nm2.get_notification(n.notification_id)
        assert got.negative_screen_pushed is True
        assert nm2.get_push_statistics("alice")["pushed_to_negative_screen"] == 1
