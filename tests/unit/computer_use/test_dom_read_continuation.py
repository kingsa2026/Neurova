"""dom_read 续读测试（红→绿 TDD）—— BrowserManager 层快照正文分片续读。

语义（一代页面一份游标）：
- dom_read：走既有 dom_snapshot 观察链（任意 backend，playwright/camofox 通用），
  把快照正文按 chunk（默认 8_000，与 tool_executor LLM 面截断契约一致）分片
- 首 read：data 携带 chunk 文本 + session_id + can_continue + next_offset + generation
- 续 read：传 session_id 纯缓存切片；session 绑定 (target_id, generation)，
  活动 tab 导航/交互后 generation 递增 → stale 拒绝，引导重新 dom_read
- 不改 dom_snapshot 既有契约（API 端点 computer.py 等消费方零影响）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.computer_use.browser_manager import BrowserManager, BrowserResult
from neurova.core.read_sessions import get_read_session_store, reset_read_session_store


def _seed_manager(snapshot_tree="- button \"x\"\n- textbox \"q\"", generation=3, url="https://a.com"):
    """mock backend：显式定死 _active_target_id/_active_generation（MagicMock 自动属性
    会让 tab/generation 守卫在续读时误触发，必须钉死真实值）"""
    mgr = BrowserManager(config={})
    fb = MagicMock()
    fb._active_target_id = "tab_t1"
    fb._active_generation = MagicMock(return_value=generation)
    fb.dom_snapshot = AsyncMock(
        return_value=BrowserResult(success=True, data=snapshot_tree, url=url, generation=generation)
    )
    mgr._get_backend = AsyncMock(return_value=fb)
    return mgr, fb


@pytest.fixture(autouse=True)
def _isolate():
    reset_read_session_store()
    yield
    reset_read_session_store()


class TestDomReadFresh:
    @pytest.mark.asyncio
    async def test_first_read_returns_chunk_and_cursor(self):
        mgr, fb = _seed_manager(snapshot_tree="树" * 20_000, generation=3)

        result = await mgr.dom_read()

        assert result.success is True
        assert len(result.data["text"]) == 8_000
        assert result.data["can_continue"] is True
        assert result.data["next_offset"] == 8_000
        assert result.data["session_id"]
        assert result.data["total_length"] == 20_000
        assert result.generation == 3
        fb.dom_snapshot.assert_awaited_once()  # 走既有观察链

    @pytest.mark.asyncio
    async def test_short_snapshot_single_chunk(self):
        """短快照（未超 chunk）LLM 已拿全量——不建会话，与 browser_read 短页规则一致"""
        mgr, _ = _seed_manager(snapshot_tree="- button \"x\"", generation=1)

        result = await mgr.dom_read()

        assert result.success is True
        assert result.data["can_continue"] is False
        assert result.data["next_offset"] is None
        assert result.data["session_id"] is None
        # 未产生会话
        store = get_read_session_store()
        assert store.size() == 0

    @pytest.mark.asyncio
    async def test_snapshot_failure_propagates(self):
        mgr, fb = _seed_manager()
        fb.dom_snapshot = AsyncMock(return_value=BrowserResult(success=False, error="无活动浏览器 tab"))

        result = await mgr.dom_read()

        assert result.success is False
        assert "无活动" in result.error

    @pytest.mark.asyncio
    async def test_custom_chunk_size(self):
        mgr, _ = _seed_manager(snapshot_tree="y" * 1_000, generation=2)

        result = await mgr.dom_read(chunk_size=300)

        assert len(result.data["text"]) == 300
        assert result.data["next_offset"] == 300


class TestDomReadContinuation:
    @pytest.mark.asyncio
    async def test_continuation_without_backend_call(self):
        mgr, fb = _seed_manager(snapshot_tree="n" * 20_000, generation=3)
        first = await mgr.dom_read()
        sid = first.data["session_id"]

        fb.dom_snapshot.reset_mock()
        second = await mgr.dom_read(session_id=sid)

        fb.dom_snapshot.assert_not_awaited()  # 续读零观察开销
        assert second.success is True
        assert second.data["offset"] == 8_000
        assert len(second.data["text"]) == 8_000  # 20k 全文按 8k 分：第二片 8k
        assert second.generation == 3

    @pytest.mark.asyncio
    async def test_generation_stale_rejected(self):
        """导航/交互后 generation 递增 → 旧游标拒绝续读"""
        mgr, fb = _seed_manager(snapshot_tree="s" * 20_000, generation=5)
        first = await mgr.dom_read()
        sid = first.data["session_id"]

        # 同一 tab 上 generation 递增（navigate/交互后 5→6）
        fb._active_generation = MagicMock(return_value=6)
        result = await mgr.dom_read(session_id=sid)

        assert result.success is False
        assert result.data["stale"] is True
        assert "重新" in result.error

    @pytest.mark.asyncio
    async def test_tab_switch_rejected(self):
        """活动 tab 切换 → 会话失效（快照属于原 tab）"""
        mgr, fb = _seed_manager(snapshot_tree="s" * 20_000, generation=5)
        first = await mgr.dom_read()
        sid = first.data["session_id"]

        fb._active_target_id = "tab_other"
        result = await mgr.dom_read(session_id=sid)

        assert result.success is False
        assert result.data["stale"] is True

    @pytest.mark.asyncio
    async def test_unknown_session_rejected(self):
        mgr, _ = _seed_manager()

        result = await mgr.dom_read(session_id="rs_ghost")

        assert result.success is False
        assert "重新" in result.error

    @pytest.mark.asyncio
    async def test_backend_without_active_tab_still_rejects_continuation(self):
        """无活动 tab（backend 可能已重置）时续读必须 fail-closed 而非放行"""
        mgr, _ = _seed_manager(snapshot_tree="s" * 20_000, generation=5)
        first = await mgr.dom_read()
        sid = first.data["session_id"]

        mgr._get_backend = AsyncMock(side_effect=RuntimeError("No browser backend available"))
        result = await mgr.dom_read(session_id=sid)

        assert result.success is False
        assert result.data.get("stale") is True


class TestManagerLevelContract:
    @pytest.mark.asyncio
    async def test_result_to_dict_carries_cursor_fields(self):
        """cursor 字段必须走 to_dict() 抵达 LLM 面（_normalize_browser_result 依赖 to_dict）"""
        mgr, _ = _seed_manager(snapshot_tree="t" * 20_000, generation=4)

        result = await mgr.dom_read()
        d = result.to_dict()

        assert d["data"]["session_id"]
        assert d["data"]["can_continue"] is True
        assert d["generation"] == 4
