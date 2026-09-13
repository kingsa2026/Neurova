"""桌面运行权限 4 档策略（decide_desktop 决策矩阵 + 持久化）"""

import pytest

from neurova.computer_use.runtime_policy import (
    DesktopAction,
    classify_risk,
    decide_desktop,
    get_runtime_mode,
    set_runtime_mode,
)


class TestRiskClassification:
    def test_readonly_low(self):
        for t in ("computer_screenshot", "computer_dom_snapshot", "computer_som_snapshot"):
            assert classify_risk(t) == "low"

    def test_shell_high(self):
        assert classify_risk("computer_shell") == "high"

    def test_mutating_medium(self):
        for t in ("computer_click", "computer_type", "computer_click_element", "computer_set_value", "computer_click_mark"):
            assert classify_risk(t) == "medium"


class TestDecideMatrix:
    def test_readonly_always_proceeds(self):
        for mode in ("full", "sandbox", "review", "auto"):
            assert decide_desktop(mode, "computer_screenshot")["action"] == DesktopAction.PROCEED.value

    def test_full_proceeds_all(self):
        assert decide_desktop("full", "computer_click")["action"] == DesktopAction.PROCEED.value
        assert decide_desktop("full", "computer_shell")["action"] == DesktopAction.PROCEED.value

    def test_sandbox_requires_sandbox_for_mutating(self):
        assert decide_desktop("sandbox", "computer_click")["action"] == DesktopAction.REQUIRE_SANDBOX.value
        assert decide_desktop("sandbox", "computer_shell")["action"] == DesktopAction.REQUIRE_SANDBOX.value

    def test_review_requires_approval(self):
        assert decide_desktop("review", "computer_click")["action"] == DesktopAction.REQUIRE_APPROVAL.value

    def test_auto_low_proceeds_medium_high_sandbox(self):
        assert decide_desktop("auto", "computer_click")["action"] == DesktopAction.REQUIRE_SANDBOX.value
        assert decide_desktop("auto", "computer_shell")["action"] == DesktopAction.REQUIRE_SANDBOX.value

    def test_unknown_mode_falls_back_full(self):
        assert decide_desktop("bogus", "computer_click")["action"] == DesktopAction.PROCEED.value


class TestPersistence:
    def test_default_is_full(self, monkeypatch):
        monkeypatch.setattr("neurova.core.app_settings.get_advanced_settings", lambda *a, **k: {})
        assert get_runtime_mode() == "full"

    def test_set_and_get(self, tmp_path, monkeypatch):
        from neurova.core import app_settings as s

        # monkeypatch 自动还原；lambda 尊重传入 path（None→tmp，显式→原值），
        # 否则直接赋值会泄漏污染后续 app_settings 测试
        monkeypatch.setattr(
            s, "_settings_path", lambda path=None: path or (tmp_path / "app_settings.json")
        )
        assert set_runtime_mode("review")
        assert get_runtime_mode() == "review"

    def test_reject_invalid_mode(self):
        assert set_runtime_mode("nope") is False


import asyncio
from unittest.mock import MagicMock

from neurova.tool_executor import ToolExecutor


def _exec():
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None
    inst._agent._current_user_id = "u1"
    return inst


class TestRuntimeGateIntegration:
    @pytest.mark.asyncio
    async def test_full_proceeds(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "full")
        hit = {}

        async def fake_click(self, params):
            hit["ran"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", fake_click)
        out = await _exec()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        assert hit.get("ran") and out["success"]

    @pytest.mark.asyncio
    async def test_sandbox_no_session_refused(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        monkeypatch.setattr("neurova.computer_use.get_active_remote_desktop", lambda: None)
        ran = {}

        async def fake_click(self, params):
            ran["yes"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", fake_click)
        out = await _exec()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        assert out["success"] is False
        assert "沙箱" in out["error"]
        assert not ran.get("yes"), "无沙箱会话不得执行"

    @pytest.mark.asyncio
    async def test_sandbox_with_session_proceeds(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        monkeypatch.setattr("neurova.computer_use.get_active_remote_desktop", lambda: object())
        ran = {}

        async def fake_click(self, params):
            ran["yes"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", fake_click)
        out = await _exec()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        assert ran.get("yes") and out["success"]

    @pytest.mark.asyncio
    async def test_review_creates_approval(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "review")
        created = {}

        class FakeAM:
            def create_approval_request(self, **kw):
                created.update(kw)
                return type("R", (), {"request_id": "req-9"})()

        monkeypatch.setattr("neurova.security.approval_manager.get_approval_manager", lambda *a, **k: FakeAM())
        ran = {}

        async def fake_click(self, params):
            ran["yes"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_click", fake_click)
        out = await _exec()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        assert out["success"] is False and "req-9" in out["error"]
        assert created["metadata"]["kind"] == "desktop_review"
        assert created["metadata"]["tool_name"] == "computer_click"
        assert not ran.get("yes")
        # 契约：审核模式弹出的审批必须走既有 approval_required SSE 链路——
        # console._extract_approval_payload 只认顶层 pending_approval+approval_id，
        # 缺字段则对话页交互面板永不弹出（审核模式形同静默拒绝）。
        assert out.get("pending_approval") is True
        assert out.get("approval_id") == "req-9"
        assert out.get("tool_name") == "computer_click"
        assert out.get("params") == {"x": 1, "y": 2}

    @pytest.mark.asyncio
    async def test_readonly_always_proceeds(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        ran = {}

        async def fake_shot(self, params):
            ran["yes"] = True
            return {"success": True}

        monkeypatch.setattr(ToolExecutor, "_execute_computer_screenshot", fake_shot)
        await _exec()._execute_builtin_tool("computer_screenshot", {})
        assert ran.get("yes"), "只读动作任何档都放行"

    @pytest.mark.asyncio
    async def test_bypass_on_approved_replay(self, monkeypatch):
        """skip_governance（审批重放）旁路运行门，否则审核模式批准后重放死循环。"""
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "review")
        tok = rp.set_gate_bypass(True)
        try:
            ran = {}

            async def fake_click(self, params):
                ran["yes"] = True
                return {"success": True}

            monkeypatch.setattr(ToolExecutor, "_execute_computer_click", fake_click)
            out = await _exec()._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
            assert ran.get("yes") and out["success"]
        finally:
            rp.reset_gate_bypass(tok)


class TestSandboxScope:
    """沙箱/自动档：pool 可用时 _sandbox_scope 在本动作执行期绑定来宾、退出归还。"""

    def test_binds_and_releases_when_pool_available(self, monkeypatch):
        from neurova.computer_use import get_active_remote_desktop
        from neurova.computer_use import runtime_policy as rp
        from neurova.computer_use.session_pool import DesktopSession, DesktopSessionPool, SessionProvider

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")

        class P(SessionProvider):
            def __init__(self): self.created = self.destroyed = 0
            def create(self, user):
                self.created += 1
                return DesktopSession(session_id="c1", base_url="http://127.0.0.1:1", token="t", user_id=user)
            def destroy(self, s): self.destroyed += 1

        prov = P()
        monkeypatch.setattr("neurova.computer_use.session_pool.get_default_desktop_pool", lambda: DesktopSessionPool(prov))
        inst = _exec()
        assert get_active_remote_desktop() is None
        with inst._sandbox_scope("computer_click", skip_governance=False):
            assert get_active_remote_desktop() is not None, "动作执行期须绑定来宾会话"
        assert get_active_remote_desktop() is None, "退出后解绑"

    def test_noop_when_no_pool(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp
        from contextlib import nullcontext

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        monkeypatch.setattr("neurova.computer_use.session_pool.get_default_desktop_pool", lambda: None)
        inst = _exec()
        assert isinstance(inst._sandbox_scope("computer_click", skip_governance=False), nullcontext)

    def test_noop_for_readonly_and_full(self, monkeypatch):
        from neurova.computer_use import runtime_policy as rp
        from contextlib import nullcontext

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "full")
        inst = _exec()
        # full 档不领用
        assert isinstance(inst._sandbox_scope("computer_click", skip_governance=False), type(nullcontext()))
