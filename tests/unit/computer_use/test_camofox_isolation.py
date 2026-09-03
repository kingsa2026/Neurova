"""Camofox 三层隔离合规测试

TDD 红→绿:
- 红:本文件先写,验证未实现时的失败状态
- 绿:实现 identity_context + 后端池化 + supervisor track_user_id

覆盖:
1. ContextVar 隔离:set_request_user_id / get_request_user_id 跨任务不污染
2. CamofoxServerBackend._eff_user_id() 优先读 ContextVar,后端 _user_id 兜底
3. BrowserManager 按 userId 池化:同 user 同实例,不同 user 不同实例
4. BrowserManager._backends 不再直接含 camofox key(已池化)
5. CamofoxSupervisor.track_user_id() 累积, _cleanup_temp_traces() 按列表清理
6. _cleanup_temp_traces() tracks 为空时回退到 fallback_user_id
7. BrowserManager 加锁:并发 N 次同 user 池化只创建 1 个实例
8. tool_executor._execute_builtin_tool("browser_*") 写 ContextVar
9. tool_executor._execute_builtin_tool("non_browser_*") 不写 ContextVar
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── 1. ContextVar 基础 ──


class TestIdentityContext:
    """identity_context 模块的 ContextVar 行为"""

    def test_default_is_none(self):
        from neurova.core.identity_context import get_request_user_id

        # 测试时先清,避免被其它测试污染
        from neurova.core.identity_context import clear_request_user_id

        clear_request_user_id()
        assert get_request_user_id() is None

    def test_set_and_get(self):
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
            set_request_user_id,
        )

        clear_request_user_id()
        set_request_user_id("alice")
        assert get_request_user_id() == "alice"
        clear_request_user_id()

    def test_clear_resets_to_none(self):
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
            set_request_user_id,
        )

        set_request_user_id("bob")
        clear_request_user_id()
        assert get_request_user_id() is None

    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated(self):
        """两个 async task 各设自己的 userId,互不污染"""
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
            set_request_user_id,
        )

        clear_request_user_id()
        results = {}

        async def task_a():
            set_request_user_id("alice")
            await asyncio.sleep(0.05)
            results["a"] = get_request_user_id()

        async def task_b():
            set_request_user_id("bob")
            await asyncio.sleep(0.05)
            results["b"] = get_request_user_id()

        await asyncio.gather(task_a(), task_b())
        assert results["a"] == "alice"
        assert results["b"] == "bob"


# ── 2. CamofoxServerBackend._eff_user_id ──


class TestCamofoxServerBackendEffUserId:
    """后端 _eff_user_id() 优先 ContextVar,后端 _user_id 兜底"""

    def test_falls_back_to_self_user_id(self):
        from neurova.core.identity_context import clear_request_user_id
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        clear_request_user_id()
        b = CamofoxServerBackend({"base_url": "http://test:9377"}, user_id="bob")
        assert b._eff_user_id() == "bob"

    def test_context_var_overrides(self):
        from neurova.core.identity_context import (
            clear_request_user_id,
            set_request_user_id,
        )
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        clear_request_user_id()
        b = CamofoxServerBackend({"base_url": "http://test:9377"}, user_id="bob")
        set_request_user_id("alice")
        try:
            assert b._eff_user_id() == "alice"
        finally:
            clear_request_user_id()

    def test_empty_context_var_uses_self(self):
        from neurova.core.identity_context import (
            clear_request_user_id,
            set_request_user_id,
        )
        from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

        b = CamofoxServerBackend({"base_url": "http://test:9377"}, user_id="bob")
        # 显式设置空字符串,应该回退到 self
        set_request_user_id("")
        try:
            assert b._eff_user_id() == "bob"
        finally:
            clear_request_user_id()


# ── 3+4. BrowserManager 池化 ──


class TestBrowserManagerPool:
    """BrowserManager 按 userId 池化"""

    def test_camofox_not_in_backends_dict(self, monkeypatch):
        """camofox 不再预注册到 _backends——延迟到首次 get 时创建"""
        from neurova.core.identity_context import clear_request_user_id
        from neurova.computer_use.browser_manager import BrowserManager

        clear_request_user_id()
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        mgr = BrowserManager()
        # camofox 不应在 _backends(被池化到 _user_camofox_backends)
        assert "camofox" not in mgr._backends
        # 但 _camofox_enabled 应为 True
        assert getattr(mgr, "_camofox_enabled", False) is True

    def test_camofox_disabled_when_no_env(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_URL", raising=False)
        from neurova.core.identity_context import clear_request_user_id
        from neurova.computer_use.browser_manager import BrowserManager

        clear_request_user_id()
        mgr = BrowserManager()
        assert getattr(mgr, "_camofox_enabled", False) is False
        assert "camofox" not in mgr._backends

    def test_pool_returns_same_instance_per_user(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        from neurova.core.identity_context import (
            clear_request_user_id,
            set_request_user_id,
        )
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager()
        clear_request_user_id()

        set_request_user_id("alice")
        b1 = mgr._get_or_create_user_camofox_backend()
        b2 = mgr._get_or_create_user_camofox_backend()
        assert b1 is b2
        clear_request_user_id()

        set_request_user_id("bob")
        b3 = mgr._get_or_create_user_camofox_backend()
        assert b3 is not b1
        b4 = mgr._get_or_create_user_camofox_backend()
        assert b3 is b4
        clear_request_user_id()

    def test_default_user_fallback(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
        )
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager()
        clear_request_user_id()
        # 没有设置 userId,应该回退到 "default"
        b = mgr._get_or_create_user_camofox_backend()
        assert b._user_id == "default"
        # 显式设置 None 走 default
        assert get_request_user_id() is None


# ── 7. 并发安全 ──


class TestBrowserManagerPoolConcurrency:
    """并发 N 次池化同 user,只创建 1 个实例"""

    def test_concurrent_same_user_one_instance(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        from neurova.core.identity_context import (
            clear_request_user_id,
            set_request_user_id,
        )
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager()
        set_request_user_id("alice")
        try:
            N = 50
            results = [None] * N

            def worker(i):
                results[i] = mgr._get_or_create_user_camofox_backend()

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            # 所有线程拿到同一实例
            assert all(b is results[0] for b in results)
        finally:
            clear_request_user_id()


# ── 5+6. CamofoxSupervisor 多用户清理 ──


class TestCamofoxSupervisorTrackAndCleanup:
    """track_user_id + 按列表清理"""

    def test_track_user_id_accumulates(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s.track_user_id("alice")
        s.track_user_id("bob")
        s.track_user_id("alice")  # 重复
        assert "alice" in s._tracked_user_ids
        assert "bob" in s._tracked_user_ids
        assert len(s._tracked_user_ids) == 2

    def test_track_user_id_empty_skipped(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s.track_user_id("")
        s.track_user_id(None)
        assert len(s._tracked_user_ids) == 0

    def test_cleanup_no_tracks_uses_fallback(self, tmp_path, monkeypatch):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        # 没有 track_user_id,清理时应该回退到 NEUROVA_CAMOFOX_USER env 或 "neurova"
        monkeypatch.setenv("NEUROVA_CAMOFOX_USER", "default")
        s = CamofoxSupervisor()
        assert s._fallback_user_id == "default"
        # 这里只验证不抛异常
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        cleaned = s._cleanup_temp_traces()
        # tracks 为空,fallback 是 default
        # 应该走 default 路径(目录不存在,no-op,但 users 计数 +1)
        assert cleaned["users"] == 1

    def test_cleanup_traces_for_multiple_users(self, tmp_path, monkeypatch):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor
        import hashlib

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # 两个 user 的 traces,一个超 TTL 一个未超
        s = CamofoxSupervisor({"trace_ttl_hours": 1})
        s.track_user_id("alice")
        s.track_user_id("bob")

        for uid in ("alice", "bob"):
            sha = hashlib.sha256(uid.encode()).hexdigest()[:32]
            user_traces = tmp_path / ".camofox" / "traces" / sha
            user_traces.mkdir(parents=True)
            # alice 有 1 个旧 zip,bob 有 1 个新 zip
            if uid == "alice":
                old = user_traces / "old.zip"
                old.write_bytes(b"x" * 100)
                import os, time as t
                old_time = t.time() - 7200
                os.utime(old, (old_time, old_time))
            else:
                new = user_traces / "new.zip"
                new.write_bytes(b"y" * 50)

        cleaned = s._cleanup_temp_traces()
        assert cleaned["users"] == 2
        # alice 旧 zip 被删,bob 新 zip 保留
        assert cleaned["traces_zip"] == 1
        alice_sha = hashlib.sha256(b"alice").hexdigest()[:32]
        bob_sha = hashlib.sha256(b"bob").hexdigest()[:32]
        assert not (tmp_path / ".camofox" / "traces" / alice_sha / "old.zip").exists()
        assert (tmp_path / ".camofox" / "traces" / bob_sha / "new.zip").exists()


# ── 8+9. tool_executor._execute_builtin_tool 入口注入 ──


class TestToolExecutorIdentityInjection:
    """tool_executor 在 browser_* 入口注入 userId"""

    @pytest.mark.asyncio
    async def test_browser_navigate_injects_user_id(self, monkeypatch):
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
        )
        from neurova.tool_executor import ToolExecutor

        clear_request_user_id()

        # mock 一个 agent,_current_user_id="alice"
        mock_agent = MagicMock()
        mock_agent._current_user_id = "alice"
        mock_agent.config = MagicMock()
        mock_agent.config.user_id = "config-bob"
        mock_agent.config.agent_id = "config-agent"

        executor = ToolExecutor(agent_ref=mock_agent)

        # mock 实际的 browser_navigate 实现,只观察 ContextVar
        async def fake_navigate(self, params):
            # 入口注入后,这里应该能读到 alice
            return {"ctx_user_id": get_request_user_id()}

        # 替换 _execute_browser_navigate 方法
        executor._execute_browser_navigate = fake_navigate.__get__(executor)

        try:
            result = await executor._execute_builtin_tool(
                "browser_navigate", {"url": "https://example.com"}
            )
            assert result["ctx_user_id"] == "alice"
        finally:
            clear_request_user_id()

    @pytest.mark.asyncio
    async def test_non_browser_does_not_inject(self, monkeypatch):
        from neurova.core.identity_context import (
            clear_request_user_id,
            get_request_user_id,
        )
        from neurova.tool_executor import ToolExecutor

        clear_request_user_id()

        mock_agent = MagicMock()
        mock_agent._current_user_id = "alice"
        mock_agent.config = MagicMock()
        mock_agent.config.user_id = "config-bob"
        mock_agent.config.agent_id = "config-agent"

        executor = ToolExecutor(agent_ref=mock_agent)

        async def fake_get_datetime(self, params):
            # 非 browser 路径,ContextVar 应保持 None
            return {"ctx_user_id": get_request_user_id()}

        executor._execute_get_datetime = fake_get_datetime.__get__(executor)

        try:
            result = await executor._execute_builtin_tool("get_datetime", {})
            # 非 browser 路径不应设置 ContextVar
            assert result["ctx_user_id"] is None
        finally:
            clear_request_user_id()


# ── Supervisor track_user_id 集成 ──


class TestSupervisorTrackIntegration:
    """tool_executor / API 路径都应触发 supervisor.track_user_id"""

    @pytest.mark.asyncio
    async def test_tool_executor_tracks_user_id(self, monkeypatch):
        from neurova.computer_use.camofox_supervisor import (
            get_camofox_supervisor,
            reset_camofox_supervisor,
        )
        from neurova.core.identity_context import clear_request_user_id
        from neurova.tool_executor import ToolExecutor

        reset_camofox_supervisor()
        clear_request_user_id()

        mock_agent = MagicMock()
        mock_agent._current_user_id = "alice"
        mock_agent.config = MagicMock()
        mock_agent.config.user_id = "config"
        mock_agent.config.agent_id = "config-agent"

        executor = ToolExecutor(agent_ref=mock_agent)

        async def fake_navigate(self, params):
            return {"ok": True}

        executor._execute_browser_navigate = fake_navigate.__get__(executor)

        await executor._execute_builtin_tool(
            "browser_navigate", {"url": "https://example.com"}
        )

        supervisor = get_camofox_supervisor()
        assert "alice" in supervisor._tracked_user_ids


# ── close_all 清理池 ──


class TestBrowserManagerCloseAll:
    """close_all 应清理 camofox 池的所有 user 后端"""

    @pytest.mark.asyncio
    async def test_close_all_closes_pooled_backends(self, monkeypatch):
        from neurova.core.identity_context import (
            clear_request_user_id,
            set_request_user_id,
        )
        from neurova.computer_use.browser_manager import BrowserManager

        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        mgr = BrowserManager()

        clear_request_user_id()
        set_request_user_id("alice")
        mgr._get_or_create_user_camofox_backend()
        set_request_user_id("bob")
        mgr._get_or_create_user_camofox_backend()
        clear_request_user_id()

        assert len(mgr._user_camofox_backends) == 2
        await mgr.close_all()
        assert len(mgr._user_camofox_backends) == 0