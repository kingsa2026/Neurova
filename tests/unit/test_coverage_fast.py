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


@pytest.fixture
def app():
    """创建测试应用"""
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return TestClient(app)


# ============================================================
# 测试聊天接口错误处理（覆盖59-96行）
# ============================================================

class TestChatErrors:
    """测试聊天接口的错误处理"""
    
    def test_chat_empty_message(self, client):
        """测试空消息"""
        response = client.post(
            "/console/chat",
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
            "/console/chat",
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
        response = client.post("/console/upload")
        assert response.status_code == 422
    
    def test_upload_large_file(self, client, tmp_path):
        """测试上传超大文件"""
        # 创建一个超过限制的文件
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (50 * 1024 * 1024 + 1))
        
        with open(large_file, "rb") as f:
            response = client.post(
                "/console/upload",
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
        response = client.get("/console/upload/non_existent_file.txt")
        assert response.status_code == 404
    
    def test_download_exception(self, client):
        """测试文件下载异常"""
        # 创建一个测试文件
        from neurova.api.endpoints.console import UPLOAD_DIR
        test_file = UPLOAD_DIR / "test_error.txt"
        test_file.write_text("test")
        
        try:
            # 模拟异常
            with patch("pathlib.Path.stat", side_effect=Exception("Mocked")):
                response = client.get(f"/console/upload/{test_file.name}")
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
            "/console/push-messages",
            params={"after": "invalid_datetime"},
        )
        # 应该返回200（带警告）或400
        assert response.status_code in [200, 400]
    
    def test_push_messages_exception(self, client):
        """测试推送消息异常"""
        with patch(
            "neurova.api.endpoints.console._push_messages_lock",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/console/push-messages")
            assert response.status_code == 500


# ============================================================
# 测试聊天历史和会话列表错误处理（覆盖424-426, 438-440, 460行）
# ============================================================

class TestChatHistoryErrors:
    """测试聊天历史和会话列表的错误处理"""
    
    def test_chat_history_exception(self, client):
        """测试聊天历史异常"""
        with patch(
            "neurova.api.endpoints.console.get_session_manager",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/console/chat/history?session_id=test")
            assert response.status_code == 500
    
    def test_chat_sessions_exception(self, client):
        """测试会话列表异常"""
        with patch(
            "neurova.api.endpoints.console.get_session_manager",
            side_effect=Exception("Mocked")
        ):
            response = client.get("/console/chat/sessions?user_id=test")
            assert response.status_code == 500


# ============================================================
# 测试边界情况（覆盖134-135, 142-146, 150行）
# ============================================================

class TestEdgeCases:
    """测试边界情况"""
    
    def test_chat_history_with_negative_limit(self, client):
        """测试负数limit"""
        response = client.get("/console/chat/history?limit=-1")
        # 应该返回422（验证错误）或200（带默认值）
        assert response.status_code in [200, 422]
    
    def test_chat_sessions_with_empty_user_id(self, client):
        """测试空user_id"""
        response = client.get("/console/chat/sessions?user_id=")
        assert response.status_code in [200, 400, 422]
    
    def test_upload_with_special_filename(self, client, tmp_path):
        """测试特殊文件名"""
        # 创建带有特殊字符的文件名
        test_file = tmp_path / "test file with spaces.txt"
        test_file.write_text("Test content")
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/console/upload",
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
        with client.websocket_connect("/console/ws") as websocket:
            websocket.send_text(json.dumps({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["event"] == "pong"
    
    def test_websocket_subscribe_unsubscribe(self, client):
        """测试订阅和取消订阅"""
        with client.websocket_connect("/console/ws") as websocket:
            # 订阅
            websocket.send_text(json.dumps({
                "type": "subscribe",
                "task_id": "test_task",
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["event"] == "subscribed"
            
            # 取消订阅
            websocket.send_text(json.dumps({
                "type": "unsubscribe",
                "task_id": "test_task",
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["event"] == "unsubscribed"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=30"])
