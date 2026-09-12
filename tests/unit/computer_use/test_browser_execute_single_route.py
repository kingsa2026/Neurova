"""R1-4 /browser/execute 路由单源化（CUA 升级方案 Phase 1，净 LOC ≤ 0）

病根（修复前）：POST /browser/execute 被 register 了两次（computer.py 两处），
除 _dispatch_browser_command 外还有两份 if/elif 命令映射副本，历史上已漂移。

验收：
- 路由表里 POST /browser/execute 只注册一次
- 全部命令经 _dispatch_browser_command 单点分发
- 失败 502 携带后端错误；screenshot 命令结果不含 has_screenshot 大对象标记
- 幻觉字段/未知命令在判别联合层被拒（422 语义）
"""

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from neurova.api.endpoints import computer as computer_api


class TestSingleRoute:
    def test_browser_execute_registered_once(self):
        """路由表只允许一个 POST /browser/execute"""
        entries = [
            r for r in computer_api.router.routes
            if isinstance(r, APIRoute) and r.path == "/browser/execute"
        ]
        assert len(entries) == 1
        assert "POST" in entries[0].methods

    def test_dispatch_is_single_source(self):
        """两份 if/elif 副本已删除：路由体调用 _dispatch_browser_command"""
        import inspect

        source = inspect.getsource(computer_api.browser_execute_route)
        assert "_dispatch_browser_command" in source
        assert "isinstance(cmd, NavigateCmd)" not in source, "命令映射必须单点在 _dispatch_browser_command"


class TestRouteBehavior:
    @pytest.mark.asyncio
    async def test_success_via_single_dispatch(self, monkeypatch):
        from neurova.computer_use.browser_manager import BrowserResult

        async def fake_dispatch(cmd):
            return BrowserResult(success=True, url="https://x")

        monkeypatch.setattr(computer_api, "_dispatch_browser_command", fake_dispatch)
        cmd = computer_api.NavigateCmd(url="https://x")
        resp = await computer_api.browser_execute_route(cmd, current_user={"user_id": "u1"})
        assert resp["code"] == 0
        assert resp["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_failure_raises_502_with_upstream_error(self, monkeypatch):
        from neurova.computer_use.browser_manager import BrowserResult

        async def fake_dispatch(cmd):
            return BrowserResult(success=False, error="后端炸了")

        monkeypatch.setattr(computer_api, "_dispatch_browser_command", fake_dispatch)
        with pytest.raises(HTTPException) as exc:
            await computer_api.browser_execute_route(
                computer_api.NavigateCmd(url="https://x"), current_user={"user_id": "u1"}
            )
        assert exc.value.status_code == 502
        assert "后端炸了" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_screenshot_cmd_strips_has_screenshot(self, monkeypatch):
        from neurova.computer_use.browser_manager import BrowserResult

        async def fake_dispatch(cmd):
            return BrowserResult(success=True, screenshot="ZmFrZQ==")

        monkeypatch.setattr(computer_api, "_dispatch_browser_command", fake_dispatch)
        resp = await computer_api.browser_execute_route(
            computer_api.ScreenshotCmd(), current_user={"user_id": "u1"}
        )
        assert "has_screenshot" not in resp["data"]

    def test_hallucinated_field_rejected_at_schema_layer(self):
        """extra="forbid"：未知字段无法通过判别联合校验"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            computer_api.BrowserCommandAdapter.validate_python(
                {"command": "navigate", "url": "https://x", "bogus": 1}
            )
