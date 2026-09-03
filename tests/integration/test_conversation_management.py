"""
对话管理模块测试

验证三大组件的闭环：
1. SessionManager: 文件会话存储
2. ConversationBuffer: 内存对话缓冲
3. 端到端: 缓冲 -> 存储 -> 检索
"""
import pytest
import tempfile
import os
import shutil
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════
# 1. SessionManager 测试
# ═══════════════════════════════════════════════════════

class TestSessionManager:
    """SessionManager 文件存储测试"""

    @pytest.fixture
    def sm(self):
        """创建临时目录的 SessionManager"""
        from neurova.session_manager import SessionManager
        # 重置单例
        SessionManager._instance = None
        manager = SessionManager()
        tmpdir = tempfile.mkdtemp()
        manager._sessions_dir = __import__('pathlib').Path(tmpdir)
        yield manager
        shutil.rmtree(tmpdir, ignore_errors=True)
        SessionManager._instance = None

    def test_add_message_creates_session(self, sm):
        """添加消息创建新 session"""
        result = sm.add_message("agent_1", "sess_1", "Hello", "Hi there!")
        assert result == "agent_1_sess_1"

        record = sm.get_session("agent_1", "sess_1")
        assert len(record.messages) == 2
        assert record.messages[0].role == "user"
        assert record.messages[0].content == "Hello"
        assert record.messages[1].role == "assistant"
        assert record.messages[1].content == "Hi there!"

    def test_add_multiple_messages(self, sm):
        """多次添加消息"""
        sm.add_message("a1", "s1", "Q1", "A1")
        sm.add_message("a1", "s1", "Q2", "A2")
        sm.add_message("a1", "s1", "Q3", "A3")

        record = sm.get_session("a1", "s1")
        assert len(record.messages) == 6  # 3 user + 3 assistant

    def test_get_session_not_found(self, sm):
        """获取不存在的 session"""
        record = sm.get_session("a1", "nonexistent")
        assert record.messages == []

    def test_search_session(self, sm):
        """搜索 session 内容"""
        sm.add_message("a1", "s1", "Python programming", "Python is great")
        sm.add_message("a1", "s1", "Java cooking", "Java is okay")

        results = sm.search_session("a1", "s1", "Python")
        assert len(results) == 2  # user + assistant

    def test_search_session_no_match(self, sm):
        """搜索无匹配"""
        sm.add_message("a1", "s1", "Hello", "Hi")
        results = sm.search_session("a1", "s1", "xyz")
        assert len(results) == 0

    def test_delete_session(self, sm):
        """删除 session"""
        sm.add_message("a1", "s1", "Q", "A")
        assert sm.delete_session("a1", "s1") is True
        record = sm.get_session("a1", "s1")
        assert record.messages == []

    def test_get_sessions_by_agent(self, sm):
        """获取 agent 的所有 session"""
        sm.add_message("a1", "s1", "Q1", "A1")
        sm.add_message("a1", "s2", "Q2", "A2")
        sm.add_message("a2", "s3", "Q3", "A3")

        sessions = sm.get_sessions_by_agent("a1")
        assert len(sessions) == 2

    def test_create_session_returns_id(self, sm):
        """创建 session 返回 ID"""
        session_id = sm.create_session("a1")
        assert isinstance(session_id, str)
        assert len(session_id) == 8

    def test_get_session_stats(self, sm):
        """获取 session 统计"""
        sm.add_message("a1", "s1", "Q1", "A1")
        sm.add_message("a1", "s1", "Q2", "A2")

        stats = sm.get_session_stats("a1", "s1")
        assert stats["total_messages"] == 4  # 2 user + 2 assistant
        assert stats["total_files"] >= 1

    def test_session_isolation(self, sm):
        """不同 agent 的 session 隔离"""
        sm.add_message("agent_1", "s1", "Q1", "A1")
        sm.add_message("agent_2", "s1", "Q2", "A2")

        r1 = sm.get_session("agent_1", "s1")
        r2 = sm.get_session("agent_2", "s1")

        assert len(r1.messages) == 2
        assert len(r2.messages) == 2
        assert r1.messages[0].content == "Q1"
        assert r2.messages[0].content == "Q2"


# ═══════════════════════════════════════════════════════
# 2. ConversationBuffer 测试
# ═══════════════════════════════════════════════════════

class TestConversationBuffer:
    """ConversationBuffer 内存缓冲测试"""

    @pytest.fixture
    def buf(self):
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
        return ConversationBuffer(
            memory_limit_bytes=1024,
            turn_limit=5,
            timeout_seconds=3600,
        )

    def test_add_user_message(self, buf):
        """添加用户消息"""
        result = buf.add_user_message("Hello")
        assert result is True
        assert buf._buffer[0].content == "Hello"
        assert buf._buffer[0].classification == "user_message"

    def test_add_agent_message(self, buf):
        """添加 AI 回复"""
        buf.add_user_message("Hello")
        buf.add_agent_message("Hi there!")
        assert buf._buffer[1].content == "Hi there!"
        assert buf._buffer[1].classification == "agent_message"

    def test_turn_management(self, buf):
        """轮次管理"""
        buf.add_user_message("Q1")
        buf.add_agent_message("A1")
        buf.add_user_message("Q2")
        buf.add_agent_message("A2")

        stats = buf.get_stats()
        assert stats["current_turns"] == 2

    def test_is_full_memory_limit(self):
        """内存限制检测"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
        buf = ConversationBuffer(memory_limit_bytes=10, turn_limit=100, timeout_seconds=3600)
        buf.add_user_message("x" * 20)  # 20 bytes > 10 limit
        assert buf.is_full() is True

    def test_is_full_turn_limit(self):
        """轮次限制检测"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
        buf = ConversationBuffer(memory_limit_bytes=999999, turn_limit=2, timeout_seconds=3600)
        for i in range(3):
            buf.add_user_message("Q")
            buf.add_agent_message("A")
        assert buf.is_full() is True

    def test_flush_returns_items(self, buf):
        """刷新返回所有项"""
        buf.add_user_message("Q1")
        buf.add_agent_message("A1")

        items = buf.flush()
        assert len(items) == 2
        assert len(buf._buffer) == 0
        assert len(buf._turns) == 0

    def test_stats(self, buf):
        """统计信息"""
        buf.add_user_message("Hello")
        stats = buf.get_stats()
        assert stats["buffer_size"] == 1
        assert stats["total_bytes"] > 0


# ═══════════════════════════════════════════════════════
# 3. 端到端: 缓冲 -> 存储 -> 检索 闭环
# ═══════════════════════════════════════════════════════

class TestConversationE2E:
    """对话管理端到端闭环"""

    def test_buffer_to_session_loop(self):
        """缓冲 -> 刷新 -> 存储 -> 检索 闭环"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
        from neurova.session_manager import SessionManager
        import pathlib

        # 1. 创建缓冲区
        buf = ConversationBuffer(memory_limit_bytes=999999, turn_limit=100, timeout_seconds=3600)

        # 2. 模拟对话
        buf.add_user_message("我想学习Python")
        buf.add_agent_message("Python是一门很好的语言")
        buf.add_user_message("有什么推荐的教程？")
        buf.add_agent_message("推荐官方教程和Real Python")

        # 3. 刷新缓冲区
        items = buf.flush()
        assert len(items) == 4

        # 4. 存储到 SessionManager
        SessionManager._instance = None
        sm = SessionManager()
        tmpdir = tempfile.mkdtemp()
        sm._sessions_dir = pathlib.Path(tmpdir)

        # 将缓冲项转为消息存储
        user_items = [i for i in items if i.classification == "user_message"]
        agent_items = [i for i in items if i.classification == "agent_message"]
        for u, a in zip(user_items, agent_items):
            sm.add_message("agent_1", "session_1", u.content, a.content)

        # 5. 检索验证
        record = sm.get_session("agent_1", "session_1")
        assert len(record.messages) == 4

        # 6. 搜索验证
        results = sm.search_session("agent_1", "session_1", "Python")
        assert len(results) > 0

        shutil.rmtree(tmpdir, ignore_errors=True)
        SessionManager._instance = None

    def test_multi_session_isolation(self):
        """多 session 隔离"""
        from neurova.session_manager import SessionManager
        import pathlib

        SessionManager._instance = None
        sm = SessionManager()
        tmpdir = tempfile.mkdtemp()
        sm._sessions_dir = pathlib.Path(tmpdir)

        # 两个 session
        sm.add_message("a1", "s1", "Q1", "A1")
        sm.add_message("a1", "s2", "Q2", "A2")

        # 搜索隔离
        r1 = sm.search_session("a1", "s1", "Q1")
        r2 = sm.search_session("a1", "s2", "Q2")
        assert len(r1) > 0
        assert len(r2) > 0

        # Q1 不应出现在 s2
        r3 = sm.search_session("a1", "s2", "Q1")
        assert len(r3) == 0

        shutil.rmtree(tmpdir, ignore_errors=True)
        SessionManager._instance = None

    def test_conversation_history_round_trip(self):
        """对话历史完整往返"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer
        from neurova.session_manager import SessionManager
        import pathlib

        # 模拟多轮对话
        buf = ConversationBuffer()
        conversation = [
            ("你好", "你好！有什么可以帮你的？"),
            ("今天天气怎么样", "今天天气不错"),
            ("帮我写一段代码", "好的，这是代码..."),
        ]

        for user_msg, agent_msg in conversation:
            buf.add_user_message(user_msg)
            buf.add_agent_message(agent_msg)

        # 刷新
        items = buf.flush()
        assert len(items) == 6  # 3 user + 3 agent

        # 存储
        SessionManager._instance = None
        sm = SessionManager()
        tmpdir = tempfile.mkdtemp()
        sm._sessions_dir = pathlib.Path(tmpdir)

        user_items = [i for i in items if i.classification == "user_message"]
        agent_items = [i for i in items if i.classification == "agent_message"]
        for u, a in zip(user_items, agent_items):
            sm.add_message("agent_1", "test_session", u.content, a.content)

        # 验证完整往返
        record = sm.get_session("agent_1", "test_session")
        assert len(record.messages) == 6

        # 验证内容完整性
        messages = [(m.role, m.content) for m in record.messages]
        for i, (user_msg, agent_msg) in enumerate(conversation):
            assert ("user", user_msg) in messages
            assert ("assistant", agent_msg) in messages

        shutil.rmtree(tmpdir, ignore_errors=True)
        SessionManager._instance = None
