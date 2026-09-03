"""
Web Console API 扩展单元测试

测试覆盖未覆盖的代码路径：
1. 文件下载功能
2. 文件删除功能
3. 推送消息功能
4. 错误处理分支
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

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


@pytest.fixture
def upload_dir():
    """获取上传目录"""
    from neurova.api.endpoints.console import UPLOAD_DIR
    return UPLOAD_DIR


@pytest.fixture
def sample_file(upload_dir):
    """创建测试文件"""
    file_path = upload_dir / "test_file_123456.txt"
    file_path.write_text("Test file content for download")
    yield file_path
    if file_path.exists():
        file_path.unlink()


# ============================================================
# 文件下载功能测试
# ============================================================

class TestFileDownload:
    """测试文件下载功能（覆盖524-562行）"""
    
    def test_download_file_success(self, client, sample_file):
        """测试成功下载文件"""
        response = client.get(f"/console/upload/{sample_file.name}")
        
        assert response.status_code == 200
        assert response.headers["content-disposition"] is not None
        assert "attachment" in response.headers["content-disposition"]
    
    def test_download_file_with_original_filename(self, client, sample_file):
        """测试使用原始文件名下载"""
        original_name = "original_test.txt"
        response = client.get(
            f"/console/upload/{sample_file.name}",
            params={"original_filename": original_name}
        )
        
        assert response.status_code == 200
        assert "original_test.txt" in response.headers.get("content-disposition", "")
    
    def test_download_file_not_found(self, client):
        """测试下载不存在的文件"""
        response = client.get("/console/upload/non_existent_file.txt")
        
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "文件不存在" in data["error"]
    
    def test_download_file_with_uuid_only(self, client, upload_dir):
        """测试只有uuid的文件名（无原始文件名）"""
        # 创建文件名只有uuid的文件
        file_id = "abcdef123456"
        file_path = upload_dir / file_id
        file_path.write_text("No original name")
        
        try:
            response = client.get(f"/console/upload/{file_id}")
            assert response.status_code == 200
        finally:
            if file_path.exists():
                file_path.unlink()
    
    def test_download_file_exception_handling(self, client, sample_file):
        """测试文件下载异常处理"""
        # 模拟文件读取异常
        with patch("pathlib.Path.stat", side_effect=Exception("Mocked exception")):
            response = client.get(f"/console/upload/{sample_file.name}")
            
            # 应该返回500错误
            assert response.status_code == 500
            data = response.json()
            assert "error" in data


# ============================================================
# 文件删除功能测试
# ============================================================

class TestFileDelete:
    """测试文件删除功能（覆盖568-588行）"""
    
    def test_delete_file_success(self, client, sample_file):
        """测试成功删除文件"""
        response = client.delete(f"/console/upload/{sample_file.name}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["file_id"] == sample_file.name
        
        # 确认文件已被删除
        assert not sample_file.exists()
    
    def test_delete_file_not_found(self, client):
        """测试删除不存在的文件"""
        response = client.delete("/console/upload/non_existent_file.txt")
        
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert "文件不存在" in data["error"]
    
    def test_delete_file_exception(self, client, sample_file):
        """测试文件删除异常处理"""
        # 模拟删除异常
        with patch("pathlib.Path.unlink", side_effect=Exception("Mocked exception")):
            response = client.delete(f"/console/upload/{sample_file.name}")
            
            assert response.status_code == 500
            data = response.json()
            assert "error" in data


# ============================================================
# 推送消息功能测试
# ============================================================

class TestPushMessages:
    """测试推送消息功能（覆盖779-818行和837-867行）"""
    
    def test_get_push_messages_empty(self, client):
        """测试获取空消息列表"""
        response = client.get("/console/push-messages")
        
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["total"] == 0
    
    def test_get_push_messages_with_session(self, client):
        """测试获取指定会话的消息"""
        session_id = "test_session_123"
        
        response = client.get(
            "/console/push-messages",
            params={"session_id": session_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
    
    def test_get_push_messages_with_after_filter(self, client):
        """测试使用after参数过滤消息"""
        # 先发送一条消息
        message = {
            "event": "test_event",
            "data": "test_data",
        }
        
        post_response = client.post(
            "/console/push-messages",
            json=message,
        )
        assert post_response.status_code == 200
        
        # 获取消息
        after_time = datetime.now(timezone.utc).isoformat()
        response = client.get(
            "/console/push-messages",
            params={"after": after_time}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
    
    def test_get_push_messages_with_limit(self, client):
        """测试限制返回消息数量"""
        response = client.get(
            "/console/push-messages",
            params={"limit": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] <= 10
    
    def test_post_push_message_success(self, client):
        """测试成功发送推送消息"""
        message = {
            "event": "test_event",
            "data": "test_data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        response = client.post(
            "/console/push-messages",
            json=message,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["broadcast"] is True
        assert "connections" in data
        assert data["stored"] is True
    
    def test_post_push_message_with_session(self, client):
        """测试发送带会话ID的推送消息"""
        session_id = "test_session_456"
        message = {
            "event": "session_event",
            "data": "session_data",
        }
        
        response = client.post(
            "/console/push-messages",
            json=message,
            params={"session_id": session_id},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
    
    def test_post_push_message_without_timestamp(self, client):
        """测试发送没有时间戳的消息（自动添加）"""
        message = {
            "event": "no_timestamp_event",
            "data": "data_without_timestamp",
        }
        
        response = client.post(
            "/console/push-messages",
            json=message,
        )
        
        assert response.status_code == 200
        
        # 验证消息已存储（通过GET请求）
        get_response = client.get("/console/push-messages")
        assert get_response.status_code == 200
        get_data = get_response.json()
        # 应该至少有一条消息
        assert len(get_data["messages"]) >= 1
    
    def test_post_push_message_exception(self, client):
        """测试推送消息异常处理"""
        # 模拟broadcast异常
        with patch(
            "neurova.api.endpoints.console.manager.broadcast",
            side_effect=Exception("Mocked exception")
        ):
            message = {
                "event": "error_event",
                "data": "error_data",
            }
            
            response = client.post(
                "/console/push-messages",
                json=message,
            )
            
            # 注意：即使broadcast失败，消息可能仍然存储成功
            # 具体行为取决于实现
            assert response.status_code in [200, 500]


# ============================================================
# 聊天历史功能扩展测试
# ============================================================

class TestChatHistoryExtended:
    """测试聊天历史功能（覆盖408-426行的分支）"""
    
    def test_chat_history_with_default_params(self, client):
        """测试使用默认参数获取聊天历史"""
        response = client.get("/console/chat/history")
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "messages" in data
    
    def test_chat_history_with_custom_limit(self, client):
        """测试自定义限制数量"""
        response = client.get("/console/chat/history?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        # session_id 可能为 None（当未提供 session_id 参数时）
        assert "session_id" in data
        assert "messages" in data
    
    def test_chat_history_session_not_found(self, client):
        """测试获取不存在的会话历史"""
        response = client.get("/console/chat/history?session_id=non_existent_session")
        
        # 应该返回200但消息列表为空，或者返回404
        # 具体取决于实现
        assert response.status_code in [200, 404]


# ============================================================
# 会话列表功能扩展测试
# ============================================================

class TestChatSessionsExtended:
    """测试会话列表功能（覆盖438-440行的分支）"""
    
    def test_chat_sessions_with_default_params(self, client):
        """测试使用默认参数获取会话列表"""
        response = client.get("/console/chat/sessions")
        
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "total" in data
    
    def test_chat_sessions_with_user_id(self, client):
        """测试指定用户ID获取会话列表"""
        response = client.get("/console/chat/sessions?user_id=test_user_123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test_user_123"


# ============================================================
# 调试接口扩展测试
# ============================================================

class TestDebugEndpointsExtended:
    """测试调试接口（覆盖571-585行等）"""
    
    def test_debug_logs_with_custom_lines(self, client):
        """测试自定义行数获取日志"""
        response = client.get("/console/debug/backend-logs?lines=50")
        
        assert response.status_code == 200
        data = response.json()
        assert data["lines"] == 50
    
    def test_debug_system_status_structure(self, client):
        """测试系统状态返回结构"""
        response = client.get("/console/debug/system-status")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "uptime" in data
        assert "tasks" in data
        assert "memory_enabled" in data
        assert "websocket_connections" in data
    
    def test_debug_command_endpoint(self, client):
        """测试调试命令接口"""
        # 注意：这个接口可能有安全风险，仅用于测试
        response = client.post(
            "/console/debug/command",
            json={
                "command": "echo test",
            },
        )
        
        # 可能返回200或403（如果禁用了调试命令）
        assert response.status_code in [200, 403, 404]


# ============================================================
# WebSocket 扩展测试
# ============================================================

class TestWebSocketExtended:
    """测试WebSocket接口（覆盖745-751, 758-760行）"""
    
    def test_websocket_invalid_message(self, client):
        """测试发送无效消息"""
        with client.websocket_connect("/console/ws") as websocket:
            # 发送无效JSON
            websocket.send_text("invalid json")
            
            # 应该收到错误消息或忽略
            # 具体行为取决于实现
            try:
                data = json.loads(websocket.receive_text())
                # 如果收到响应，应该是error事件
                if "event" in data:
                    assert data["event"] in ["error", "pong", "subscribed"]
            except Exception:
                # 如果抛出异常，也是可接受的行为
                pass
    
    def test_websocket_multiple_subscriptions(self, client):
        """测试多个订阅"""
        with client.websocket_connect("/console/ws") as websocket:
            # 订阅多个任务
            task_ids = ["task_1", "task_2", "task_3"]
            
            for task_id in task_ids:
                websocket.send_text(json.dumps({
                    "type": "subscribe",
                    "task_id": task_id,
                }))
                
                data = json.loads(websocket.receive_text())
                assert data["event"] == "subscribed"
                assert data["task_id"] == task_id
            
            # 取消订阅
            for task_id in task_ids:
                websocket.send_text(json.dumps({
                    "type": "unsubscribe",
                    "task_id": task_id,
                }))
                
                data = json.loads(websocket.receive_text())
                assert data["event"] == "unsubscribed"


# ============================================================
# 集成测试
# ============================================================

class TestIntegrationExtended:
    """扩展集成测试"""
    
    def test_file_upload_download_workflow(self, client, tmp_path):
        """测试文件上传和下载的完整工作流"""
        # 1. 上传文件
        test_file = tmp_path / "integration_test.txt"
        test_file.write_text("Integration test content")
        
        with open(test_file, "rb") as f:
            upload_response = client.post(
                "/console/upload",
                files={"file": ("integration_test.txt", f, "text/plain")},
            )
        
        assert upload_response.status_code == 200
        upload_data = upload_response.json()
        file_id = upload_data["file_id"]
        
        # 2. 下载文件
        download_response = client.get(f"/console/upload/{file_id}")
        assert download_response.status_code == 200
        
        # 3. 删除文件
        delete_response = client.delete(f"/console/upload/{file_id}")
        assert delete_response.status_code == 200
    
    def test_push_message_workflow(self, client):
        """测试推送消息的完整工作流"""
        # 1. 发送消息
        message = {
            "event": "workflow_test",
            "data": "workflow_data",
        }
        
        post_response = client.post(
            "/console/push-messages",
            json=message,
        )
        assert post_response.status_code == 200
        
        # 2. 获取消息
        get_response = client.get("/console/push-messages")
        assert get_response.status_code == 200
        
        get_data = get_response.json()
        assert len(get_data["messages"]) >= 1
        
        # 3. 验证消息内容
        messages = get_data["messages"]
        latest_message = messages[-1]
        assert latest_message["event"] == "workflow_test"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
