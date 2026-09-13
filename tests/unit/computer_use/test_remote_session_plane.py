"""RS-1/3/4 远程会话平面核心（remote 后端 + 会话池 + Sandbox 提供者 + 路由）

验收：
- RemoteComputerUseManager 与本地同 duck-type，动作代理到 guest client
- attach_remote_action_result：route=remote / delivery=background
- DesktopSessionPool：claim/release、per-user 复用、容量上限、空闲 TTL 回收
- WindowsSandboxProvider：wsb XML 含端口/token/启动命令（确定性）
- 路由 ContextVar：绑定远程会话后 get_computer_use_manager() 返回代理，解绑回本地
"""

import time

import pytest

from neurova.computer_use import (
    bind_remote_desktop,
    get_computer_use_manager,
    unbind_remote_desktop,
)
from neurova.computer_use.remote_backend import (
    RemoteComputerUseManager,
    attach_remote_action_result,
)
from neurova.computer_use.sandbox_provider import WindowsSandboxProvider
from neurova.computer_use.session_pool import DesktopSession, DesktopSessionPool, SessionProvider


class FakeClient:
    def __init__(self):
        self.calls = []

    def action(self, kind, params=None):
        self.calls.append((kind, params or {}))
        if kind == "screenshot":
            return {"success": True, "png_b64": "aGk=", "size_bytes": 2}  # b"hi"
        return {"success": True}


class TestRemoteBackend:
    def test_click_proxies_to_client(self):
        c = FakeClient()
        m = RemoteComputerUseManager(c)
        assert m.click_screenshot_point(5, 6, "right") is True
        assert c.calls[0] == ("click", {"x": 5, "y": 6, "button": "right"})

    def test_screenshot_decodes_b64(self):
        m = RemoteComputerUseManager(FakeClient())
        assert m.screenshot() == b"hi"

    def test_attach_remote_action_result(self):
        r = attach_remote_action_result({"success": True}, confirmed=True)
        ar = r["action_result"]
        assert ar["route"] == "remote"
        assert ar["delivery"] == "background"
        assert ar["effect"] == "confirmed"

    def test_attach_suspected_noop(self):
        r = attach_remote_action_result({"error": "x"}, confirmed=False)
        assert r["action_result"]["effect"] == "suspected_noop"


class FakeProvider(SessionProvider):
    def __init__(self):
        self.created = 0
        self.destroyed = 0

    def create(self, user_id):
        self.created += 1
        return DesktopSession(session_id="", base_url="http://x", token="t", user_id=user_id)

    def destroy(self, session):
        self.destroyed += 1


class TestSessionPool:
    def test_claim_release_reuse_same_user(self):
        p = FakeProvider()
        pool = DesktopSessionPool(p)
        s1 = pool.claim("u1")
        pool.release(s1.session_id)
        s2 = pool.claim("u1")
        assert s1.session_id == s2.session_id, "同用户空闲会话应复用"
        assert p.created == 1

    def test_per_user_isolation(self):
        p = FakeProvider()
        pool = DesktopSessionPool(p)
        a = pool.claim("u1")
        b = pool.claim("u2")
        assert a.session_id != b.session_id
        assert p.created == 2

    def test_capacity_limit(self):
        p = FakeProvider()
        pool = DesktopSessionPool(p, max_sessions=2)
        pool.claim("u1")
        pool.claim("u2")
        with pytest.raises(RuntimeError):
            pool.claim("u3")

    def test_idle_ttl_reap(self):
        p = FakeProvider()
        pool = DesktopSessionPool(p, idle_ttl=10)
        s = pool.claim("u1")
        pool.release(s.session_id)
        assert pool.reap_idle(now=time.time() + 5) == 0
        assert pool.reap_idle(now=time.time() + 100) == 1
        assert p.destroyed == 1
        assert pool.stats()["total"] == 0


class TestSandboxProvider:
    def test_wsb_contains_port_token_startup(self):
        prov = WindowsSandboxProvider(guest_port=8765)
        xml = prov.build_wsb("TOKEN123")
        assert "8765" in xml
        assert "TOKEN123" in xml
        assert "run_guest_agent.py" in xml
        assert "<Networking>Enable</Networking>" in xml

    def test_create_launches_via_injected_runner(self):
        launched = []

        def fake_runner(cmd):
            launched.append(cmd)
            return type("P", (), {"terminate": lambda self: None})()

        prov = WindowsSandboxProvider(runner=fake_runner)
        s = prov.create("u1")
        assert s.base_url.startswith("http://127.0.0.1:")
        assert s.token
        assert len(launched) == 1 and launched[0][1].endswith(".wsb")
        prov.destroy(s)


class TestRoutingSeam:
    def test_bind_returns_remote_proxy_then_unbind_restores_local(self):
        local = get_computer_use_manager()
        remote = RemoteComputerUseManager(FakeClient())
        token = bind_remote_desktop(remote)
        try:
            assert get_computer_use_manager() is remote
        finally:
            unbind_remote_desktop(token)
        assert get_computer_use_manager() is local, "解绑后回落本地单例"

    @pytest.mark.asyncio
    async def test_dom_snapshot_routes_to_remote_when_bound(self):
        from neurova.tool_executor import ToolExecutor

        client = FakeClient()
        remote = RemoteComputerUseManager(client)
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()

        async def fake_emit(self, *a, **k):
            return None

        import neurova.tool_executor as te
        orig = te.ToolExecutor._emit_computer_event
        te.ToolExecutor._emit_computer_event = fake_emit
        token = bind_remote_desktop(remote)
        try:
            out = await inst._execute_computer_dom_snapshot({"window_title": "记事本"})
            assert out["success"] is True
            assert client.calls and client.calls[0][0] == "dom_snapshot", "语义快照须代理到来宾"
        finally:
            unbind_remote_desktop(token)
            te.ToolExecutor._emit_computer_event = orig

    @pytest.mark.asyncio
    async def test_pixel_action_result_is_remote_when_bound(self):
        """远程会话下像素动作 ActionResult 必须是 route=remote/delivery=background，
        而非本地的 global_input/foreground（来宾隔离机不抢真机焦点）。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()

        async def fake_emit(self, *a, **k):
            return None

        import neurova.tool_executor as te
        origs = (te.ToolExecutor._emit_computer_event, te.ToolExecutor._emit_action_refreshed_screenshot)
        te.ToolExecutor._emit_computer_event = fake_emit
        te.ToolExecutor._emit_action_refreshed_screenshot = fake_emit
        remote = RemoteComputerUseManager(FakeClient())
        token = bind_remote_desktop(remote)
        try:
            out = await inst._execute_computer_click({"x": 1, "y": 2})
            ar = out["action_result"]
            assert ar["route"] == "remote"
            assert ar["delivery"] == "background"
            assert ar["effect"] == "confirmed"
        finally:
            unbind_remote_desktop(token)
            te.ToolExecutor._emit_computer_event, te.ToolExecutor._emit_action_refreshed_screenshot = origs


class TestUseRemoteSession:
    """闭环胶水：claim→bind→路由生效→异常也 release+unbind。"""

    def test_binds_inside_and_releases_after(self):
        from neurova.computer_use import get_computer_use_manager
        from neurova.computer_use.remote_backend import use_remote_session

        pool = DesktopSessionPool(FakeProvider())
        before = get_computer_use_manager()
        with use_remote_session(pool, "u1") as mgr:
            assert get_computer_use_manager() is mgr, "上下文内 computer_* 路由到来宾"
            assert pool.stats()["busy"] == 1
        assert get_computer_use_manager() is before, "退出后解绑回落本地"
        assert pool.stats()["busy"] == 0 and pool.stats()["idle"] == 1, "退出后归还池"

    def test_releases_on_exception(self):
        from neurova.computer_use import get_computer_use_manager
        from neurova.computer_use.remote_backend import use_remote_session

        pool = DesktopSessionPool(FakeProvider())
        with pytest.raises(RuntimeError):
            with use_remote_session(pool, "u1"):
                raise RuntimeError("boom")
        assert get_computer_use_manager() is not None
        assert pool.stats()["busy"] == 0, "异常也必须归还会话"
