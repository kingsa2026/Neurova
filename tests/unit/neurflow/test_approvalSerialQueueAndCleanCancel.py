# -*- coding: utf-8 -*-
"""批 B1：同会话审批串行排队（T2 已裁）＋ 取消不泄漏线程。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 B1）：
`_PENDING_APPROVALS` 支持同会话多未决——两个节点同时把问题抛给同一个人，
违反"一次一问"；等待实现把 `threading.Event.wait` 整体丢进默认线程池
（run_in_executor），任务取消时那颗线程卡在 wait 里最长泄漏 timeout 秒
（`:2384 except Exception` 不接 CancelledError，线程成为唯一残留）。

本批裁定与语义（随格落死）：
- 同一 `chat:{channel}:{chat_id}` 至多一个未决在"问"：锁从发通知持到等待
  终结，第二单在前一单终结后自动继续，**排队时间不计入本单超时**；
- 广播（无 channel）没有会话可排，维持原行为（边界随格钉住）；
- 等待改轮询（具名间隔常量）：取消即时生效、线程零占用。
"""
from __future__ import annotations

import asyncio
import threading
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


def _cfg(approver="u1", timeout=5.0, chat_id=None, channel="feishu"):
    cfg = {"approver": approver, "message": "请审批", "timeout": timeout}
    if channel is not None:
        cfg["channel"] = channel
    if chat_id is not None:
        cfg["chat_id"] = chat_id
    return cfg


def _ctx(execution_id, node_id):
    return {"execution_id": execution_id, "node_id": node_id}


async def _waitUntil(predicate, timeout=2.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def env(monkeypatch):
    mgr = FakeChannelManager()
    monkeypatch.setattr(builtin, "_get_channel_manager", lambda: mgr)
    builtin._resetPendingApprovalsForTests()
    resetQueues = getattr(builtin, "_resetChatApprovalQueuesForTests", None)
    assert resetQueues is not None, (
        "builtin 没有会话队列登记表的测试重置口——批 B1 未实现"
    )
    resetQueues()
    yield mgr
    builtin._resetPendingApprovalsForTests()
    resetQueues()


class TestSameChatSerialQueue:
    @pytest.mark.asyncio
    async def test_sameChatSecondApprovalWaitsForItsTurn(self, env):
        """同会话两单：第二单的通知与等待都必须等第一单终结（一次一问）。"""
        mgr = env
        taskA = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_1"), _ctx("exec-a", "n1")))
        await _waitUntil(lambda: len(mgr.sent) >= 1)
        taskB = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_1"), _ctx("exec-b", "n2")))
        await asyncio.sleep(0.35)

        assert len(mgr.sent) == 1, (
            f"第二单没排队：同会话已抛出 {len(mgr.sent)} 个问题（一次一问被破坏）"
        )

        await mgr.fanout("同意", "u1")           # 此时唯一未决是 A
        resultA = await asyncio.wait_for(taskA, timeout=2.0)
        assert resultA["status"] == "success" and resultA["output"]["approved"] is True

        assert await _waitUntil(lambda: len(mgr.sent) >= 2), (
            "第一单终结后第二单没有自动继续（排队成了永久等待）"
        )
        await mgr.fanout("同意", "u1")           # 此时唯一未决是 B
        resultB = await asyncio.wait_for(taskB, timeout=2.0)
        assert resultB["status"] == "success", f"排队的第二单没有拿到自己的裁决：{resultB}"

    @pytest.mark.asyncio
    async def test_queuedNodeTimeoutStartsAfterItsTurn(self, env):
        """超时归属（随格落死）：排队时间不计入本单预算——B 的 0.5s 从轮到它
        才起算，A 占用会话的 0.3s 不吃掉 B 的等待。"""
        mgr = env
        taskA = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_2", timeout=30), _ctx("exec-a", "n1")))
        await _waitUntil(lambda: len(mgr.sent) >= 1)
        taskB = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_2", timeout=0.5), _ctx("exec-b", "n2")))
        await asyncio.sleep(0.3)
        assert len(mgr.sent) == 1, "B 没排队（前置失效）"

        await mgr.fanout("同意", "u1")           # A 过，B 轮到
        await asyncio.wait_for(taskA, timeout=2.0)
        turnAt = asyncio.get_event_loop().time()

        resultB = await asyncio.wait_for(taskB, timeout=5.0)
        waited = asyncio.get_event_loop().time() - turnAt
        assert resultB["status"] == "timeout", f"B 应以自己的预算超时：{resultB}"
        assert waited >= 0.45, (
            f"B 的超时预算被排队时间吃掉了（轮到后只等了 {waited:.2f}s）"
        )

    @pytest.mark.asyncio
    async def test_differentChatsRunConcurrently(self, env):
        """对照（不许顺手改坏）：不同会话不互相排队。"""
        mgr = env
        taskA = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_a"), _ctx("exec-a", "n1")))
        taskB = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_b"), _ctx("exec-b", "n2")))
        assert await _waitUntil(lambda: len(mgr.sent) >= 2), (
            "不同会话的两个审批被串行化了（过严）"
        )
        await mgr.fanout("同意 exec-a", "u1")
        await mgr.fanout("同意 exec-b", "u1")
        resultA = await asyncio.wait_for(taskA, timeout=2.0)
        resultB = await asyncio.wait_for(taskB, timeout=2.0)
        assert resultA["status"] == "success" and resultB["status"] == "success"

    @pytest.mark.asyncio
    async def test_broadcastHasNoChatQueue(self, env):
        """边界（随格钉住）：广播没有会话可排，维持原并发行为。"""
        mgr = env
        taskA = asyncio.create_task(builtin.exec_approval(
            _cfg(channel=None), _ctx("exec-a", "n1")))
        taskB = asyncio.create_task(builtin.exec_approval(
            _cfg(channel=None), _ctx("exec-b", "n2")))
        assert await _waitUntil(lambda: len(mgr.sent) >= 2), (
            "广播审批被误加了会话队列（边界被改宽）"
        )
        await mgr.fanout("同意 exec-a", "u1")
        await mgr.fanout("同意 exec-b", "u1")
        await asyncio.wait_for(asyncio.gather(taskA, taskB), timeout=2.0)


class TestCleanCancel:
    @pytest.mark.asyncio
    async def test_cancelMidWaitLeavesNoResidue(self, env):
        """取消等待：CancelledError 照常上抛、登记与处理器清干净、线程零增长。"""
        mgr = env
        threads_before = threading.active_count()
        task = asyncio.create_task(builtin.exec_approval(
            _cfg(chat_id="oc_c", timeout=30), _ctx("exec-c", "n1")))
        assert await _waitUntil(lambda: builtin._pendingApprovalCountForTests() == 1), (
            "前置未生效：审批没有进入未决登记"
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert builtin._pendingApprovalCountForTests() == 0, (
            "取消后未决登记没清——下一个回复会命中的是幽灵审批"
        )
        assert mgr.handlers == {}, "取消后消息处理器没摘——常驻 handler 吞后续回复"
        assert threading.active_count() <= threads_before, (
            "取消后线程数回落不了——等待还在往默认线程池里塞卡住的线程"
        )

    def test_waitSectionMustNotUseRunInExecutor(self):
        """结构钉：等待段不许再走 run_in_executor（线程泄漏的根）——回归即红。"""
        import ast
        import pathlib

        src = pathlib.Path(builtin.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                    and node.name in ("exec_approval", "_execApprovalCore"):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        name = getattr(inner.func, "attr", None) or getattr(inner.func, "id", None)
                        assert name != "run_in_executor", (
                            f"{node.name} 里又把等待丢进线程池了（线程泄漏根因回归）"
                        )
