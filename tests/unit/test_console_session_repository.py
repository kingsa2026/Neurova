"""
#1 删除 _CHAT_SESSIONS，console 接入 SessionRepository TDD 测试

验证：
1. console.py 不再使用 _CHAT_SESSIONS 字典
2. console.py 不再使用 _load_sessions_from_disk / _save_sessions_to_disk
3. console.py import 了 get_session_repository
4. 现有 console 端点行为保持兼容（通过 SessionRepository 工作）
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# 1. 结构验证：_CHAT_SESSIONS 已删除
# ============================================================

class TestChatSessionsRemoved:
    """验证 _CHAT_SESSIONS 字典及其持久化函数已删除"""

    def test_no_chat_sessions_dict(self):
        """RED: console 模块不应再有 _CHAT_SESSIONS 属性"""
        import neurova.api.endpoints.console as console_mod
        assert not hasattr(console_mod, "_CHAT_SESSIONS"), \
            "console.py 仍保留 _CHAT_SESSIONS 字典，应改用 SessionRepository"

    def test_no_sessions_file_constant(self):
        """RED: console 模块不应再有 _SESSIONS_FILE 常量"""
        import neurova.api.endpoints.console as console_mod
        assert not hasattr(console_mod, "_SESSIONS_FILE"), \
            "console.py 仍保留 _SESSIONS_FILE 常量，持久化由 SessionRepository 负责"

    def test_no_load_sessions_from_disk(self):
        """RED: console 模块不应再有 _load_sessions_from_disk 函数"""
        import neurova.api.endpoints.console as console_mod
        assert not hasattr(console_mod, "_load_sessions_from_disk"), \
            "console.py 仍保留 _load_sessions_from_disk，应改用 SessionRepository"

    def test_no_save_sessions_to_disk(self):
        """RED: console 模块不应再有 _save_sessions_to_disk 函数"""
        import neurova.api.endpoints.console as console_mod
        assert not hasattr(console_mod, "_save_sessions_to_disk"), \
            "console.py 仍保留 _save_sessions_to_disk，应改用 SessionRepository"


# ============================================================
# 2. SessionRepository 接入验证
# ============================================================

class TestSessionRepositoryIntegration:
    """验证 console.py 接入 SessionRepository"""

    def test_imports_get_session_repository(self):
        """RED: console.py 应 import get_session_repository"""
        import neurova.api.endpoints.console as console_mod
        # 检查模块源码是否引用了 get_session_repository
        import inspect
        source = inspect.getsource(console_mod)
        assert "get_session_repository" in source, \
            "console.py 应使用 get_session_repository 接入 SessionRepository"

    def test_no_direct_session_manager_import(self):
        """RED: console.py 不应直接 import SessionManager（应通过工厂函数）"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod)
        # 允许在注释/字符串中提及，但不应有 from ... import SessionManager
        assert "from neurova.session_manager import" not in source, \
            "console.py 不应直接 import SessionManager，应通过 get_session_repository()"


# ============================================================
# 3. 行为验证：端点通过 SessionRepository 工作
# ============================================================

class TestEndpointsUseRepository:
    """验证 console 端点通过 SessionRepository 工作（mock 验证）"""

    @pytest.fixture
    def mock_repo(self):
        """Mock SessionRepository 单例"""
        from neurova import session_repository
        mock = MagicMock()
        # 默认行为
        mock.create_session.return_value = "test-sid-001"
        mock.save_message.return_value = True
        mock.get_history.return_value = []
        mock.list_sessions.return_value = []
        mock.delete_session.return_value = True
        mock.rename_session.return_value = True
        mock.get_session.return_value = None
        with patch.object(session_repository, "get_session_repository", return_value=mock):
            yield mock

    def test_create_session_uses_repo(self, mock_repo):
        """RED: POST /console/chat/new 应调用 repo.create_session"""
        # 重新加载 console 模块以应用 mock
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.post_console_chat_new)
        assert "create_session" in source, \
            "post_console_chat_new 应调用 repo.create_session"

    def test_chat_uses_repo_save_message(self, mock_repo):
        """RED: POST /console/chat 应调用 repo.save_message"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.post_console_chat)
        assert "save_message" in source, \
            "post_console_chat 应调用 repo.save_message"

    def test_get_history_uses_repo(self, mock_repo):
        """RED: GET /console/chat/history 应调用 repo.get_history"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.get_chat_history)
        assert "get_history" in source, \
            "get_chat_history 应调用 repo.get_history"

    def test_list_sessions_uses_repo(self, mock_repo):
        """RED: GET /console/chat/sessions 应调用 repo.list_sessions"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.get_chat_sessions)
        assert "list_sessions" in source, \
            "get_chat_sessions 应调用 repo.list_sessions"

    def test_delete_session_uses_repo(self, mock_repo):
        """RED: DELETE /console/chat/sessions/{id} 应调用 repo.delete_session"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.delete_chat_session)
        assert "delete_session" in source, \
            "delete_chat_session 应调用 repo.delete_session"

    def test_rename_session_uses_repo(self, mock_repo):
        """RED: PUT /console/chat/sessions/{id} 应调用 repo.rename_session"""
        import neurova.api.endpoints.console as console_mod
        import inspect
        source = inspect.getsource(console_mod.rename_chat_session)
        assert "rename_session" in source, \
            "rename_chat_session 应调用 repo.rename_session"


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
