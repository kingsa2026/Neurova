"""P1-11 审批持久化状态机（OpenClaw 启发）— TDD 测试

参照 OpenClaw exec-approvals：审批是持久化状态机——
- first-answer-wins：并发/重复裁决只有第一次 PENDING→terminal 生效，其余返回 False；
- 状态机迁移合法：仅 PENDING 可迁出到 APPROVED/REJECTED/EXPIRED；
- 通知镜像：创建与裁决都发站内通知（聊天渠道/铃铛镜像路由的底座）；
- terminal 记录保留（30 天窗口查询），批准/拒绝记录落 SQLite。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.security.approval_manager import (
    ApprovalManager,
    ApprovalStatus,
)


class _StateMachineTest(unittest.TestCase):
    """SQLite 持久化状态机"""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp()
        self.am = ApprovalManager(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class TestFirstAnswerWins(_StateMachineTest):
    """first-answer-wins：一次裁决，重复裁决拒绝"""

    def test_double_approve_second_fails(self):
        r = self.am.create_approval_request("a1", "u1", "sudo rm -rf /")
        assert self.am.approve_request(r.request_id, "user_a") is True
        # 第二次批准（哪怕换人）必须失败
        assert self.am.approve_request(r.request_id, "user_b") is False
        assert self.am.get_request(r.request_id).approved_by == "user_a"

    def test_approve_after_reject_fails(self):
        r = self.am.create_approval_request("a1", "u1", "sudo rm -rf /")
        assert self.am.reject_request(r.request_id, "user_a") is True
        assert self.am.approve_request(r.request_id, "user_b") is False

    def test_reject_after_approve_fails(self):
        r = self.am.create_approval_request("a1", "u1", "sudo rm -rf /")
        self.am.approve_request(r.request_id, "user_a")
        assert self.am.reject_request(r.request_id, "user_b") is False

    def test_concurrent_decisions_only_one_wins(self):
        """并发裁决（两线程同时批准）恰好一个成功"""
        import threading

        r = self.am.create_approval_request("a1", "u1", "sudo rm -rf /")
        results = []

        def decider(name):
            results.append(self.am.approve_request(r.request_id, name))

        t1 = threading.Thread(target=decider, args=("user_a",))
        t2 = threading.Thread(target=decider, args=("user_b",))
        t1.start(); t2.start(); t1.join(); t2.join()
        assert sorted(results) == [False, True]


class TestStateMachineTransitions(_StateMachineTest):
    """状态机迁移合法性"""

    def test_approved_request_not_in_pending(self):
        r = self.am.create_approval_request("a1", "u1", "cmd")
        self.am.approve_request(r.request_id, "u")
        assert all(x.request_id != r.request_id for x in self.am.get_pending_requests())

    def test_expired_request_cannot_be_approved(self):
        import datetime

        r = self.am.create_approval_request("a1", "u1", "cmd")
        # 手动把请求改为已过期
        req = self.am.get_request(r.request_id)
        req.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        assert self.am.approve_request(r.request_id, "u") is False
        assert self.am.get_request(r.request_id).status == ApprovalStatus.EXPIRED

    def test_terminal_records_kept(self):
        """terminal 记录保留可查（非删除）"""
        r1 = self.am.create_approval_request("a1", "u1", "cmd1")
        r2 = self.am.create_approval_request("a1", "u1", "cmd2")
        self.am.approve_request(r1.request_id, "u")
        self.am.reject_request(r2.request_id, "u")
        assert self.am.get_request(r1.request_id).status == ApprovalStatus.APPROVED
        assert self.am.get_request(r2.request_id).status == ApprovalStatus.REJECTED


class TestSqlitePersistence(_StateMachineTest):
    """SQLite 持久化：重启恢复"""

    def test_sqlite_db_created(self):
        import sqlite3

        db_path = Path(self.tmp) / ".approval" / "approvals.db"
        assert db_path.exists(), "审批 SQLite 库应随管理器初始化创建"
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "approval_requests" in tables

    def test_requests_survive_restart(self):
        """裁决后重建管理器：状态从 SQLite 恢复"""
        r = self.am.create_approval_request("a1", "u1", "sudo rm -rf /tmp/x")
        self.am.approve_request(r.request_id, "user_a", note="ok")

        am2 = ApprovalManager(self.tmp)
        restored = am2.get_request(r.request_id)
        assert restored is not None
        assert restored.status == ApprovalStatus.APPROVED
        assert restored.approved_by == "user_a"
        assert restored.approval_note == "ok"

    def test_pending_survives_restart(self):
        """未裁决请求重启后仍 PENDING 可继续审批"""
        r = self.am.create_approval_request("a1", "u1", "cmd-x")
        am2 = ApprovalManager(self.tmp)
        pend = [x.request_id for x in am2.get_pending_requests()]
        assert r.request_id in pend
        assert am2.approve_request(r.request_id, "late_user") is True


class TestNotificationMirror(_StateMachineTest):
    """站内通知镜像（渠道镜像路由底座）"""

    def test_creation_mirrors_notification(self):
        from neurova.notifications.manager import NotificationManager

        nm = NotificationManager()
        with patch(
            "neurova.notifications.manager.get_notification_manager", return_value=nm
        ):
            r = self.am.create_approval_request("a1", "u1", "sudo reboot")
        types = [n.notification_type for n in nm._notifications.values()]
        assert "approval_request" in types

    def test_decision_mirrors_notification(self):
        from neurova.notifications.manager import NotificationManager

        nm = NotificationManager()
        with patch(
            "neurova.notifications.manager.get_notification_manager", return_value=nm
        ):
            r = self.am.create_approval_request("a1", "u1", "sudo reboot")
            self.am.approve_request(r.request_id, "u")
        types = [n.notification_type for n in nm._notifications.values()]
        assert "approval_request" in types
        assert "approval_result" in types

    def test_notification_failure_never_blocks_approval(self):
        """通知故障不阻断审批主流程"""
        with patch(
            "neurova.security.approval_manager._mirror_approval_notification",
            side_effect=RuntimeError("notify down"),
        ):
            r = self.am.create_approval_request("a1", "u1", "cmd")
            assert self.am.approve_request(r.request_id, "u") is True


class TestGovernanceEndpointGuards(_StateMachineTest):
    """端点层 409 幂等防护（governance.py 已有，锁状态机契约）"""

    def test_status_transition_methods_exist(self):
        """管理器暴露裁决 API（端点契约面）"""
        assert hasattr(self.am, "approve_request")
        assert hasattr(self.am, "reject_request")
        assert hasattr(self.am, "get_pending_requests")
        assert hasattr(self.am, "get_request")
