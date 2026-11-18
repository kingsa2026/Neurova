"""P3-9（电脑操控对照评测）：远程会话 screen_metadata 补齐。

RemoteComputerUseManager.screen_metadata() 此前恒返 None → 远程坐标链退化为
恒等（RDP 150% 缩放下 LLM 截图像素坐标直接当屏幕坐标用，点击错位）。补齐：
guest agent 暴露 screen_metadata 动作（真取来宾机元数据），宿主侧代理并缓存。
"""

import pytest

from neurova.computer_use.remote_backend import RemoteComputerUseManager

META = {
    "virtual_origin": (0, 0),
    "screen_size": (1920, 1080),
    "pixel_size": (1920, 1080),
    "scale": 1.0,
}


class TestRemoteScreenMetadata:
    def test_metadata_from_guest(self):
        class FakeClient:
            def action(self, kind, params=None):
                assert kind == "screen_metadata"
                return {"success": True, "metadata": META}

        m = RemoteComputerUseManager(FakeClient())
        assert m.screen_metadata() == META

    def test_metadata_failure_returns_none(self):
        """来宾不可达/未返回 → 诚实回 None（调用方恒等回退），不编造。"""
        class FakeClient:
            def action(self, kind, params=None):
                return {"error": "guest agent 不可达"}

        assert RemoteComputerUseManager(FakeClient()).screen_metadata() is None

    def test_metadata_cached(self):
        calls = []

        class FakeClient:
            def action(self, kind, params=None):
                calls.append(kind)
                return {"success": True, "metadata": META}

        m = RemoteComputerUseManager(FakeClient())
        m.screen_metadata()
        m.screen_metadata()
        assert len(calls) == 1, "元数据应缓存（一次真取即可，屏幕几何不会轮次变化）"

    def test_guest_agent_serves_screen_metadata(self):
        from fastapi.testclient import TestClient

        from neurova.guest_agent.server import create_app

        class StubMgr:
            def screen_metadata(self):
                return META

        app = create_app(manager=StubMgr(), uia_manager=object(), token=None)
        r = TestClient(app).post("/action", json={"kind": "screen_metadata", "params": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        got = body["metadata"]
        # JSON 往返把元组转列表——按 JSON 形态逐字段比对
        assert got["scale"] == META["scale"]
        assert list(got["virtual_origin"]) == list(META["virtual_origin"])
        assert list(got["screen_size"]) == list(META["screen_size"])
        assert list(got["pixel_size"]) == list(META["pixel_size"])
