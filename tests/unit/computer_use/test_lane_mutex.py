# -*- coding: utf-8 -*-
"""护栏三招之车道互斥（实施计划项 8）红灯测试。

- desktop 与 browser:<session> 两把容量 1 锁，需要前台窗口的桌面动作与浏览器动作互斥
- 任一侧存在 unknown 结果（本地标记或 tool_call_journal 同工具 unknown）时对侧拒绝
- 接线：actions.* 桌面前台动作体 与 BrowserManager.navigate 双侧互拒
"""

import pytest

from neurova.computer_use import actions
from neurova.computer_use.browser_manager import BrowserManager, BrowserResult
from neurova.computer_use.lane_mutex import (
    LaneMutex,
    LaneRefusal,
    get_lane_mutex,
    reset_lane_mutex,
)


@pytest.fixture(autouse=True)
def laneClean(tmp_path, monkeypatch):
    # journal 判据收在临时库：车道测试不触碰真实数据根（hermetic）
    monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "lane_journal.db"))
    from neurova.core.tool_call_journal import reset_tool_call_journal

    reset_tool_call_journal()
    reset_lane_mutex()
    yield
    reset_lane_mutex()
    reset_tool_call_journal()


class StubBackend:
    """桩后端：记录 navigate 调用。"""

    def __init__(self, current_url: str = "https://portal.example.com/inbox"):
        self._initialized = True
        self._url = current_url
        self.navigateCalls: list = []

    async def navigate(self, url, generation=None):
        self.navigateCalls.append(url)
        self._url = url
        return BrowserResult(success=True, url=url, generation=1)

    def currentUrl(self):
        return self._url


class TestLaneMutex:
    def test_desktop_blocks_browser(self):
        lm = LaneMutex()
        with lm.hold("desktop"):
            with pytest.raises(LaneRefusal) as ei:
                with lm.hold("browser:s1"):
                    pass
            assert ei.value.code == "lane_busy"

    def test_browser_blocks_desktop(self):
        lm = LaneMutex()
        with lm.hold("browser:s1"):
            with pytest.raises(LaneRefusal) as ei:
                with lm.hold("desktop"):
                    pass
            assert ei.value.code == "lane_busy"

    def test_same_lane_capacity_one(self):
        lm = LaneMutex()
        with lm.hold("desktop"):
            with pytest.raises(LaneRefusal):
                with lm.hold("desktop"):
                    pass

    def test_release_reopens_other_lane(self):
        lm = LaneMutex()
        with lm.hold("desktop"):
            pass
        with lm.hold("browser:s1"):
            pass  # 释放后对侧可进

    def test_browser_sessions_independent(self):
        lm = LaneMutex()
        with lm.hold("browser:s1"):
            with lm.hold("browser:s2"):
                pass  # 不同浏览器会话互不阻塞

    def test_unknown_marker_rejects_opposite_lane(self):
        lm = LaneMutex()
        lm.markUnknown("desktop")
        with pytest.raises(LaneRefusal) as ei:
            with lm.hold("browser:s1"):
                pass
        assert ei.value.code == "lane_unknown"
        lm.clearUnknown("desktop")
        with lm.hold("browser:s1"):
            pass  # 标记清除后放行

    def test_unknown_marker_on_browser_rejects_desktop(self):
        lm = LaneMutex()
        lm.markUnknown("browser:s1")
        with pytest.raises(LaneRefusal) as ei:
            with lm.hold("desktop"):
                pass
        assert ei.value.code == "lane_unknown"

    def test_singleton_is_shared(self):
        assert get_lane_mutex() is get_lane_mutex()


class TestJournalUnknownBlocksLane:
    def test_unknown_browser_tool_blocks_desktop_in_same_scope(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "journal.db"))
        from neurova.core.tool_call_journal import (
            get_tool_call_journal,
            reset_tool_call_journal,
        )

        reset_tool_call_journal()
        try:
            journal = get_tool_call_journal()
            entry, claimed = journal.begin(
                "k-nav-1", "browser_navigate", scope="u1:s1", owner="call-nav-1"
            )
            assert claimed is True
            journal.settle(entry.id, "unknown", error_class="timeout", owner="call-nav-1")
            lm = LaneMutex()
            with pytest.raises(LaneRefusal) as ei:
                with lm.hold("desktop", scope="u1:s1"):
                    pass
            assert ei.value.code == "lane_unknown"
            # 其它会话不受这笔 unknown 影响
            with lm.hold("desktop", scope="u1:s2"):
                pass
        finally:
            reset_tool_call_journal()

    def test_unknown_desktop_tool_blocks_browser_in_same_scope(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "journal.db"))
        from neurova.core.tool_call_journal import (
            get_tool_call_journal,
            reset_tool_call_journal,
        )

        reset_tool_call_journal()
        try:
            journal = get_tool_call_journal()
            entry, claimed = journal.begin(
                "k-click-1", "computer_click", scope="u1:s1", owner="call-click-1"
            )
            assert claimed is True
            journal.settle(entry.id, "unknown", error_class="timeout", owner="call-click-1")
            lm = LaneMutex()
            with pytest.raises(LaneRefusal) as ei:
                with lm.hold("browser:s1", scope="u1:s1"):
                    pass
            assert ei.value.code == "lane_unknown"
        finally:
            reset_tool_call_journal()

    def test_settled_journal_does_not_block(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "journal.db"))
        from neurova.core.tool_call_journal import (
            get_tool_call_journal,
            reset_tool_call_journal,
        )

        reset_tool_call_journal()
        try:
            journal = get_tool_call_journal()
            entry, claimed = journal.begin(
                "k-ok-1", "browser_navigate", scope="u1:s1", owner="call-ok-1"
            )
            assert claimed is True
            journal.settle(entry.id, "succeeded", result_json="{}", owner="call-ok-1")
            lm = LaneMutex()
            with lm.hold("desktop", scope="u1:s1"):
                pass  # 已收敛的账目不阻塞
        finally:
            reset_tool_call_journal()


class TestLaneWiring:
    @pytest.mark.asyncio
    async def test_desktop_click_refused_while_browser_lane_held(self):
        calls = []

        class StubMgr:
            def click_screenshot_point(self, x, y, button="left"):
                calls.append((x, y))
                return True

        with get_lane_mutex().hold("browser:s1"):
            result = actions.click_screenshot_point(StubMgr(), 10, 20)
        assert calls == [], "浏览器车道占用时桌面点击必须 0 执行"
        assert result.get("success") is False
        assert result["guardrail"]["code"] == "lane_busy"

    @pytest.mark.asyncio
    async def test_browser_navigation_refused_while_desktop_lane_held(self):
        bm = BrowserManager(config={})
        stub = StubBackend()
        bm._backends["playwright"] = stub
        bm._active_backend = stub
        with get_lane_mutex().hold("desktop"):
            result = await bm.navigate("https://app.example.com/page2")
        assert stub.navigateCalls == [], "桌面车道占用时浏览器导航必须 0 执行"
        assert result.success is False
        assert result.data["guardrail"]["code"] == "lane_busy"

    @pytest.mark.asyncio
    async def test_desktop_click_runs_when_lanes_free(self):
        calls = []

        class StubMgr:
            def click_screenshot_point(self, x, y, button="left"):
                calls.append((x, y))
                return True

        result = actions.click_screenshot_point(StubMgr(), 10, 20)
        assert calls == [(10, 20)]
        assert result.get("success") is True
