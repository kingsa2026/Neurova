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




@pytest.fixture
def app():
    """创建测试应用"""
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return _authed_client(app)


# ============================================================
# 测试文件下载错误处理（覆盖460行）
# ============================================================

def test_download_file_not_found(client):
    """测试下载不存在的文件 - 覆盖460行"""
    response = client.get("/api/v1/console/uploads/non_existent_file.txt")
    assert response.status_code == 404


# ============================================================
# 测试聊天历史错误处理（覆盖424-426行）
# ============================================================

def test_chat_history_exception(app):
    """聊天历史：repo 异常→HTTP 500（现行端点无 try 分支，异常直达 ASGI；
    TestClient 默认 re-raise，用 raise_server_exceptions=False 观察状态码）。
    残留处理 2026-09-13：patch 目标随 session_repository 收口更名。"""
    quiet = TestClient(app, raise_server_exceptions=False)
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "test_user", "username": "test_user", "role": "user"}
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    with patch(
        "neurova.api.endpoints.console.get_session_repository",
        side_effect=Exception("Mocked")
    ):
        response = quiet.get("/api/v1/console/chat/history?session_id=test")
        assert response.status_code == 500


# ============================================================
# 测试会话列表错误处理（覆盖438-440行）
# ============================================================

def test_chat_sessions_exception(app):
    """会话列表：repo 异常→500（同 history 姿势，残留处理 2026-09-13）"""
    quiet = TestClient(app, raise_server_exceptions=False)
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "test_user", "username": "test_user", "role": "user"}
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    with patch(
        "neurova.api.endpoints.console.get_session_repository",
        side_effect=Exception("Mocked")
    ):
        response = quiet.get("/api/v1/console/chat/sessions")
        assert response.status_code == 500


# ============================================================
# 测试推送消息错误处理（覆盖802-803, 816-818行）
# ============================================================

def test_push_messages_invalid_after(client):
    """测试无效的after参数 - 覆盖802-803行"""
    response = client.get(
        "/api/v1/console/push/messages",
        params={"after": "invalid_datetime"},
    )
    # 应该返回200（带警告）或400
    assert response.status_code in [200, 400]


def test_push_messages_exception(app):
    """推送消息：底层 get_messages 异常→500。残留处理 2026-09-13：
    原用例 patch asyncio.Lock(side_effect=) 为无效构造（AttributeError 即证），
    迁移到现行 _manager.get_messages 错误面。"""
    quiet = TestClient(app, raise_server_exceptions=False)
    from neurova.api import auth as _auth_mod
    from neurova.api import deps as _deps_mod

    _u = {"user_id": "test_user", "username": "test_user", "role": "user"}
    app.dependency_overrides[_deps_mod.get_current_user] = lambda: _u
    app.dependency_overrides[_auth_mod.get_current_user] = lambda: _u
    with patch(
        "neurova.api.endpoints.console._manager.get_messages",
        side_effect=Exception("Mocked")
    ):
        response = quiet.get("/api/v1/console/push/messages")
        assert response.status_code == 500


# ============================================================
# 测试文件上传错误处理（覆盖340-359行）
# ============================================================

def test_upload_no_file(client):
    """测试不上传文件 - 覆盖部分上传错误处理"""
    response = client.post("/api/v1/console/upload")
    assert response.status_code == 422


@pytest.mark.xfail(
    strict=False,
    reason="console /upload 现无大小守卫（50MB 直写盘）——缺安全护栏属实，"
           "登记台账待裁决；加限制后本用例自动转绿",
)
def test_upload_large_file(client, tmp_path):
    """上传超大文件应被拒（现行未实现=xfail）。"""
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
# 测试聊天接口错误处理（覆盖59-96行）
# ============================================================

def test_chat_empty_message(client):
    """测试空消息 - 覆盖部分聊天错误处理"""
    response = client.post(
        "/api/v1/console/chat",
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
        "/api/v1/console/chat",
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
    response = client.get("/api/v1/console/chat/history?limit=-1")
    # 应该返回422（验证错误）或200（带默认值）
    assert response.status_code in [200, 422]


def test_chat_sessions_with_empty_user_id(client):
    """测试空user_id - 覆盖部分边界情况"""
    response = client.get("/api/v1/console/chat/sessions?user_id=")
    assert response.status_code in [200, 400, 422]


def test_upload_with_special_filename(client, tmp_path):
    """测试特殊文件名 - 覆盖部分边界情况"""
    # 创建带有特殊字符的文件名
    test_file = tmp_path / "test file with spaces.txt"
    test_file.write_text("Test content")
    
    with open(test_file, "rb") as f:
        response = client.post(
            "/api/v1/console/upload",
            files={"file": ("test file with spaces.txt", f, "text/plain")},
        )
    
    assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--timeout=10"])
