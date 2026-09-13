"""RS-2 guest agent 守护进程

验收：
- /health ok
- /action click/type/scroll/screenshot 路由到 actions.py 同一实现（逐字段结果）
- screenshot 回 png_b64 + size_bytes
- token 鉴权：配置 token 后无凭证 401、带凭证 200
- 未知 kind → 结构化 error（不抛）
- GuestAgentClient.action 正确封装 POST /action
"""

import base64

import pytest
from fastapi.testclient import TestClient

from neurova.guest_agent.client import GuestAgentClient
from neurova.guest_agent.server import create_app

FAKE_PNG = b"fake-png-bytes-1234"


class FakeManager:
    def __init__(self):
        self.clicks = []

    def screenshot(self, region=None):
        return FAKE_PNG

    def click_screenshot_point(self, x, y, button="left"):
        self.clicks.append((x, y, button))
        return True

    def type_text(self, text, interval=0.05):
        return True

    def scroll(self, x, y, v, h):
        return True

    def snapshot(self, window_title=None, max_nodes=None, max_depth=None):
        self.snap_calls = getattr(self, "snap_calls", [])
        self.snap_calls.append((window_title, max_nodes, max_depth))
        return {"success": True, "nodes": []}

    def click_element(self, index=None, runtime_id=None, window_title=None, button="left", generation=None):
        return {"success": True, "clicked": index}

    def set_value(self, value, index=None, runtime_id=None, window_title=None, generation=None):
        return {"success": True, "set": value}


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def client(mgr):
    return TestClient(create_app(manager=mgr))


class TestGuestServer:
    def test_health(self, client):
        assert client.get("/health").json()["ok"] is True

    def test_click_routes_to_actions(self, client, mgr):
        out = client.post("/action", json={"kind": "click", "params": {"x": 10, "y": 20}}).json()
        assert out["success"] is True
        assert mgr.clicks == [(10, 20, "left")]

    def test_screenshot_returns_b64(self, client):
        out = client.post("/action", json={"kind": "screenshot", "params": {}}).json()
        assert out["success"] is True
        assert out["size_bytes"] == len(FAKE_PNG)
        assert base64.b64decode(out["png_b64"]) == FAKE_PNG

    def test_type_and_scroll(self, client, mgr):
        assert client.post("/action", json={"kind": "type", "params": {"text": "hi"}}).json()["success"] is True
        assert client.post("/action", json={"kind": "scroll", "params": {"scroll_y": -3}}).json()["success"] is True

    def test_unknown_kind_structured_error(self, client):
        out = client.post("/action", json={"kind": "teleport", "params": {}}).json()
        assert "error" in out and "teleport" in out["error"]

    def test_token_required_when_configured(self, mgr):
        c = TestClient(create_app(manager=mgr, token="s3cr3t"))
        assert c.post("/action", json={"kind": "screenshot"}).status_code == 401
        ok = c.post("/action", json={"kind": "screenshot"}, headers={"Authorization": "Bearer s3cr3t"})
        assert ok.status_code == 200


class TestGuestUiaActions:
    """dom_snapshot/click_element/set_value 经注入 uia_manager（回归：方法名 snapshot 非 dom_snapshot）。"""

    def test_dom_snapshot_calls_snapshot(self):
        calls = {}

        class FakeUia:
            def snapshot(self, window_title=None, max_nodes=None, max_depth=None):
                calls["snapshot"] = (window_title, max_nodes, max_depth)
                return {"success": True, "nodes": [{"index": 1}]}

        c = TestClient(create_app(manager=FakeManager(), uia_manager=FakeUia()))
        out = c.post("/action", json={"kind": "dom_snapshot", "params": {"window_title": "记事本"}}).json()
        assert out["success"] is True
        assert calls["snapshot"] == ("记事本", None, None)

    def test_click_element_and_set_value(self):
        class FakeUia:
            def click_element(self, index=None, runtime_id=None, window_title=None, button="left", generation=None):
                return {"success": True, "clicked": index}

            def set_value(self, value, index=None, runtime_id=None, window_title=None, generation=None):
                return {"success": True, "written": value}

        c = TestClient(create_app(manager=FakeManager(), uia_manager=FakeUia()))
        assert c.post("/action", json={"kind": "click_element", "params": {"index": 3}}).json()["clicked"] == 3
        assert c.post("/action", json={"kind": "set_value", "params": {"value": "hi", "index": 2}}).json()["written"] == "hi"


class TestGuestClient:
    def test_action_wraps_post(self, monkeypatch):
        cl = GuestAgentClient("http://127.0.0.1:8765", token="t")
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"success": True, "echo": captured.get("json")}

        def fake_post(url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResp()

        monkeypatch.setattr(cl._client, "post", fake_post)
        out = cl.action("click", {"x": 1, "y": 2})
        assert captured["url"] == "/action"
        assert captured["json"] == {"kind": "click", "params": {"x": 1, "y": 2}}
        assert out["success"] is True

    def test_action_unreachable_returns_error(self, monkeypatch):
        cl = GuestAgentClient("http://127.0.0.1:1")

        def boom(*a, **k):
            raise RuntimeError("conn refused")

        monkeypatch.setattr(cl._client, "post", boom)
        out = cl.action("screenshot")
        assert "error" in out and "不可达" in out["error"]
