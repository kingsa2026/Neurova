# -*- coding: utf-8 -*-
"""批 B3：工作流审批真合并——未决登记与裁决下沉 ApprovalManager（唯一事实源）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 B3，
教义第 7 条）：链 A（工作流 exec_approval）此前自持内存登记 + Event 等待；
治理 ASK（ApprovalManager）有 SQLite 落库、裁决回调、带外重放。同一功能两套
实现并存。本批：登记与裁决收口到 ApprovalManager——关键词面与治理 HTTP 面
同源同权（谁先裁决谁生效），等待走 relay future（跨线程裁决经
call_soon_threadsafe 唤醒），内存 dict 退役。

复活语义（随格落死）：工作流实例是进程内状态，重启后 PENDING 行**不假复活**
——由 ApprovalManager 的 TTL 惰性到期诚实闭单（登记落库的价值是治理面可见
与带外裁决，不是假装工作流还活着）。
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import neurova.collaboration.neurflow.builtin as builtin


class FakeChannelManager:
    def __init__(self):
        self.handlers = {}
        self._nextId = 0
        self.sent = []

    async def send_message(self, channel_type, chat_id, content, message_type="text", **kw):
        self.sent.append(content)
        return "msg-1"

    def add_message_handler(self, handler, priority=0):
        hid = self._nextId
        self._nextId += 1
        self.handlers[hid] = handler
        return hid

    def remove_message_handler(self, hid):
        self.handlers.pop(hid, None)
        return True

    async def fanout(self, content, sender_id):
        self._fanoutSeq = getattr(self, "_fanoutSeq", 0) + 1
        message = SimpleNamespace(content=content, sender_id=sender_id,
                                  message_id=f"om_fanout_{self._fanoutSeq}")
        for handler in list(self.handlers.values()):
            await handler(message)


@pytest.fixture
def env(monkeypatch, tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    mgr = FakeChannelManager()
    monkeypatch.setattr(builtin, "_get_channel_manager", lambda: mgr)
    builtin._resetPendingApprovalsForTests()
    builtin._resetChatApprovalQueuesForTests()
    yield mgr
    builtin._resetPendingApprovalsForTests()
    builtin._resetChatApprovalQueuesForTests()


def _cfg(timeout=5.0):
    return {"approver": "u1", "channel": "feishu", "message": "请审批", "timeout": timeout}


def _ctx(execution_id="exec-m", node_id="n1"):
    return {"execution_id": execution_id, "node_id": node_id}


def _workflowPendings():
    from neurova.security.approval_manager import get_approval_manager

    return [r for r in get_approval_manager().get_pending_requests()
            if (r.metadata or {}).get("source") == "workflow"]


class TestManagedRegistration:
    @pytest.mark.asyncio
    async def test_pendingIsPersistedInApprovalManager(self, env):
        """登记下沉：未决在 ApprovalManager 里可见（治理面从此看得到工作流审批）。"""
        task = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx()))
        for _ in range(200):
            if _workflowPendings():
                break
            await asyncio.sleep(0.01)

        pendings = _workflowPendings()
        assert len(pendings) == 1, f"未决没有落 ApprovalManager（实得 {len(pendings)}）"
        req = pendings[0]
        assert req.user_id == "u1"
        assert req.metadata.get("approval_key") == "exec-m:n1"
        assert req.metadata.get("execution_id") == "exec-m"

        await env.fanout("同意", "u1")
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result["status"] == "success" and result["output"]["approved"] is True
        from neurova.security.approval_manager import get_approval_manager
        assert _workflowPendings() == [], "裁决后未决应清零"

    @pytest.mark.asyncio
    async def test_keywordApprovalGoesThroughManager(self, env):
        """关键词裁决走 ApprovalManager 落库——终态在事实源可查，不只在节点返回值里。"""
        task = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx()))
        for _ in range(200):
            if _workflowPendings():
                break
            await asyncio.sleep(0.01)

        await env.fanout("拒绝，先别上线", "u1")
        result = await asyncio.wait_for(task, timeout=2.0)

        assert result["status"] == "success" and result["output"]["approved"] is False
        from neurova.security.approval_manager import ApprovalStatus, get_approval_manager
        rows = [r for r in get_approval_manager()._requests.values()
                if (r.metadata or {}).get("source") == "workflow"]
        assert rows and rows[0].status == ApprovalStatus.REJECTED, (
            "关键词裁决没有经 ApprovalManager 落库——事实源与节点返回值脱节"
        )

    @pytest.mark.asyncio
    async def test_httpApprovalWakesTheChannelWaiter(self, env):
        """带外裁决（治理 HTTP 面）唤醒渠道等待方——两条裁决面同源同权。"""
        from neurova.security.approval_manager import get_approval_manager

        task = asyncio.create_task(builtin.exec_approval(_cfg(timeout=10), _ctx()))
        for _ in range(200):
            if _workflowPendings():
                break
            await asyncio.sleep(0.01)
        request_id = _workflowPendings()[0].request_id

        # 模拟治理 HTTP 线程：跨线程裁决（relay 经 call_soon_threadsafe 唤醒）
        def _httpApprove():
            assert get_approval_manager().approve_request(request_id, approved_by="admin") is True

        await asyncio.get_event_loop().run_in_executor(None, _httpApprove)

        result = await asyncio.wait_for(task, timeout=2.0)
        assert result["status"] == "success" and result["output"]["approved"] is True, (
            f"带外批准没有唤醒渠道等待方：{result}"
        )

    @pytest.mark.asyncio
    async def test_timeoutExpiresTheRequestHonestly(self, env):
        """超时闭单：请求显式 EXPIRED——不留给 HTTP 裁决一个'批了也没人听'的假面。"""
        from neurova.security.approval_manager import ApprovalStatus, get_approval_manager

        result = await builtin.exec_approval(_cfg(timeout=0.3), _ctx())
        assert result["status"] == "timeout"
        rows = [r for r in get_approval_manager()._requests.values()
                if (r.metadata or {}).get("source") == "workflow"]
        assert rows and rows[0].status == ApprovalStatus.EXPIRED, (
            f"超时后请求状态 {rows[0].status if rows else '无'}——PENDING 残留是假面"
        )

    def test_inMemoryDictRegistryIsRetired(self):
        """退役判据（教义第 7 条）：内存平行登记不许残留——留下第二份即未闭环。"""
        import inspect
        import pathlib

        src = pathlib.Path(builtin.__file__).read_text(encoding="utf-8")
        assert "_PENDING_APPROVALS" not in src, "内存登记 dict 还在——真合并没闭环"
        assert inspect.iscoroutinefunction(builtin.exec_approval)
