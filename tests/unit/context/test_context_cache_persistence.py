"""
ContextCache 持久化接口修复测试

修复: save_context_from_data() 缺少 session_id 参数
影响: 缓存写入磁盘异常
"""

import pytest
from unittest.mock import MagicMock, patch
from neurova.context_cache import ContextCacheManager, CacheEntry


class TestCacheEntrySessionId:
    """CacheEntry session_id 字段测试"""

    def test_cache_entry_has_session_id(self):
        """CacheEntry 包含 session_id 字段"""
        entry = CacheEntry(
            key="test",
            context_data={"messages": []},
            channel="default",
            agent_id="agent_1",
            session_id="session_123"
        )
        assert entry.session_id == "session_123"

    def test_cache_entry_session_id_optional(self):
        """CacheEntry session_id 可选"""
        entry = CacheEntry(
            key="test",
            context_data={"messages": []},
            channel="default",
            agent_id="agent_1"
        )
        assert entry.session_id is None


class TestWriteToDiskSessionId:
    """_write_to_disk 传递 session_id 测试"""

    def test_write_to_disk_passes_session_id(self):
        """_write_to_disk 将 session_id 传递给 save_context_from_data"""
        cache = ContextCacheManager.__new__(ContextCacheManager)
        cache._lock = __import__('threading').RLock()
        cache._cache = {}
        cache._stats = {'evictions': 0}
        cache.enable_persistence = True

        # 创建 mock persistence
        mock_persistence = MagicMock()
        mock_persistence.save_context_from_data = MagicMock(return_value=True)
        cache._persistence = mock_persistence

        # 创建 cache entry
        entry = CacheEntry(
            key="test_key",
            context_data={"messages": [{"role": "user", "content": "hello"}]},
            channel="default",
            agent_id="agent_1",
            session_id="session_abc"
        )
        cache._cache["test_key"] = entry

        # 执行写入
        result = cache._write_to_disk("test_key")

        # 验证
        assert result is True
        mock_persistence.save_context_from_data.assert_called_once()
        call_kwargs = mock_persistence.save_context_from_data.call_args[1]
        assert call_kwargs['session_id'] == 'session_abc'
        assert call_kwargs['agent_id'] == 'agent_1'
        assert call_kwargs['channel'] == 'default'

    def test_write_to_disk_fallback_session_id(self):
        """session_id 为 None 时使用 key 作为 fallback"""
        cache = ContextCacheManager.__new__(ContextCacheManager)
        cache._lock = __import__('threading').RLock()
        cache._cache = {}
        cache._stats = {'evictions': 0}
        cache.enable_persistence = True

        mock_persistence = MagicMock()
        mock_persistence.save_context_from_data = MagicMock(return_value=True)
        cache._persistence = mock_persistence

        # session_id 为 None
        entry = CacheEntry(
            key="fallback_key",
            context_data={"messages": []},
            channel="default",
            agent_id="agent_1"
        )
        cache._cache["fallback_key"] = entry

        result = cache._write_to_disk("fallback_key")

        assert result is True
        call_kwargs = mock_persistence.save_context_from_data.call_args[1]
        # session_id 应该 fallback 到 key
        assert call_kwargs['session_id'] == 'fallback_key'


class TestPutToCacheSessionId:
    """_put_to_cache 传递 session_id 测试"""

    def test_put_to_cache_with_session_id(self):
        """_put_to_cache 创建的 CacheEntry 包含 session_id"""
        cache = ContextCacheManager.__new__(ContextCacheManager)
        cache._lock = __import__('threading').RLock()
        cache._cache = {}
        cache._stats = {'memory_usage': 0}

        cache._put_to_cache(
            key="test_key",
            context_data={"messages": []},
            channel="default",
            agent_id="agent_1",
            user_id="user_1",
            session_id="session_xyz"
        )

        entry = cache._cache["test_key"]
        assert entry.session_id == "session_xyz"

    def test_put_to_cache_without_session_id(self):
        """_put_to_cache 不传 session_id 时为 None"""
        cache = ContextCacheManager.__new__(ContextCacheManager)
        cache._lock = __import__('threading').RLock()
        cache._cache = {}
        cache._stats = {'memory_usage': 0}

        cache._put_to_cache(
            key="test_key",
            context_data={"messages": []},
            channel="default",
            agent_id="agent_1"
        )

        entry = cache._cache["test_key"]
        assert entry.session_id is None


class TestStoreContextSessionId:
    """session_id 传播到 CacheEntry 端到端测试"""

    def test_full_flow_session_id_propagation(self):
        """从 put_context 到 CacheEntry 到 _write_to_disk，session_id 完整传播"""
        cache = ContextCacheManager.__new__(ContextCacheManager)
        cache._lock = __import__('threading').RLock()
        cache._cache = {}
        cache._stats = {'memory_usage': 0, 'writes': 0, 'hits': 0, 'misses': 0}
        cache.enable_persistence = True

        # Mock persistence
        mock_persistence = MagicMock()
        mock_persistence.save_context_from_data = MagicMock(return_value=True)
        cache._persistence = mock_persistence

        # Step 1: 通过 _put_to_cache 创建条目（含 session_id）
        cache._put_to_cache(
            key="agent_1:default:user_1:session_789",
            context_data={"messages": [{"role": "user", "content": "hello"}]},
            channel="default",
            agent_id="agent_1",
            user_id="user_1",
            session_id="session_789"
        )

        # Step 2: 标记为 dirty
        entry = cache._cache["agent_1:default:user_1:session_789"]
        entry.mark_dirty()

        # Step 3: 写入磁盘
        result = cache._write_to_disk("agent_1:default:user_1:session_789")

        # 验证完整传播
        assert result is True
        assert entry.session_id == "session_789"
        call_kwargs = mock_persistence.save_context_from_data.call_args[1]
        assert call_kwargs['session_id'] == 'session_789'


class TestPersistenceInterface:
    """验证 save_context_from_data 接口匹配"""

    def test_save_context_from_data_signature(self):
        """save_context_from_data 包含 session_id 参数"""
        from neurova.context_persistence import ContextPersistence
        import inspect

        sig = inspect.signature(ContextPersistence.save_context_from_data)
        params = list(sig.parameters.keys())
        assert 'session_id' in params
        assert 'agent_id' in params
        assert 'messages' in params
