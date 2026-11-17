"""P1-1（ZCode 电脑操控对照评测）：桌面帧权威——坐标必须对最近观测帧负责。

ZCode CUA 的核心纪律：模型只能对"刚看过的那一帧"下坐标，画面一变帧即失效，
陈旧帧 fail-closed（强制先重新观察）。Neurova 此前像素点击路径没有这层约束——
模型可凭早已过期的截图坐标盲点。本文件钉：观测发 frame_id → 新观测替代旧帧 →
变更动作失效帧 → click/click_mark 携带 frame_id 时校验新鲜度，过期返回
stale_frame（retry=reobserve）。frame_id 省略时保持既有行为（向后兼容：
REST/用户口述坐标路径不受影响）。

注：不把"截图 base64 是否进模型"当新鲜度门槛——Neurova 的观测事实
（SOM marks/屏幕元数据）以文本随工具结果必达模型，像素图走感知门按需附；
帧权威管的是"事实是否仍然新鲜"，不是"图有没有进上下文"。
"""

from unittest.mock import MagicMock

import pytest

from neurova.computer_use import frame_registry
from neurova.tool_executor import ToolExecutor

FAKE_PNG = b"fake-png-bytes"


def _real_png():
    """真 PNG（SOM 检测器要 PIL 解码；空白图 → 零标注，不影响 frame_id 断言）。"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
    return buf.getvalue()


class FakeManager:
    def __init__(self, png: bytes = FAKE_PNG):
        self._png = png

    def screenshot(self, region=None):
        return self._png

    def screen_metadata(self):
        return {
            "virtual_origin": (0, 0),
            "screen_size": (1280, 720),
            "pixel_size": (1280, 720),
            "scale": 1.0,
        }


@pytest.fixture
def executor(monkeypatch):
    frame_registry.resetForTest()
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, *args, **kwargs):
        return None

    async def fake_refresh(self, *args, **kwargs):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    monkeypatch.setattr(ToolExecutor, "_emit_action_refreshed_screenshot", fake_refresh)
    yield inst
    frame_registry.resetForTest()


class TestFrameRegistry:
    def test_issue_and_check_fresh(self):
        key = "s1"
        fid = frame_registry.issueFrame(key, {"scale": 1.0})
        ok, why = frame_registry.checkFresh(key, fid)
        assert ok is True and why == ""

    def test_new_observation_replaces_old_frame(self):
        key = "s1"
        f1 = frame_registry.issueFrame(key)
        f2 = frame_registry.issueFrame(key)
        assert f1 != f2
        ok, why = frame_registry.checkFresh(key, f1)
        assert ok is False and why == "stale_frame"

    def test_mutation_invalidates(self):
        key = "s1"
        fid = frame_registry.issueFrame(key)
        frame_registry.invalidateFrame(key)
        ok, why = frame_registry.checkFresh(key, fid)
        assert ok is False and why == "stale_frame"

    def test_unknown_frame_rejected(self):
        frame_registry.issueFrame("s1")
        ok, why = frame_registry.checkFresh("s1", "f-nowhere")
        assert ok is False and why == "stale_frame"

    def test_sessions_isolated(self):
        f1 = frame_registry.issueFrame("s1")
        ok, _ = frame_registry.checkFresh("s2", f1)
        assert ok is False, "他会话的帧不得在本会话通过校验"

    def test_store_bounded(self):
        for i in range(200):
            frame_registry.issueFrame(f"s{i}")
        assert frame_registry._latestBySession("s199") is not None
        assert frame_registry._latestBySession("s0") is None, "超界的旧会话帧应被逐出"


class TestObservationIssuesFrame:
    @pytest.mark.asyncio
    async def test_screenshot_carries_frame_id(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager()
        )
        result = await executor._execute_computer_screenshot({})
        assert result["success"] is True
        assert result.get("frame_id"), "截图结果必须携带 frame_id"

    @pytest.mark.asyncio
    async def test_som_snapshot_carries_frame_id(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager(png=_real_png())
        )
        result = await executor._execute_computer_som_snapshot({})
        assert result["success"] is True
        assert result.get("frame_id"), "SOM 快照结果必须携带 frame_id"


class TestClickFrameCheck:
    @pytest.mark.asyncio
    async def _click(self, executor, monkeypatch, params):
        hit = {}

        def fake_click(manager, x, y, button="left"):
            hit["ran"] = True
            return {"success": True, "x": x, "y": y}

        monkeypatch.setattr(
            "neurova.computer_use.actions.click_screenshot_point", fake_click
        )
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager()
        )
        out = await executor._execute_computer_click(params)
        return out, hit

    @pytest.mark.asyncio
    async def test_click_without_frame_id_proceeds(self, executor, monkeypatch):
        """向后兼容：不带 frame_id 的点击（REST/用户口述坐标）行为不变。"""
        out, hit = await self._click(executor, monkeypatch, {"x": 10, "y": 20})
        assert out["success"] is True and hit.get("ran")

    @pytest.mark.asyncio
    async def test_click_with_fresh_frame_proceeds(self, executor, monkeypatch):
        fid = frame_registry.issueFrame(executor._somSessionKey())
        out, hit = await self._click(executor, monkeypatch, {"x": 10, "y": 20, "frame_id": fid})
        assert out["success"] is True and hit.get("ran")

    @pytest.mark.asyncio
    async def test_click_with_stale_frame_refused(self, executor, monkeypatch):
        """陈旧帧 fail-closed：强制先重新观察，建议 reobserve，不触碰输入设备。"""
        fid = frame_registry.issueFrame(executor._somSessionKey())
        frame_registry.invalidateFrame(executor._somSessionKey())
        out, hit = await self._click(executor, monkeypatch, {"x": 10, "y": 20, "frame_id": fid})
        assert hit.get("ran") is None, "陈旧帧点击不得落到输入设备"
        assert out["success"] is False
        assert out.get("action_result", {}).get("refusal_code") == "stale_frame"
        assert out.get("action_result", {}).get("retry") == "reobserve"

    @pytest.mark.asyncio
    async def test_mutation_invalidates_frame_for_next_click(self, executor, monkeypatch):
        """动作成功即失效帧：第二次凭同一帧的点击被拒（观察-动作-再观察纪律）。"""
        fid = frame_registry.issueFrame(executor._somSessionKey())
        out1, _ = await self._click(executor, monkeypatch, {"x": 10, "y": 20, "frame_id": fid})
        assert out1["success"] is True
        out2, hit2 = await self._click(executor, monkeypatch, {"x": 10, "y": 20, "frame_id": fid})
        assert out2["success"] is False
        assert out2.get("action_result", {}).get("refusal_code") == "stale_frame"
        assert hit2.get("ran") is None


class TestClickMarkFrameCheck:
    @pytest.mark.asyncio
    async def test_click_mark_honors_frame_check(self, executor, monkeypatch):
        executor._rememberSomMarks({"7": [100, 200]})
        fid = frame_registry.issueFrame(executor._somSessionKey())
        frame_registry.invalidateFrame(executor._somSessionKey())

        def fake_click(manager, x, y, button="left"):
            return {"success": True, "x": x, "y": y}

        monkeypatch.setattr(
            "neurova.computer_use.actions.click_screenshot_point", fake_click
        )
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager", lambda: FakeManager()
        )
        out = await executor._execute_computer_click_mark({"index": 7, "frame_id": fid})
        assert out["success"] is False
        assert out.get("action_result", {}).get("refusal_code") == "stale_frame"
