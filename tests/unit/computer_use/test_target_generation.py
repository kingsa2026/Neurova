"""Tab 级 target 代际管理测试（后续项之二，对标 ZCode browserGeneration）

语义：
- 每个 tab（target）持有自己的 generation，navigate 该 tab 时 +1
- 调用方携带旧 generation 操作 → 拒绝并提示重新快照（快照事实已失效）
- 不携带 generation → 跳过校验（向后兼容）
- 活动 tab 被关闭时自动回落到剩余 tab
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.computer_use.browser_manager import BrowserResult, PlaywrightBackend


def _make_page(url="https://example.com", title="Example"):
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.goto = AsyncMock()
    page.locator = MagicMock(return_value=MagicMock(aria_snapshot=AsyncMock(return_value='- button "x"')))
    locator = MagicMock(click=AsyncMock(), fill=AsyncMock())
    page.get_by_role = MagicMock(return_value=locator)
    page._role_locator = locator
    return page


def _seed_backend(tabs_spec):
    """按 {target_id: (generation, url)} 造 backend，最后一个为活动 tab"""
    backend = PlaywrightBackend(config={"headless": True})
    backend._tabs = {}
    for tid, (gen, url) in tabs_spec.items():
        backend._tabs[tid] = {"page": _make_page(url=url), "generation": gen}
    backend._active_target_id = list(tabs_spec)[-1] if tabs_spec else None
    return backend


class TestTargetLifecycle:
    @pytest.mark.asyncio
    async def test_open_target_creates_and_activates_tab(self):
        backend = PlaywrightBackend(config={"headless": True})
        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=_make_page(url="about:blank"))
        backend._context = ctx

        result = await backend.open_target()

        assert result.success is True
        assert result.data["target_id"] in backend._tabs
        assert result.data["generation"] >= 1
        assert backend._active_target_id == result.data["target_id"]
        ctx.new_page.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_open_target_with_url_navigates(self):
        backend = PlaywrightBackend(config={"headless": True})
        page = _make_page(url="about:blank")
        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        backend._context = ctx

        result = await backend.open_target(url="https://example.com/a")

        assert result.success is True
        page.goto.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_targets_reports_active_flag(self):
        backend = _seed_backend({"t1": (1, "https://a.com"), "t2": (3, "https://b.com")})

        result = await backend.list_targets()

        assert result.success is True
        targets = {t["target_id"]: t for t in result.data}
        assert targets["t1"]["generation"] == 1
        assert targets["t2"]["generation"] == 3
        assert targets["t1"]["active"] is False
        assert targets["t2"]["active"] is True
        assert targets["t1"]["url"] == "https://a.com"

    @pytest.mark.asyncio
    async def test_switch_target_activates(self):
        backend = _seed_backend({"t1": (1, "https://a.com"), "t2": (3, "https://b.com")})

        result = await backend.switch_target("t1", generation=1)

        assert result.success is True
        assert backend._active_target_id == "t1"

    @pytest.mark.asyncio
    async def test_switch_target_stale_generation_rejected(self):
        backend = _seed_backend({"t1": (2, "https://a.com"), "t2": (1, "https://b.com")})

        result = await backend.switch_target("t1", generation=1)

        assert result.success is False
        assert "generation" in (result.error or "")
        assert backend._active_target_id == "t2"  # 失败时活动 tab 不变

    @pytest.mark.asyncio
    async def test_switch_unknown_target_rejected(self):
        backend = _seed_backend({"t1": (1, "https://a.com")})

        result = await backend.switch_target("ghost")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_close_target_falls_back_to_remaining_tab(self):
        backend = _seed_backend({"t1": (1, "https://a.com"), "t2": (3, "https://b.com")})

        result = await backend.close_target("t2", generation=3)

        assert result.success is True
        assert "t2" not in backend._tabs
        assert backend._active_target_id == "t1"

    @pytest.mark.asyncio
    async def test_close_target_stale_generation_rejected(self):
        backend = _seed_backend({"t1": (1, "https://a.com"), "t2": (3, "https://b.com")})

        result = await backend.close_target("t2", generation=1)

        assert result.success is False
        assert "t2" in backend._tabs


class TestGenerationFreshness:
    """navigate 递增 generation；携带过期 generation 的操作被拒绝"""

    @pytest.mark.asyncio
    async def test_navigate_bumps_generation(self):
        backend = _seed_backend({"t1": (1, "https://a.com")})

        result = await backend.navigate("https://a.com/page2")

        assert result.success is True
        assert backend._tabs["t1"]["generation"] == 2

    @pytest.mark.asyncio
    async def test_dom_snapshot_stale_generation_rejected(self):
        backend = _seed_backend({"t1": (5, "https://a.com")})

        result = await backend.dom_snapshot(generation=4)

        assert result.success is False
        assert "generation" in (result.error or "")

    @pytest.mark.asyncio
    async def test_click_role_stale_generation_rejected(self):
        backend = _seed_backend({"t1": (5, "https://a.com")})
        page = backend._tabs["t1"]["page"]

        result = await backend.click_role("button", name="x", generation=4)

        assert result.success is False
        page.get_by_role.assert_not_called()

    @pytest.mark.asyncio
    async def test_fill_role_matching_generation_passes(self):
        backend = _seed_backend({"t1": (5, "https://a.com")})

        result = await backend.fill_role("textbox", name="q", text="kw", generation=5)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_omitted_generation_skips_check(self):
        """不传 generation → 跳过校验（向后兼容）"""
        backend = _seed_backend({"t1": (5, "https://a.com")})

        result = await backend.dom_snapshot()

        assert result.success is True

    @pytest.mark.asyncio
    async def test_snapshot_result_carries_generation_for_roundtrip(self):
        """快照/操作结果必须带回当前 generation，agent 才能回传做新鲜度校验"""
        backend = _seed_backend({"t1": (5, "https://a.com")})

        snap = await backend.dom_snapshot()
        assert snap.generation == 5

        click = await backend.click_role("button", name="x")
        assert click.generation == 5

        nav = await backend.navigate("https://a.com/p2", generation=5)
        assert nav.generation == 6  # 导航后的新代数

    @pytest.mark.asyncio
    async def test_role_ops_target_active_tab(self):
        """role 操作必须作用在活动 tab 的页面上"""
        backend = _seed_backend({"t1": (1, "https://a.com"), "t2": (3, "https://b.com")})

        result = await backend.click_role("button", name="x")

        assert result.success is True
        active_page = backend._tabs["t2"]["page"]
        active_page.get_by_role.assert_called_once_with("button", name="x")


class TestLegacyCompat:
    """单 tab 既有行为保持：不传 target/generation 时一切照旧"""

    @pytest.mark.asyncio
    async def test_navigate_screenshot_flow_on_active_tab(self):
        backend = _seed_backend({"t1": (1, "https://a.com")})

        nav = await backend.navigate("https://a.com/p")
        snap = await backend.dom_snapshot()

        assert nav.success is True and snap.success is True
        assert backend._tabs["t1"]["generation"] == 2


class TestManagerTargetPassthrough:
    @pytest.mark.asyncio
    async def test_manager_target_ops_passthrough(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fb = MagicMock()
        fb.open_target = AsyncMock(return_value=BrowserResult(success=True, data={"target_id": "t9", "generation": 1}))
        fb.list_targets = AsyncMock(return_value=BrowserResult(success=True, data=[]))
        fb.switch_target = AsyncMock(return_value=BrowserResult(success=True))
        fb.close_target = AsyncMock(return_value=BrowserResult(success=True))
        mgr._get_backend = AsyncMock(return_value=fb)

        assert (await mgr.open_target(url="https://x.com")).success is True
        fb.open_target.assert_awaited_once_with("https://x.com")
        assert (await mgr.list_targets()).success is True
        assert (await mgr.switch_target("t9", generation=1)).success is True
        fb.switch_target.assert_awaited_once_with("t9", 1)
        assert (await mgr.close_target("t9", generation=1)).success is True
        fb.close_target.assert_awaited_once_with("t9", 1)

    @pytest.mark.asyncio
    async def test_manager_role_ops_pass_generation(self):
        from neurova.computer_use.browser_manager import BrowserManager

        mgr = BrowserManager(config={})
        fb = MagicMock()
        fb.dom_snapshot = AsyncMock(return_value=BrowserResult(success=True, data="tree"))
        fb.click_role = AsyncMock(return_value=BrowserResult(success=True))
        mgr._get_backend = AsyncMock(return_value=fb)

        await mgr.dom_snapshot(generation=7)
        fb.dom_snapshot.assert_awaited_once_with(7)

        await mgr.click_role("button", name="x", generation=7)
        fb.click_role.assert_awaited_once_with("button", "x", 7)
