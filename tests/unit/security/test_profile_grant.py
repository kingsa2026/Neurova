"""R3-4 profile 附身授权（camofox 登录态）

fail-closed 红线：无有效 grant 即拒，绝不静默用 profile。
验收：
1. store mint/has_valid/revoke + TTL（session 过期、long 不过期）
2. ensure_profile_grant：有 grant 放行；无 grant 铸造审批请求 + 拒绝
3. ApprovalManager 不可用时仍拒绝（不放行）
4. mint_from_approval：kind=profile_grant 批准后落授权；非该 kind 忽略
5. tool_executor browser_* 分发门：camofox 激活且无 grant → 结构化拒绝，
   不触达后端；有 grant → 正常执行
"""

import time

import pytest

from neurova.security import profile_grant as pg


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    pg.reset_profile_grant_store()
    pg._store = pg.ProfileGrantStore(path=str(tmp_path / "grants.json"))
    yield
    pg.reset_profile_grant_store()


class TestStore:
    def test_mint_and_valid(self):
        s = pg.get_profile_grant_store()
        assert s.mint("u1", "p1", scope="session")
        assert s.has_valid_grant("u1", "p1")
        assert not s.has_valid_grant("u1", "p2")

    def test_session_ttl_expiry(self):
        s = pg.get_profile_grant_store()
        s.mint("u1", "p1", scope="task")  # 3600s
        assert s.has_valid_grant("u1", "p1", now=time.time() + 100)
        assert not s.has_valid_grant("u1", "p1", now=time.time() + 99999)

    def test_long_never_expires(self):
        s = pg.get_profile_grant_store()
        s.mint("u1", "p1", scope="long")
        assert s.has_valid_grant("u1", "p1", now=time.time() + 10 ** 9)

    def test_revoke(self):
        s = pg.get_profile_grant_store()
        s.mint("u1", "p1")
        assert s.revoke("u1", "p1")
        assert not s.has_valid_grant("u1", "p1")
        assert not s.revoke("u1", "p1")  # 幂等：不存在返回 False

    def test_invalid_scope_falls_back_session(self):
        s = pg.get_profile_grant_store()
        s.mint("u1", "p1", scope="bogus")
        assert s.has_valid_grant("u1", "p1")


class TestEnsureGate:
    def test_granted_when_valid(self):
        pg.get_profile_grant_store().mint("u1", "p1")
        out = pg.ensure_profile_grant("u1", "p1")
        assert out["granted"] is True

    def test_denied_and_mints_approval(self, monkeypatch):
        created = {}

        class FakeAM:
            def create_approval_request(self, **kw):
                created.update(kw)
                return type("R", (), {"request_id": "req-1"})()

        monkeypatch.setattr("neurova.security.approval_manager.get_approval_manager", lambda *a, **k: FakeAM())
        out = pg.ensure_profile_grant("u1", "p1", agent_id="a1", session_id="s1", reason="发帖")
        assert out["granted"] is False
        assert out["request_id"] == "req-1"
        assert created["metadata"]["kind"] == "profile_grant"
        assert created["metadata"]["profile"] == "p1"

    def test_denied_even_when_approval_unavailable(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no approval subsystem")

        monkeypatch.setattr("neurova.security.approval_manager.get_approval_manager", boom)
        out = pg.ensure_profile_grant("u1", "p1")
        assert out["granted"] is False  # fail-closed：审批挂了也不放行


class TestApprovalHook:
    def test_mint_from_approval(self):
        ok = pg.mint_from_approval(
            {"kind": "profile_grant", "user_id": "u1", "profile": "p1", "scope": "long"},
            approved_by="admin",
        )
        assert ok
        assert pg.get_profile_grant_store().has_valid_grant("u1", "p1")

    def test_non_profile_grant_ignored(self):
        assert pg.mint_from_approval({"kind": "other"}, approved_by="x") is False


class TestDispatchGate:
    @pytest.mark.asyncio
    async def test_browser_denied_without_grant(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()

        class FakeMgr:
            def camofox_active(self):
                return True

        monkeypatch.setattr("neurova.computer_use.browser_manager.get_browser_manager", lambda *a, **k: FakeMgr())
        monkeypatch.setattr(pg, "ensure_profile_grant",
                            lambda *a, **k: {"granted": False, "request_id": "r1", "message": "需授权"})
        called = {"hit": False}

        async def fake_nav(self, params):
            called["hit"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_browser_navigate", fake_nav)
        out = await inst._execute_builtin_tool("browser_navigate", {"url": "https://x.com"})
        assert out["success"] is False
        assert "profile_grant" in out or "附身授权" in out.get("error", "")
        assert called["hit"] is False, "无 grant 不得触达后端"

    @pytest.mark.asyncio
    async def test_browser_proceeds_with_grant(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()

        class FakeMgr:
            def camofox_active(self):
                return True

        monkeypatch.setattr("neurova.computer_use.browser_manager.get_browser_manager", lambda *a, **k: FakeMgr())
        monkeypatch.setattr(pg, "ensure_profile_grant", lambda *a, **k: {"granted": True, "message": "ok"})

        async def fake_nav(self, params):
            return {"success": True, "ok": 1}

        monkeypatch.setattr(ToolExecutor, "_execute_browser_navigate", fake_nav)
        out = await inst._execute_builtin_tool("browser_navigate", {"url": "https://x.com"})
        assert out.get("ok") == 1
