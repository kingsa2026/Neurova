"""控制台删除端点的历史无主会话属主契约。

旧文件缺失 `user_id` 或显式空字符串时，不再按"共享会话"放行任意认证用户；
读取边界统一解析为 `role=admin` 中 id 最小者，删除校验与该读侧事实一致：

- 主管理员可删除历史无主会话；
- 普通用户删除历史无主会话返回 403；
- 显式属主不匹配仍返回 403。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def app(monkeypatch):
    """创建测试应用 (无 memory / channels, 减少干扰)."""
    from neurova import post_chat_pipeline

    monkeypatch.setattr(post_chat_pipeline, "_adminOwnerId", lambda: "u1")
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """创建 TestClient（console 端点鉴权收紧后注入测试身份）。"""
    from neurova.api.deps import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin"}
    return TestClient(app)


@pytest.fixture
def mock_repo():
    """Mock SessionRepository 单例.

    patch 路径必须是 `neurova.api.endpoints.console.get_session_repository`
    (console.py 用 `from neurova.session_repository import get_session_repository`
    把函数对象绑定到本模块, patch session_repository 模块属性不会生效).

    默认行为:
      - list_sessions 返回单个 session (可被测试覆盖)
      - delete_session 返回 True
      - 其他方法返回安全默认值
    """
    mock = MagicMock()
    mock.create_session.return_value = "new-sid"
    mock.save_message.return_value = True
    mock.get_history.return_value = []
    mock.list_sessions.return_value = []
    mock.delete_session.return_value = True
    mock.rename_session.return_value = True
    mock.get_session.return_value = None

    # 2026-09-10: 适配既有 P1-F4 契约（delete/auto-title/archive 端点已改用
    # find_session 索引式定位, 见 HEAD console.py）。原桩仅播种 list_sessions,
    # find_session 落到 MagicMock → 恒非空且 user_id 比对失真 → 预存 403/404 假失败。
    def _find_session(session_id):
        for s in mock.list_sessions.return_value:
            if (s.get("session_id") or s.get("id")) == session_id:
                return s
        return None

    mock.find_session.side_effect = _find_session
    with patch("neurova.api.endpoints.console.get_session_repository", return_value=mock):
        yield mock


# ============================================================
# Slice 1: session.user_id 缺失 (None) → 主管理员可删除
# ============================================================

class TestDeleteSessionWithoutUserIdField:
    """老 session 文件没有 user_id 字段 → 按主管理员归属校验。"""

    def test_session_with_missing_user_id_field_is_deletable(
        self, client, mock_repo
    ):
        """历史无字段会话解析到主管理员 u1，DELETE 应返回 200。"""
        # 模拟老 session 文件 — 无 user_id 字段
        mock_repo.list_sessions.return_value = [
            {
                "session_id": "auto-old-001",
                "id": "auto-old-001",
                "agent_id": "yi_ling",
                "title": "老会话",
                # 注意: 没有 "user_id" 键
                "created_at": "2026-07-09T09:12:46",
            }
        ]

        response = client.delete("/api/v1/console/chat/sessions/auto-old-001")

        assert response.status_code == 200, (
            f"主管理员应能删除历史无主会话, 实际 status={response.status_code}, "
            f"body={response.text}."
        )
        # repo.delete_session 应被调用
        mock_repo.delete_session.assert_called_once_with(
            agent_id="yi_ling", session_id="auto-old-001"
        )


# ============================================================
# Slice 2: session.user_id 为空字符串 → 主管理员可删除
# ============================================================

class TestDeleteSessionWithEmptyUserId:
    """session.user_id == "" → 按主管理员归属校验。"""

    def test_session_with_empty_user_id_is_deletable(self, client, mock_repo):
        """空属主解析到主管理员 u1，DELETE 应返回 200。"""
        mock_repo.list_sessions.return_value = [
            {
                "session_id": "sess-empty-uid",
                "id": "sess-empty-uid",
                "agent_id": "yi_ling",
                "title": "空 user_id 会话",
                "user_id": "",  # 显式空字符串
                "created_at": "2026-07-10T10:00:00",
            }
        ]

        response = client.delete("/api/v1/console/chat/sessions/sess-empty-uid")

        assert response.status_code == 200, (
            f"主管理员应能删除空属主会话, "
            f"实际 status={response.status_code}, body={response.text}"
        )
        mock_repo.delete_session.assert_called_once()

    def test_ownerless_session_is_forbidden_for_non_admin(self, client, mock_repo):
        from neurova.api.deps import get_current_user

        mock_repo.list_sessions.return_value = [
            {"session_id": "sess-empty-uid", "agent_id": "yi_ling", "user_id": ""}
        ]
        client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "bob", "role": "user"
        }
        response = client.delete("/api/v1/console/chat/sessions/sess-empty-uid")
        assert response.status_code == 403
        mock_repo.delete_session.assert_not_called()


# ============================================================
# Slice 3: user_id 不匹配 (均非空) → 403 (权限拒绝保持)
# ============================================================

class TestDeleteSessionUserIdMismatch:
    """session.user_id="alice" + 调用者 "u1" → 403 Forbidden。"""

    def test_session_with_mismatched_non_empty_user_id_returns_403(
        self, client, mock_repo
    ):
        """显式属主不匹配时仍拒绝删除。"""
        mock_repo.list_sessions.return_value = [
            {
                "session_id": "sess-alice-001",
                "id": "sess-alice-001",
                "agent_id": "yi_ling",
                "title": "alice 的会话",
                "user_id": "alice",  # 非空, 属于 alice
                "created_at": "2026-07-15T10:00:00",
            }
        ]

        # mock request.state.user_id = "bob" (与 alice 不匹配)
        # _get_user_id 调 getattr(request.state, "user_id", "anonymous")
        # TestClient 默认无 middleware 设置 user_id, 所以是 "anonymous"
        # 这里我们直接验证: 当 user_id 不匹配时 (无论 "anonymous" 还是 "bob")
        # 都应 403, 因为 session.user_id="alice" 非空.
        response = client.delete("/api/v1/console/chat/sessions/sess-alice-001")

        assert response.status_code == 403, (
            f"session.user_id='alice' 与调用者 user_id 不匹配时应 403, "
            f"实际 status={response.status_code}"
        )
        # repo.delete_session 不应被调用
        mock_repo.delete_session.assert_not_called()
