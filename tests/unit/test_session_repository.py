"""
SessionRepository 统一接口 TDD 测试

候选 #3：定义 SessionRepository ABC，SessionManager 实现之。
验证：
- ABC 存在，定义 7 个抽象方法
- SessionManager 实现 SessionRepository（isinstance 检查）
- 接口方法签名符合契约
- 工厂函数 get_session_repository() 返回 SessionRepository 实例
"""
from __future__ import annotations

import inspect
from abc import ABC
from typing import Optional, List, Dict, Any
from unittest.mock import patch

import pytest


# ============================================================
# 1. SessionRepository ABC 存在性与结构
# ============================================================

class TestSessionRepositoryABCStructure:
    """验证 SessionRepository ABC 定义正确"""

    def test_abc_exists_and_is_abstract(self):
        """RED: neurova.session_repository 模块存在 SessionRepository ABC"""
        from neurova.session_repository import SessionRepository
        assert inspect.isabstract(SessionRepository), "SessionRepository 必须是抽象类"
        assert issubclass(SessionRepository, ABC)

    def test_required_abstract_methods_defined(self):
        """RED: SessionRepository 必须定义 7 个抽象方法"""
        from neurova.session_repository import SessionRepository
        expected = {
            "create_session",
            "save_message",
            "get_history",
            "list_sessions",
            "delete_session",
            "rename_session",
            "get_session",
        }
        actual = set(SessionRepository.__abstractmethods__)
        missing = expected - actual
        assert not missing, f"SessionRepository 缺少抽象方法: {missing}"

    def test_create_session_signature(self):
        """RED: create_session(agent_id, user_id='', title='') -> str"""
        from neurova.session_repository import SessionRepository
        sig = inspect.signature(SessionRepository.create_session)
        params = set(sig.parameters.keys())
        assert {"agent_id", "user_id", "title"}.issubset(params), \
            f"create_session 参数缺失: {params}"
        # from __future__ import annotations 让注解变为字符串 'str'
        assert sig.return_annotation in (str, "str"), \
            f"create_session 返回类型应为 str，实际 {sig.return_annotation!r}"

    def test_save_message_signature(self):
        """RED: save_message(agent_id, session_id, role, content, metadata=None) -> bool"""
        from neurova.session_repository import SessionRepository
        sig = inspect.signature(SessionRepository.save_message)
        params = set(sig.parameters.keys())
        assert {"agent_id", "session_id", "role", "content", "metadata"}.issubset(params), \
            f"save_message 参数缺失: {params}"

    def test_get_history_signature(self):
        """RED: get_history(agent_id, session_id, max_messages=0) -> List[Dict]"""
        from neurova.session_repository import SessionRepository
        sig = inspect.signature(SessionRepository.get_history)
        params = set(sig.parameters.keys())
        assert {"agent_id", "session_id", "max_messages"}.issubset(params), \
            f"get_history 参数缺失: {params}"

    def test_list_sessions_signature(self):
        """RED: list_sessions(agent_id='', user_id='') -> List[Dict]"""
        from neurova.session_repository import SessionRepository
        sig = inspect.signature(SessionRepository.list_sessions)
        params = set(sig.parameters.keys())
        assert {"agent_id", "user_id"}.issubset(params), \
            f"list_sessions 参数缺失: {params}"


# ============================================================
# 2. SessionManager 实现 SessionRepository
# ============================================================

class TestSessionManagerImplementsRepository:
    """验证 SessionManager 类声明实现 SessionRepository"""

    def test_session_manager_is_subclass(self):
        """RED: SessionManager 必须是 SessionRepository 的子类"""
        from neurova.session_repository import SessionRepository
        from neurova.session_manager import SessionManager
        assert issubclass(SessionManager, SessionRepository), \
            "SessionManager 必须声明实现 SessionRepository"

    def test_session_manager_instance_is_repository(self):
        """RED: SessionManager 实例 isinstance(SessionRepository) 为 True"""
        from neurova.session_repository import SessionRepository
        from neurova.session_manager import SessionManager
        # 单例可能被其他测试污染，用 __new__ 强制新实例
        sm = object.__new__(SessionManager)
        assert isinstance(sm, SessionRepository)

    def test_session_manager_has_all_methods(self):
        """RED: SessionManager 必须实现所有抽象方法（不仍是 abstract）"""
        from neurova.session_repository import SessionRepository
        from neurova.session_manager import SessionManager
        # SessionManager 必须不是抽象类
        assert not inspect.isabstract(SessionManager), \
            "SessionManager 仍有未实现的抽象方法"


# ============================================================
# 3. 工厂函数 get_session_repository
# ============================================================

class TestSessionFactory:
    """验证依赖注入点存在"""

    def test_get_session_repository_exists(self):
        """RED: neurova.session_repository 必须提供 get_session_repository() 工厂"""
        from neurova.session_repository import get_session_repository
        assert callable(get_session_repository)

    def test_get_session_repository_returns_repository(self):
        """RED: get_session_repository() 返回 SessionRepository 实例"""
        from neurova.session_repository import SessionRepository, get_session_repository
        repo = get_session_repository()
        assert isinstance(repo, SessionRepository), \
            f"get_session_repository 返回类型 {type(repo)}，应为 SessionRepository"

    def test_get_session_repository_is_singleton(self):
        """RED: 多次调用返回同一实例（单例）"""
        from neurova.session_repository import get_session_repository
        r1 = get_session_repository()
        r2 = get_session_repository()
        assert r1 is r2, "get_session_repository 应返回单例"


# ============================================================
# 4. SessionManager 通过接口的行为测试（端到端）
# ============================================================

class TestSessionManagerViaInterface:
    """通过 SessionRepository 接口测试 SessionManager 行为"""

    @pytest.fixture
    def isolated_repo(self, tmp_path):
        """隔离的 SessionManager 实例（指向 tmp_path）

        注意: 用 object.__new__ 绕过单例 __init__,必须手动初始化所有 __init__ 中
        创建的实例属性,包括 S3 新增的 _file_locks_lock (RLock). 遗漏会导致
        _get_file_lock 调用 with self._file_locks_lock 时 AttributeError.
        """
        from neurova.session_manager import SessionManager
        from neurova.session_repository import SessionRepository
        from threading import RLock
        sm = object.__new__(SessionManager)
        sm._initialized = True
        sm._sessions_dir = tmp_path / "sessions"
        sm._sessions_dir.mkdir(exist_ok=True)
        sm._file_locks = {}
        # S3 修复补全: __init__ 新增的 _file_locks_lock 必须在此同步初始化
        sm._file_locks_lock = RLock()
        assert isinstance(sm, SessionRepository)
        return sm

    def test_create_session_returns_string_id(self, isolated_repo):
        """RED: create_session 返回字符串 session_id"""
        sid = isolated_repo.create_session(agent_id="test-agent", user_id="u1", title="测试")
        assert isinstance(sid, str) and len(sid) > 0

    def test_save_message_single_role(self, isolated_repo):
        """RED: save_message 保存单条消息（不要求 user+assistant 配对）"""
        sid = isolated_repo.create_session(agent_id="test-agent")
        ok1 = isolated_repo.save_message("test-agent", sid, "user", "你好")
        ok2 = isolated_repo.save_message("test-agent", sid, "assistant", "你好，有什么可以帮你？")
        assert ok1 and ok2

    def test_get_history_returns_all_messages(self, isolated_repo):
        """RED: get_history 返回所有消息"""
        sid = isolated_repo.create_session(agent_id="test-agent")
        isolated_repo.save_message("test-agent", sid, "user", "第一条")
        isolated_repo.save_message("test-agent", sid, "assistant", "回复1")
        isolated_repo.save_message("test-agent", sid, "user", "第二条")
        isolated_repo.save_message("test-agent", sid, "assistant", "回复2")
        history = isolated_repo.get_history("test-agent", sid)
        assert len(history) == 4, f"期望 4 条历史，实际 {len(history)}"

    def test_list_sessions_by_agent(self, isolated_repo):
        """RED: list_sessions 按 agent_id 过滤"""
        sid1 = isolated_repo.create_session(agent_id="agent-A")
        sid2 = isolated_repo.create_session(agent_id="agent-A")
        sid3 = isolated_repo.create_session(agent_id="agent-B")
        sessions_a = isolated_repo.list_sessions(agent_id="agent-A")
        sessions_b = isolated_repo.list_sessions(agent_id="agent-B")
        assert len(sessions_a) == 2, f"agent-A 应有 2 个会话，实际 {len(sessions_a)}"
        assert len(sessions_b) == 1

    def test_rename_session(self, isolated_repo):
        """RED: rename_session 修改会话标题"""
        sid = isolated_repo.create_session(agent_id="test-agent", user_id="u1", title="原名")
        ok = isolated_repo.rename_session("test-agent", sid, "新名")
        assert ok
        session = isolated_repo.get_session("test-agent", sid)
        # SessionRecord 应有 title 字段（或通过 list_sessions 验证）
        sessions = isolated_repo.list_sessions(agent_id="test-agent")
        target = [s for s in sessions if s.get("session_id") == sid or s.get("id") == sid][0]
        assert target.get("title") == "新名", f"重命名失败: {target}"

    def test_delete_session(self, isolated_repo):
        """RED: delete_session 删除会话"""
        sid = isolated_repo.create_session(agent_id="test-agent")
        isolated_repo.save_message("test-agent", sid, "user", "test")
        ok = isolated_repo.delete_session("test-agent", sid)
        assert ok
        # 删除后历史应为空
        history = isolated_repo.get_history("test-agent", sid)
        assert len(history) == 0


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
