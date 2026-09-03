"""执行事件流 API 测试（P0-1 run/stream 分离）。

契约：
- POST /api/v1/neurflow/workflows/{id}/execute 新增 wait=false：
  立即返回 {runId, status, workflow_id, events_url}，后台执行并落库；
  默认 wait=true 行为不变（等价性）。
- GET /api/v1/neurflow/executions/{id}/events：SSE 事件流——
  回放历史帧 + 实时推送 + 终态收尾；用户隔离（跨用户 403）；未知执行 404。

测试用 httpx.ASGITransport（而非 TestClient）：请求返回后同一事件循环
继续运行后台任务——模拟真实 uvicorn 单循环语义（TestClient 每请求
即关 loop，会取消 asyncio.create_task 后台执行）。
"""

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage


def _linear_workflow(wf_id="wf_stream_test"):
    nodes = [
        WorkflowNode(id="n0", type="builtin:start", position={"x": 0, "y": 0}, config={}),
        WorkflowNode(id="n1", type="builtin:end", position={"x": 100, "y": 0}, config={}),
    ]
    edges = [WorkflowEdge(id="e0", source="n0", target="n1")]
    return WorkflowDefinition(
        id=wf_id,
        name="事件流测试流",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=[],
        tags=[],
        category="general",
        author="tester",
        created_at=0.0,
        updated_at=0.0,
        status=WorkflowStatus.PUBLISHED,
    )


class ExecutionStreamTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from neurova.api.endpoints import neurflow_api
        from neurova.collaboration.neurflow import event_recorder

        self.module = neurflow_api
        event_recorder.reset_execution_event_recorder()
        self.addCleanup(event_recorder.reset_execution_event_recorder)

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = NeurflowStorage(str(Path(self._tmp.name) / "neurflow.db"))
        # LIFO：先关连接再删目录（Windows 文件占用）
        self.addCleanup(self.storage.close)
        self.storage.save_workflow(_linear_workflow())

        self.app = FastAPI()
        self.app.include_router(neurflow_api.router, prefix="/api/v1/neurflow")
        patcher = patch.object(neurflow_api, "_get_storage", return_value=self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)

        # 每测试独立事件录制器 + 挂到全局 executor（幂等）
        from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

        self.executor = get_workflow_executor()
        event_recorder.attach_event_recorder(self.executor)
        self.recorder = event_recorder.get_execution_event_recorder()

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        self.addCleanup(self.client.aclose)

    # ── 便捷方法 ────────────────────────────────────────────────

    async def _execute(self, body):
        return await self.client.post(
            "/api/v1/neurflow/workflows/wf_stream_test/execute", json=body
        )

    async def _wait_stored(self, run_id, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            stored = self.storage.get_execution(run_id)
            if stored is not None:
                return stored
            await asyncio_sleep(0.05)
        return None

    async def _collect_stream(self, run_id, max_seconds=10.0, after=None):
        """读取 SSE 流直到终态事件，返回全部事件帧。"""
        frames = []
        deadline = time.time() + max_seconds
        params = {"after": after} if after is not None else None
        async with self.client.stream(
            "GET", f"/api/v1/neurflow/executions/{run_id}/events", params=params
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            async for line in resp.aiter_lines():
                if time.time() > deadline:
                    self.fail("SSE 流未在限时内收到终态事件")
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line[len("data:") :].strip())
                frames.append(frame)
                if frame.get("type") in ("workflow_completed", "workflow_failed"):
                    break
        return frames


async def asyncio_sleep(seconds):
    import asyncio

    await asyncio.sleep(seconds)


class TestExecuteWaitFalse(ExecutionStreamTestBase):
    async def test_returns_immediately_with_events_url(self):
        resp = await self._execute({"inputs": {"q": 1}, "wait": False})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body.get("runId"))
        self.assertIn("events_url", body)
        self.assertIn(body["runId"], body["events_url"])
        self.assertIn(body.get("status"), ("running", "pending"))

    async def test_background_execution_persists_result(self):
        resp = await self._execute({"inputs": {"q": 1}, "wait": False})
        run_id = resp.json()["runId"]

        stored = await self._wait_stored(run_id)
        self.assertIsNotNone(stored, "后台执行未在 10s 内落库")
        self.assertEqual(stored.status.value, "completed")

    async def test_wait_true_backward_compatible(self):
        resp = await self._execute({"inputs": {"q": 1}})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("instance", body)
        # 同步路径返回终态实例
        self.assertIn(body["instance"]["status"], ("completed", "failed"))
        # 且已落库
        self.assertIsNotNone(self.storage.get_execution(body["instance"]["id"]))

    async def test_unknown_workflow_404(self):
        resp = await self.client.post(
            "/api/v1/neurflow/workflows/wf_ghost/execute", json={"wait": False}
        )
        self.assertEqual(resp.status_code, 404)


class TestExecutionEventsStream(ExecutionStreamTestBase):
    async def _run_to_completion(self):
        resp = await self._execute({"inputs": {"q": 1}, "wait": False})
        self.assertEqual(resp.status_code, 200, resp.text)
        run_id = resp.json()["runId"]
        stored = await self._wait_stored(run_id)
        self.assertIsNotNone(stored, "执行未在 10s 内落库")
        return run_id

    async def test_stream_replays_full_lifecycle(self):
        run_id = await self._run_to_completion()

        frames = await self._collect_stream(run_id)
        types = [f["type"] for f in frames]
        self.assertEqual(types[0], "workflow_started")
        self.assertEqual(types[-1], "workflow_completed")
        self.assertIn("node_started", types)
        # seq 单调递增
        seqs = [f["seq"] for f in frames]
        self.assertEqual(seqs, sorted(seqs))

    async def test_stream_after_cursor_continues(self):
        run_id = await self._run_to_completion()

        all_frames = await self._collect_stream(run_id)
        # after=1 续传：首帧 seq 应为 2
        resumed = await self._collect_stream(run_id, after=1)
        self.assertEqual(resumed[0]["seq"], all_frames[1]["seq"])

    async def test_stream_unknown_execution_404(self):
        resp = await self.client.get("/api/v1/neurflow/executions/exec_ghost/events")
        self.assertEqual(resp.status_code, 404)

    async def test_stream_user_isolation(self):
        # 以 user_a 身份发起执行
        self.app.dependency_overrides[
            self.module.get_current_user_or_default
        ] = lambda: {"user_id": "user_a"}
        try:
            resp = await self._execute({"inputs": {}, "wait": False})
            self.assertEqual(resp.status_code, 200, resp.text)
            run_id = resp.json()["runId"]
            stored = await self._wait_stored(run_id)
            self.assertIsNotNone(stored)

            # user_b 订阅 → 403
            self.app.dependency_overrides[
                self.module.get_current_user_or_default
            ] = lambda: {"user_id": "user_b"}
            blocked = await self.client.get(
                f"/api/v1/neurflow/executions/{run_id}/events"
            )
            self.assertEqual(blocked.status_code, 403)

            # 属主本人可订阅
            self.app.dependency_overrides[
                self.module.get_current_user_or_default
            ] = lambda: {"user_id": "user_a"}
            ok = await self.client.get(f"/api/v1/neurflow/executions/{run_id}/events")
            self.assertEqual(ok.status_code, 200)
        finally:
            self.app.dependency_overrides.clear()

    async def test_stream_falls_back_to_storage_after_restart(self):
        """进程重启（recorder 无缓冲）但执行已落库：合成终态帧收尾。"""
        run_id = await self._run_to_completion()

        # 模拟重启：清空 recorder
        from neurova.collaboration.neurflow import event_recorder

        event_recorder.reset_execution_event_recorder()
        fresh_recorder = event_recorder.get_execution_event_recorder()

        frames = await self._collect_stream(run_id)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["type"], "workflow_completed")
        # 合成帧不进新 recorder（避免污染后续订阅回放语义）
        self.assertEqual(fresh_recorder.snapshot(run_id), [])


if __name__ == "__main__":
    unittest.main()
