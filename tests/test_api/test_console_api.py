"""
Web Console API 单元测试

测试覆盖:
1. TaskTracker 任务追踪器
2. 聊天接口
3. 文件上传接口
4. 调试接口
5. WebSocket 接口
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from neurova.core.task_tracker import get_task_tracker


def _make_ws_token():
    from neurova.api.auth import create_access_token
    return create_access_token({'user_id': 'test_user', 'sub': 'test_user', 'role': 'user'})

from neurova.api.app import create_app

def _authed_client(app):
    """统一注入登录态（admin 角色——console debug 面需管理员）。

    残留处理 2026-09-13：这些 root ad-hoc 用例写于 console 面未收鉴权
    时期；路径/鉴权契约迁移后统一补 auth 替身（两模块各有 get_current_user，
    全部覆盖）。"""
    from fastapi.testclient import TestClient
    from neurova.api import auth as auth_mod
    from neurova.api import deps as deps_mod

    user = {"user_id": "test_user", "username": "test_user", "role": "admin"}
    app.dependency_overrides[deps_mod.get_current_user] = lambda: user
    app.dependency_overrides[auth_mod.get_current_user] = lambda: user
    return TestClient(app)




# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def app():
    """创建测试应用"""
    return create_app(
        enable_memory=False,
        enable_channels=False,
    )


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return _authed_client(app)


@pytest.fixture
def tracker():
    """创建任务追踪器实例"""
    return TaskTracker()


@pytest.fixture
def sample_metadata():
    """示例元数据"""
    return {
        "user_id": "test_user",
        "session_id": "test_session",
        "type": "chat",
    }


class TestTaskTrackerSingleton:
    """全局单例（同步路径删除后仅存的使用面）"""

    def test_get_task_tracker_singleton(self):
        tracker1 = get_task_tracker()
        tracker2 = get_task_tracker()
        assert tracker1 is tracker2


# ============================================================
# Web Console API 测试
# ============================================================

class TestConsoleAPI:
    """Web Console API 测试类"""
    
    def test_chat_endpoint(self, client):
        """测试聊天接口"""
        response = client.post(
            "/api/v1/console/chat",
            json={
                "message": "Hello, Neurova!",
                "session_id": "test_session",
                "stream": True,
            },
        )
        
        # 检查是否是 SSE 响应
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
    
    def test_chat_stop_endpoint(self, client):
        """停止聊天接口（现行 session 面契约）。

        残留处理 2026-09-13：原用例基于 B-11/B-12 已删的同步任务 API
        （start_tracking/?task_id=），迁移到现行 /chat/stop?session_id= 面——
        无运行任务时诚实返回 stopped=False 而非 404。"""
        response = client.post("/api/v1/console/chat/stop?session_id=stop_test_session")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["stopped"] is False
    
    def test_chat_history_endpoint(self, client):
        """获取聊天历史（现行契约：信封 {code,data:{messages,session_id}}；
        未知会话 404——归属校验收口，先建会话再查）。残留处理 2026-09-13"""
        sid = client.post("/api/v1/console/chat/new", json={}).json()["data"]["session_id"]
        response = client.get(f"/api/v1/console/chat/history?session_id={sid}&limit=10")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["session_id"] == sid
        assert isinstance(data["messages"], list)
        # 未知会话诚实 404（不得伪装空历史）
        assert client.get("/api/v1/console/chat/history?session_id=no_such_session").status_code == 404
    
    def test_chat_new_endpoint(self, client):
        """测试创建新会话接口"""
        response = client.post(
            "/api/v1/console/chat/new",
            json={
                "user_id": "test_user",
                "metadata": {"source": "test"},
            },
        )
        
        assert response.status_code == 200
        # 信封 {code,message,data:{session_id}}（统一响应面）
        data = response.json()["data"]
        assert "session_id" in data
    
    def test_chat_sessions_endpoint(self, client):
        """测试获取会话列表接口"""
        response = client.get("/api/v1/console/chat/sessions")
        
        assert response.status_code == 200
        # 用户维度以 JWT 身份为准（S3 隔离收口），响应在 data 信封内
        data = response.json()["data"]
        assert "sessions" in data
        assert "total" in data
    
    def test_upload_endpoint(self, client, tmp_path):
        """测试文件上传接口"""
        # 创建测试文件
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, Neurova!")
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/api/v1/console/upload",
                files={"file": ("test.txt", f, "text/plain")},
            )
        
        assert response.status_code == 200
        # 信封 + 现行键名 filename（非 file_name）；残留处理 2026-09-13
        data = response.json()["data"]
        assert "file_id" in data
        assert "filename" in data
        assert data["size"] > 0
    
    def test_upload_list_endpoint(self, client):
        """测试获取上传文件列表接口"""
        response = client.get("/api/v1/console/uploads?limit=10&offset=0")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "files" in data
        assert "total" in data
    
    def test_debug_logs_endpoint(self, client):
        """后端日志（现行契约：admin 门禁 + data={content,lines}；
        ENABLE_DEBUG_ENDPOINT env 门禁已被 require_admin 收口取代）。残留处理 2026-09-13"""
        response = client.get("/api/v1/console/debug/logs?lines=50")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "content" in data
        assert data["lines"] == 50
    
    def test_debug_logs_endpoint_denied_for_non_admin(self, client):
        """非管理员访问 debug 面 403（现行鉴权契约）。残留处理 2026-09-13：
        原用例基于已删的 ENABLE_DEBUG_ENDPOINT 门禁。"""
        from neurova.api import deps as deps_mod

        plain = {"user_id": "plain", "username": "plain", "role": "user"}
        client.app.dependency_overrides[deps_mod.get_current_user] = lambda: plain
        try:
            assert client.get("/api/v1/console/debug/logs?lines=50").status_code == 403
        finally:
            client.app.dependency_overrides.pop(deps_mod.get_current_user, None)
    
    def test_debug_system_status_endpoint(self, client):
        """系统状态（现行 data 面：资源水位）。残留处理 2026-09-13：
        原 status/version/tasks 键随 debug 面收口改为资源指标。"""
        response = client.get("/api/v1/console/debug/status")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "cpu_percent" in data
        assert "uptime_seconds" in data
    
    def test_debug_status_denied_for_non_admin(self, client):
        """非管理员访问 debug status 403（现行鉴权契约）。"""
        from neurova.api import deps as deps_mod

        plain = {"user_id": "plain", "username": "plain", "role": "user"}
        client.app.dependency_overrides[deps_mod.get_current_user] = lambda: plain
        try:
            assert client.get("/api/v1/console/debug/status").status_code == 403
        finally:
            client.app.dependency_overrides.pop(deps_mod.get_current_user, None)
    
    def test_websocket_endpoint(self, client):
        """测试 WebSocket 接口"""
        with client.websocket_connect(f"/api/v1/console/ws/test-client?token={_make_ws_token()}") as websocket:
            # 发送 ping
            websocket.send_text(json.dumps({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
            
            # 接收 pong（现行协议键="type"；subscribe 面不存在，未知类型回 ack）
            data = json.loads(websocket.receive_text())
            assert data["type"] == "pong"

            websocket.send_text(json.dumps({"type": "whatever"}))
            data = json.loads(websocket.receive_text())
            assert data["type"] == "ack"


# ============================================================
# 集成测试
# ============================================================

class TestIntegration:
    """集成测试"""
    
    def test_chat_and_stop_workflow(self, client):
        """测试完整的聊天和停止工作流"""
        # 1. 创建新会话
        new_session_resp = client.post("/api/v1/console/chat/new")
        assert new_session_resp.status_code == 200
        session_id = new_session_resp.json()["data"]["session_id"]
        
        # 2. 发送聊天请求（非流式，以便测试）
        # 注意：实际 SSE 响应需要特殊处理，这里只测试接口是否可用
        chat_resp = client.post(
            "/api/v1/console/chat",
            json={
                "message": "Integration test message",
                "session_id": session_id,
                "stream": False,
            },
        )
        # 即使返回 SSE 流，也应该成功（200）
        assert chat_resp.status_code == 200

        # 3. 停止（现行 session 面：无运行任务诚实 stopped=False，不 404）
        stop_resp = client.post(f"/api/v1/console/chat/stop?session_id={session_id}")
        assert stop_resp.status_code == 200
        assert stop_resp.json()["data"]["stopped"] is False

    def test_task_lifecycle(self):
        """任务登记→运行→停止生命周期（现行 task_tracker API）。

        残留处理 2026-09-13：同步任务面（start_tracking/update_progress/
        complete_task/TaskStatus）随 B-11/B-12 清理删除；迁移到
        register_async_task + request_session_stop 等价意图。"""
        async def scenario():
            tracker = get_task_tracker()
            sid = "lifecycle_test"

            async def work():
                import asyncio as _a
                await _a.sleep(30)

            task = asyncio.get_running_loop().create_task(work())
            tracker.register_async_task(sid, task, kind="chat")
            assert tracker.request_session_stop(sid) >= 1
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert task.cancelled()

        asyncio.run(scenario())


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
