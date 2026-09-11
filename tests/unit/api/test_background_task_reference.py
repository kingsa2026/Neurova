# -*- coding: utf-8 -*-
"""P2-6 防回归：fire-and-forget 后台任务必须持强引用并回收。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md P2 第6条）：
``neurflow_api.py`` execute(wait=false) 与 ``collaboration_api.py``
canvas run 的 ``asyncio.create_task(...)`` 返回值被丢弃——任务可能被
GC 中途回收，异常成为 unretrieved-exception。

修复：模块级 ``_background_tasks: set`` 持引用 +
``add_done_callback(set.discard)``（对照 multi_model_client._pending_tasks）。

本测试锁定：端点返回后任务在集合中（强引用存活）；任务完成后集合排空
（done_callback 生效，集合本身不泄漏）。全部依赖以 fake 注入，无真实执行。
"""

import asyncio
from types import SimpleNamespace

from fastapi import Request

from neurova.api.endpoints import collaboration_api as ca
from neurova.api.endpoints import neurflow_api as nf


# --------------------------------------------------------------------------- #
# neurflow_api.execute_workflow(wait=False)
# --------------------------------------------------------------------------- #


def test_neurflow_background_execution_holds_task_reference(monkeypatch):
    finished = []

    class _FakeWorkflow:
        id = "wf-1"

    class _FakeExecutor:
        def create_instance(self, workflow, inputs=None, user_id=None, agent_id=None):
            return SimpleNamespace(id="inst-1")

        async def execute(self, **kwargs):
            await asyncio.sleep(0.01)
            finished.append(kwargs["instance"].id)
            return kwargs["instance"]

    class _FakeStorage:
        def save_execution(self, result):
            pass

    class _FakeMemory:
        _emotion_module = object()

    class _FakeAgent:
        memory_manager = _FakeMemory()
        context_pool = object()
        crystallizer = object()

    monkeypatch.setattr(nf, "_get_storage", lambda: _FakeStorage())
    monkeypatch.setattr(
        nf, "_owned_workflow_or_404", lambda storage, wf_id, user, writable=False: _FakeWorkflow()
    )
    monkeypatch.setattr(nf, "get_agent_instance", lambda agent_id: _FakeAgent())
    monkeypatch.setattr(nf, "get_workflow_executor", lambda: _FakeExecutor())

    async def main():
        resp = await nf.execute_workflow(
            workflow_id="wf-1",
            inputs={},
            user_id=None,
            agent_id=None,
            wait=False,
            current_user={"user_id": "u1"},
        )
        assert resp["status"] == "pending", "wait=false 契约改变"
        held = list(nf._background_tasks)
        assert len(held) == 1, (
            "create_task 返回值被丢弃：后台任务无强引用，可被 GC 中途回收（P2-6）"
        )
        await held[0]
        await asyncio.sleep(0)  # 让 done_callback 排空集合

    asyncio.run(main())

    assert finished == ["inst-1"], "后台执行未真正跑完"
    assert not nf._background_tasks, "done_callback 未回收任务引用，集合本身泄漏"


# --------------------------------------------------------------------------- #
# collaboration_api.run_canvas_workflow
# --------------------------------------------------------------------------- #


def test_collaboration_canvas_run_holds_task_reference(monkeypatch):
    finished = []

    class _FakeExecutor:
        def create_instance(self, workflow, inputs=None, user_id=None):
            return SimpleNamespace(id="exec-1")

        async def execute(self, *args, **kwargs):
            await asyncio.sleep(0.01)
            finished.append(kwargs["instance"].id)
            return kwargs["instance"]

    class _FakeStore:
        def get(self, canvas_id):
            return {"id": canvas_id, "name": "c1"}

    fake_workflow = SimpleNamespace(id="wf-1", status=None)

    monkeypatch.setattr(ca, "_get_canvas_store", lambda: _FakeStore())
    monkeypatch.setattr(
        "neurova.collaboration.canvas_bridge.canvas_to_workflow",
        lambda record, name=None: fake_workflow,
    )
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.validation.validate_node_configs", lambda wf: []
    )
    monkeypatch.setattr(
        "neurova.collaboration.neurflow.execution_engine.get_workflow_executor",
        lambda: _FakeExecutor(),
    )

    async def main():
        resp = await ca.run_canvas_workflow(
            request=Request(scope={"type": "http"}),
            canvas_id="c1",
            body={},
            current_user={"user_id": "u1"},
        )
        assert resp["data"]["status"] == "running", "run 契约改变"
        held = list(ca._background_tasks)
        assert len(held) == 1, (
            "create_task 返回值被丢弃：后台任务无强引用，可被 GC 中途回收（P2-6）"
        )
        await held[0]
        await asyncio.sleep(0)  # 让 done_callback 排空集合

    asyncio.run(main())

    assert finished == ["exec-1"], "后台执行未真正跑完"
    assert not ca._background_tasks, "done_callback 未回收任务引用，集合本身泄漏"
