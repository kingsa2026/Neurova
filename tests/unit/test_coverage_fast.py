"""
快速覆盖率测试

针对"容易"目标，创建简单、快速的测试
避免WebSocket超时问题
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from fastapi import status

from neurova.api.app import create_app

def _authed_client(app):
    """统一注入登录态（console 面 S-08 收口后需鉴权；残留处理 2026-09-13）。

    admin 角色——debug 面现行 require_admin。"""
    from fastapi.testclient import TestClient
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "test_user", "username": "test_user", "role": "admin"}
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    return TestClient(app)






def _make_ws_token():
    from neurova.api.auth import create_access_token

    return create_access_token({"user_id": "test_user", "sub": "test_user", "role": "user"})


def _quiet_client(app):
    """raise_server_exceptions=False：观察端点未捕获异常的 500 形态（现行
    console 面部分端点无 try 分支，异常直达 ASGI）。残留处理 2026-09-13。"""
    from fastapi import FastAPI as _F  # noqa: F401  (docstring anchor)
    from fastapi.testclient import TestClient
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "test_user", "username": "test_user", "role": "admin"}
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    return TestClient(app, raise_server_exceptions=False)



@pytest.fixture
def app():
    """创建测试应用"""
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return _authed_client(app)


# ============================================================
# 测试聊天接口错误处理（覆盖59-96行）
# ============================================================

class TestChatErrors:
    """测试聊天接口的错误处理"""
    
    def test_chat_empty_message(self, client):
        """测试空消息"""
        response = client.post(
            "/api/v1/console/chat",
            json={
                "message": "",
                "session_id": "test",
                "stream": False,
            },
        )
        assert response.status_code in [200, 400, 422]
    
    def test_chat_missing_message(self, client):
        """测试缺少消息字段"""
        response = client.post(
            "/api/v1/console/chat",
            json={
                "session_id": "test",
                "stream": False,
            },
        )
        assert response.status_code == 422


# ============================================================
# 测试文件上传错误处理（覆盖340-359行）
# ============================================================

class TestFileUploadErrors:
    """测试文件上传的错误处理"""
    
    def test_upload_no_file(self, client):
        """测试不上传文件"""
        response = client.post("/api/v1/console/upload")
        assert response.status_code == 422
    
    @pytest.mark.xfail(
        strict=False,
        reason="console /upload 现无大小守卫（50MB 直写盘）——安全护栏待裁决，"
               "与 tests/test_api 同因（台账十二）。守卫落地后自动转绿",
    )
    def test_upload_large_file(self, client, tmp_path):
        """上传超大文件应被拒（现行未实现=xfail）"""
        # 创建一个超过限制的文件
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (50 * 1024 * 1024 + 1))
        
        with open(large_file, "rb") as f:
            response = client.post(
                "/api/v1/console/upload",
                files={"file": ("large.txt", f, "text/plain")},
            )
        
        assert response.status_code == 400
        data = response.json()
        assert "error" in data


# ============================================================
# 测试文件下载错误处理（覆盖460行）
# ============================================================

class TestFileDownloadErrors:
    """测试文件下载的错误处理"""
    
    def test_download_file_not_found(self, client):
        """测试下载不存在的文件"""
        response = client.get("/api/v1/console/uploads/non_existent_file.txt")
        assert response.status_code == 404
    
    def test_download_exception(self, app):
        """下载内部异常→500。原全局 patch pathlib.Path.stat 连测试自身
        finally 的 exists/unlink 一起炸（stat 全局副作用）——迁到端点读面
        seam（FileResponse 构造抛错）+ quiet client。残留处理 2026-09-13"""
        client = _quiet_client(app)
        from neurova.api.endpoints.console import _CONSOLE_UPLOAD_DIR as UPLOAD_DIR
        test_file = UPLOAD_DIR / "test_error.txt"
        test_file.write_text("test")

        try:
            with patch(
                "neurova.api.endpoints.console.FileResponse",
                side_effect=Exception("Mocked"),
            ):
                response = client.get(f"/api/v1/console/uploads/{test_file.name}")
                assert response.status_code == 500
        finally:
            if test_file.exists():
                test_file.unlink()


# ============================================================
# 测试推送消息错误处理（覆盖802-803, 816-818行）
# ============================================================

class TestPushMessagesErrors:
    """测试推送消息的错误处理"""
    
    def test_push_messages_invalid_after(self, client):
        """测试无效的after参数"""
        response = client.get(
            "/api/v1/console/push/messages",
            params={"after": "invalid_datetime"},
        )
        # 应该返回200（带警告）或400
        assert response.status_code in [200, 400]
    
    def test_push_messages_exception(self, app):
        """推送消息：底层异常→500（quiet client，残留处理 2026-09-13）"""
        client = _quiet_client(app)
        with patch(
            "neurova.api.endpoints.console._manager.get_messages",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/api/v1/console/push/messages")
            assert response.status_code == 500


# ============================================================
# 测试聊天历史和会话列表错误处理（覆盖424-426, 438-440, 460行）
# ============================================================

class TestChatHistoryErrors:
    """测试聊天历史和会话列表的错误处理"""
    
    def test_chat_history_exception(self, app):
        """聊天历史：repo 异常→500（quiet client 观察 ASGI 层，残留处理 2026-09-13）"""
        client = _quiet_client(app)
        with patch(
            "neurova.api.endpoints.console.get_session_repository",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/api/v1/console/chat/history?session_id=test")
            assert response.status_code == 500
    
    def test_chat_sessions_exception(self, app):
        """会话列表：repo 异常→500（quiet client，残留处理 2026-09-13）"""
        client = _quiet_client(app)
        with patch(
            "neurova.api.endpoints.console.get_session_repository",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/api/v1/console/chat/sessions?user_id=test")
            assert response.status_code == 500


# ============================================================
# 测试边界情况（覆盖134-135, 142-146, 150行）
# ============================================================

class TestEdgeCases:
    """测试边界情况"""
    
    def test_chat_history_with_negative_limit(self, client):
        """测试负数limit"""
        response = client.get("/api/v1/console/chat/history?limit=-1")
        # 应该返回422（验证错误）或200（带默认值）
        assert response.status_code in [200, 422]
    
    def test_chat_sessions_with_empty_user_id(self, client):
        """测试空user_id"""
        response = client.get("/api/v1/console/chat/sessions?user_id=")
        assert response.status_code in [200, 400, 422]
    
    def test_upload_with_special_filename(self, client, tmp_path):
        """测试特殊文件名"""
        # 创建带有特殊字符的文件名
        test_file = tmp_path / "test file with spaces.txt"
        test_file.write_text("Test content")
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/api/v1/console/upload",
                files={"file": ("test file with spaces.txt", f, "text/plain")},
            )
        
        assert response.status_code == 200


# ============================================================
# 测试WebSocket简单情况（覆盖745, 758-760行）
# ============================================================

class TestWebSocketSimple:
    """测试WebSocket简单情况"""
    
    def test_websocket_ping(self, client):
        """测试ping消息"""
        with client.websocket_connect(f"/api/v1/console/ws/tc?token={_make_ws_token()}") as websocket:
            websocket.send_text(json.dumps({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["type"] == "pong"  # 现行 type 键协议
    
    def test_websocket_subscribe_unsubscribe(self, client):
        """测试订阅和取消订阅"""
        with client.websocket_connect(f"/api/v1/console/ws/tc?token={_make_ws_token()}") as websocket:
            # 订阅
            websocket.send_text(json.dumps({
                "type": "subscribe",
                "task_id": "test_task",
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["type"] == "ack"  # 现行无 subscribe 面，未知类型回 ack
            
            # 取消订阅
            websocket.send_text(json.dumps({
                "type": "unsubscribe",
                "task_id": "test_task",
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["type"] == "ack"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=30"])
