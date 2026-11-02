# -*- coding: utf-8 -*-
"""批 B2：审批等待语义三件套（剩余两格）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 B2）：
① 通知被"人在等"窗口压住（held）时，`msg_id` 为空且 `coalesced` 为假——现判据
把这种在途态当成"发送失败"提前返回 pending，**审批人稍后收到补发通知、回复
却没有任何处理器在听**（死审批）。held 必须继续走注册与等待；送达延迟是
窗口收尾（同回合 finally），相对超时预算可忽略——"未送达不计时"以本形落死。
② 引擎把节点内层 status（pending/timeout）一律写成外层 success——面板/快照
把没批下来的节点画成"成功"。修正：这两类外显；resume 恢复集同步扩（有终态
输出、重跑会二次打扰审批人，照 success 恢复，行为不变）。
"""
from __future__ import annotations

import asyncio
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
        message = SimpleNamespace(content=content, sender_id=sender_id)
        for handler in list(self.handlers.values()):
            await handler(message)


class _HeldBudget:
    """deliver 恒返回 held：通知压在「人在等」窗口里，关窗才补发。"""

    async def deliver(self, key, text, sendFn, holdKey=None):
        from neurova.channels.attention_budget import DeliveryResult

        return DeliveryResult(sent=False, coalesced=False, message_id=None, held=True)


@pytest.fixture
def env(monkeypatch):
    mgr = FakeChannelManager()
    monkeypatch.setattr(builtin, "_get_channel_manager", lambda: mgr)
    builtin._resetPendingApprovalsForTests()
    builtin._resetChatApprovalQueuesForTests()
    yield mgr
    builtin._resetPendingApprovalsForTests()
    builtin._resetChatApprovalQueuesForTests()


class TestHeldNotificationKeepsWaiting:
    @pytest.mark.asyncio
    async def test_heldApprovalIsNotADeadApproval(self, env, monkeypatch):
        """通知被压住（held）≠ 发送失败：必须继续注册处理器等待回复——
        修前提前返回 pending，审批人之后回复落空（死审批）。"""
        import neurova.channels.attention_budget as budgetModule

        monkeypatch.setattr(budgetModule, "getAttentionBudget", lambda: _HeldBudget())
        mgr = env
        task = asyncio.create_task(builtin.exec_approval(
            {"approver": "u1", "channel": "feishu", "message": "请审批", "timeout": 5},
            {"execution_id": "exec-h", "node_id": "n1"}))

        for _ in range(200):
            if builtin._pendingApprovalCountForTests() == 1:
                break
            await asyncio.sleep(0.01)
        assert builtin._pendingApprovalCountForTests() == 1, (
            "held 通知被当成发送失败提前返回 pending——审批人补发通知后的回复没人听"
        )

        await mgr.fanout("同意", "u1")
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result["status"] == "success" and result["output"]["approved"] is True


class TestEngineSurfacesInnerStatus:
    @pytest.fixture
    def approvalWorkflow(self):
        import time

        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowEdge, WorkflowNode,
        )

        return WorkflowDefinition(
            id="wf_appr", name="审批工作流", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="start", type="builtin:start", label="开始",
                             position={"x": 0, "y": 0}, config={}),
                WorkflowNode(id="appr", type="builtin:approval", label="审批",
                             position={"x": 100, "y": 0},
                             config={"approver": "u1", "channel": "feishu",
                                     "message": "请审批", "timeout": 0.4}),
                WorkflowNode(id="end", type="builtin:end", label="结束",
                             position={"x": 200, "y": 0}, config={}),
            ],
            edges=[
                WorkflowEdge(id="e1", source="start", target="appr"),
                WorkflowEdge(id="e2", source="appr", target="end"),
            ],
            variables=[], tags=[], category="test", author="test",
            created_at=time.time(), updated_at=time.time(),
            status=__import__("neurova.collaboration.neurflow.models", fromlist=["WorkflowStatus"]).WorkflowStatus.PUBLISHED,
        )

    @pytest.mark.asyncio
    async def test_engineSurfacesApprovalTimeout(self, env, approvalWorkflow, monkeypatch):
        """审批超时：节点读面必须外显 timeout——修前一律画成 success。"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor

        executor = WorkflowExecutor()
        instance = await executor.execute(workflow=approvalWorkflow, inputs={})
        node_result = instance.node_results.get("appr")
        assert node_result is not None, "审批节点没有结果"
        assert node_result.status == "timeout", (
            f"内层 timeout 被引擎画成 {node_result.status}——没批下来却显示成功"
        )

    def test_resumeRestoreSetCoversTimeoutAndPending(self):
        """resume 恢复集同步扩：timeout/pending 的节点照 success 恢复（有终态
        输出，重跑会二次打扰审批人）——结构钉，防有人只改外显忘了恢复集。"""
        import pathlib

        import neurova.collaboration.neurflow.execution_engine as engineModule

        src = pathlib.Path(engineModule.__file__).read_text(encoding="utf-8")
        start = src.index("Resume（Checkpoint 续跑）")
        seg = src[start:src.index("for layer in layers", start)]
        assert '"timeout"' in seg and '"pending"' in seg, (
            "resume 恢复集没有覆盖 timeout/pending——这两类节点会在续跑时被重跑，"
            "审批人被二次打扰"
        )
