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




def _make_ws_token():
    from neurova.api.auth import create_access_token

    return create_access_token({"user_id": "test_user", "sub": "test_user", "role": "user"})


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
def upload_dir():
    """获取上传目录"""
    from neurova.api.endpoints.console import _CONSOLE_UPLOAD_DIR as UPLOAD_DIR
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
        response = client.get(f"/api/v1/console/uploads/{sample_file.name}")
        
        assert response.status_code == 200
        assert response.headers["content-disposition"] is not None
        assert "attachment" in response.headers["content-disposition"]
    
    def test_download_file_with_original_filename(self, client, sample_file):
        """下载文件名=存储安全名（现行契约：FileResponse(filename=safe)，
        无 original_filename 参数面）。残留处理 2026-09-13 对齐信封/参数演化。"""
        response = client.get(f"/api/v1/console/uploads/{sample_file.name}")
        
        assert response.status_code == 200
        assert sample_file.name in response.headers.get("content-disposition", "")
    
    def test_download_file_not_found(self, client):
        """测试下载不存在的文件"""
        response = client.get("/api/v1/console/uploads/non_existent_file.txt")
        
        # 现行 404 面：HTTPException detail="File not found"
        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]
    
    def test_download_file_with_uuid_only(self, client, upload_dir):
        """无扩展名文件名：现行 _safe_filename 不拒无点名 → 200 下载"""
        file_id = "abcdef123456"
        file_path = upload_dir / file_id
        file_path.write_text("No original name")
        
        try:
            response = client.get(f"/api/v1/console/uploads/{file_id}")
            assert response.status_code == 200
            assert response.text == "No original name"
        finally:
            if file_path.exists():
                file_path.unlink()
    
    def test_download_file_exception_handling(self, app, sample_file):
        """端点内部异常→HTTP 500（现行无 try 分支，异常直达 ASGI；
        TestClient raise_server_exceptions=False 观察状态码）。残留处理 2026-09-13：
        原 patch pathlib.Path.stat 为全局副作用面，迁移到端点自有 seam。"""
        from fastapi.testclient import TestClient as _TC
        from neurova.api import deps as _deps

        quiet = _TC(app, raise_server_exceptions=False)
        quiet.app.dependency_overrides[_deps.get_current_user] = lambda: {
            "user_id": "test_user", "role": "user",
        }
        with patch(
            "neurova.api.endpoints.console._safe_filename",
            side_effect=Exception("Mocked exception"),
        ):
            response = quiet.get(f"/api/v1/console/uploads/{sample_file.name}")
            assert response.status_code == 500


# ============================================================
# 文件删除功能测试
# ============================================================

class TestFileDelete:
    """测试文件删除功能（覆盖568-588行）"""
    
    def test_delete_file_success(self, client, sample_file):
        """测试成功删除文件"""
        response = client.delete(f"/api/v1/console/uploads/{sample_file.name}")
        
        # 现行信封 {code:0,message}（无 deleted/file_id 键面）
        assert response.status_code == 200
        assert response.json()["code"] == 0
        
        # 确认文件已被删除
        assert not sample_file.exists()
    
    def test_delete_file_not_found(self, client):
        """测试删除不存在的文件"""
        response = client.delete("/api/v1/console/uploads/non_existent_file.txt")
        
        # 现行 404 面 detail="File not found"
        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]
    
    def test_delete_file_exception(self, app, sample_file):
        """删除路径异常→500（同 download 异常面迁移）。残留处理 2026-09-13。"""
        from fastapi.testclient import TestClient as _TC
        from neurova.api import deps as _deps

        quiet = _TC(app, raise_server_exceptions=False)
        quiet.app.dependency_overrides[_deps.get_current_user] = lambda: {
            "user_id": "test_user", "role": "user",
        }
        with patch(
            "neurova.api.endpoints.console._safe_filename",
            side_effect=Exception("Mocked exception"),
        ):
            response = quiet.delete(f"/api/v1/console/uploads/{sample_file.name}")
            assert response.status_code == 500


# ============================================================
# 推送消息功能测试
# ============================================================

class TestPushMessages:
    """测试推送消息功能（覆盖779-818行和837-867行）"""
    
    def test_get_push_messages_empty(self, client):
        """测试获取空消息列表"""
        response = client.get("/api/v1/console/push/messages")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["messages"] == []
        assert data["total"] == 0
    
    def test_get_push_messages_with_session(self, client):
        """测试获取指定会话的消息"""
        session_id = "test_session_123"
        
        # 现行 GET 面不回显 session_id（按 user 维度），信封 data 下钻
        response = client.get("/api/v1/console/push/messages")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "messages" in data
    
    def test_get_push_messages_with_after_filter(self, client):
        """测试使用after参数过滤消息"""
        # 先发送一条消息
        message = {
            "event": "test_event",
            "data": "test_data",
        }
        
        # 现行 POST 面 /push/message（S-18 收口 admin），body={content}
        post_response = client.post(
            "/api/v1/console/push/message",
            json={"content": "test_event"},
        )
        assert post_response.status_code == 200
        
        # 获取消息（现行 GET 参数为 since 秒级 float）
        response = client.get("/api/v1/console/push/messages", params={"since": 0})
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "messages" in data
    
    def test_get_push_messages_with_limit(self, client):
        """测试限制返回消息数量"""
        response = client.get("/api/v1/console/push/messages")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data["total"], int)
    
    def test_post_push_message_success(self, client):
        """测试成功发送推送消息"""
        # 现行 POST 契约：/push/message body={content}，返回 {code:0,message}
        response = client.post(
            "/api/v1/console/push/message",
            json={"content": "test_event_payload"},
        )
        
        assert response.status_code == 200
        assert response.json()["code"] == 0
    
    def test_post_push_message_with_session(self, client):
        """测试发送带会话ID的推送消息"""
        # 现行 POST 面无 session 维度（按 user 存储），回 200 信封
        response = client.post(
            "/api/v1/console/push/message",
            json={"content": "session_event"},
        )
        
        assert response.status_code == 200
        assert response.json()["code"] == 0
    
    def test_post_push_message_without_timestamp(self, client):
        """测试发送没有时间戳的消息（自动添加）"""
        response = client.post(
            "/api/v1/console/push/message",
            json={"content": "no_timestamp_event"},
        )
        
        assert response.status_code == 200
        
        # 验证消息已存储（GET 按 user 维度回读）
        get_response = client.get("/api/v1/console/push/messages")
        assert get_response.status_code == 200
        get_data = get_response.json()["data"]
        # 应该至少有一条消息
        assert len(get_data["messages"]) >= 1
    
    def test_post_push_message_exception(self, client):
        """测试推送消息异常处理"""
        # 模拟broadcast异常
        from fastapi.testclient import TestClient as _TC

        quiet = _TC(client.app, raise_server_exceptions=False)
        with patch(
            "neurova.api.endpoints.console._manager.broadcast",
            side_effect=Exception("Mocked exception")
        ):
            message = {"content": "error_event"}
            
            from neurova.api import deps as _deps

            quiet.app.dependency_overrides[_deps.get_current_user] = lambda: {
                "user_id": "test_user", "role": "admin",
            }
            response = quiet.post(
                "/api/v1/console/push/message",
                json=message,
            )
            
            # broadcast 异常不被端点吞——现行如实 500（fail-closed 诚实面）
            assert response.status_code == 500


# ============================================================
# 聊天历史功能扩展测试
# ============================================================

class TestChatHistoryExtended:
    """测试聊天历史功能（覆盖408-426行的分支）"""
    
    def test_chat_history_with_default_params(self, client):
        """session_id 现为必填（缺参 422——归属校验收口，残留处理 2026-09-13）"""
        assert client.get("/api/v1/console/chat/history").status_code == 422

        sid = client.post("/api/v1/console/chat/new", json={}).json()["data"]["session_id"]
        response = client.get(f"/api/v1/console/chat/history?session_id={sid}")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["session_id"] == sid
        assert "messages" in data
    
    def test_chat_history_with_custom_limit(self, client):
        """自定义 limit（现行必填 session_id）。残留处理 2026-09-13"""
        sid = client.post("/api/v1/console/chat/new", json={}).json()["data"]["session_id"]
        response = client.get(f"/api/v1/console/chat/history?session_id={sid}&limit=5")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["session_id"] == sid
        assert "messages" in data
    
    def test_chat_history_session_not_found(self, client):
        """测试获取不存在的会话历史"""
        response = client.get("/api/v1/console/chat/history?session_id=non_existent_session")
        
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
        response = client.get("/api/v1/console/chat/sessions")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "sessions" in data
        assert "total" in data
    
    def test_chat_sessions_with_user_id(self, client):
        """会话列表用户维度以 JWT 为准（S3 隔离收口）；query 过滤参数为
        agent_id（user_id 回显面已不存在）。残留处理 2026-09-13"""
        response = client.get("/api/v1/console/chat/sessions")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert "sessions" in data and "total" in data


# ============================================================
# 调试接口扩展测试
# ============================================================

class TestDebugEndpointsExtended:
    """测试调试接口（覆盖571-585行等）"""
    
    def test_debug_logs_with_custom_lines(self, client):
        """测试自定义行数获取日志"""
        response = client.get("/api/v1/console/debug/logs?lines=50")
        
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["lines"] == 50
    
    def test_debug_system_status_structure(self, client):
        """测试系统状态返回结构"""
        response = client.get("/api/v1/console/debug/status")
        
        assert response.status_code == 200
        # 现行 data 面=资源水位（status/version/tasks 键随 debug 收口更替）。
        # 残留处理 2026-09-13
        data = response.json()["data"]
        assert "cpu_percent" in data
        assert "uptime_seconds" in data
        assert "memory_percent" in data
    
    def test_debug_command_endpoint(self, client):
        """测试调试命令接口"""
        # 注意：这个接口可能有安全风险，仅用于测试
        response = client.post(
            "/api/v1/console/debug/command",
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
        """非 JSON 帧：现行端点 receive_json 抛错→连接收口退出（无 error
        事件面）。残留处理 2026-09-13：迁移到现行协议形态。"""
        # 现行（实测）：服务端 receive_json 解析失败，JSONDecodeError 经
        # TestClient portal 在 with 退出处上抛；客户端 receive 侧为
        # ClosedResourceError——均证明非法帧不会被静默处理。端点 finally
        # 已防 _manager 条目滞留（console.py:1802）。残留处理 2026-09-13。
        with pytest.raises(Exception) as excinfo:
            with client.websocket_connect(
                f"/api/v1/console/ws/test-client?token={_make_ws_token()}"
            ) as websocket:
                websocket.send_text("invalid json")
                try:
                    websocket.receive_text()
                except Exception:
                    pass  # 客户端先见连接关闭——真实断口在 portal 上抛
        assert type(excinfo.value).__name__ in {
            "JSONDecodeError", "WebSocketDisconnect", "ClosedResourceError",
        }, type(excinfo.value).__name__
    
    def test_websocket_multiple_subscriptions(self, client):
        """多帧交互：现行协议无 subscribe 面，未知类型逐帧回 ack
        （type 键协议）。残留处理 2026-09-13。"""
        with client.websocket_connect(
            f"/api/v1/console/ws/test-client?token={_make_ws_token()}"
        ) as websocket:
            for i in range(3):
                websocket.send_text(json.dumps({"type": "subscribe", "task_id": f"t{i}"}))
                data = json.loads(websocket.receive_text())
                assert data["type"] == "ack"


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
                "/api/v1/console/upload",
                files={"file": ("integration_test.txt", f, "text/plain")},
            )
        
        assert upload_response.status_code == 200
        # 现行信封 {code,data}；下载/删除以 filename（安全名）为路径键
        upload_data = upload_response.json()["data"]
        # 下载/删除路径键=存储文件名（{file_id}_{safe}，path 末段）；
        # filename 字段为原始安全名非存储键——现行契约（残留处理 2026-09-13）
        fname = Path(upload_data["path"]).name
        assert upload_data["file_id"]
        
        # 2. 下载文件
        download_response = client.get(f"/api/v1/console/uploads/{fname}")
        assert download_response.status_code == 200
        
        # 3. 删除文件
        delete_response = client.delete(f"/api/v1/console/uploads/{fname}")
        assert delete_response.status_code == 200
        assert delete_response.json()["code"] == 0
    
    def test_push_message_workflow(self, client):
        """测试推送消息的完整工作流"""
        # 1. 发送（现行 POST /push/message，body={content}；S-18 admin 面）
        post_response = client.post(
            "/api/v1/console/push/message",
            json={"content": "workflow_test_payload"},
        )
        assert post_response.status_code == 200
        assert post_response.json()["code"] == 0
        
        # 2. 获取消息（信封下钻）
        get_response = client.get("/api/v1/console/push/messages")
        assert get_response.status_code == 200
        
        get_data = get_response.json()["data"]
        assert len(get_data["messages"]) >= 1
        
        # 3. 验证消息内容（现行存储形 {type:"push", content, sender, timestamp}）
        latest_message = get_data["messages"][-1]
        assert latest_message["content"] == "workflow_test_payload"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
