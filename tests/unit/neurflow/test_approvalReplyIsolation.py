# -*- coding: utf-8 -*-
"""并发审批的回复隔离（D-3 / N-4）。

立项理由（本仓可核实）：`builtin.exec_approval` 每个节点各自注册一个消息处理器，
处理器只按 `sender_id == approver` 过滤。同一审批人同时有两个未决节点时，一句
`approve` 会命中所有处理器 —— 一次回复批准了**所有**在等的工作流，且没有任何
「同时只容一个未决问题」的隔离。本判据把失败方向钉成：无法定向的回复一律不动。

另两处同文件缺陷一并钉住：
- 关键词表先比批准后比拒绝，`不同意` 里含 `同意` ⇒ 被读成批准；
- 等待被取消时处理器不在 finally 里摘除 ⇒ 每取消一次泄漏一个常驻 handler。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import neurova.collaboration.neurflow.builtin as builtin


class FakeChannelManager:
    """只实现 exec_approval 用到的四个面；handler 列表就是真实扇出入口。"""

    def __init__(self):
        self.handlers = {}
        self._nextId = 0
        self.sent = []

    async def send_message(self, channel_type, chat_id, content, message_type="text", **kw):
        self.sent.append(content)
        return "msg-1"

    async def broadcast_message(self, content, message_type="text", **kw):
        self.sent.append(content)
        return {"feishu": "msg-1"}

    def add_message_handler(self, handler, priority=0):
        hid = self._nextId
        self._nextId += 1
        self.handlers[hid] = handler
        return hid

    def remove_message_handler(self, hid):
        self.handlers.pop(hid, None)
        return True

    async def fanout(self, content, sender_id):
        """平台侧行为：一条入站消息送给当前所有处理器。"""
        message = SimpleNamespace(content=content, sender_id=sender_id)
        for handler in list(self.handlers.values()):
            await handler(message)


def _cfg(approver="u1", timeout=0.4):
    return {"approver": approver, "channel": "feishu", "message": "请审批", "timeout": timeout}


def _ctx(execution_id, node_id):
    return {"execution_id": execution_id, "node_id": node_id}


async def _waitUntil(predicate, timeout=1.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def manager(monkeypatch):
    mgr = FakeChannelManager()
    monkeypatch.setattr(builtin, "_get_channel_manager", lambda: mgr)
    resetter = getattr(builtin, "_resetPendingApprovalsForTests", None)
    if resetter:
        resetter()
    yield mgr
    if resetter:
        resetter()


@pytest.mark.asyncio
async def test_bareKeywordDoesNotApproveTwoPendingNodes(manager):
    t1 = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execA", "n1")))
    t2 = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execB", "n2")))
    assert await _waitUntil(lambda: len(manager.handlers) == 2)

    await manager.fanout("approve", "u1")

    r1, r2 = await asyncio.gather(t1, t2)
    assert r1["status"] == "timeout" and r1["output"]["approved"] is None
    assert r2["status"] == "timeout" and r2["output"]["approved"] is None


@pytest.mark.asyncio
async def test_explicitApprovalIdResolvesOnlyItsNode(manager):
    t1 = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execA", "n1")))
    t2 = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execB", "n2")))
    assert await _waitUntil(lambda: len(manager.handlers) == 2)

    await manager.fanout("审批ID: execA 节点: n1 approve", "u1")

    r1, r2 = await asyncio.gather(t1, t2)
    assert r1["status"] == "success" and r1["output"]["approved"] is True
    assert r2["status"] == "timeout" and r2["output"]["approved"] is None


@pytest.mark.asyncio
async def test_singlePendingKeepsBareKeywordWorking(manager):
    """只有一个未决时，裸关键词仍是明确指向——不要求用户改习惯。"""
    task = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execA", "n1")))
    assert await _waitUntil(lambda: len(manager.handlers) == 1)
    await manager.fanout("同意", "u1")
    result = await task
    assert result["status"] == "success" and result["output"]["approved"] is True


@pytest.mark.asyncio
async def test_negatedApprovalIsNotReadAsApproval(manager):
    """`不同意` 含 `同意`：拒绝词必须先于批准词判定。"""
    task = asyncio.create_task(builtin.exec_approval(_cfg(), _ctx("execA", "n1")))
    assert await _waitUntil(lambda: len(manager.handlers) == 1)
    await manager.fanout("不同意，先别上线", "u1")
    result = await task
    assert result["status"] == "success"
    assert result["output"]["approved"] is False


@pytest.mark.asyncio
async def test_cancelledWaitRemovesItsHandler(manager):
    """取消等待不得留下常驻 handler（每取消一次泄漏一个）。"""
    task = asyncio.create_task(builtin.exec_approval(_cfg(timeout=0.3), _ctx("execA", "n1")))
    assert await _waitUntil(lambda: len(manager.handlers) == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.handlers == {}


@pytest.mark.asyncio
async def test_pendingRegistryIsEmptyAfterTimeout(manager):
    result = await builtin.exec_approval(_cfg(timeout=0.15), _ctx("execA", "n1"))
    assert result["status"] == "timeout"
    assert builtin._pendingApprovalCountForTests() == 0


def test_timeoutDefaultIsANamedBudget():
    """60/3600 这类等待预算必须是具名常量，便于与父墙一起核算。"""
    import inspect

    source = inspect.getsource(builtin.exec_approval)
    assert "DEFAULT_APPROVAL_TIMEOUT_SECONDS" in source
    assert isinstance(builtin.DEFAULT_APPROVAL_TIMEOUT_SECONDS, (int, float))


@pytest.mark.asyncio
async def test_approvalNotificationGoesThroughTheAttentionBudget(manager, monkeypatch):
    """审批通知是唯一的自动渠道出口：必须经出口预算，而不是 manager 直发。"""
    seen = {}

    class _Budget:
        async def deliver(self, key, text, sendFn, holdKey=None):
            from neurova.channels.attention_budget import DeliveryResult

            seen["key"] = key
            seen["holdKey"] = holdKey
            return DeliveryResult(sent=True, coalesced=False, message_id=await sendFn(text))

    monkeypatch.setattr("neurova.channels.attention_budget.getAttentionBudget", lambda: _Budget())
    result = await builtin.exec_approval(_cfg(timeout=0.1), _ctx("execA", "n1"))

    assert result["status"] == "timeout"
    assert "execA" in seen.get("key", "") and "n1" in seen.get("key", ""), (
        "审批通知没有走出口预算（key 应按 execution:node 区分）"
    )
    assert seen.get("holdKey") == "chat:feishu:u1", (
        "审批通知没带会话 holdKey——人在等的窗口里压不住它"
    )
