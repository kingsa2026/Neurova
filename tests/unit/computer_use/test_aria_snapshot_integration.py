"""可访问性快照 + role 定位整合测试（对标 ZCode 内置浏览器控制模式）

整合的模式要点：
1. dom_snapshot —— aria 可访问性树文本观察（代替原始 HTML page.content()）
2. click_role / fill_role —— 从快照事实（role+name）驱动定位，不猜 CSS 选择器
3. capabilities —— 按后端声明能力，不支持的后端优雅降级（等价 unsupportedByDefaultIn）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.computer_use.browser_manager import (
    BrowserResult,
    PlaywrightBackend,
    ScraplingBackend,
)


def _make_backend_with_page() -> tuple:
    """构造未 initialize 的 PlaywrightBackend 并注入活动 tab（_page 现为只读 property）"""
    backend = PlaywrightBackend(config={"headless": True})
    page = MagicMock()
    page.url = "http://localhost:8100/chat"
    page.title = AsyncMock(return_value="Neurova")
    backend._tabs = {"tab_test": {"page": page, "generation": 1}}
    backend._active_target_id = "tab_test"
    return backend, page


class TestPlaywrightAriaSnapshot:
    """dom_snapshot 必须返回 aria 可访问性树文本"""

    @pytest.mark.asyncio
    async def test_dom_snapshot_returns_aria_tree(self):
        backend, page = _make_backend_with_page()
        aria_tree = '- button "登录"\n- textbox "用户名"'
        page.locator = MagicMock(return_value=MagicMock(aria_snapshot=AsyncMock(return_value=aria_tree)))

        result = await backend.dom_snapshot()

        assert isinstance(result, BrowserResult)
        assert result.success is True
        assert result.data == aria_tree
        assert result.url == "http://localhost:8100/chat"
        assert result.title == "Neurova"
        page.locator.assert_called_once_with("html")

    @pytest.mark.asyncio
    async def test_dom_snapshot_not_initialized_returns_error(self):
        backend = PlaywrightBackend(config={"headless": True})
        assert backend._page is None

        result = await backend.dom_snapshot()

        assert result.success is False
        assert "error" in (result.error or "").lower() or result.error


class TestPlaywrightRoleLocator:
    """click_role / fill_role 必须走 get_by_role 快照事实定位"""

    @pytest.mark.asyncio
    async def test_click_role_builds_get_by_role(self):
        backend, page = _make_backend_with_page()
        locator = MagicMock(click=AsyncMock())
        page.get_by_role = MagicMock(return_value=locator)

        result = await backend.click_role("button", name="登录")

        assert result.success is True
        page.get_by_role.assert_called_once_with("button", name="登录")
        locator.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_click_role_without_name(self):
        backend, page = _make_backend_with_page()
        locator = MagicMock(click=AsyncMock())
        page.get_by_role = MagicMock(return_value=locator)

        result = await backend.click_role("banner")

        assert result.success is True
        page.get_by_role.assert_called_once_with("banner")

    @pytest.mark.asyncio
    async def test_fill_role_builds_get_by_role_and_fills(self):
        backend, page = _make_backend_with_page()
        locator = MagicMock(fill=AsyncMock())
        page.get_by_role = MagicMock(return_value=locator)

        result = await backend.fill_role("textbox", name="用户名", text="uitest")

        assert result.success is True
        page.get_by_role.assert_called_once_with("textbox", name="用户名")
        locator.fill.assert_awaited_once_with("uitest", timeout=10000)

    @pytest.mark.asyncio
    async def test_click_role_empty_role_rejected_without_touching_page(self):
        backend, page = _make_backend_with_page()
        page.get_by_role = MagicMock()

        result = await backend.click_role("")

        assert result.success is False
        assert result.error
        page.get_by_role.assert_not_called()

    @pytest.mark.asyncio
    async def test_fill_role_none_text_rejected(self):
        backend, page = _make_backend_with_page()
        page.get_by_role = MagicMock()

        result = await backend.fill_role("textbox", name="搜索", text=None)

        assert result.success is False
        assert result.error
        page.get_by_role.assert_not_called()

    @pytest.mark.asyncio
    async def test_click_role_timeout_returns_error_result(self):
        """元素不存在/不可交互时必须返回错误结果而非抛异常（agent 可读）"""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        backend, page = _make_backend_with_page()
        locator = MagicMock(click=AsyncMock(side_effect=PlaywrightTimeoutError("Timeout 10000ms exceeded")))
        page.get_by_role = MagicMock(return_value=locator)

        result = await backend.click_role("button", name="不存在")

        assert result.success is False
        assert result.error


class TestCapabilityGating:
    """能力按后端声明；不支持的后端优雅降级（不抛异常）"""

    def test_playwright_backend_declares_full_capabilities(self):
        backend = PlaywrightBackend(config={"headless": True})
        caps = backend.capabilities
        assert caps["aria_snapshot"] is True
        assert caps["role_locator"] is True
        assert caps["pixel_screenshot"] is True

    def test_base_capabilities_default_all_false(self):
        from neurova.computer_use.browser_manager import BrowserBackend

        class DummyBackend(BrowserBackend):
            async def initialize(self):
                return True

            async def navigate(self, url):
                return BrowserResult(success=False)

            async def screenshot(self):
                return BrowserResult(success=False)

            async def click(self, selector):
                return BrowserResult(success=False)

            async def type_text(self, selector, text):
                return BrowserResult(success=False)

            async def extract_text(self):
                return BrowserResult(success=False)

            async def extract_links(self):
                return BrowserResult(success=False)

            async def execute_js(self, script):
                return BrowserResult(success=False)

            async def snapshot(self):
                return BrowserResult(success=False)

            async def close(self):
                pass

        caps = DummyBackend().capabilities
        assert caps["aria_snapshot"] is False
        assert caps["role_locator"] is False

    @pytest.mark.asyncio
    async def test_scrapling_degrades_gracefully(self):
        """Scrapling 后端不支持 aria/role —— 必须返回错误结果而非抛异常"""
        backend = ScraplingBackend()
        snap = await backend.dom_snapshot()
        click = await backend.click_role("button", name="x")
        fill = await backend.fill_role("textbox", name="x", text="y")

        for r in (snap, click, fill):
            assert isinstance(r, BrowserResult)
            assert r.success is False
            assert r.error

    def test_scrapling_capabilities_declare_absence(self):
        backend = ScraplingBackend()
        caps = backend.capabilities
        assert caps["aria_snapshot"] is False
        assert caps["role_locator"] is False


class TestBrowserManagerPassthrough:
    """BrowserManager 必须透传新模式方法并暴露能力清单"""

    @pytest.mark.asyncio
    async def test_manager_dom_snapshot_passthrough(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fake_backend = MagicMock()
        fake_backend.dom_snapshot = AsyncMock(return_value=BrowserResult(success=True, data="- button \"x\""))
        mgr._get_backend = AsyncMock(return_value=fake_backend)

        result = await mgr.dom_snapshot()

        assert result.success is True
        assert result.data == '- button "x"'
        fake_backend.dom_snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manager_click_role_passthrough(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fake_backend = MagicMock()
        fake_backend.click_role = AsyncMock(return_value=BrowserResult(success=True))
        mgr._get_backend = AsyncMock(return_value=fake_backend)

        result = await mgr.click_role("button", name="登录")

        assert result.success is True
        fake_backend.click_role.assert_awaited_once_with("button", "登录", None)

    @pytest.mark.asyncio
    async def test_manager_fill_role_passthrough(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fake_backend = MagicMock()
        fake_backend.fill_role = AsyncMock(return_value=BrowserResult(success=True))
        mgr._get_backend = AsyncMock(return_value=fake_backend)

        result = await mgr.fill_role("textbox", name="搜索", text="kw")

        assert result.success is True
        fake_backend.fill_role.assert_awaited_once_with("textbox", "搜索", "kw", None)

    @pytest.mark.asyncio
    async def test_manager_get_capabilities(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fake_backend = MagicMock()
        fake_backend.capabilities = {"aria_snapshot": True, "role_locator": True, "pixel_screenshot": True}
        mgr._get_backend = AsyncMock(return_value=fake_backend)

        caps = await mgr.get_capabilities()

        assert caps["backend"] == fake_backend.__class__.__name__
        assert caps["capabilities"]["aria_snapshot"] is True
