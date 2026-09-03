"""
测试 context.py 端点的三层隔离机制

验证：
1. build_context 端点从 JWT 获取 user_id
2. build_context_v2 端点从 JWT 获取 user_id
3. ContextPool 被正确调用（带隔离参数）
4. 未认证请求返回 401
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_current_user():
    """模拟 JWT 认证用户"""
    return {"user_id": "user_123", "username": "testuser", "role": "user"}


@pytest.fixture
def mock_context_pool():
    """模拟 ContextPool 实例"""
    pool = Mock()
    pool.add_context = Mock()
    pool.build_context_for_model = Mock(return_value=[
        {"role": "user", "content": "测试输入", "source": "user_input"},
    ])
    return pool


@pytest.fixture
def app_with_isolation(mock_current_user, mock_context_pool):
    """创建带隔离的测试应用"""
    from neurova.api.endpoints.context import router, _get_context_builder
    
    app = FastAPI()
    app.include_router(router)
    
    # Mock get_current_user 依赖
    async def override_get_current_user():
        return mock_current_user
    
    # Override 依赖
    from neurova.api.auth import get_current_user
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    return app, mock_context_pool


class TestContextEndpointIsolation:
    """测试端点隔离"""

    @patch('neurova.api.endpoints.context._get_context_builder')
    def test_build_context_passes_user_id_to_context_pool(
        self, mock_get_builder, app_with_isolation, mock_context_pool
    ):
        """测试 build_context 端点将 user_id 传递给 ContextPool"""
        app, _ = app_with_isolation
        mock_get_builder.return_value = mock_context_pool
        
        client = TestClient(app)
        response = client.post("/build", json={
            "agent_id": "test_agent",
            "user_input": "你好",
        })
        
        assert response.status_code == 200
        # 验证 _get_context_builder 被调用时传入了 user_id
        mock_get_builder.assert_called_once_with(
            user_id="user_123",
            agent_id="test_agent",
            session_id=None
        )

    @patch('neurova.api.endpoints.context._get_context_builder')
    def test_build_context_v2_passes_user_id_to_context_pool(
        self, mock_get_builder, app_with_isolation, mock_context_pool
    ):
        """测试 build_context_v2 端点将 user_id 传递给 ContextPool"""
        app, _ = app_with_isolation
        mock_get_builder.return_value = mock_context_pool
        
        client = TestClient(app)
        response = client.post("/build/v2", json={
            "agent_id": "test_agent",
            "user_input": "你好",
        })
        
        assert response.status_code == 200
        # 验证 _get_context_builder 被调用时传入了 user_id
        mock_get_builder.assert_called_once_with(
            user_id="user_123",
            agent_id="test_agent",
            session_id=None
        )

    @patch('neurova.api.endpoints.context._get_context_builder')
    def test_build_context_passes_session_id(
        self, mock_get_builder, app_with_isolation, mock_context_pool
    ):
        """测试 session_id 正确传递"""
        app, _ = app_with_isolation
        mock_get_builder.return_value = mock_context_pool
        
        client = TestClient(app)
        response = client.post("/build", json={
            "agent_id": "test_agent",
            "user_input": "你好",
            "session_id": "session_456",
        })
        
        assert response.status_code == 200
        mock_get_builder.assert_called_once_with(
            user_id="user_123",
            agent_id="test_agent",
            session_id="session_456"
        )

    def test_build_context_requires_authentication(self):
        """测试未认证请求返回 401"""
        app = FastAPI()
        from neurova.api.endpoints.context import router
        app.include_router(router)
        
        client = TestClient(app)
        response = client.post("/build", json={
            "agent_id": "test_agent",
            "user_input": "你好",
        })
        
        assert response.status_code == 401

    @patch('neurova.api.endpoints.context._get_context_builder')
    def test_different_users_get_different_context_pools(
        self, mock_get_builder, mock_context_pool
    ):
        """测试不同用户获得不同的上下文池"""
        # 第一个用户
        user1 = {"user_id": "user_1", "username": "user1", "role": "user"}
        
        app1 = FastAPI()
        from neurova.api.endpoints.context import router
        app1.include_router(router)
        
        from neurova.api.auth import get_current_user
        app1.dependency_overrides[get_current_user] = lambda: user1
        
        mock_get_builder.return_value = mock_context_pool
        
        client1 = TestClient(app1)
        client1.post("/build", json={"agent_id": "agent", "user_input": "hi"})
        
        # 验证 user_1 的参数
        call_args = mock_get_builder.call_args
        assert call_args.kwargs.get("user_id") == "user_1" or call_args[1].get("user_id") == "user_1"
        
        # 第二个用户
        user2 = {"user_id": "user_2", "username": "user2", "role": "user"}
        
        app2 = FastAPI()
        app2.include_router(router)
        app2.dependency_overrides[get_current_user] = lambda: user2
        
        mock_get_builder.reset_mock()
        mock_get_builder.return_value = mock_context_pool
        
        client2 = TestClient(app2)
        client2.post("/build", json={"agent_id": "agent", "user_input": "hi"})
        
        # 验证 user_2 的参数
        call_args = mock_get_builder.call_args
        assert call_args.kwargs.get("user_id") == "user_2" or call_args[1].get("user_id") == "user_2"


class TestContextBuilderFunction:
    """测试 _get_context_builder 函数"""

    def test_get_context_builder_with_params(self):
        """测试带参数创建 ContextPool"""
        from neurova.api.endpoints.context import _get_context_builder
        
        with patch('neurova.context_pool.ContextPool') as MockPool:
            MockPool.return_value = Mock()
            builder = _get_context_builder(
                user_id="user_1",
                agent_id="agent_1",
                session_id="session_1"
            )
            MockPool.assert_called_once_with(
                user_id="user_1",
                agent_id="agent_1",
                session_id="session_1"
            )

    def test_get_context_builder_missing_user_id(self):
        """测试缺少 user_id 时使用默认值"""
        from neurova.api.endpoints.context import _get_context_builder
        
        with patch('neurova.context_pool.ContextPool') as MockPool:
            MockPool.return_value = Mock()
            builder = _get_context_builder(
                user_id=None,
                agent_id="agent_1"
            )
            MockPool.assert_called_once_with(
                user_id="default_user",
                agent_id="agent_1",
                session_id=None
            )

    def test_get_context_builder_missing_agent_id(self):
        """测试缺少 agent_id 时使用默认值"""
        from neurova.api.endpoints.context import _get_context_builder
        
        with patch('neurova.context_pool.ContextPool') as MockPool:
            MockPool.return_value = Mock()
            builder = _get_context_builder(
                user_id="user_1",
                agent_id=None
            )
            MockPool.assert_called_once_with(
                user_id="user_1",
                agent_id="default_agent",
                session_id=None
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
