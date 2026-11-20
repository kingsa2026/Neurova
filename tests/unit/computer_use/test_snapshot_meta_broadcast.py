"""AD 批可视化增强：computer_dom_snapshot 的快照质量元信息随 WS 载荷。

depth_truncated / subtree_truncated / omitted_count / drilled_from 此前只进
模型可见结果；分屏面板（ComputerUsePanel）要展示"快照被剪/骨架折叠/已下钻"，
需要这些事实经 computer_action 通道到达前端。按需出现——完整树且非骨架/下钻
的载荷不带 snapshot_meta（未超限就静）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.tool_executor import ToolExecutor


def _executor(session_id: str = "sess-snap") -> ToolExecutor:
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = session_id
    inst._agent._current_user_id = "u1"
    return inst


def _capture(broadcasted: list):
    fake = MagicMock()
    fake.register_or_create_session = MagicMock()
    fake.broadcast_event = AsyncMock(side_effect=lambda sid, ev: broadcasted.append(ev))
    return fake


def _payloads(broadcasted: list) -> list:
    return [ev.to_dict()["payload"] for ev in broadcasted]


class TestSnapshotMetaBroadcast:
    @pytest.mark.asyncio
    async def test_depth_truncated_result_carries_meta(self, monkeypatch):
        """depth 剪枝结果 → snapshot_meta（truncated/depth_truncated/实深/被切计数）。"""

        class StubUia:
            def snapshot(self, *args, **kwargs):
                return {
                    "success": True,
                    "generation": 1,
                    "window": {},
                    "elements": [
                        {"index": 0, "role": "window", "name": "w", "depth": 0},
                        {"index": 1, "role": "pane", "name": "", "depth": 1, "subtree_truncated": True},
                        {"index": 2, "role": "pane", "name": "", "depth": 1},
                    ],
                    "truncated": True,
                    "depth_truncated": True,
                    "observed_max_depth": 1,
                    "max_nodes": 400,
                    "max_depth": 1,
                }

        inst = _executor()
        monkeypatch.setattr(ToolExecutor, "_desktop_uia", lambda self: StubUia())
        broadcasted = []
        fake = _capture(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake):
            await inst._execute_builtin_tool("computer_dom_snapshot", {"max_depth": 1})

        payloads = _payloads(broadcasted)
        assert payloads, "dom_snapshot 未广播事件"
        meta = payloads[0].get("snapshot_meta")
        assert meta, "深度剪枝结果必须携带 snapshot_meta"
        assert meta["truncated"] is True
        assert meta["depth_truncated"] is True
        assert meta["observed_max_depth"] == 1
        assert meta["subtree_truncated_count"] == 1

    @pytest.mark.asyncio
    async def test_skeleton_meta_carries_omitted_and_drill(self, monkeypatch):
        """骨架/下钻信息随行：omitted_count 与 drilled_from 原样透传。"""

        class StubUia:
            def snapshot(self, *args, **kwargs):
                return {
                    "success": True,
                    "generation": 1,
                    "window": {},
                    "elements": [],
                    "truncated": False,
                    "skeleton": True,
                    "omitted_count": 76,
                    "drilled_from": {"index": 3, "runtime_id": "42.1"},
                    "max_nodes": 400,
                    "max_depth": 32,
                }

        inst = _executor()
        monkeypatch.setattr(ToolExecutor, "_desktop_uia", lambda self: StubUia())
        broadcasted = []
        fake = _capture(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake):
            await inst._execute_builtin_tool(
                "computer_dom_snapshot", {"skeleton": True, "root_index": 3}
            )

        meta = _payloads(broadcasted)[0]["snapshot_meta"]
        assert meta["skeleton"] is True
        assert meta["omitted_count"] == 76
        assert meta["drilled_from"] == {"index": 3, "runtime_id": "42.1"}

    @pytest.mark.asyncio
    async def test_clean_snapshot_has_no_meta(self, monkeypatch):
        """未超限就静：完整树且非骨架/下钻 → 载荷不带 snapshot_meta。"""

        class StubUia:
            def snapshot(self, *args, **kwargs):
                return {
                    "success": True,
                    "generation": 1,
                    "window": {},
                    "elements": [{"index": 0, "role": "window", "name": "w", "depth": 0}],
                    "truncated": False,
                    "max_nodes": 400,
                    "max_depth": 32,
                }

        inst = _executor()
        monkeypatch.setattr(ToolExecutor, "_desktop_uia", lambda self: StubUia())
        broadcasted = []
        fake = _capture(broadcasted)

        with patch("neurova.sync.session_sync_manager.get_session_sync_manager", return_value=fake):
            await inst._execute_builtin_tool("computer_dom_snapshot", {})

        assert "snapshot_meta" not in _payloads(broadcasted)[0]
