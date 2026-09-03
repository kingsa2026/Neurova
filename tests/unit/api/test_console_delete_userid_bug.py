"""
chat.deleteSessionFailed bug 修复 TDD 测试

Bug: 会话列表不能删除会话
根因: console.py delete_chat_session 端点的 user_id 校验用严格相等
      (`target[0].get("user_id") != user_id`), 而老 session 文件没有
      user_id 字段 (get 返回 None), _get_user_id 默认返回 "anonymous",
      None != "anonymous" → 403 Forbidden.

矛盾点:
  - list_sessions 端点的 SessionManager.list_sessions 用宽松过滤
    (`if user_id and s_user_id and s_user_id != user_id: continue`),
    空 user_id 视为"共享", 所有用户可见
  - delete_chat_session 端点用严格相等, 空 user_id 视为"不属于任何人",
    谁都不能删
  → "看得到删不掉" 死锁

修复: delete 端点的 user_id 校验与 list 端点一致 — 空 user_id 视为共享.

测试策略 (TDD vertical slice):
  Slice 1: session.user_id 为 None (字段缺失) → 允许任何已认证用户删除
  Slice 2: session.user_id 为 "" (空字符串) → 允许任何已认证用户删除
  Slice 3: session.user_id="alice" + 调用者 "bob" → 403 (权限拒绝保持)
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
def app():
    """创建测试应用 (无 memory / channels, 减少干扰)."""
    return create_app(enable_memory=False, enable_channels=False)


@pytest.fixture
def client(app):
    """创建 TestClient."""
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
    with patch("neurova.api.endpoints.console.get_session_repository", return_value=mock):
        yield mock


# ============================================================
# Slice 1: session.user_id 缺失 (None) → 允许任何已认证用户删除
# ============================================================

class TestDeleteSessionWithoutUserIdField:
    """老 session 文件没有 user_id 字段 → DELETE 应成功 (非 403)."""

    def test_session_with_missing_user_id_field_is_deletable(
        self, client, mock_repo
    ):
        """RED: list_sessions 返回无 user_id 字段的 session,
        DELETE 应返回 200, 不应因 user_id 不匹配而 403.

        复现: auto-acfca5ef8ca0 是 2026-07-09 创建的老 session,
        session 文件无 user_id 字段, _get_user_id(request)="anonymous".
        """
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

        # 调用 DELETE — _get_user_id 默认 "anonymous"
        response = client.delete("/api/v1/console/chat/sessions/auto-old-001")

        # 修复后契约: 200 (而非 403)
        assert response.status_code == 200, (
            f"老 session (无 user_id 字段) 应可删除, 实际 status={response.status_code}, "
            f"body={response.text}. 根因: delete 端点 user_id 校验与 list 端点不一致."
        )
        # repo.delete_session 应被调用
        mock_repo.delete_session.assert_called_once_with(
            agent_id="yi_ling", session_id="auto-old-001"
        )


# ============================================================
# Slice 2: session.user_id 为空字符串 → 允许删除
# ============================================================

class TestDeleteSessionWithEmptyUserId:
    """session.user_id == "" → DELETE 应成功 (与 list 端点宽松过滤一致)."""

    def test_session_with_empty_user_id_is_deletable(self, client, mock_repo):
        """RED: session.user_id="" (空字符串) 时应允许删除.

        与 SessionManager.list_sessions line 598 逻辑一致:
          `if user_id and s_user_id and s_user_id != user_id: continue`
        空 s_user_id 不过滤 (共享), delete 也应允许.
        """
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
            f"session.user_id='' 应可删除 (与 list 端点宽松过滤一致), "
            f"实际 status={response.status_code}, body={response.text}"
        )
        mock_repo.delete_session.assert_called_once()


# ============================================================
# Slice 3: user_id 不匹配 (均非空) → 403 (权限拒绝保持)
# ============================================================

class TestDeleteSessionUserIdMismatch:
    """session.user_id="alice" + 调用者 "bob" → 403 Forbidden.

    回归保护: 修复 user_id 一致性后, 真正的不匹配仍应拒绝.
    """

    def test_session_with_mismatched_non_empty_user_id_returns_403(
        self, client, mock_repo
    ):
        """session 属于 alice, bob 调用 DELETE → 403 (权限拒绝保持)."""
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
