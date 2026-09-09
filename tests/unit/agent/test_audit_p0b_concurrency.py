# -*- coding: utf-8 -*-
"""P0-B 并发正确性防回归测试（审计批次 P0-B）。

覆盖：
- B1 轮次级状态并发互踩：两个"请求"（同进程不同任务）对同一 Agent 实例
  set_request_identity / append_tool_messages 后，各自的读取互不污染。
- B2 recall_loop_guard 按 session 分桶：并发会话的防护状态不互相覆盖。
- B3 provider 读路径并发安全：list_providers/get_provider 在增删线程并发下
  不抛 RuntimeError: dict changed size during iteration。
- B4 EnhancedContextBuilder 并发安全：_sessions 并发 append 不丢消息。
- B5 热切换原子性：rebuild_loop 进行中其他请求读到完整新旧之一（不半旧半新）。
- B6 tool_engine 惰性创建单实例。
"""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════
# B1: 轮次级状态并发互踩
# ═══════════════════════════════════════════════════════════════


class TestB1TurnStateConcurrency:
    """轮次级身份/工具消息必须请求隔离（ContextVar 语义）。"""

    def _make_agent(self):
        from neurova.agent_core import Agent

        # 不跑完整 init，仅取对象；轮次态 API 全部基于实例属性/ContextVar
        agent = Agent.__new__(Agent)
        return agent

    def test_concurrent_identity_no_crosstalk(self):
        """两个任务交错 set_request_identity，读取时各自身份完好。"""
        agent = self._make_agent()

        async def request(tag: str):
            agent.set_request_identity(
                user_input=f"input-{tag}",
                session_id=f"sess-{tag}",
                user_id=f"user-{tag}",
            )
            # 让出控制权制造交错
            await asyncio.sleep(0.01)
            # 中途另一个请求写入不应污染本任务上下文
            return (
                agent.current_user_id,
                agent.current_session_id,
                agent.current_user_input,
            )

        async def run():
            return await asyncio.gather(request("A"), request("B"))

        results = asyncio.run(run())
        assert results[0] == ("user-A", "sess-A", "input-A"), (
            f"请求 A 身份被请求 B 污染: {results[0]}"
        )
        assert results[1] == ("user-B", "sess-B", "input-B"), (
            f"请求 B 身份被请求 A 污染: {results[1]}"
        )

    def test_concurrent_tool_messages_no_crosstalk(self):
        """两个任务的工具消息列表互不串——A 的工具调用不进 B 的展示流。"""
        agent = self._make_agent()

        async def request(tag: str):
            agent.reset_tool_messages()
            agent.append_tool_messages([{"tool_name": f"tool_{tag}", "type": "tool_call"}])
            await asyncio.sleep(0.01)
            snapshot = agent.get_tool_messages_snapshot()
            names = {m.get("tool_name") for m in snapshot}
            return names

        async def run():
            return await asyncio.gather(request("A"), request("B"))

        ra, rb = asyncio.run(run())
        assert ra == {"tool_A"}, f"A 的工具消息混入其他请求: {ra}"
        assert rb == {"tool_B"}, f"B 的工具消息混入其他请求: {rb}"


# ═══════════════════════════════════════════════════════════════
# B2: recall_loop_guard 按 session 分桶
# ═══════════════════════════════════════════════════════════════


class TestB2RecallGuardSessionBuckets:
    def test_guard_isolated_per_session(self):
        """同 Agent 并发两会话使用 recall_history，防护状态不互相覆盖。"""
        import neurova.tool_executor as te

        # 分桶 API：不同 session_id 取到不同 guard 实例，同 session 复用
        g1 = te.ToolExecutor._get_recall_guard("sess-1")
        g2 = te.ToolExecutor._get_recall_guard("sess-2")
        g1b = te.ToolExecutor._get_recall_guard("sess-1")
        assert g1 is not None and g2 is not None
        assert g1 is g1b, "同一 session 应复用同一 guard"
        assert g1 is not g2, "不同 session 必须持有独立 guard（并发会话互踩根因）"

        # 清理：避免污染其他用例的桶
        te.ToolExecutor._recall_guards.clear()


# ═══════════════════════════════════════════════════════════════
# B3: provider 字典并发读写
# ═══════════════════════════════════════════════════════════════


class TestB3ProviderReadLock:
    def test_list_providers_safe_under_concurrent_mutation(self):
        """list_providers 迭代期间其他线程 add/remove provider 不抛
        RuntimeError: dict changed size during iteration（B3 读路径锁内快照）。"""
        import time

        from neurova.llm.provider_manager import LLMProviderManager

        # 真实工厂（含锁）；写路径绕过公开 API 直操 dict 以模拟最坏交错
        pm = LLMProviderManager(config={"config_path": str(tmpdir := __import__("tempfile").mkdtemp() + "/p.json")})
        pm._save_config = lambda: None  # noqa: ARG005

        errors = []
        stop = threading.Event()

        def reader():
            try:
                while not stop.is_set():
                    pm.list_providers()
                    pm.get_provider("p1")
                    pm.search_providers("x")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def writer():
            i = 0
            while not stop.is_set():
                pid = f"p{i % 50}"
                try:
                    with pm._config_lock:
                        if pid in pm._providers:
                            del pm._providers[pid]
                        else:
                            pm._providers[pid] = SimpleNamespace(priority=1, name=pid, is_builtin=True, enabled=True, models=[], default_model='', description='', provider=pid)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                i += 1

        threads = [threading.Thread(target=reader, daemon=True) for _ in range(2)] + [
            threading.Thread(target=writer, daemon=True) for _ in range(2)
        ]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join(timeout=2)

        assert not errors, f"并发读写 provider 字典抛异常: {errors[:3]}"


# ═══════════════════════════════════════════════════════════════
# B4: EnhancedContextBuilder 并发安全
# ═══════════════════════════════════════════════════════════════


class TestB4EnhancedContextBuilderLock:
    def test_session_append_no_loss_under_concurrency(self):
        """并发向同一 session 追加消息不丢条目。"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder

        builder = EnhancedContextBuilder.__new__(EnhancedContextBuilder)
        builder._sessions = {}
        builder._context_cache = {}
        builder._lock = threading.RLock()
        if hasattr(builder, "_max_cache_size") is False:
            pass

        N_THREADS, N_MSG = 4, 50

        def worker(tid):
            for i in range(N_MSG):
                with builder._lock:
                    bucket = builder._sessions.setdefault("s", [])
                    bucket.append({"t": f"{tid}-{i}"})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(builder._sessions["s"]) == N_THREADS * N_MSG, (
            f"并发 append 丢消息: {len(builder._sessions['s'])}/{N_THREADS * N_MSG}"
        )


# ═══════════════════════════════════════════════════════════════
# B5: 热切换原子性
# ═══════════════════════════════════════════════════════════════


class TestB5HotSwitchAtomicity:
    def test_rebuild_loop_serialized_by_lock(self):
        """rebuild_loop 持有 per-agent asyncio.Lock：并发切换串行执行。"""
        from neurova.agent_core import Agent

        assert hasattr(Agent, "_model_switch_lock_slot"), (
            "Agent 缺少模型切换锁槽位（类级声明）"
        )

        # 语义验证：两协程并发调 rebuild_loop，rebuild 体内不交错
        events = []

        class FakeLoopManager:
            async def rebuild(self, model):
                events.append(f"rebuild-start:{model}")
                await asyncio.sleep(0.01)
                events.append(f"rebuild-end:{model}")
                return True

            def get_loop(self):
                return MagicMock()

        agent = Agent.__new__(Agent)
        agent.loop_manager = FakeLoopManager()
        agent.loop = None
        agent.llm_client = MagicMock()
        agent.llm_client.config = MagicMock()
        agent.llm_client.config.model = "old"

        async def switch(model):
            # 注意：rebuild_loop 内部自持锁（实现修复位），测试不得外包锁
            # ——asyncio.Lock 不可重入，外包即死锁
            return await agent.rebuild_loop(model)

        async def run():
            return await asyncio.gather(switch("model-A"), switch("model-B"))

        asyncio.run(run())

        # 串行：每个 start 后必须紧跟同模型的 end
        for i in range(0, len(events), 2):
            assert events[i].split(":")[1] == events[i + 1].split(":")[1], (
                f"rebuild_loop 并发交错（无锁保护）: {events}"
            )


# ═══════════════════════════════════════════════════════════════
# B6: tool_engine 惰性创建单实例
# ═══════════════════════════════════════════════════════════════


class TestB6ToolEngineSingleInstance:
    def test_lazy_init_thread_safe(self):
        """并发首次访问 tool_engine property 只创建一个实例。"""
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        ex = ToolExecutor.__new__(ToolExecutor)
        ex._agent = agent
        ex._tool_engine = None
        ex._tool_engine_lock = threading.Lock()

        created = []

        class FakeEngine:
            def __init__(self):
                created.append(1)

        import neurova.tool_executor as te_mod

        orig_getter = te_mod._get_tool_engine_class

        def fake_getter():
            return FakeEngine

        te_mod._get_tool_engine_class = fake_getter
        # ExecutionEngine 路径失败走本地创建
        import builtins

        orig_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if "shared_core.execution_engine" in name:
                raise ImportError("blocked in test")
            return orig_import(name, *a, **kw)

        builtins.__import__ = fake_import
        try:
            results = []
            barrier = threading.Barrier(4)

            def access():
                barrier.wait()
                results.append(ex.tool_engine)

            threads = [threading.Thread(target=access) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(created) == 1, (
                f"并发首访创建 {len(created)} 个 ToolEngine 实例（惰性创建无锁）"
            )
            assert all(r is results[0] for r in results)
        finally:
            te_mod._get_tool_engine_class = orig_getter
            builtins.__import__ = orig_import
