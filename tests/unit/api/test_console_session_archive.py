"""会话存档/恢复端点 TDD 测试（console 层）

契约：
- POST /api/v1/console/chat/sessions/{sid}/archive    存档（替代 UI 删除）
- POST /api/v1/console/chat/sessions/{sid}/unarchive  恢复
- GET  /api/v1/console/chat/sessions/archived         存档会话列表

user_id 校验与 delete_chat_session 一致（空 user_id 视为共享）。
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app


@pytest.fixture
def app():
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def mock_repo():
    """Mock SessionRepository（patch 路径同 test_console_delete_userid_bug.py）。"""
    mock = MagicMock()
    mock.list_sessions.return_value = []
    mock.list_archived_sessions.return_value = []
    mock.archive_session.return_value = True
    mock.unarchive_session.return_value = True
    with patch("neurova.api.endpoints.console.get_session_repository", return_value=mock):
        yield mock


def _seed_normal_session(mock_repo, session_id="sess-1", agent_id="kai", user_id=""):
    mock_repo.list_sessions.return_value = [
        {
            "session_id": session_id,
            "id": session_id,
            "agent_id": agent_id,
            "title": "测试会话",
            "user_id": user_id,
            "created_at": "2026-08-29T10:00:00",
        }
    ]


class TestArchiveEndpoint:
    def test_archive_returns_200_and_calls_repo(self, client, mock_repo):
        _seed_normal_session(mock_repo)
        resp = client.post("/api/v1/console/chat/sessions/sess-1/archive")
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0
        mock_repo.archive_session.assert_called_once_with(agent_id="kai", session_id="sess-1")

    def test_archive_unknown_session_returns_404(self, client, mock_repo):
        mock_repo.list_sessions.return_value = []
        resp = client.post("/api/v1/console/chat/sessions/ghost/archive")
        assert resp.status_code == 404
        mock_repo.archive_session.assert_not_called()

    def test_archive_user_id_mismatch_returns_403(self, client, mock_repo):
        _seed_normal_session(mock_repo, user_id="alice")
        resp = client.post("/api/v1/console/chat/sessions/sess-1/archive")
        assert resp.status_code == 403
        mock_repo.archive_session.assert_not_called()

    def test_archive_repo_failure_returns_404(self, client, mock_repo):
        """repo 返回 False（文件不存在等）→ 404，不得谎报成功。"""
        _seed_normal_session(mock_repo)
        mock_repo.archive_session.return_value = False
        resp = client.post("/api/v1/console/chat/sessions/sess-1/archive")
        assert resp.status_code == 404


class TestUnarchiveEndpoint:
    def test_unarchive_returns_200_and_calls_repo(self, client, mock_repo):
        mock_repo.list_archived_sessions.return_value = [
            {
                "session_id": "sess-1",
                "id": "sess-1",
                "agent_id": "kai",
                "title": "已存档",
                "user_id": "",
                "created_at": "2026-08-29T10:00:00",
            }
        ]
        resp = client.post("/api/v1/console/chat/sessions/sess-1/unarchive")
        assert resp.status_code == 200, resp.text
        mock_repo.unarchive_session.assert_called_once_with(agent_id="kai", session_id="sess-1")

    def test_unarchive_unknown_session_returns_404(self, client, mock_repo):
        mock_repo.list_archived_sessions.return_value = []
        resp = client.post("/api/v1/console/chat/sessions/ghost/unarchive")
        assert resp.status_code == 404
        mock_repo.unarchive_session.assert_not_called()


class TestArchivedListEndpoint:
    def test_list_archived_returns_summaries(self, client, mock_repo):
        mock_repo.list_archived_sessions.return_value = [
            {
                "session_id": "sess-a",
                "id": "sess-a",
                "agent_id": "kai",
                "title": "存档一",
                "user_id": "",
                "created_at": "2026-08-29T09:00:00",
            }
        ]
        resp = client.get("/api/v1/console/chat/sessions/archived")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["total"] == 1
        assert body["data"]["sessions"][0]["id"] == "sess-a"
        mock_repo.list_archived_sessions.assert_called_once()

    def test_list_archived_passes_agent_filter(self, client, mock_repo):
        client.get("/api/v1/console/chat/sessions/archived", params={"agent_id": "kai"})
        mock_repo.list_archived_sessions.assert_called_once_with(agent_id="kai", user_id="anonymous")
