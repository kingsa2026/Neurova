"""
P0-7 工作流子系统安全快修红测（对比 v2 §3 N1-N5 + N6 调试接线）

- N1: 触发器 CRUD/fire 零鉴权 → 全部挂 get_current_user（严格）
- N2: cron _scheduled_fire 断链 → configure_runtime(trigger_loader/dispatch)
      + bind_loop + run_coroutine_threadsafe（APScheduler 线程池线程安全派发）
- N3: webhook 重放防护 → verify_request（签名覆盖 "timestamp." 前缀 + 时效校验）
- N4: receive 端点 body 1MB 上限 → 413
- N5: 限流器清理分支不可达 → 桶满时可达并清理空闲桶
- N6: 调试引擎消费节点级 mock_output/_NODE_MOCKS；step_mode 每节点后暂停
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.core.trigger_rate_limiter import TriggerRateLimiter
from neurova.core.webhook_security import (
    compute_signature,
    compute_signed_payload_signature,
    verify_request,
)

RECEIVE = "/triggers/webhook/t1/receive"


# ── N5：限流器清理可达 ───────────────────────────────────────────


class TestRateLimiterCleanup:
    def test_cleanup_reachable_when_buckets_full(self):
        clock = {"t": 0.0}
        limiter = TriggerRateLimiter(60, clock=lambda: clock["t"])
        # 填满桶（第 4096 个新建时触发一次清理，此时无 stale）
        for i in range(4096):
            assert limiter.acquire(f"k{i}") is True
        # 时间前进，全部桶变 stale；新 key 再建桶应触发清理
        clock["t"] = 7200.0
        assert limiter.acquire("fresh") is True
        assert len(limiter._buckets) < 4096  # stale 桶已被清走

    def test_no_cleanup_when_under_threshold(self):
        limiter = TriggerRateLimiter(60)
        for i in range(10):
            limiter.acquire(f"k{i}")
        assert len(limiter._buckets) == 10


# ── N3：verify_request 重放防护 ──────────────────────────────────


class TestVerifyRequest:
    BODY = b'{"payload": "hello"}'
    SECRET = "s3cret"

    def test_fresh_timestamp_valid_signature_ok(self):
        ts = str(int(time.time()))
        sig = compute_signed_payload_signature(ts, self.BODY, self.SECRET)
        ok, reason = verify_request(
            self.BODY, self.SECRET, sig, ts, now_s=time.time()
        )
        assert ok is True and reason == "OK"

    def test_missing_timestamp_rejected(self):
        sig = compute_signed_payload_signature("123", self.BODY, self.SECRET)
        ok, reason = verify_request(
            self.BODY, self.SECRET, sig, None, now_s=time.time()
        )
        assert ok is False and reason == "MISSING_TIMESTAMP"

    def test_stale_timestamp_rejected(self):
        old_ts = str(int(time.time()) - 3600)
        sig = compute_signed_payload_signature(old_ts, self.BODY, self.SECRET)
        ok, reason = verify_request(
            self.BODY, self.SECRET, sig, old_ts, now_s=time.time()
        )
        assert ok is False and reason == "SIGNATURE_STALE"

    def test_bad_timestamp_rejected(self):
        ok, reason = verify_request(
            self.BODY, self.SECRET, "sha256=ab", "not-a-number", now_s=time.time()
        )
        assert ok is False and reason == "BAD_TIMESTAMP"

    def test_body_tamper_rejected(self):
        ts = str(int(time.time()))
        sig = compute_signed_payload_signature(ts, self.BODY, self.SECRET)
        ok, _ = verify_request(
            self.BODY + b"x", self.SECRET, sig, ts, now_s=time.time()
        )
        assert ok is False

    def test_replay_of_old_but_valid_signature_rejected(self):
        """重放核心场景：签名本身有效但时间戳过期 → 拒绝"""
        old_ts = str(int(time.time()) - 600)  # 超过默认 300s 容忍
        sig = compute_signed_payload_signature(old_ts, self.BODY, self.SECRET)
        ok, reason = verify_request(
            self.BODY, self.SECRET, sig, old_ts, now_s=time.time()
        )
        assert ok is False and reason == "SIGNATURE_STALE"


# ── N2：cron 派发断链修复 ────────────────────────────────────────


def _make_trigger(enabled=True):
    return SimpleNamespace(
        id="t1", workflow_id="wf1", type="cron", enabled=enabled, config={"cron": "* * * * *"}
    )


class TestCronScheduledFire:
    @pytest.mark.asyncio
    async def test_configure_runtime_and_scheduled_fire_dispatches(self):
        from neurova.collaboration.neurflow.triggers import TriggerManager

        manager = TriggerManager()
        dispatch = AsyncMock(return_value={"success": True})
        manager.configure_runtime(
            dispatch=dispatch, trigger_loader=lambda tid: _make_trigger()
        )
        manager.bind_loop()

        manager._scheduled_fire("t1")  # APScheduler 线程池线程语境
        # run_coroutine_threadsafe 经 call_soon_threadsafe 投递，轮询等它执行
        for _ in range(50):
            if dispatch.await_count:
                break
            await asyncio.sleep(0.01)
        dispatch.assert_awaited_once()
        assert dispatch.await_args.args[0] == "wf1"

    @pytest.mark.asyncio
    async def test_disabled_trigger_not_dispatched(self):
        from neurova.collaboration.neurflow.triggers import TriggerManager

        manager = TriggerManager()
        dispatch = AsyncMock()
        manager.configure_runtime(
            dispatch=dispatch, trigger_loader=lambda tid: _make_trigger(enabled=False)
        )
        manager.bind_loop()

        manager._scheduled_fire("t1")
        await asyncio.sleep(0)
        dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unconfigured_runtime_no_crash(self):
        from neurova.collaboration.neurflow.triggers import TriggerManager

        manager = TriggerManager()
        manager._scheduled_fire("t1")  # 无 loader/dispatch：警告但不抛
        manager.bind_loop()

    @pytest.mark.asyncio
    async def test_setup_workflow_triggers_threads_runtime(self, monkeypatch):
        """启动装配把 dispatch/trigger_loader 传入 manager 并绑定 loop"""
        import neurova.collaboration.neurflow.triggers as trg

        monkeypatch.setattr(trg, "_bootstrapped", False)
        captured = {}

        class FakeManager:
            def configure_runtime(self, dispatch=None, trigger_loader=None):
                captured["dispatch"] = dispatch
                captured["trigger_loader"] = trigger_loader

            def bind_loop(self):
                captured["loop_bound"] = True

            async def restore_enabled(self, loader):
                return 0

        monkeypatch.setattr(trg, "get_trigger_manager", lambda: FakeManager())
        loader = lambda: []
        dispatch = lambda wf_id, inputs: None
        restored = await trg.setup_workflow_triggers(
            loader=loader, scheduler=object(), dispatch=dispatch, trigger_loader=loader
        )
        assert restored == 0
        assert captured["dispatch"] is dispatch
        assert captured["trigger_loader"] is loader
        assert captured["loop_bound"] is True


# ── N1：触发器端点鉴权 ───────────────────────────────────────────


class TestTriggerAuth:
    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)  # 真实 get_current_user，无 token → 401

    def test_list_triggers_requires_auth(self, client):
        assert client.get("/workflows/wf1/triggers").status_code == 401

    def test_create_trigger_requires_auth(self, client):
        resp = client.post(
            "/workflows/wf1/triggers",
            json={"type": "webhook", "config": {}},
        )
        assert resp.status_code == 401

    def test_delete_trigger_requires_auth(self, client):
        assert client.delete("/triggers/t1").status_code == 401

    def test_fire_trigger_requires_auth(self, client):
        resp = client.post("/triggers/t1/fire", json={})
        assert resp.status_code == 401


# ── N4：webhook body 上限 ────────────────────────────────────────


class TestWebhookBodyLimit:
    def test_oversized_body_413(self):
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        big = b"x" * (1024 * 1024 + 1)
        resp = client.post(
            RECEIVE, content=big, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 413

    def test_normal_body_not_413(self):
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        resp = client.post(RECEIVE, content=b"{}")
        assert resp.status_code != 413


# ── N6：调试引擎消费 mock 与 step_mode ───────────────────────────


def _mini_workflow():
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
        WorkflowVariable,
    )

    return WorkflowDefinition(
        id="wf",
        name="wf",
        description="",
        version="1",
        nodes=[
            WorkflowNode(id="n1", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="n2", type="builtin:noop", position={"x": 1, "y": 0}, config={}),
            WorkflowNode(id="n3", type="builtin:end", position={"x": 2, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="n1", target="n2"),
            WorkflowEdge(id="e2", source="n2", target="n3"),
        ],
        variables=[WorkflowVariable(name="v", type="string")],
        tags=[],
        category="",
        author="",
        status=WorkflowStatus.DRAFT,
        created_at="2026-08-31T00:00:00",
        updated_at="2026-08-31T00:00:00",
    )


def _collect_events(events):
    return [(e.type.value, getattr(e, "node_id", None), e.data) for e in events]


class TestDebugMockAndStep:
    @pytest.mark.asyncio
    async def test_node_mock_output_consumed(self):
        from neurova.collaboration.neurflow.execution_engine import (
            WorkflowExecutor,
            DebugSession,
        )
        import neurova.collaboration.neurflow.execution_engine as ee

        wf = _mini_workflow()
        wf.nodes[1].mock_output = {"answer": 42}
        events = [
            e
            async for e in WorkflowExecutor().execute_debug(
                wf, {}, DebugSession(breakpoints=set())
            )
        ]
        completed = [
            (nid, d) for t, nid, d in _collect_events(events) if t == "node_completed"
        ]
        n2 = dict(completed).get("n2") or {}
        assert n2.get("output") == {"answer": 42}

    @pytest.mark.asyncio
    async def test_node_global_mocks_consumed(self):
        from neurova.collaboration.neurflow.execution_engine import (
            WorkflowExecutor,
            DebugSession,
        )
        import neurova.collaboration.neurflow.execution_engine as ee

        wf = _mini_workflow()
        old = dict(ee._NODE_MOCKS)
        ee._NODE_MOCKS["n2"] = "mocked-out"
        try:
            events = [
                e
                async for e in WorkflowExecutor().execute_debug(
                    wf, {}, DebugSession(breakpoints=set())
                )
            ]
        finally:
            ee._NODE_MOCKS.clear()
            ee._NODE_MOCKS.update(old)
        completed = [d for t, nid, d in _collect_events(events) if t == "node_completed" and nid == "n2"]
        assert completed and completed[0].get("output") == "mocked-out"

    @pytest.mark.asyncio
    async def test_step_mode_pauses_after_each_node(self):
        from neurova.collaboration.neurflow.execution_engine import (
            WorkflowExecutor,
            DebugSession,
        )

        wf = _mini_workflow()
        session = DebugSession(breakpoints=set(), step_mode="over")
        types = []
        # 测试扮演调试器驱动方（等价 API resume 端点）：
        # step 暂停（breakpoint_hit）到来时驱动 resume
        async for e in WorkflowExecutor().execute_debug(wf, {}, session):
            types.append(e.type.value)
            if e.type.value == "breakpoint_hit":
                session.resume()
        # 三节点：每节点完成后各一次 step 暂停
        assert types.count("breakpoint_hit") == 3
        assert types.count("node_completed") == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
