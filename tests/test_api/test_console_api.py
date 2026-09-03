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

from neurova.core.task_tracker import (
    TaskTracker,
    TaskStatus,
    TaskInfo,
    get_task_tracker,
)
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


# ============================================================
# TaskTracker 测试
# ============================================================

class TestTaskTracker:
    """TaskTracker 测试类"""
    
    def test_start_tracking(self, tracker, sample_metadata):
        """测试开始追踪任务"""
        task_id = "test_task_1"
        
        # 创建事件循环来运行异步函数
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            task_info = loop.run_until_complete(
                tracker.start_tracking(task_id, sample_metadata)
            )
        finally:
            loop.close()
        
        assert task_info.task_id == task_id
        assert task_info.status == TaskStatus.PENDING
        assert task_info.metadata == sample_metadata
        assert task_id in tracker._tasks
    
    def test_start_tracking_duplicate(self, tracker, sample_metadata):
        """测试重复创建任务"""
        task_id = "test_task_2"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 第一次创建
            task_info1 = loop.run_until_complete(
                tracker.start_tracking(task_id, sample_metadata)
            )
            
            # 第二次创建（应该返回已存在的任务）
            task_info2 = loop.run_until_complete(
                tracker.start_tracking(task_id, sample_metadata)
            )
        finally:
            loop.close()
        
        assert task_info1.task_id == task_info2.task_id
    
    def test_update_progress(self, tracker, sample_metadata):
        """测试更新任务进度"""
        task_id = "test_task_3"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
            
            # 更新进度
            result = loop.run_until_complete(
                tracker.update_progress(task_id, 0.5, "处理中...")
            )
        finally:
            loop.close()
        
        assert result is True
        task_info = tracker.get_task_status(task_id)
        assert task_info.status == TaskStatus.RUNNING
        assert task_info.progress == 0.5
        assert task_info.message == "处理中..."
        assert task_info.started_at is not None
    
    def test_update_progress_invalid_task(self, tracker):
        """测试更新不存在的任务进度"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                tracker.update_progress("non_existent", 0.5, "test")
            )
        finally:
            loop.close()
        
        assert result is False
    
    def test_complete_task(self, tracker, sample_metadata):
        """测试完成任务"""
        task_id = "test_task_4"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
            loop.run_until_complete(tracker.update_progress(task_id, 0.5, "processing"))
            
            # 完成任务
            result = loop.run_until_complete(
                tracker.complete_task(task_id, {"result": "success"})
            )
        finally:
            loop.close()
        
        assert result is True
        task_info = tracker.get_task_status(task_id)
        assert task_info.status == TaskStatus.COMPLETED
        assert task_info.progress == 1.0
        assert task_info.result == {"result": "success"}
        assert task_info.completed_at is not None
    
    def test_fail_task(self, tracker, sample_metadata):
        """测试任务失败"""
        task_id = "test_task_5"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
            
            # 任务失败
            result = loop.run_until_complete(
                tracker.fail_task(task_id, Exception("Test error"))
            )
        finally:
            loop.close()
        
        assert result is True
        task_info = tracker.get_task_status(task_id)
        assert task_info.status == TaskStatus.FAILED
        assert task_info.error is not None
        assert "Test error" in str(task_info.error)
    
    def test_stop_task(self, tracker, sample_metadata):
        """测试停止任务"""
        task_id = "test_task_6"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
            loop.run_until_complete(tracker.update_progress(task_id, 0.3, "running"))
            
            # 停止任务
            result = loop.run_until_complete(tracker.stop_task(task_id))
        finally:
            loop.close()
        
        assert result is True
        task_info = tracker.get_task_status(task_id)
        assert task_info.status == TaskStatus.CANCELLED
        assert task_info._cancel_requested is True
    
    def test_stop_task_not_running(self, tracker, sample_metadata):
        """测试停止已完成的任务"""
        task_id = "test_task_7"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
            loop.run_until_complete(tracker.complete_task(task_id, {}))
            
            # 尝试停止已完成的任务
            result = loop.run_until_complete(tracker.stop_task(task_id))
        finally:
            loop.close()
        
        assert result is False
    
    def test_get_task_status(self, tracker, sample_metadata):
        """测试获取任务状态"""
        task_id = "test_task_8"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
        finally:
            loop.close()
        
        task_info = tracker.get_task_status(task_id)
        assert task_info is not None
        assert task_info.task_id == task_id
        
        # 不存在的任务
        non_existent = tracker.get_task_status("non_existent")
        assert non_existent is None
    
    def test_get_all_tasks(self, tracker, sample_metadata):
        """测试获取所有任务"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for i in range(3):
                loop.run_until_complete(
                    tracker.start_tracking(f"task_{i}", sample_metadata)
                )
        finally:
            loop.close()
        
        all_tasks = tracker.get_all_tasks()
        assert len(all_tasks) == 3
    
    def test_get_tasks_by_status(self, tracker, sample_metadata):
        """测试根据状态筛选任务"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 创建几个任务
            for i in range(3):
                task_id = f"task_{i}"
                loop.run_until_complete(tracker.start_tracking(task_id, sample_metadata))
                if i < 2:
                    loop.run_until_complete(tracker.update_progress(task_id, 0.5, "running"))
            
            # 完成一个任务
            loop.run_until_complete(tracker.complete_task("task_0", {}))
        finally:
            loop.close()
        
        pending_tasks = tracker.get_tasks_by_status(TaskStatus.PENDING)
        running_tasks = tracker.get_tasks_by_status(TaskStatus.RUNNING)
        completed_tasks = tracker.get_tasks_by_status(TaskStatus.COMPLETED)
        
        assert len(pending_tasks) == 1
        assert len(running_tasks) == 1
        assert len(completed_tasks) == 1
    
    def test_task_info_to_dict(self, sample_metadata):
        """测试 TaskInfo.to_dict() 方法"""
        task_info = TaskInfo(
            task_id="test_task",
            metadata=sample_metadata,
            status=TaskStatus.RUNNING,
            progress=0.5,
            message="处理中",
        )
        
        task_dict = task_info.to_dict()
        
        assert task_dict["task_id"] == "test_task"
        assert task_dict["status"] == "running"
        assert task_dict["progress"] == 0.5
        assert task_dict["message"] == "处理中"
        assert "created_at" in task_dict
        assert "started_at" in task_dict


# ============================================================
# 便捷函数测试
# ============================================================

class TestConvenienceFunctions:
    """测试便捷函数（全局单例）"""
    
    def test_get_task_tracker_singleton(self):
        """测试单例模式"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tracker1 = loop.run_until_complete(asyncio.to_thread(get_task_tracker))
            tracker2 = loop.run_until_complete(asyncio.to_thread(get_task_tracker))
        finally:
            loop.close()
        
        assert tracker1 is tracker2
    
    def test_start_tracking_convenience(self, sample_metadata):
        """测试 start_tracking 便捷函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            task_info = loop.run_until_complete(
                start_tracking("conv_task_1", sample_metadata)
            )
        finally:
            loop.close()
        
        assert task_info.task_id == "conv_task_1"
    
    def test_update_progress_convenience(self):
        """测试 update_progress 便捷函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_tracking("conv_task_2", {}))
            result = loop.run_until_complete(
                update_progress("conv_task_2", 0.7, "convenience test")
            )
        finally:
            loop.close()
        
        assert result is True
    
    def test_complete_task_convenience(self):
        """测试 complete_task 便捷函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_tracking("conv_task_3", {}))
            result = loop.run_until_complete(
                complete_task("conv_task_3", {"done": True})
            )
        finally:
            loop.close()
        
        assert result is True
    
    def test_fail_task_convenience(self):
        """测试 fail_task 便捷函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_tracking("conv_task_4", {}))
            result = loop.run_until_complete(
                fail_task("conv_task_4", Exception("Convenience error"))
            )
        finally:
            loop.close()
        
        assert result is True
    
    def test_stop_task_convenience(self):
        """测试 stop_task 便捷函数"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_tracking("conv_task_5", {}))
            result = loop.run_until_complete(stop_task("conv_task_5"))
        finally:
            loop.close()
        
        assert result is True


# ============================================================
# Web Console API 测试
# ============================================================

class TestConsoleAPI:
    """Web Console API 测试类"""
    
    def test_chat_endpoint(self, client):
        """测试聊天接口"""
        response = client.post(
            "/console/chat",
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
        """测试停止聊天接口"""
        # 先创建一个任务
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(start_tracking("stop_test_task", {}))
        finally:
            loop.close()
        
        # 停止任务
        response = client.post("/console/chat/stop?task_id=stop_test_task")
        
        assert response.status_code == 200
        data = response.json()
        assert "stopped" in data
    
    def test_chat_history_endpoint(self, client):
        """测试获取聊天历史接口"""
        response = client.get("/console/chat/history?session_id=test_session&limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "messages" in data
    
    def test_chat_new_endpoint(self, client):
        """测试创建新会话接口"""
        response = client.post(
            "/console/chat/new",
            json={
                "user_id": "test_user",
                "metadata": {"source": "test"},
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "created_at" in data
    
    def test_chat_sessions_endpoint(self, client):
        """测试获取会话列表接口"""
        response = client.get("/console/chat/sessions?user_id=test_user")
        
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "total" in data
    
    def test_upload_endpoint(self, client, tmp_path):
        """测试文件上传接口"""
        # 创建测试文件
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, Neurova!")
        
        with open(test_file, "rb") as f:
            response = client.post(
                "/console/upload",
                files={"file": ("test.txt", f, "text/plain")},
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert "file_name" in data
        assert data["size"] > 0
    
    def test_upload_list_endpoint(self, client):
        """测试获取上传文件列表接口"""
        response = client.get("/console/upload/list?limit=10&offset=0")
        
        assert response.status_code == 200
        data = response.json()
        assert "files" in data
        assert "total" in data
    
    def test_debug_logs_endpoint(self, client, monkeypatch):
        """测试获取后端日志接口"""
        # 启用调试端点
        monkeypatch.setenv("ENABLE_DEBUG_ENDPOINT", "true")
        
        response = client.get("/console/debug/backend-logs?lines=50")
        
        assert response.status_code == 200
        data = response.json()
        assert "path" in data
        assert "exists" in data
        assert "content" in data
    
    def test_debug_logs_endpoint_disabled(self, client):
        """测试禁用调试端点时访问日志接口"""
        import os
        # 确保环境变量未设置或设置为false
        enable_debug = os.getenv("ENABLE_DEBUG_ENDPOINT", "false").lower() == "true"
        
        response = client.get("/console/debug/backend-logs?lines=50")
        
        if not enable_debug:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
    
    def test_debug_system_status_endpoint(self, client, monkeypatch):
        """测试获取系统状态接口"""
        # 启用调试端点
        monkeypatch.setenv("ENABLE_DEBUG_ENDPOINT", "true")
        
        response = client.get("/console/debug/system-status")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "uptime" in data
        assert "tasks" in data
    
    def test_debug_system_status_endpoint_disabled(self, client):
        """测试禁用调试端点时访问系统状态接口"""
        import os
        # 确保环境变量未设置或设置为false
        enable_debug = os.getenv("ENABLE_DEBUG_ENDPOINT", "false").lower() == "true"
        
        response = client.get("/console/debug/system-status")
        
        if not enable_debug:
            assert response.status_code == 403
        else:
            assert response.status_code == 200
    
    def test_websocket_endpoint(self, client):
        """测试 WebSocket 接口"""
        with client.websocket_connect("/console/ws") as websocket:
            # 发送 ping
            websocket.send_text(json.dumps({
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
            
            # 接收 pong
            data = json.loads(websocket.receive_text())
            assert data["event"] == "pong"
            
            # 发送 subscribe
            task_id = "ws_test_task"
            websocket.send_text(json.dumps({
                "type": "subscribe",
                "task_id": task_id,
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["event"] == "subscribed"
            
            # 发送 unsubscribe
            websocket.send_text(json.dumps({
                "type": "unsubscribe",
                "task_id": task_id,
            }))
            
            data = json.loads(websocket.receive_text())
            assert data["event"] == "unsubscribed"


# ============================================================
# 集成测试
# ============================================================

class TestIntegration:
    """集成测试"""
    
    def test_chat_and_stop_workflow(self, client):
        """测试完整的聊天和停止工作流"""
        # 1. 创建新会话
        new_session_resp = client.post("/console/chat/new")
        assert new_session_resp.status_code == 200
        session_id = new_session_resp.json()["session_id"]
        
        # 2. 发送聊天请求（非流式，以便测试）
        # 注意：实际 SSE 响应需要特殊处理，这里只测试接口是否可用
        chat_resp = client.post(
            "/console/chat",
            json={
                "message": "Integration test message",
                "session_id": session_id,
                "stream": False,
            },
        )
        # 即使返回 SSE 流，也应该成功（200）
        assert chat_resp.status_code == 200
    
    def test_task_lifecycle(self):
        """测试任务完整生命周期"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            task_id = "lifecycle_test"
            metadata = {"test": "lifecycle"}
            
            # 1. 创建任务
            task_info = loop.run_until_complete(
                start_tracking(task_id, metadata)
            )
            assert task_info.status == TaskStatus.PENDING
            
            # 2. 更新进度
            loop.run_until_complete(update_progress(task_id, 0.3, "step 1"))
            task_info = get_task_tracker().get_task_status(task_id)
            assert task_info.status == TaskStatus.RUNNING
            
            # 3. 继续更新
            loop.run_until_complete(update_progress(task_id, 0.7, "step 2"))
            
            # 4. 完成任务
            loop.run_until_complete(complete_task(task_id, {"result": "success"}))
            task_info = get_task_tracker().get_task_status(task_id)
            assert task_info.status == TaskStatus.COMPLETED
            assert task_info.result == {"result": "success"}
        finally:
            loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
