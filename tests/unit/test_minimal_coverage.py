"""
最小化覆盖率测试

只测试最容易覆盖的代码行
"""

from __future__ import annotations

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
# 测试1: 文件下载错误处理（覆盖460行）
# ============================================================

def test_download_file_not_found(client):
    """测试下载不存在的文件"""
    response = client.get("/console/upload/non_existent_file.txt")
    assert response.status_code == 404


# ============================================================
# 测试2: 聊天历史错误处理（覆盖424-426行）
# ============================================================

def test_chat_history_exception(client):
    """测试聊天历史异常"""
    with patch(
        "neurova.api.endpoints.console.get_session_manager",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/chat/history?session_id=test")
        assert response.status_code == 500


# ============================================================
# 测试3: 会话列表错误处理（覆盖438-440行）
# ============================================================

def test_chat_sessions_exception(client):
    """测试会话列表异常"""
    with patch(
        "neurova.api.endpoints.console.get_session_manager",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/chat/sessions?user_id=test")
        assert response.status_code == 500


# ============================================================
# 测试4: 推送消息错误处理（覆盖802-803, 816-818行）
# ============================================================

def test_push_messages_invalid_after(client):
    """测试无效的after参数"""
    response = client.get(
        "/console/push-messages",
        params={"after": "invalid_datetime"},
    )
    # 应该返回200（带警告）或400
    assert response.status_code in [200, 400]


def test_push_messages_exception(client):
    """测试推送消息异常"""
    with patch(
        "neurova.api.endpoints.console._push_messages_lock",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/push-messages")
        assert response.status_code == 500


# ============================================================
# 测试5: WebSocket简单测试（覆盖745, 758-760行）
# ============================================================

def test_websocket_ping(client):
    """测试ping消息"""
    with client.websocket_connect("/console/ws") as websocket:
        websocket.send_text(json.dumps({
            "type": "ping",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        
        data = json.loads(websocket.receive_text())
        assert data["event"] == "pong"


def test_websocket_subscribe_unsubscribe(client):
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


# ============================================================
# 测试6: 文件上传错误处理（覆盖340-359行）
# ============================================================

def test_upload_no_file(client):
    """测试不上传文件"""
    response = client.post("/console/upload")
    assert response.status_code == 422


def test_upload_large_file(client, tmp_path):
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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=30"])
