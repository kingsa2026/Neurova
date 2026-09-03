"""
无WebSocket测试

只测试HTTP端点，避免超时问题
"""

from __future__ import annotations

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
# 测试文件下载错误处理（覆盖460行）
# ============================================================

def test_download_file_not_found(client):
    """测试下载不存在的文件 - 覆盖460行"""
    response = client.get("/console/upload/non_existent_file.txt")
    assert response.status_code == 404


# ============================================================
# 测试聊天历史错误处理（覆盖424-426行）
# ============================================================

def test_chat_history_exception(client):
    """测试聊天历史异常 - 覆盖424-426行"""
    with patch(
        "neurova.api.endpoints.console.get_session_manager",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/chat/history?session_id=test")
        assert response.status_code == 500


# ============================================================
# 测试会话列表错误处理（覆盖438-440行）
# ============================================================

def test_chat_sessions_exception(client):
    """测试会话列表异常 - 覆盖438-440行"""
    with patch(
        "neurova.api.endpoints.console.get_session_manager",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/chat/sessions?user_id=test")
        assert response.status_code == 500


# ============================================================
# 测试推送消息错误处理（覆盖802-803, 816-818行）
# ============================================================

def test_push_messages_invalid_after(client):
    """测试无效的after参数 - 覆盖802-803行"""
    response = client.get(
        "/console/push-messages",
        params={"after": "invalid_datetime"},
    )
    # 应该返回200（带警告）或400
    assert response.status_code in [200, 400]


def test_push_messages_exception(client):
    """测试推送消息异常 - 覆盖816-818行"""
    with patch(
        "neurova.api.endpoints.console._push_messages_lock",
        side_effect=Exception("Mocked")
    ):
        response = client.get("/console/push-messages")
        assert response.status_code == 500


# ============================================================
# 测试文件上传错误处理（覆盖340-359行）
# ============================================================

def test_upload_no_file(client):
    """测试不上传文件 - 覆盖部分上传错误处理"""
    response = client.post("/console/upload")
    assert response.status_code == 422


def test_upload_large_file(client, tmp_path):
    """测试上传超大文件 - 覆盖340-359行"""
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
# 测试聊天接口错误处理（覆盖59-96行）
# ============================================================

def test_chat_empty_message(client):
    """测试空消息 - 覆盖部分聊天错误处理"""
    response = client.post(
        "/console/chat",
        json={
            "message": "",
            "session_id": "test",
            "stream": False,
        },
    )
    assert response.status_code in [200, 400, 422]


def test_chat_missing_message(client):
    """测试缺少消息字段 - 覆盖部分聊天错误处理"""
    response = client.post(
        "/console/chat",
        json={
            "session_id": "test",
            "stream": False,
        },
    )
    assert response.status_code == 422


# ============================================================
# 测试边界情况（覆盖134-135, 142-146, 150行）
# ============================================================

def test_chat_history_with_negative_limit(client):
    """测试负数limit - 覆盖部分边界情况"""
    response = client.get("/console/chat/history?limit=-1")
    # 应该返回422（验证错误）或200（带默认值）
    assert response.status_code in [200, 422]


def test_chat_sessions_with_empty_user_id(client):
    """测试空user_id - 覆盖部分边界情况"""
    response = client.get("/console/chat/sessions?user_id=")
    assert response.status_code in [200, 400, 422]


def test_upload_with_special_filename(client, tmp_path):
    """测试特殊文件名 - 覆盖部分边界情况"""
    # 创建带有特殊字符的文件名
    test_file = tmp_path / "test file with spaces.txt"
    test_file.write_text("Test content")
    
    with open(test_file, "rb") as f:
        response = client.post(
            "/console/upload",
            files={"file": ("test file with spaces.txt", f, "text/plain")},
        )
    
    assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=10"])
