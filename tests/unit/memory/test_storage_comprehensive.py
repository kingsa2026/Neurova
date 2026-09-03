"""
全面单元测试 - MemoryStorage 模块

测试 neurova/cognitive_layers/memory_layer/storage.py
覆盖 MemoryStorage 类的所有公共方法、边界情况和错误处理。

L-3 OBSOLETE 标记(2026-07-03):
本测试基于 docs/architecture/LONG_TERM_PLAN.md 描绘的 SQLite 增强版 storage 设计
(整合 VectorSearch/MemorySecurityGuard/MemoryCache/BatchWriter),但该设计从未落地
——BatchWriter 类在整个代码库中零实现。实际 storage.py 走了 JSON 简化版路线,
且已有独立正确测试覆盖(tests/cognitive_layers/memory_layer/test_storage.py)。
SQLite 持久化由 manager.py _init_persistence_db 和 cognitive_storage_engine.py
独立实现。详见 docs/bugfix-memory-system-breakpoints.md L-3 调查报告。
"""

import pytest
import sqlite3
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# L-3: 标记整个模块为 obsolete,设计方向已变更
pytestmark = pytest.mark.skip(
    reason="L-3 obsolete: 测试基于未实现的 SQLite 增强版 storage 设计, "
    "实际 storage.py 为 JSON-backed 简化版, "
    "JSON 版测试见 tests/cognitive_layers/memory_layer/test_storage.py"
)


# 模拟依赖
class MockVectorSearch:
    """模拟 VectorSearch 类"""
    def __init__(self, *args, **kwargs):
        self.texts = []
        self.add_text_called = False
        self.add_texts_called = False
        self.remove_text_called = False
    
    def add_text(self, text, rebuild=False):
        self.add_text_called = True
        self.texts.append(text)
        return True
    
    def add_texts(self, texts, rebuild=False):
        self.add_texts_called = True
        self.texts.extend(texts)
        return True
    
    def remove_text(self, text):
        self.remove_text_called = True
        if text in self.texts:
            self.texts.remove(text)
        return True


class MockMemorySecurityGuard:
    """模拟 MemorySecurityGuard 类"""
    def __init__(self, *args, **kwargs):
        self.should_remember_result = True
        # 创建一个简单的 SafetyResult
        self.check_memory_safety_result = type('SafetyCheckResult', (), {
            'is_safe': True,
            'threats': [],
            'safety_level': 'safe'  # 默认安全
        })()
        self.sanitize_memory_result = None  # None 表示返回原始内容
    
    def should_remember(self, content):
        return self.should_remember_result
    
    def check_memory_safety(self, content):
        return self.check_memory_safety_result
    
    def sanitize_memory(self, content):
        return self.sanitize_memory_result if self.sanitize_memory_result else content


class MockCache:
    """模拟 MemoryCache 类"""
    def __init__(self, *args, **kwargs):
        self._cache = {}
    
    def get(self, key):
        return self._cache.get(key)
    
    def set(self, key, value):
        self._cache[key] = value
    
    def delete(self, key):
        if key in self._cache:
            del self._cache[key]


@pytest.fixture
def temp_db_path():
    """创建临时数据库路径"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_memory.db")
        yield db_path


@pytest.fixture
def mock_dependencies(monkeypatch):
    """模拟所有依赖"""
    # 模拟 VectorSearch
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage.VectorSearch',
        MockVectorSearch
    )
    
    # 模拟 MemorySecurityGuard
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage.MemorySecurityGuard',
        MockMemorySecurityGuard
    )
    
    # 模拟 MemoryCache
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage.MemoryCache',
        MockCache
    )
    
    # 模拟 BatchWriter (简单的 mock)
    class MockBatchWriter:
        def __init__(self, *args, **kwargs):
            pass
    
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage.BatchWriter',
        MockBatchWriter
    )
    
    # 模拟 schema 初始化函数
    def mock_init_schema(conn, lock):
        """创建内存数据库表的模拟实现"""
        with lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    neuser_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'yi_ling',
                    type TEXT DEFAULT 'long_term',
                    category TEXT DEFAULT 'conversation',
                    content TEXT NOT NULL,
                    channel TEXT DEFAULT 'default',
                    weight REAL DEFAULT 1.0,
                    temperature REAL DEFAULT 50.0,
                    lifecycle_stage TEXT DEFAULT 'active',
                    is_important INTEGER DEFAULT 0,
                    is_crystallized INTEGER DEFAULT 0,
                    crystallized_at TEXT,
                    emotion_score REAL DEFAULT 0.0,
                    emotion_tags TEXT DEFAULT '[]',
                    perspective TEXT DEFAULT 'ai_inference',
                    perspective_confidence REAL DEFAULT 1.0,
                    source TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed_at TEXT,
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT '',
                    expires_at TEXT,
                    attachment_ids TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}'
                )
            """)
    
    def mock_migrate_schema(conn, lock):
        """模拟数据库迁移"""
        pass
    
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage.init_schema',
        mock_init_schema
    )
    
    monkeypatch.setattr(
        'neurova.cognitive_layers.memory_layer.storage._migrate',
        mock_migrate_schema
    )


@pytest.fixture
def storage(temp_db_path, mock_dependencies):
    """创建 MemoryStorage 实例"""
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    
    storage = MemoryStorage(
        db_path=temp_db_path,
        neuser_id="test_neuser",
        user_id="test_user",
        enable_cache=True,
        enable_batch_write=False
    )
    
    yield storage
    
    storage.close()


class TestMemoryStorageInit:
    """测试 MemoryStorage 初始化"""
    
    def test_init_default(self, temp_db_path, mock_dependencies):
        """测试默认初始化"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        storage = MemoryStorage(db_path=temp_db_path)
        
        assert storage.db_path == temp_db_path
        assert storage.neuser_id == "default"
        assert storage.user_id == "default"
        assert storage.enable_cache == True
        assert storage.cache is not None
        assert storage.enable_batch_write == False
        assert storage.batch_writer is None
        assert storage.vector_search is not None
        assert storage._memory_security is not None
        assert storage._enable_memory_security == True
        
        storage.close()
    
    def test_init_custom_params(self, temp_db_path, mock_dependencies):
        """测试自定义参数初始化"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        storage = MemoryStorage(
            db_path=temp_db_path,
            neuser_id="custom_neuser",
            user_id="custom_user",
            enable_cache=False,
            cache_max_size=500,
            cache_ttl=600,
            enable_batch_write=True,
            batch_size=50,
            batch_flush_interval=60
        )
        
        assert storage.neuser_id == "custom_neuser"
        assert storage.user_id == "custom_user"
        assert storage.enable_cache == False
        assert storage.cache is None
        assert storage.enable_batch_write == True
        assert storage.batch_writer is not None
        
        storage.close()
    
    def test_init_creates_db_directory(self, mock_dependencies):
        """测试初始化时创建数据库目录"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "subdir", "test.db")
        
        assert not os.path.exists(os.path.dirname(db_path))
        
        storage = MemoryStorage(db_path=db_path)
        
        assert os.path.exists(os.path.dirname(db_path))
        
        storage.close()
        os.remove(db_path)
        os.rmdir(os.path.join(temp_dir, "subdir"))
        os.rmdir(temp_dir)
    
    def test_init_memory_db(self, mock_dependencies):
        """测试内存数据库初始化"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        storage = MemoryStorage(db_path=":memory:")
        
        assert storage.db_path == ":memory:"
        # 内存数据库不应该有 vector_index 文件
        assert "memory.pkl" in storage.vector_search.index_path
        
        storage.close()


class TestSave:
    """测试 save 方法"""
    
    def test_save_success(self, storage):
        """测试成功保存记忆"""
        memory_data = {
            'id': 'mem_001',
            'content': 'This is a test memory'
        }
        
        result = storage.save(memory_data)
        
        assert result == True
        
        # 验证数据已保存
        saved = storage.get('mem_001')
        assert saved is not None
        assert saved['id'] == 'mem_001'
        assert saved['content'] == 'This is a test memory'
    
    def test_save_missing_id(self, storage):
        """测试缺少 id 字段"""
        memory_data = {
            'content': 'This is a test memory'
        }
        
        result = storage.save(memory_data)
        
        assert result == False
    
    def test_save_missing_content(self, storage):
        """测试缺少 content 字段"""
        memory_data = {
            'id': 'mem_001'
        }
        
        result = storage.save(memory_data)
        
        assert result == False
    
    def test_save_empty_id(self, storage):
        """测试空 id"""
        memory_data = {
            'id': '',
            'content': 'This is a test memory'
        }
        
        result = storage.save(memory_data)
        
        assert result == False
    
    def test_save_empty_content(self, storage):
        """测试空 content"""
        memory_data = {
            'id': 'mem_001',
            'content': ''
        }
        
        result = storage.save(memory_data)
        
        assert result == False
    
    def test_save_with_all_fields(self, storage):
        """测试保存包含所有字段的记忆"""
        memory_data = {
            'id': 'mem_002',
            'content': 'Full memory',
            'agent_id': 'test_agent',
            'type': 'short_term',
            'category': 'fact',
            'channel': 'webchat',
            'weight': 2.0,
            'temperature': 30.0,
            'lifecycle_stage': 'active',
            'is_important': True,
            'is_crystallized': False,
            'crystallized_at': None,
            'emotion_score': 0.8,
            'emotion_tags': ['happy', 'excited'],
            'perspective': 'user_statement',
            'perspective_confidence': 0.9,
            'source': 'user_input',
            'access_count': 5,
            'last_accessed_at': '2026-05-20T03:00:00',
            'created_at': '2026-05-20T02:00:00',
            'expires_at': '2026-05-21T02:00:00',
            'attachment_ids': ['att_001'],
            'metadata': {'key': 'value'}
        }
        
        result = storage.save(memory_data)
        
        assert result == True
        
        # 验证数据
        saved = storage.get('mem_002')
        assert saved['agent_id'] == 'test_agent'
        assert saved['type'] == 'short_term'
        assert saved['category'] == 'fact'
        assert saved['weight'] == 2.0
        assert saved['temperature'] == 30.0
        assert saved['is_important'] == True
        assert saved['emotion_score'] == 0.8
        assert saved['emotion_tags'] == ['happy', 'excited']
    
    def test_save_security_block(self, storage):
        """测试安全检查阻止保存"""
        # 模拟 should_remember 返回 False
        storage._memory_security.should_remember_result = False
        
        memory_data = {
            'id': 'mem_003',
            'content': 'Sensitive content'
        }
        
        result = storage.save(memory_data)
        
        assert result == False
        
        # 验证数据未保存
        saved = storage.get('mem_003')
        assert saved is None
    
    def test_save_security_high_risk(self, storage):
        """测试高风险内容被阻止保存"""
        # 模拟 check_memory_safety 返回高风险结果
        storage._memory_security.check_memory_safety_result.is_safe = False
        storage._memory_security.check_memory_safety_result.safety_level = type('SafetyLevel', (), {'CRITICAL': 'CRITICAL'})()
        
        memory_data = {
            'id': 'mem_004',
            'content': 'High risk content'
        }
        
        result = storage.save(memory_data)
        
        assert result == False
        
        # 验证数据未保存
        saved = storage.get('mem_004')
        assert saved is None
    
    def test_save_security_sanitize(self, storage):
        """测试安全清理"""
        # 模拟 sanitize_memory 返回清理后的内容
        storage._memory_security.sanitize_memory_result = 'Sanitized content'
        
        memory_data = {
            'id': 'mem_005',
            'content': 'Content with sensitive info'
        }
        
        result = storage.save(memory_data)
        
        assert result == True
        
        # 验证保存的是清理后的内容
        saved = storage.get('mem_005')
        assert saved['content'] == 'Sanitized content'
    
    def test_save_update_existing(self, storage):
        """测试更新已存在的记忆"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_006',
            'content': 'Original content'
        }
        storage.save(memory_data)
        
        # 更新同一个 id
        memory_data['content'] = 'Updated content'
        result = storage.save(memory_data)
        
        assert result == True
        
        # 验证内容已更新
        saved = storage.get('mem_006')
        assert saved['content'] == 'Updated content'
    
    def test_save_with_neuser_id_user_id(self, storage):
        """测试使用 memory_data 中的 neuser_id 和 user_id"""
        memory_data = {
            'id': 'mem_007',
            'content': 'Test with custom user ids',
            'neuser_id': 'custom_neuser',
            'user_id': 'custom_user'
        }
        
        result = storage.save(memory_data)
        
        assert result == True
        
        # 验证使用自定义的 user ids 保存
        with storage._lock:
            cursor = storage.conn.execute(
                "SELECT neuser_id, user_id FROM memories WHERE id = ?",
                ('mem_007',)
            )
            row = cursor.fetchone()
        
        assert row[0] == 'custom_neuser'
        assert row[1] == 'custom_user'


class TestGet:
    """测试 get 方法"""
    
    def test_get_existing(self, storage):
        """测试获取已存在的记忆"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_101',
            'content': 'Test get'
        }
        storage.save(memory_data)
        
        # 获取记忆
        result = storage.get('mem_101')
        
        assert result is not None
        assert result['id'] == 'mem_101'
        assert result['content'] == 'Test get'
    
    def test_get_non_existent(self, storage):
        """测试获取不存在的记忆"""
        result = storage.get('non_existent_id')
        
        assert result is None
    
    def test_get_with_cache(self, storage):
        """测试从缓存获取"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_102',
            'content': 'Test cache'
        }
        storage.save(memory_data)
        
        # 清除缓存（模拟缓存未命中）
        storage.cache.delete('mem:mem_102')
        
        # 获取记忆（应该从数据库读取并缓存）
        result = storage.get('mem_102')
        
        assert result is not None
        assert result['id'] == 'mem_102'
        
        # 再次获取（应该从缓存读取）
        result2 = storage.get('mem_102')
        
        assert result2 is not None
        assert result2['id'] == 'mem_102'
    
    def test_get_with_filter_sensitive(self, storage):
        """测试过滤敏感信息"""
        # 模拟 sanitize_memory 返回清理后的内容
        storage._memory_security.sanitize_memory_result = 'Sanitized content'
        
        # 保存记忆
        memory_data = {
            'id': 'mem_103',
            'content': 'Original sensitive content'
        }
        storage.save(memory_data)
        
        # 获取记忆（过滤敏感信息）
        result = storage.get('mem_103', filter_sensitive=True)
        
        assert result is not None
        assert result['content'] == 'Sanitized content'
        assert result.get('_sanitized') == True
    
    def test_get_without_filter_sensitive(self, storage):
        """测试不过滤敏感信息"""
        # 保存记忆
        memory_data = {
            'id': 'mem_104',
            'content': 'Original content'
        }
        storage.save(memory_data)
        
        # 获取记忆（不过滤敏感信息）
        result = storage.get('mem_104', filter_sensitive=False)
        
        assert result is not None
        assert result['content'] == 'Original content'
        assert '_sanitized' not in result
    
    def test_get_user_isolation(self, storage):
        """测试用户隔离"""
        # 保存一个记忆（属于 test_neuser/test_user）
        memory_data = {
            'id': 'mem_105',
            'content': 'User specific memory'
        }
        storage.save(memory_data)
        
        # 创建另一个用户的存储实例
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        other_storage = MemoryStorage(
            db_path=storage.db_path,
            neuser_id="other_neuser",
            user_id="other_user"
        )
        
        # 另一个用户不应该能获取到这个记忆
        result = other_storage.get('mem_105')
        
        assert result is None
        
        other_storage.close()


class TestIncrementAccess:
    """测试 increment_access 方法"""
    
    def test_increment_access_success(self, storage):
        """测试成功增加访问次数"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_201',
            'content': 'Test increment access'
        }
        storage.save(memory_data)
        
        # 增加访问次数
        result = storage.increment_access('mem_201')
        
        assert result == True
        
        # 验证访问次数已增加
        saved = storage.get('mem_201')
        assert saved['access_count'] == 1
        assert saved['last_accessed_at'] is not None
    
    def test_increment_access_non_existent(self, storage):
        """测试增加不存在的记忆的访问次数"""
        result = storage.increment_access('non_existent_id')
        
        assert result == True  # SQLite UPDATE 不会报错，只是没有影响任何行
    
    def test_increment_access_multiple_times(self, storage):
        """测试多次增加访问次数"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_202',
            'content': 'Test multiple access'
        }
        storage.save(memory_data)
        
        # 增加访问次数 5 次
        for _ in range(5):
            storage.increment_access('mem_202')
        
        # 验证访问次数
        saved = storage.get('mem_202')
        assert saved['access_count'] == 5


class TestDelete:
    """测试 delete 方法"""
    
    def test_delete_success(self, storage):
        """测试成功删除记忆"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_301',
            'content': 'Test delete'
        }
        storage.save(memory_data)
        
        # 验证记忆存在
        assert storage.get('mem_301') is not None
        
        # 删除记忆
        result = storage.delete('mem_301')
        
        assert result == True
        
        # 验证记忆已删除
        assert storage.get('mem_301') is None
    
    def test_delete_non_existent(self, storage):
        """测试删除不存在的记忆"""
        result = storage.delete('non_existent_id')
        
        assert result == True  # SQLite DELETE 不会报错，只是没有影响任何行
    
    def test_delete_cascade_relations(self, storage):
        """测试删除记忆时级联删除关联"""
        # 先保存两个记忆
        memory_data_1 = {
            'id': 'mem_302',
            'content': 'Memory 1'
        }
        memory_data_2 = {
            'id': 'mem_303',
            'content': 'Memory 2'
        }
        storage.save(memory_data_1)
        storage.save(memory_data_2)
        
        # 添加关联（需要直接操作数据库，因为 add_relation 方法在 RelationMixin 中）
        with storage._lock:
            storage.conn.execute("""
                INSERT INTO memory_relations (id, source_memory_id, target_memory_id, relation_type, strength)
                VALUES (?, ?, ?, ?, ?)
            """, ('rel_001', 'mem_302', 'mem_303', 'similar', 0.8))
            storage.conn.commit()
        
        # 删除记忆 1
        result = storage.delete('mem_302')
        
        assert result == True
        
        # 验证关联已删除
        with storage._lock:
            cursor = storage.conn.execute(
                "SELECT COUNT(*) FROM memory_relations WHERE source_memory_id = ? OR target_memory_id = ?",
                ('mem_302', 'mem_302')
            )
            count = cursor.fetchone()[0]
        
        assert count == 0
    
    def test_delete_invalidates_cache(self, storage):
        """测试删除记忆时使缓存失效"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_304',
            'content': 'Test cache invalidation'
        }
        storage.save(memory_data)
        
        # 验证缓存存在
        assert storage.cache.get('mem:mem_304') is not None
        
        # 删除记忆
        storage.delete('mem_304')
        
        # 验证缓存已删除
        assert storage.cache.get('mem:mem_304') is None


class TestCount:
    """测试 count 方法"""
    
    def test_count_empty(self, storage):
        """测试空数据库的记忆数"""
        result = storage.count()
        
        assert result == 0
    
    def test_count_with_memories(self, storage):
        """测试有记忆时的记忆数"""
        # 保存 3 个记忆
        for i in range(3):
            memory_data = {
                'id': f'mem_401_{i}',
                'content': f'Memory {i}'
            }
            storage.save(memory_data)
        
        result = storage.count()
        
        assert result == 3
    
    def test_count_with_agent_id_filter(self, storage):
        """测试按 agent_id 过滤的记忆数"""
        # 保存 3 个记忆，其中 2 个属于 agent_1
        for i in range(3):
            memory_data = {
                'id': f'mem_402_{i}',
                'content': f'Memory {i}',
                'agent_id': 'agent_1' if i < 2 else 'agent_2'
            }
            storage.save(memory_data)
        
        result_all = storage.count()
        result_agent_1 = storage.count(agent_id='agent_1')
        result_agent_2 = storage.count(agent_id='agent_2')
        
        assert result_all == 3
        assert result_agent_1 == 2
        assert result_agent_2 == 1
    
    def test_count_user_isolation(self, storage):
        """测试用户隔离"""
        # 保存一个记忆（属于 test_neuser/test_user）
        memory_data = {
            'id': 'mem_403',
            'content': 'User specific memory'
        }
        storage.save(memory_data)
        
        # 创建另一个用户的存储实例
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        other_storage = MemoryStorage(
            db_path=storage.db_path,
            neuser_id="other_neuser",
            user_id="other_user"
        )
        
        # 另一个用户的 count 应该是 0
        result = other_storage.count()
        
        assert result == 0
        
        other_storage.close()


class TestGetStats:
    """测试 get_stats 方法"""
    
    def test_get_stats_empty(self, storage):
        """测试空数据库的统计信息"""
        result = storage.get_stats()
        
        assert result['total'] == 0
        assert result['by_type'] == {}
        assert result['by_category'] == {}
        assert result['crystallized'] == 0
        assert result['avg_temperature'] == 0.0
    
    def test_get_stats_with_memories(self, storage):
        """测试有记忆时的统计信息"""
        # 保存 3 个记忆，不同类型/类别
        memory_data_1 = {
            'id': 'mem_501',
            'content': 'Memory 1',
            'type': 'long_term',
            'category': 'conversation',
            'temperature': 30.0,
            'is_crystallized': True
        }
        memory_data_2 = {
            'id': 'mem_502',
            'content': 'Memory 2',
            'type': 'long_term',
            'category': 'fact',
            'temperature': 40.0,
            'is_crystallized': False
        }
        memory_data_3 = {
            'id': 'mem_503',
            'content': 'Memory 3',
            'type': 'short_term',
            'category': 'conversation',
            'temperature': 50.0,
            'is_crystallized': False
        }
        
        storage.save(memory_data_1)
        storage.save(memory_data_2)
        storage.save(memory_data_3)
        
        result = storage.get_stats()
        
        assert result['total'] == 3
        assert result['by_type'] == {'long_term': 2, 'short_term': 1}
        assert result['by_category'] == {'conversation': 2, 'fact': 1}
        assert result['crystallized'] == 1
        assert abs(result['avg_temperature'] - 40.0) < 0.01  # (30 + 40 + 50) / 3 = 40
    
    def test_get_stats_with_agent_id_filter(self, storage):
        """测试按 agent_id 过滤的统计信息"""
        # 保存 3 个记忆，其中 2 个属于 agent_1
        for i in range(3):
            memory_data = {
                'id': f'mem_504_{i}',
                'content': f'Memory {i}',
                'agent_id': 'agent_1' if i < 2 else 'agent_2',
                'type': 'long_term',
                'category': 'conversation',
                'temperature': 50.0
            }
            storage.save(memory_data)
        
        result_all = storage.get_stats()
        result_agent_1 = storage.get_stats(agent_id='agent_1')
        result_agent_2 = storage.get_stats(agent_id='agent_2')
        
        assert result_all['total'] == 3
        assert result_agent_1['total'] == 2
        assert result_agent_2['total'] == 1


class TestUpdateMemoryLifecycle:
    """测试 update_memory_lifecycle 方法"""
    
    def test_update_lifecycle_success(self, storage):
        """测试成功更新生命周期阶段"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_601',
            'content': 'Test lifecycle'
        }
        storage.save(memory_data)
        
        # 更新生命周期阶段
        result = storage.update_memory_lifecycle('mem_601', 'archived')
        
        assert result == True
        
        # 验证生命周期阶段已更新
        saved = storage.get('mem_601')
        assert saved['lifecycle_stage'] == 'archived'
    
    def test_update_lifecycle_non_existent(self, storage):
        """测试更新不存在的记忆的生命周期阶段"""
        result = storage.update_memory_lifecycle('non_existent_id', 'archived')
        
        assert result == True  # SQLite UPDATE 不会报错，只是没有影响任何行
    
    def test_update_lifecycle_invalid_stage(self, storage):
        """测试更新为无效的生命周期阶段"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_602',
            'content': 'Test invalid lifecycle'
        }
        storage.save(memory_data)
        
        # 更新为无效的生命周期阶段（数据库不会报错，但可能不符合业务逻辑）
        result = storage.update_memory_lifecycle('mem_602', 'invalid_stage')
        
        assert result == True
        
        # 验证生命周期阶段已更新为无效值
        saved = storage.get('mem_602')
        assert saved['lifecycle_stage'] == 'invalid_stage'


class TestUpdateMetadata:
    """测试 update_metadata 方法"""
    
    def test_update_metadata_success(self, storage):
        """测试成功更新元数据"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_701',
            'content': 'Test metadata',
            'metadata': {'key1': 'value1'}
        }
        storage.save(memory_data)
        
        # 更新元数据（合并更新）
        result = storage.update_metadata('mem_701', {'key2': 'value2'})
        
        assert result == True
        
        # 验证元数据已更新
        saved = storage.get('mem_701')
        assert saved['metadata']['key1'] == 'value1'
        assert saved['metadata']['key2'] == 'value2'
    
    def test_update_metadata_non_existent(self, storage):
        """测试更新不存在的记忆的元数据"""
        result = storage.update_metadata('non_existent_id', {'key': 'value'})
        
        assert result == False
    
    def test_update_metadata_merge(self, storage):
        """测试元数据合并更新"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_702',
            'content': 'Test metadata merge',
            'metadata': {'key1': 'value1', 'key2': 'value2'}
        }
        storage.save(memory_data)
        
        # 更新元数据（只更新 key1，添加 key3）
        result = storage.update_metadata('mem_702', {'key1': 'updated', 'key3': 'value3'})
        
        assert result == True
        
        # 验证元数据已合并更新
        saved = storage.get('mem_702')
        assert saved['metadata']['key1'] == 'updated'
        assert saved['metadata']['key2'] == 'value2'
        assert saved['metadata']['key3'] == 'value3'
    
    def test_update_metadata_empty(self, storage):
        """测试更新为空元数据"""
        # 先保存一个记忆
        memory_data = {
            'id': 'mem_703',
            'content': 'Test empty metadata',
            'metadata': {'key1': 'value1'}
        }
        storage.save(memory_data)
        
        # 更新元数据（空字典）
        result = storage.update_metadata('mem_703', {})
        
        assert result == True
        
        # 验证元数据已更新（应该保留原有元数据）
        saved = storage.get('mem_703')
        assert saved['metadata']['key1'] == 'value1'


class TestClose:
    """测试 close 方法"""
    
    def test_close_success(self, temp_db_path, mock_dependencies):
        """测试成功关闭数据库连接"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        storage = MemoryStorage(db_path=temp_db_path)
        
        # 验证连接已建立
        assert storage.conn is not None
        
        # 关闭连接
        storage.close()
        
        # 验证连接已关闭
        assert storage.conn is None
    
    def test_close_multiple_times(self, temp_db_path, mock_dependencies):
        """测试多次关闭数据库连接"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        storage = MemoryStorage(db_path=temp_db_path)
        
        # 多次关闭（应该不报错）
        storage.close()
        storage.close()  # 第二次关闭
        
        assert storage.conn is None


class TestUserIsolation:
    """测试用户隔离功能"""
    
    def test_user_isolation_save_get(self, storage):
        """测试保存和获取时的用户隔离"""
        # 保存一个记忆（属于 test_neuser/test_user）
        memory_data = {
            'id': 'mem_801',
            'content': 'User specific memory'
        }
        storage.save(memory_data)
        
        # 创建另一个用户的存储实例
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        other_storage = MemoryStorage(
            db_path=storage.db_path,
            neuser_id="other_neuser",
            user_id="other_user"
        )
        
        # 另一个用户不应该能获取到这个记忆
        result = other_storage.get('mem_801')
        
        assert result is None
        
        # 但原用户应该能获取到
        result_original = storage.get('mem_801')
        
        assert result_original is not None
        
        other_storage.close()
    
    def test_user_isolation_delete(self, storage):
        """测试删除时的用户隔离"""
        # 保存一个记忆（属于 test_neuser/test_user）
        memory_data = {
            'id': 'mem_802',
            'content': 'User specific memory'
        }
        storage.save(memory_data)
        
        # 创建另一个用户的存储实例
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        other_storage = MemoryStorage(
            db_path=storage.db_path,
            neuser_id="other_neuser",
            user_id="other_user"
        )
        
        # 另一个用户删除这个记忆（应该删除失败，因为找不到）
        result = other_storage.delete('mem_802')
        
        # SQLite DELETE 不会报错，只是没有影响任何行
        assert result == True
        
        # 但原用户应该能删除
        result_original = storage.delete('mem_802')
        
        assert result_original == True
        
        other_storage.close()
