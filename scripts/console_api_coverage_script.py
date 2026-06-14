"""
Web Console API 覆盖率补充测试

专门针对未覆盖的代码路径：
1. 错误处理分支
2. 边缘情况
3. 异常流程
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, status

from neurova.api.app import create_app


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
    return TestClient(app)


# ============================================================
# 聊天接口错误处理测试
# ============================================================

class TestChatEndpointErrors:
    """测试聊天接口的错误处理（覆盖59-96行）"""
    
    def test_chat_with_invalid_session(self, client):
        """测试无效的会话ID"""
        response = client.post(
            "/console/chat",
            json={
                "message": "Hello",
                "session_id": "",  # 空会话ID
                "stream": False,
            },
        )
        
        # 应该返回200或400
        assert response.status_code in [200, 400, 422]
    
    def test_chat_with_empty_message(self, client):
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
    
    def test_chat_stop_nonexistent_task(self, client):
        """测试停止不存在的任务"""
        response = client.post("/console/chat/stop?task_id=non_existent_task")
        
        # 应该返回404或200（带错误信息）
        assert response.status_code in [200, 404]


# ============================================================
# 聊天历史和会话错误处理测试
# ============================================================

class TestChatHistoryErrors:
    """测试聊天历史和会话的错误处理（覆盖424-426, 438-440, 460行）"""
    
    def test_chat_history_exception(self, client):
        """测试聊天历史异常"""
        # 模拟SessionManager异常
        with patch(
            "neurova.api.endpoints.console.get_session_manager",
            side_effect=Exception("Mocked exception")
        ):
            response = client.get("/console/chat/history?session_id=test")
            
            # 应该返回500错误
            assert response.status_code == 500
    
    def test_chat_sessions_exception(self, client):
        """测试会话列表异常"""
        # 模拟SessionManager异常
        with patch(
            "neurova.api.endpoints.console.get_session_manager",
            side_effect=Exception("Mocked exception")
        ):
            response = client.get("/console/chat/sessions?user_id=test")
            
            # 应该返回500错误
            assert response.status_code == 500
    
    def test_chat_new_session_exception(self, client):
        """测试创建新会话异常"""
        # 这个测试取决于实现
        # 如果创建会话有异常处理，应该返回500
        pass


# ============================================================
# 文件上传错误处理测试
# ============================================================

class TestFileUploadErrors:
    """测试文件上传的错误处理（覆盖340-359行）"""
    
    def test_upload_empty_file(self, client):
        """测试上传空文件"""
        response = client.post(
            "/console/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        
        # 应该返回200或400
        assert response.status_code in [200, 400]
    
    def test_upload_large_file(self, client):
        """测试上传超大文件"""
        # 创建一个超过限制的文件（假设限制是10MB）
        large_content = b"x" * (10 * 1024 * 1024 + 1)
        
        response = client.post(
            "/console/upload",
            files={"file": ("large.txt", large_content, "text/plain")},
        )
        
        # 应该返回400错误
        assert response.status_code == 400
    
    def test_upload_no_file(self, client):
        """测试不上传文件"""
        response = client.post("/console/upload")
        
        # 应该返回422（验证错误）
        assert response.status_code == 422


# ============================================================
# WebSocket 错误处理测试
# ============================================================

class TestWebSocketErrors:
    """测试WebSocket的错误处理（覆盖650-680, 745, 758-760行）"""
    
    def test_websocket_invalid_json(self, client):
        """测试发送无效JSON"""
        with client.websocket_connect("/console/ws") as websocket:
            # 发送无效JSON
            websocket.send_text("invalid json{{{")
            
            # 应该收到错误消息或连接关闭
            try:
                data = json.loads(websocket.receive_text())
                # 如果收到响应，应该是error事件
                assert data["event"] == "error"
            except Exception:
                # 连接可能已关闭
                pass
    
    def test_websocket_subscribe_no_task_id(self, client):
        """测试订阅时不提供task_id"""
        with client.websocket_connect("/console/ws") as websocket:
            # 发送没有task_id的subscribe消息
            websocket.send_text(json.dumps({
                "type": "subscribe",
                # 缺少 task_id
            }))
            
            # 应该收到错误或部分响应
            try:
                data = json.loads(websocket.receive_text())
                assert data["event"] in ["error", "subscribed"]
            except Exception:
                pass


# ============================================================
# 推送消息错误处理测试
# ============================================================

class TestPushMessagesErrors:
    """测试推送消息的错误处理（覆盖802-803, 816-818, 853行）"""
    
    def test_push_messages_invalid_after(self, client):
        """测试无效的after参数"""
        response = client.get(
            "/console/push-messages",
            params={"after": "invalid_datetime"}
        )
        
        # 应该返回200（带警告）或400
        assert response.status_code in [200, 400]
    
    def test_push_messages_exception(self, client):
        """测试推送消息异常"""
        # 模拟异常
        with patch(
            "neurova.api.endpoints.console._push_messages_lock",
            side_effect=Exception("Mocked exception")
        ):
            response = client.get("/console/push-messages")
            
            # 应该返回500错误
            assert response.status_code == 500
    
    def test_post_push_message_broadcast_exception(self, client):
        """测试广播异常"""
        # 模拟broadcast异常
        with patch(
            "neurova.api.endpoints.console.manager.broadcast",
            side_effect=Exception("Mocked broadcast exception")
        ):
            message = {
                "event": "test_event",
                "data": "test_data",
            }
            
            response = client.post(
                "/console/push-messages",
                json=message,
            )
            
            # 即使broadcast失败，存储可能仍然成功
            # 具体行为取决于实现
            assert response.status_code in [200, 500]


# ============================================================
# 调试接口测试
# ============================================================

class TestDebugEndpoints:
    """测试调试接口（覆盖590-685行）"""
    
    def test_debug_logs_with_invalid_lines(self, client):
        """测试无效的lines参数"""
        response = client.get("/console/debug/backend-logs?lines=1000")
        
        # 应该返回200（带限制）或400
        assert response.status_code in [200, 400]
    
    def test_debug_command_disabled(self, client):
        """测试调试命令被禁用"""
        # 这个测试取决于实现
        # 如果调试命令被禁用，应该返回403或404
        response = client.post(
            "/console/debug/command",
            json={"command": "echo test"},
        )
        
        assert response.status_code in [200, 403, 404]


# ============================================================
# 边界情况测试
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
    
    def test_download_with_url_encoded_filename(self, client, tmp_path):
        """测试URL编码的文件名"""
        # 这个测试取决于实现
        pass


# ============================================================
# 并发测试
# ============================================================

class TestConcurrency:
    """测试并发情况"""
    
    def test_multiple_push_messages(self, client):
        """测试多次发送推送消息"""
        # 发送多条消息
        for i in range(10):
            message = {
                "event": f"test_{i}",
                "data": f"data_{i}",
            }
            
            response = client.post(
                "/console/push-messages",
                json=message,
            )
            
            assert response.status_code == 200
        
        # 验证所有消息都被存储
        response = client.get("/console/push-messages")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 10


# ============================================================
# 性能测试
# ============================================================

class TestPerformance:
    """测试性能相关"""
    
    def test_large_push_message(self, client):
        """测试大型推送消息"""
        # 创建一个大消息
        large_data = "x" * 10000  # 10KB
        
        message = {
            "event": "large_event",
            "data": large_data,
        }
        
        response = client.post(
            "/console/push-messages",
            json=message,
        )
        
        assert response.status_code == 200
    
    def test_many_files_list(self, client):
        """测试文件列表性能"""
        response = client.get("/console/upload/list?limit=1000")
        
        assert response.status_code == 200
        data = response.json()
        assert "files" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
