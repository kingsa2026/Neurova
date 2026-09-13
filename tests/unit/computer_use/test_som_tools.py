"""R3-1 SOM 工具接线（som_snapshot / click_mark 经 tool_executor 分发）

验收：
- som_snapshot：截图→标注→返回 marks+暂存 id2xy，标注图推面板（不进 LLM 结果）
- click_mark：按编号解算中心坐标 → 复用像素点击链；编号过期 → stale_generation 拒
"""

from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor

# 400x300 两个分离矩形（SOM 默认检测器可检出）
import io
from PIL import Image, ImageDraw

def _png():
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 80], outline="black", width=3, fill="lightblue")
    d.rectangle([250, 180, 360, 260], outline="black", width=3, fill="lightyellow")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()


class FakeManager:
    def screenshot(self, region=None):
        return _png()


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, *a, **k):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    monkeypatch.setattr(ToolExecutor, "_emit_action_refreshed_screenshot", fake_emit)
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: FakeManager())
    return inst


class TestSomSnapshot:
    @pytest.mark.asyncio
    async def test_returns_marks_and_stores_id2xy(self, executor):
        out = await executor._execute_computer_som_snapshot({})
        assert out["success"] is True
        assert out["count"] >= 2
        assert "annotated_png_b64" not in out, "标注图不进 LLM 结果（只推面板）"
        assert out["marks"][0]["id"] in {int(k) for k in executor._last_som_id2xy}

    @pytest.mark.asyncio
    async def test_click_mark_resolves_to_click_chain(self, executor, monkeypatch):
        snap = await executor._execute_computer_som_snapshot({})
        mid = snap["marks"][0]["id"]
        cx, cy = snap["marks"][0]["center"]

        captured = {}

        def fake_click(manager, x, y, button="left"):
            captured["xy"] = (x, y)
            captured["button"] = button
            return {"success": True}

        import neurova.computer_use.actions as actions
        monkeypatch.setattr(actions, "click_screenshot_point", fake_click)
        out = await executor._execute_computer_click_mark({"index": mid})
        assert out["success"] is True
        assert captured["xy"] == (cx, cy), "编号必须解算成该区域中心坐标"
        assert out.get("action_result"), "点击走 ActionResult 诚实档"

    @pytest.mark.asyncio
    async def test_click_mark_stale_id_refused(self, executor):
        executor._last_som_id2xy = {"123": [10, 10]}
        out = await executor._execute_computer_click_mark({"index": 999})
        assert out["success"] is False
        assert out.get("refusal_code") == "stale_generation"
