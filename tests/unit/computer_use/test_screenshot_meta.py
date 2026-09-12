"""computer_screenshot 结果信息量修复（真机问题：盲截图循环）

病根（修复前）：截图结果只回 size_bytes——LLM 从截图一无所获，为拿 DPI
等信息去跑 reg query（还被 cmd 单引号坑），反复截图形成盲循环。

验收：
- 结果携带 screen 元数据（宽高/scale/虚拟屏原点，来自 R0-2 坐标链）
- 结果带引导文案：UI 元素事实走 computer_dom_snapshot
- screen_metadata 异常时不影响截图主结果
"""

from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor

FAKE_PNG = b"fake-png-bytes"


class FakeManager:
    """screenshot 与 screen_metadata 故障解耦（真实契约：两者独立，元数据可单独挂）"""

    def __init__(self, meta=None, broken=False, meta_broken=False):
        self._meta = meta
        self._broken = broken
        self._meta_broken = meta_broken

    def screenshot(self, region=None):
        if self._broken:
            raise RuntimeError("no screen")
        return FAKE_PNG

    def screen_metadata(self):
        if self._meta_broken:
            raise RuntimeError("boom")
        return self._meta


META = {
    "virtual_origin": (0, 0),
    "screen_size": (1280, 720),
    "pixel_size": (1920, 1080),
    "scale": 1.5,
}


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, *args, **kwargs):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    return inst


class TestScreenshotMeta:
    @pytest.mark.asyncio
    async def test_result_carries_screen_metadata(self, executor, monkeypatch):
        """150% 缩放环境：agent 直接从截图结果拿到 DPI 事实，无需 reg query"""
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager",
            lambda: FakeManager(meta=META),
        )
        result = await executor._execute_computer_screenshot({})
        assert result["success"] is True
        assert result["screen"] == {
            "width": 1920,
            "height": 1080,
            "scale": 1.5,
            "virtual_origin": [0, 0],
        }
        assert "computer_dom_snapshot" in result["note"], "引导走向语义快照"

    @pytest.mark.asyncio
    async def test_metadata_failure_keeps_screenshot_result(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager",
            lambda: FakeManager(meta_broken=True),
        )
        result = await executor._execute_computer_screenshot({})
        assert result["success"] is True
        assert result["size_bytes"] == len(FAKE_PNG)
        assert "screen" not in result

    @pytest.mark.asyncio
    async def test_no_metadata_no_screen_key(self, executor, monkeypatch):
        monkeypatch.setattr(
            "neurova.computer_use.get_computer_use_manager",
            lambda: FakeManager(meta=None),
        )
        result = await executor._execute_computer_screenshot({})
        assert result["success"] is True
        assert "screen" not in result
