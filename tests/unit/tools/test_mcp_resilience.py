# -*- coding: utf-8 -*-
"""
P1-3 MCP 可靠性红测

范围（对标实施文档 P1-3）：
- 连接状态机：CONNECTED / DISCONNECTED / OPEN（熔断）/ HALF_OPEN（探测窗）
- 熔断：5 次连续失败 → OPEN；300s 后惰性升级 HALF_OPEN；探测成功复位/失败重回 OPEN
- 退避重连：1s→60s 指数退避 + 抖动；显式 disconnect 取消重连（用户意图优先）
- 断连窗口 get_available_tools 降级返回缓存（不再返回空表）
- 工具缓存 TTL 300s（过期重拉）
- call_tool 无自动重试（副作用安全，锁定测试）——401 刷新重试例外（鉴权层，未触达工具）
- last_error/status 契约不变
"""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.tool_layers.mcp_resilience import (
    ServerResilience,
    ServerState,
    backoff_delay,
)


class TestBackoff:
    def test_exponential_growth_capped(self):
        assert backoff_delay(0, jitter=0.0) == 1.0
        assert backoff_delay(1, jitter=0.0) == 2.0
        assert backoff_delay(2, jitter=0.0) == 4.0
        assert backoff_delay(6, jitter=0.0) == 60.0
        assert backoff_delay(20, jitter=0.0) == 60.0  # 帽值

    def test_jitter_bounded(self):
        for attempt in range(8):
            base = min(1.0 * (2 ** attempt), 60.0)
            for _ in range(20):
                d = backoff_delay(attempt)
                assert base * 0.5 <= d <= base * 1.5


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


class TestServerResilience:
    def test_connect_success_resets(self):
        res = ServerResilience(clock=FakeClock())
        res.on_connect_failure("boom")
        res.on_connect_success()
        assert res.effective_state == ServerState.CONNECTED
        assert res.consecutive_failures == 0

    def test_open_after_threshold_call_failures(self):
        res = ServerResilience(clock=FakeClock())
        res.on_connect_success()
        for _ in range(4):
            res.on_call_failure("err")
        assert res.effective_state == ServerState.CONNECTED  # 未达阈值
        res.on_call_failure("err")
        assert res.effective_state == ServerState.OPEN
        assert res.last_error == "err"

    def test_open_blocks_call_then_half_open_after_window(self):
        clock = FakeClock()
        res = ServerResilience(clock=clock)
        res.on_connect_success()
        for _ in range(5):
            res.on_call_failure("err")
        ok, reason = res.can_attempt_call()
        assert not ok  # OPEN 拒绝

        clock.advance(300.0)
        ok, reason = res.can_attempt_call()
        assert ok  # HALF_OPEN 探测放行
        assert res.effective_state == ServerState.HALF_OPEN

    def test_probe_success_resets_probe_failure_reopens(self):
        clock = FakeClock()
        res = ServerResilience(clock=clock)
        res.on_connect_success()
        for _ in range(5):
            res.on_call_failure("err")
        clock.advance(300.0)
        assert res.effective_state == ServerState.HALF_OPEN

        res.on_call_success()
        assert res.effective_state == ServerState.CONNECTED

        # 再熔断，探测失败 → 重回 OPEN（计时重置）
        for _ in range(5):
            res.on_call_failure("e2")
        clock.advance(300.0)
        assert res.effective_state == ServerState.HALF_OPEN
        opened_at_before = res.opened_at
        clock.advance(1.0)
        res.on_call_failure("probe failed")
        assert res.effective_state == ServerState.OPEN
        assert res.opened_at == clock.now  # 重置

    def test_call_success_resets_failure_count(self):
        res = ServerResilience(clock=FakeClock())
        res.on_connect_success()
        res.on_call_failure("a")
        res.on_call_failure("b")
        res.on_call_success()
        assert res.consecutive_failures == 0
        res.on_call_failure("c")
        assert res.effective_state == ServerState.CONNECTED  # 计数已清零

    def test_tools_cache_degrade(self):
        res = ServerResilience(clock=FakeClock())
        assert res.get_stale_tools() == []
        res.set_tools_cache([{"name": "t1"}], res._clock())
        assert res.get_stale_tools() == [{"name": "t1"}]  # 断连窗口降级可用


def _fake_tool(name):
    return SimpleNamespace(name=name, description=name, inputSchema={})


def _fake_session(tool_names=None, call_results=None, call_script=None):
    """fake ClientSession：list_tools + 可脚本化 call_tool"""
    tools = [_fake_tool(n) for n in (tool_names or [])]
    calls = {"count": 0}
    lists = {"count": 0}
    script = list(call_script or [])
    default_results = list(call_results or [])

    async def call_tool(tool_name, params):
        calls["count"] += 1
        if script:
            b = script.pop(0)
            if isinstance(b, Exception):
                raise b
            return b
        if default_results:
            return default_results.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], isError=False)

    async def list_tools():
        lists["count"] += 1
        return SimpleNamespace(tools=tools)

    return SimpleNamespace(call_tool=call_tool, list_tools=list_tools), calls, lists


def _make_client(clock=None):
    from neurova.tool_layers.mcp_client import MCPToolClient

    if clock is None:
        clock = FakeClock()
    return MCPToolClient(user_id="t", clock=clock)


CFG = {"id": "s1", "name": "s1", "transport": "http", "url": "http://127.0.0.1:9/mcp"}


async def _connect_ok(client, session, server_id="s1"):
    async def fake_open(sid, cfg):
        return session

    client._open_session = fake_open
    return await client.connect_server(server_id, CFG)


class TestClientWiring:
    @pytest.mark.asyncio
    async def test_call_tool_no_auto_retry_side_effect_safety(self):
        """非鉴权失败绝不自动重试（工具可能已产生副作用）"""
        client = _make_client()
        session, calls, lists = _fake_session(tool_names=["t"], call_script=[RuntimeError("transient")])
        assert await _connect_ok(client, session)

        from neurova.tool_layers.mcp_config import validate_mcp_server_config
        client._servers["s1"]["tools"] = [
            client._tool_to_dict(_fake_tool("t"))
        ]

        with pytest.raises(RuntimeError):
            await client.call_tool("s1", "t", {}, user_id="u1")
        assert calls["count"] == 1  # 只调一次——无同会话自动重试

    @pytest.mark.asyncio
    async def test_circuit_opens_after_5_failures_and_blocks_fast(self):
        client = _make_client()
        session, calls, lists = _fake_session(
            tool_names=["t"], call_script=[RuntimeError(f"e{i}") for i in range(5)]
        )
        assert await _connect_ok(client, session)
        client._servers["s1"]["tools"] = [client._tool_to_dict(_fake_tool("t"))]

        for i in range(5):
            with pytest.raises(RuntimeError):
                await client.call_tool("s1", "t", {}, user_id="u1")

        res = client._resilience["s1"]
        assert res.effective_state == ServerState.OPEN

        # OPEN 窗口：快速拒绝，不触达会话
        with pytest.raises(ValueError, match="not connected|熔断"):
            await client.call_tool("s1", "t", {}, user_id="u1")
        assert calls["count"] == 5  # 第 6 次未触达

    @pytest.mark.asyncio
    async def test_half_open_probe_allows_one_call(self):
        clock = FakeClock()
        client = _make_client(clock=clock)
        # 前 5 次失败（熔断），第 6 次成功（探测）
        session, calls, lists = _fake_session(
            tool_names=["t"],
            call_script=[RuntimeError(f"e{i}") for i in range(5)]
            + [SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], isError=False)],
        )
        assert await _connect_ok(client, session)
        client._servers["s1"]["tools"] = [client._tool_to_dict(_fake_tool("t"))]

        for i in range(5):
            with pytest.raises(RuntimeError):
                await client.call_tool("s1", "t", {}, user_id="u1")

        # 惰性推进探测窗（open_duration 后）
        res = client._resilience["s1"]
        clock.advance(300.0)

        result = await client.call_tool("s1", "t", {}, user_id="u1")
        assert calls["count"] == 6  # 探测放行
        assert res.effective_state == ServerState.CONNECTED

    @pytest.mark.asyncio
    async def test_degraded_tools_served_from_cache_when_disconnected(self):
        """断连窗口 get_available_tools 降级返回缓存（原为 []）"""
        client = _make_client()
        session, calls, lists = _fake_session(tool_names=["alpha", "beta"])
        assert await _connect_ok(client, session)

        tools = await client.get_available_tools("s1")
        assert [t["name"] for t in tools] == ["alpha", "beta"]

        # 模拟断连（会话死掉）：状态 DISCONNECTED，但缓存仍在
        client._resilience["s1"].state = ServerState.DISCONNECTED
        client._servers["s1"]["connected"] = False

        tools2 = await client.get_available_tools("s1")
        assert [t["name"] for t in tools2] == ["alpha", "beta"]  # 降级命中缓存

    @pytest.mark.asyncio
    async def test_tools_cache_ttl_refresh(self):
        clock = FakeClock()
        client = _make_client(clock=clock)
        session, calls, lists = _fake_session(tool_names=["t1"])
        assert await _connect_ok(client, session)

        await client.get_available_tools("s1")
        await client.get_available_tools("s1")  # TTL 内：不重拉
        fetch_count = lists["count"]
        assert fetch_count == 1  # 仅 connect 时拉过一次

        clock.advance(301.0)  # 过期
        await client.get_available_tools("s1")
        assert lists["count"] == 2  # TTL 过期重拉

    @pytest.mark.asyncio
    async def test_disconnect_cancels_reconnect(self):
        client = _make_client()
        session, calls, lists = _fake_session(tool_names=["t"])
        assert await _connect_ok(client, session)

        # 制造断连 → 自动调度重连
        client._resilience["s1"].state = ServerState.DISCONNECTED
        loop = asyncio.get_running_loop()
        scheduled = []

        def fake_reconnect(sid, cfg):  # 同步：_schedule_reconnect 是同步方法
            scheduled.append(sid)

        client._schedule_reconnect = fake_reconnect  # type: ignore
        client._mark_disconnected("s1", "session closed", reschedule=True)
        assert scheduled == ["s1"]

        # 显式断开：取消重连（用户意图优先）
        ok = await client.disconnect_server("s1")
        assert ok is True
        assert "s1" not in client._resilience

    @pytest.mark.asyncio
    async def test_status_contract_preserved(self):
        client = _make_client()
        session, calls, lists = _fake_session(tool_names=["t"])
        assert await _connect_ok(client, session)

        st = client.get_server_status("s1")
        # 既有契约键不变
        assert st["connected"] is True
        assert st["last_error"] is None
        assert st["tool_count"] == 1
        assert st["transport"] == "http"
        assert st["server_id"] == "s1"

    @pytest.mark.asyncio
    async def test_reconnect_after_session_death(self):
        """会话死亡 → 标记断连 + 自动重连成功后恢复 CONNECTED"""
        client = _make_client()
        session1, calls1, lists1 = _fake_session(tool_names=["t"])
        assert await _connect_ok(client, session1)

        reopened = []

        async def fake_open(sid, cfg):
            reopened.append(sid)
            return _fake_session(tool_names=["t"])[0]  # (session, calls, lists) 取首元

        client._open_session = fake_open

        # 会话操作抛连接类错误 → 断连 + 调度重连
        client._mark_disconnected("s1", "ClosedResourceError", reschedule=True)
        assert client._resilience["s1"].effective_state == ServerState.DISCONNECTED

        # 等待重连任务完成（测试内短退避：monkeypatch backoff 已注入 client._reconnect_backoff）
        task = client._reconnect_tasks.get("s1")
        assert task is not None
        await asyncio.wait_for(task, timeout=5)
        assert client.get_server_status("s1")["connected"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
