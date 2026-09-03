"""
TDD: 记忆管理端点 agent_wide 透传锁定

记忆页按 agent 隔离: 列表/统计/高温/固化/删除端点必须透传
agent_wide=True(基集=agent 全量), 使登录用户 scope 不再把
归属其他用户域的记忆从管理页抹掉。聊天检索不走这些端点。
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory.crud import router
from neurova.api.auth import get_current_user_or_default

BASE = "/api/v1/memory"


@pytest.fixture
def mock_manager():
    mm = MagicMock()
    mm.recall.return_value = []
    mm.get_stats.return_value = {"total_memories": 0}
    mm.get_hot_memories.return_value = []
    mm.get_crystallized.return_value = []
    mm.forget.return_value = True
    return mm


@pytest.fixture
def app_client(mock_manager):
    app = FastAPI()
    with patch("neurova.api.endpoints.memory.crud.get_memory_manager", return_value=mock_manager):
        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user_or_default] = lambda: {
            "user_id": "7",
            "neuser_id": "7",
            "role": "user",
        }
        client = TestClient(app)
        yield client


class TestAgentWidePassthrough:
    def test_list_passes_agent_wide(self, app_client, mock_manager):
        resp = app_client.get(f"{BASE}", params={"agent_id": "default"})
        assert resp.status_code == 200
        mock_manager.recall.assert_called_once()
        assert mock_manager.recall.call_args.kwargs.get("agent_wide") is True

    def test_stats_passes_agent_wide(self, app_client, mock_manager):
        resp = app_client.get(f"{BASE}/stats", params={"agent_id": "default"})
        assert resp.status_code == 200
        assert mock_manager.get_stats.call_args.kwargs.get("agent_wide") is True

    def test_hot_passes_agent_wide(self, app_client, mock_manager):
        resp = app_client.get(f"{BASE}/hot", params={"agent_id": "default"})
        assert resp.status_code == 200
        assert mock_manager.get_hot_memories.call_args.kwargs.get("agent_wide") is True

    def test_crystallized_passes_agent_wide(self, app_client, mock_manager):
        resp = app_client.get(f"{BASE}/crystallized", params={"agent_id": "default"})
        assert resp.status_code == 200
        assert mock_manager.get_crystallized.call_args.kwargs.get("agent_wide") is True

    def test_delete_passes_agent_wide(self, app_client, mock_manager):
        resp = app_client.delete(f"{BASE}/mem_x", params={"agent_id": "default"})
        assert resp.status_code == 200
        assert mock_manager.forget.call_args.kwargs.get("agent_wide") is True
