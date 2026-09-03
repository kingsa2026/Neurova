"""
测试聊天会话 API 处理空 agent_id 的情况

问题：前端调用 GET /api/v1/chat/sessions?agent_id= 返回 404
根因：get_agent_instance("") 返回 None，导致 _get_agent("") 返回 None
修复：get_agent_instance 空字符串时使用默认值 "default"

注意：Tests that hit actual endpoints must handle two layers:
  1. Authentication: FastAPI Depends(get_current_user) resolved at import time,
     must use app.dependency_overrides (not patch) to override.
  2. Agent resolution: get_agent_instance reads from _app_state module-level var.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints.chat import router


@pytest.fixture
def mock_agent():
    """创建模拟的 Agent"""
    agent = MagicMock()
    agent.get_sessions.return_value = [
        {"id": "session-1", "title": "Test Session 1"},
        {"id": "session-2", "title": "Test Session 2"},
    ]
    return agent


@pytest.fixture
def app_client(mock_agent):
    """创建测试客户端，正确覆盖认证和 Agent 状态"""
    app = FastAPI()
    app.include_router(router, prefix="/chat")

    # 使用 dependency_overrides 覆盖 FastAPI Depends 注入
    async def _mock_get_current_user(request: Request):
        return {"user_id": "test-user", "role": "admin"}

    app.dependency_overrides[get_current_user] = _mock_get_current_user

    # 设置 _app_state 使 get_agent_instance 能找到 agents
    agents = {
        "default": mock_agent,
        "agent-1": mock_agent,
    }
    app_state = {"agents": agents}

    with patch("neurova.api.endpoints._app_state", app_state):
        client = TestClient(app)
        yield client

    app.dependency_overrides.clear()


@pytest.mark.skip(
    reason="D4 (ADR 0008 候选 #7) 落地:chat.py 中 /sessions 端点已删除,"
    "前端已迁移到 /api/v1/console/chat/sessions (console.py + SessionRepository)."
    "测试期望的端点路径已不存在,设计方向分歧 — 详见 docs/adr/0008-session-repository.md"
)
class TestEmptyAgentId:
    """测试空 agent_id 的情况

    OBSOLETE (D4 设计方向分歧):
        原测试期望 GET /chat/sessions?agent_id=... 返回 200,
        但 D4 删除了 chat.py 的 4 个 /sessions 死端点.
        HTTP 端点级覆盖在 tests/unit/test_console_session_repository.py
        (验证 console.py 的 /chat/sessions 端点接入 SessionRepository).
        单元级 get_agent_instance 边界覆盖在本文件 TestGetAgentInstance 类保留.
    """

    def test_get_sessions_with_empty_agent_id(self, app_client):
        """测试 GET /chat/sessions?agent_id= 应该使用默认 agent"""
        response = app_client.get("/chat/sessions?agent_id=")

        # 应该返回 200，而不是 404
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "sessions" in data["data"]

    def test_get_sessions_with_no_agent_id(self, app_client):
        """测试 GET /chat/sessions（无 agent_id 参数）应该使用默认 agent"""
        response = app_client.get("/chat/sessions")

        # 应该返回 200
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_get_sessions_with_valid_agent_id(self, app_client):
        """测试 GET /chat/sessions?agent_id=agent-1 应该正常工作"""
        response = app_client.get("/chat/sessions?agent_id=agent-1")

        # 应该返回 200
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    def test_get_sessions_with_invalid_agent_id(self, app_client):
        """测试 GET /chat/sessions?agent_id=invalid 应该返回 404"""
        response = app_client.get("/chat/sessions?agent_id=invalid")

        # 应该返回 404
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == 3000


class TestGetAgentInstance:
    """测试 get_agent_instance 函数"""
    
    def test_get_agent_instance_with_empty_string(self):
        """测试 get_agent_instance('') 应该返回默认 agent"""
        from neurova.api.endpoints import get_agent_instance
        
        # 模拟 _app_state
        mock_agent = MagicMock()
        app_state = {
            "agents": {"default": mock_agent}
        }
        
        with patch("neurova.api.endpoints._app_state", app_state):
            result = get_agent_instance("")
            
            # 应该返回默认 agent
            assert result == mock_agent
    
    def test_get_agent_instance_with_none(self):
        """测试 get_agent_instance(None) 应该返回默认 agent"""
        from neurova.api.endpoints import get_agent_instance
        
        # 模拟 _app_state
        mock_agent = MagicMock()
        app_state = {
            "agents": {"default": mock_agent}
        }
        
        with patch("neurova.api.endpoints._app_state", app_state):
            result = get_agent_instance(None)
            
            # 应该返回默认 agent
            assert result == mock_agent
    
    def test_get_agent_instance_with_valid_id(self):
        """测试 get_agent_instance('agent-1') 应该返回对应 agent"""
        from neurova.api.endpoints import get_agent_instance
        
        # 模拟 _app_state
        mock_agent = MagicMock()
        app_state = {
            "agents": {"agent-1": mock_agent}
        }
        
        with patch("neurova.api.endpoints._app_state", app_state):
            result = get_agent_instance("agent-1")
            
            # 应该返回对应 agent
            assert result == mock_agent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])