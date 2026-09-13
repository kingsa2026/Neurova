# -*- coding: utf-8 -*-
"""P1-2 会话时间线 API（GET /console/chat/sessions/{sid}/timeline）。

鉴权+归属校验与 history 端点同规；数据面 read_timeline 已有单测，
本文件钉 API 契约（路由存在/归属 404/limit 语义/事件透传）。
"""
import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app


@pytest.fixture()
def isolated_repo(tmp_path, monkeypatch):
    """会话存储隔离（env 是 SessionManager 单例唯一可靠覆盖通道）。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    from neurova.session_manager import SessionManager
    from neurova.session_repository import reset_session_repository

    SessionManager._instance = None
    reset_session_repository()
    yield None
    SessionManager._instance = None
    reset_session_repository()


@pytest.fixture()
def client(isolated_repo):
    from neurova.api import auth as auth_mod
    from neurova.api import deps as deps_mod

    app = create_app(enable_memory=False, enable_channels=False)
    user = {"user_id": "test_user", "username": "test_user", "role": "admin"}
    app.dependency_overrides[deps_mod.get_current_user] = lambda: user
    app.dependency_overrides[auth_mod.get_current_user] = lambda: user
    return TestClient(app)


class TestTimelineEndpoint:
    def test_timeline_roundtrip(self, client, isolated_repo):
        from neurova.session_repository import get_session_repository

        repo = get_session_repository()
        sid = repo.create_session(agent_id="a1", user_id="test_user")
        repo.append_timeline_event("a1", sid, {"type": "chunk", "content": "你好"})
        repo.append_timeline_event("a1", sid, {"type": "done", "session_id": sid})

        resp = client.get(f"/api/v1/console/chat/sessions/{sid}/timeline")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert [e["type"] for e in data["events"]] == ["chunk", "done"]

    def test_timeline_limit_returns_latest(self, client, isolated_repo):
        from neurova.session_repository import get_session_repository

        repo = get_session_repository()
        sid = repo.create_session(agent_id="a1", user_id="test_user")
        for i in range(4):
            repo.append_timeline_event("a1", sid, {"type": "chunk", "content": str(i)})

        resp = client.get(f"/api/v1/console/chat/sessions/{sid}/timeline?limit=2")
        data = resp.json()["data"]
        assert [e["content"] for e in data["events"]] == ["2", "3"]

    def test_timeline_unknown_session_404(self, client, isolated_repo):
        resp = client.get("/api/v1/console/chat/sessions/no-such-sid/timeline")
        assert resp.status_code == 404

    def test_timeline_unknown_session_no_leak(self, isolated_repo):
        """无登录态+未知会话：绝不 200 返回数据（401/403/404 皆可，按 app 鉴权形态）。"""
        app = create_app(enable_memory=False, enable_channels=False)
        client = TestClient(app)  # 无登录态
        resp = client.get("/api/v1/console/chat/sessions/x/timeline")
        assert resp.status_code in (401, 403, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
