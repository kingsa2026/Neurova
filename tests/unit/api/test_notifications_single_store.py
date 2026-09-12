"""通知中心双实现收口 + 审批镜像真实落盘回归（2026-09-12 空数据页面排查）。

根因（比"内存无持久"更深）：存在两套并行 NotificationManager——
- neurova/notifications/manager.py（#1 内存版，含负一屏推送）：approval_manager
  的审批镜像写这套；
- neurova/api/endpoints/notifications.py（#2 JSON 持久版）：铃铛/NotificationPage
  端点读这套。
两个单例互不相通 → 审批通知在通知页**永远不可见**（不只是重启丢），且 #1 完全无持久化。

修复契约:
1. 单实现收口：#1 加 JSON 持久化（NEUROVA_NOTIFICATIONS_PATH，默认 data/notifications.json，
   格式与旧 #2 兼容并增存 negative_screen_* 推送状态），端点 re-export #1；
2. approval 镜像 → 端点同一单例可读；
3. add/mark_read/delete/负一屏状态更新 均落盘，重启可回读。
"""
import os

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_notif_merge_0123456")

from neurova.api.endpoints import notifications as api_ep
from neurova.notifications import manager as mem


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "notifications.json"
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(path))
    mem.reset_notification_manager()
    if hasattr(api_ep, "reset_notification_manager"):
        api_ep.reset_notification_manager()
    yield path
    mem.reset_notification_manager()
    if hasattr(api_ep, "reset_notification_manager"):
        api_ep.reset_notification_manager()


class TestSingleStore:
    def test_manager_is_one_singleton_across_imports(self):
        assert mem.get_notification_manager() is api_ep.get_notification_manager(), (
            "双实现未收口：approval 写入与铃铛读取不同实例"
        )

    def test_approval_mirror_visible_to_endpoint_store(self):
        from neurova.security import approval_manager as am

        am._mirror_approval_notification("approval_request", {
            "request_id": "r-1", "user_id": "admin", "command": "sudo reboot",
            "agent_id": "a1",
        })
        items = api_ep.get_notification_manager().get_user_notifications("admin", limit=50)
        assert any(n.notification_type == "approval_request" for n in items), (
            "审批镜像未进入通知页读取的存储"
        )


class TestPersistence:
    def test_add_written_to_disk_and_survives_restart(self, isolated):
        n = mem.get_notification_manager().add_notification(
            user_id="u1", title="t", message="m", notification_type="info",
        )
        assert isolated.exists(), "通知未落盘"
        mem.reset_notification_manager()
        assert mem.get_notification_manager().get_notification(n.notification_id) is not None

    def test_mark_as_read_persisted(self, isolated):
        n = mem.get_notification_manager().add_notification(
            user_id="u1", title="t", message="m",
        )
        assert mem.get_notification_manager().mark_as_read(n.notification_id, "u1")
        mem.reset_notification_manager()
        got = mem.get_notification_manager().get_notification(n.notification_id)
        assert got.read is True
        assert mem.get_notification_manager().get_unread_count("u1") == 0

    def test_negative_screen_push_state_persisted(self, isolated):
        """负一屏推送字段（#1 特有）必须随通知落盘回读，push-statistics 才有真实值。"""
        nm = mem.get_notification_manager()
        n = nm.add_notification(user_id="u1", title="t", message="m",
                                notification_type="task_completed")
        n.negative_screen_pushed = True
        n.negative_screen_task_id = "tk-9"
        nm._save()
        mem.reset_notification_manager()
        got = mem.get_notification_manager().get_notification(n.notification_id)
        assert got.negative_screen_pushed is True
        assert got.negative_screen_task_id == "tk-9"
        stats = mem.get_notification_manager().get_push_statistics("u1")
        assert stats["pushed_to_negative_screen"] == 1

    def test_delete_persisted(self, isolated):
        n = mem.get_notification_manager().add_notification(user_id="u1", title="t", message="m")
        mem.get_notification_manager().delete_notification(n.notification_id, "u1")
        mem.reset_notification_manager()
        assert mem.get_notification_manager().get_notification(n.notification_id) is None
