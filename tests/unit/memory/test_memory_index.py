"""
MemoryIndex 深度模块测试

测试 MemoryIndex 作为索引和查询深度模块的行为：
1. 小接口（3个核心方法 + 2个扩展方法）
2. 深实现（支持多维度查询、隔离过滤）
3. 线程安全
"""

import pytest
import tempfile
import shutil

from neurova.cognitive_layers.memory_layer.memory_index import (
    MemoryIndex,
    create_memory_index,
)
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext


class TestMemoryIndexInterface:
    """测试 MemoryIndex 接口设计"""

    @pytest.fixture
    def index(self):
        """创建 MemoryIndex 实例"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        return MemoryIndex(storage)

    def test_core_methods_exist(self, index):
        """验证核心方法存在"""
        assert hasattr(index, 'query')
        assert hasattr(index, 'search_by_tags')
        assert hasattr(index, 'search_by_text')

    def test_extension_methods_exist(self, index):
        """验证扩展方法存在"""
        assert hasattr(index, 'get_by_ids')
        assert hasattr(index, 'get_stats')

    def test_query_signature(self, index):
        """验证 query 方法签名"""
        import inspect
        sig = inspect.signature(index.query)
        params = list(sig.parameters.keys())
        assert 'memory_type' in params
        assert 'owner' in params
        assert 'tags' in params
        assert 'start_time' in params
        assert 'end_time' in params
        assert 'limit' in params
        assert 'isolation_context' in params

    def test_search_by_tags_signature(self, index):
        """验证 search_by_tags 方法签名"""
        import inspect
        sig = inspect.signature(index.search_by_tags)
        params = list(sig.parameters.keys())
        assert 'tags' in params
        assert 'match_all' in params
        assert 'isolation_context' in params


class TestMemoryIndexQuery:
    """测试 query 方法"""

    @pytest.fixture
    def index_with_data(self):
        """创建带测试数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        # 添加测试记忆
        storage.save(content="记忆1", memory_type="episodic", tags=["test", "unit"])
        storage.save(content="记忆2", memory_type="semantic", tags=["test"])
        storage.save(content="记忆3", memory_type="procedural", tags=["production"])
        storage.save(content="记忆4", memory_type="episodic", tags=["test", "integration"])
        
        return MemoryIndex(storage)

    def test_query_all(self, index_with_data):
        """测试查询所有记忆"""
        results = index_with_data.query()
        assert len(results) == 4

    def test_query_by_type(self, index_with_data):
        """测试按类型查询"""
        results = index_with_data.query(memory_type="episodic")
        assert len(results) == 2
        assert all(r["memory_type"] == "episodic" for r in results)

    def test_query_by_tags(self, index_with_data):
        """测试按标签查询（OR逻辑）"""
        results = index_with_data.query(tags=["test"])
        assert len(results) == 3  # 3条记忆有test标签

    def test_query_with_limit(self, index_with_data):
        """测试限制返回数量"""
        results = index_with_data.query(limit=2)
        assert len(results) == 2

    def test_query_no_results(self, index_with_data):
        """测试查询无结果"""
        results = index_with_data.query(memory_type="nonexistent")
        assert len(results) == 0


class TestMemoryIndexSearchByTags:
    """测试 search_by_tags 方法"""

    @pytest.fixture
    def index_with_tags(self):
        """创建带标签数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        storage.save(content="记忆1", memory_type="episodic", tags=["python", "test"])
        storage.save(content="记忆2", memory_type="semantic", tags=["python", "production"])
        storage.save(content="记忆3", memory_type="procedural", tags=["test", "debug"])
        storage.save(content="记忆4", memory_type="episodic", tags=["java", "test"])
        
        return MemoryIndex(storage)

    def test_search_by_tags_or(self, index_with_tags):
        """测试标签搜索（OR逻辑）"""
        results = index_with_tags.search_by_tags(["python", "java"], match_all=False)
        assert len(results) == 3  # 记忆1,2,4

    def test_search_by_tags_and(self, index_with_tags):
        """测试标签搜索（AND逻辑）"""
        results = index_with_tags.search_by_tags(["python", "test"], match_all=True)
        assert len(results) == 1  # 只有记忆1同时有python和test

    def test_search_by_single_tag(self, index_with_tags):
        """测试单个标签搜索"""
        results = index_with_tags.search_by_tags(["debug"])
        assert len(results) == 1


class TestMemoryIndexSearchByText:
    """测试 search_by_text 方法"""

    @pytest.fixture
    def index_with_text(self):
        """创建带文本数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        storage.save(content="Python是一种编程语言", memory_type="semantic")
        storage.save(content="Java也是编程语言", memory_type="semantic")
        storage.save(content="Python很流行", memory_type="episodic")
        storage.save(content="今天天气很好", memory_type="episodic")
        
        return MemoryIndex(storage)

    def test_search_by_text(self, index_with_text):
        """测试文本搜索"""
        results = index_with_text.search_by_text("Python")
        assert len(results) == 2
        assert all("Python" in r["content"] for r in results)

    def test_search_by_text_case_insensitive(self, index_with_text):
        """测试文本搜索不区分大小写"""
        results = index_with_text.search_by_text("python")
        assert len(results) == 2

    def test_search_by_text_with_limit(self, index_with_text):
        """测试文本搜索限制数量"""
        results = index_with_text.search_by_text("编程", limit=1)
        assert len(results) == 1


class TestMemoryIndexGetByIds:
    """测试 get_by_ids 方法"""

    @pytest.fixture
    def index_with_ids(self):
        """创建带ID数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        id1 = storage.save(content="记忆1", memory_type="episodic")
        id2 = storage.save(content="记忆2", memory_type="semantic")
        id3 = storage.save(content="记忆3", memory_type="procedural")
        
        return MemoryIndex(storage), [id1, id2, id3]

    def test_get_by_ids(self, index_with_ids):
        """测试按ID列表获取"""
        index, ids = index_with_ids
        results = index.get_by_ids(ids[:2])
        assert len(results) == 2
        assert results[0]["id"] == ids[0]
        assert results[1]["id"] == ids[1]

    def test_get_by_ids_partial(self, index_with_ids):
        """测试部分ID不存在"""
        index, ids = index_with_ids
        results = index.get_by_ids([ids[0], "nonexistent", ids[2]])
        assert len(results) == 2

    def test_get_by_ids_empty(self, index_with_ids):
        """测试空ID列表"""
        index, ids = index_with_ids
        results = index.get_by_ids([])
        assert len(results) == 0


class TestMemoryIndexGetStats:
    """测试 get_stats 方法"""

    @pytest.fixture
    def index_with_stats(self):
        """创建带统计数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        storage.save(content="记忆1", memory_type="episodic")
        storage.save(content="记忆2", memory_type="semantic")
        storage.save(content="记忆3", memory_type="episodic")
        
        return MemoryIndex(storage)

    def test_get_stats(self, index_with_stats):
        """测试获取统计信息"""
        stats = index_with_stats.get_stats()
        assert "total" in stats
        assert stats["total"] == 3
        assert "by_type" in stats
        assert stats["by_type"]["episodic"] == 2
        assert stats["by_type"]["semantic"] == 1


class TestMemoryIndexIsolation:
    """测试隔离上下文"""

    @pytest.fixture
    def index_with_isolation(self):
        """创建带隔离数据的 MemoryIndex"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        
        # 不同agent的记忆，添加test标签
        ctx_agent1 = IsolationContext(agent_id="agent_1")
        ctx_agent2 = IsolationContext(agent_id="agent_2")
        
        storage.save(content="Agent1记忆", memory_type="episodic", tags=["test"], isolation_context=ctx_agent1)
        storage.save(content="Agent2记忆", memory_type="episodic", tags=["test"], isolation_context=ctx_agent2)
        storage.save(content="共享记忆", memory_type="semantic", tags=["test"], isolation_context=ctx_agent1.with_shared(True))
        
        return MemoryIndex(storage)

    def test_query_with_isolation(self, index_with_isolation):
        """测试隔离查询"""
        ctx = IsolationContext(agent_id="agent_1")
        results = index_with_isolation.query(isolation_context=ctx)
        # agent_1可以访问自己的记忆和共享记忆
        assert len(results) == 2
        contents = [r["content"] for r in results]
        assert "Agent1记忆" in contents
        assert "共享记忆" in contents

    def test_search_by_tags_with_isolation(self, index_with_isolation):
        """测试标签搜索隔离"""
        ctx = IsolationContext(agent_id="agent_2")
        results = index_with_isolation.search_by_tags(["test"], isolation_context=ctx)
        # agent_2可以访问自己的记忆和共享记忆
        assert len(results) == 2
        contents = [r["content"] for r in results]
        assert "Agent2记忆" in contents
        assert "共享记忆" in contents

    def test_get_by_ids_with_isolation(self, index_with_isolation):
        """测试按ID获取隔离"""
        # 先获取所有记忆ID
        all_results = index_with_isolation.query()
        all_ids = [r["id"] for r in all_results]
        
        ctx = IsolationContext(agent_id="agent_1")
        results = index_with_isolation.get_by_ids(all_ids, isolation_context=ctx)
        # agent_1只能访问自己的记忆和共享记忆
        assert len(results) == 2


class TestMemoryIndexFactory:
    """测试工厂函数"""

    def test_create_memory_index(self):
        """测试工厂函数创建实例"""
        index = create_memory_index()
        assert isinstance(index, MemoryIndex)
        assert index.get_stats()["total"] == 0


class TestMemoryIndexThreadSafety:
    """测试线程安全"""

    def test_concurrent_queries(self):
        """测试并发查询"""
        import threading
        import time
        
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        index = MemoryIndex(storage)
        
        # 添加一些数据
        for i in range(10):
            storage.save(content=f"记忆{i}", memory_type="episodic")
        
        results = []
        errors = []
        
        def query_task():
            try:
                for _ in range(5):
                    result = index.query()
                    results.append(len(result))
                    time.sleep(0.01)
            except Exception as e:
                errors.append(str(e))
        
        # 启动多个线程并发查询
        threads = [threading.Thread(target=query_task) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 验证没有错误
        assert len(errors) == 0
        # 验证所有查询都返回了正确数量
        assert all(r == 10 for r in results)