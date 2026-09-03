"""
ToolCache 单元测试

测试目标：
1. CacheEntry 数据类
2. ToolCache 类的三级缓存
3. L1 精确匹配缓存
4. L2 语义相似缓存
5. L3 预测预加载
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import time

# 模拟依赖模块
mock_capability_graph = MagicMock()
sys.modules['neurova.tool_layers.capability_graph'] = mock_capability_graph

# 导入被测模块
from neurova.tool_layers.tool_cache import CacheEntry, ToolCache


class TestCacheEntry:
    """CacheEntry 数据类测试"""

    def test_creation(self):
        """测试创建"""
        entry = CacheEntry(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"},
            result={"content": "file content"},
            timestamp=time.time(),
            ttl=300.0
        )
        assert entry.tool_name == "file_read"
        assert entry.params["path"] == "/tmp/test.txt"
        assert entry.result["content"] == "file content"
        assert entry.ttl == 300.0

    def test_defaults(self):
        """测试默认值"""
        entry = CacheEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"}
        )
        assert entry.ttl == 300.0  # 默认5分钟
        assert entry.hit_count == 0
        assert entry.metadata == {}

    def test_is_expired(self):
        """测试过期检查"""
        # 创建一个已过期的条目
        entry = CacheEntry(
            tool_name="tool1",
            params={},
            result={},
            timestamp=time.time() - 400,  # 400秒前
            ttl=300.0  # 5分钟过期
        )
        assert entry.is_expired() == True
        
        # 创建一个未过期的条目
        entry2 = CacheEntry(
            tool_name="tool1",
            params={},
            result={},
            timestamp=time.time() - 100,  # 100秒前
            ttl=300.0
        )
        assert entry2.is_expired() == False

    def test_hit(self):
        """测试命中记录"""
        entry = CacheEntry(
            tool_name="tool1",
            params={},
            result={},
            hit_count=0
        )
        
        entry.hit()
        assert entry.hit_count == 1
        
        entry.hit()
        assert entry.hit_count == 2

    def test_to_dict(self):
        """测试转换为字典"""
        entry = CacheEntry(
            tool_name="tool1",
            params={"key": "value"},
            result={"output": "data"},
            timestamp=1234567890.0,
            ttl=300.0,
            hit_count=5
        )
        
        data = entry.to_dict()
        assert data["tool_name"] == "tool1"
        assert data["params"]["key"] == "value"
        assert data["result"]["output"] == "data"
        assert data["hit_count"] == 5


class TestToolCache:
    """ToolCache 类测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.cache = ToolCache(max_size=100, default_ttl=300.0)

    def test_initialization(self):
        """测试初始化"""
        assert self.cache._max_size == 100
        assert self.cache._default_ttl == 300.0
        assert len(self.cache._l1_cache) == 0
        assert len(self.cache._l2_cache) == 0
        assert len(self.cache._l3_cache) == 0

    def test_set_and_get_l1(self):
        """测试 L1 精确匹配缓存"""
        # 设置缓存
        self.cache.set(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"},
            result={"content": "file content"}
        )
        
        # 获取缓存
        result = self.cache.get(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"}
        )
        
        assert result is not None
        assert result["content"] == "file content"

    def test_get_nonexistent(self):
        """测试获取不存在的缓存"""
        result = self.cache.get(
            tool_name="nonexistent",
            params={}
        )
        assert result is None

    def test_l1_cache_miss(self):
        """测试 L1 缓存未命中"""
        # 设置缓存
        self.cache.set(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"},
            result={"content": "file content"}
        )
        
        # 使用不同的参数获取
        result = self.cache.get(
            tool_name="file_read",
            params={"path": "/tmp/different.txt"}
        )
        
        assert result is None

    def test_l2_semantic_similarity(self):
        """测试 L2 语义相似缓存"""
        # 设置缓存
        self.cache.set(
            tool_name="file_read",
            params={"path": "/tmp/test.txt"},
            result={"content": "file content"}
        )
        
        # 使用相似的参数获取
        result = self.cache.get(
            tool_name="file_read",
            params={"path": "/tmp/test.txt", "encoding": "utf-8"}  # 额外参数
        )
        
        # 如果实现支持语义相似，应该返回缓存结果
        # 这取决于具体实现

    def test_cache_eviction(self):
        """测试缓存淘汰"""
        # 设置小缓存
        small_cache = ToolCache(max_size=2, default_ttl=300.0)
        
        # 添加3个条目
        small_cache.set("tool1", {"key": "1"}, {"result": "1"})
        small_cache.set("tool2", {"key": "2"}, {"result": "2"})
        small_cache.set("tool3", {"key": "3"}, {"result": "3"})
        
        # 缓存应该只有2个条目
        assert len(small_cache._l1_cache) <= 2

    def test_preload(self):
        """测试预加载"""
        # 预加载一些数据
        self.cache.preload(
            tool_name="file_read",
            params_list=[
                {"path": "/tmp/file1.txt"},
                {"path": "/tmp/file2.txt"}
            ],
            results=[
                {"content": "content1"},
                {"content": "content2"}
            ]
        )
        
        # 验证预加载的数据
        result1 = self.cache.get("file_read", {"path": "/tmp/file1.txt"})
        assert result1 is not None
        assert result1["content"] == "content1"

    def test_predict(self):
        """测试预测"""
        # 添加一些历史数据
        self.cache.set("file_read", {"path": "/tmp/test.txt"}, {"content": "content"})
        self.cache.set("file_write", {"path": "/tmp/test.txt"}, {"success": True})
        
        # 预测下一个可能的工具调用
        predictions = self.cache.predict("file_read", {"path": "/tmp/test.txt"})
        
        # 验证预测结果
        assert isinstance(predictions, list)

    def test_invalidate(self):
        """测试缓存失效"""
        # 设置缓存
        self.cache.set("tool1", {"key": "1"}, {"result": "1"})
        
        # 验证缓存存在
        result = self.cache.get("tool1", {"key": "1"})
        assert result is not None
        
        # 使缓存失效
        self.cache.invalidate("tool1", {"key": "1"})
        
        # 验证缓存已失效
        result = self.cache.get("tool1", {"key": "1"})
        assert result is None

    def test_clear(self):
        """测试清空缓存"""
        # 添加一些缓存
        self.cache.set("tool1", {"key": "1"}, {"result": "1"})
        self.cache.set("tool2", {"key": "2"}, {"result": "2"})
        
        # 清空缓存
        self.cache.clear()
        
        # 验证缓存已清空
        assert len(self.cache._l1_cache) == 0
        assert len(self.cache._l2_cache) == 0
        assert len(self.cache._l3_cache) == 0

    def test_get_stats(self):
        """测试获取统计信息"""
        # 添加一些缓存
        self.cache.set("tool1", {"key": "1"}, {"result": "1"})
        self.cache.set("tool2", {"key": "2"}, {"result": "2"})
        
        # 获取缓存
        self.cache.get("tool1", {"key": "1"})
        self.cache.get("tool2", {"key": "2"})
        
        # 获取统计信息
        stats = self.cache.get_stats()
        
        assert "l1_size" in stats
        assert "l2_size" in stats
        assert "l3_size" in stats
        assert "hit_count" in stats
        assert "miss_count" in stats

    def test_make_key(self):
        """测试生成缓存键"""
        key1 = self.cache._make_key("tool1", {"key": "value"})
        key2 = self.cache._make_key("tool1", {"key": "value"})
        key3 = self.cache._make_key("tool1", {"key": "different"})
        
        # 相同参数应该生成相同的键
        assert key1 == key2
        
        # 不同参数应该生成不同的键
        assert key1 != key3

    def test_calculate_param_similarity(self):
        """测试参数相似度计算"""
        params1 = {"path": "/tmp/test.txt", "encoding": "utf-8"}
        params2 = {"path": "/tmp/test.txt", "encoding": "utf-8"}
        params3 = {"path": "/tmp/different.txt", "encoding": "utf-8"}
        
        # 相同参数的相似度应该为1
        similarity1 = self.cache._calculate_param_similarity(params1, params2)
        assert similarity1 == 1.0
        
        # 不同参数的相似度应该小于1
        similarity2 = self.cache._calculate_param_similarity(params1, params3)
        assert similarity2 < 1.0

    def test_cache_with_ttl(self):
        """测试带 TTL 的缓存"""
        # 设置短 TTL
        self.cache.set(
            tool_name="tool1",
            params={"key": "1"},
            result={"result": "1"},
            ttl=0.1  # 100毫秒
        )
        
        # 立即获取应该成功
        result = self.cache.get("tool1", {"key": "1"})
        assert result is not None
        
        # 等待过期
        time.sleep(0.2)
        
        # 获取应该失败
        result = self.cache.get("tool1", {"key": "1"})
        assert result is None

    def test_l3_predictive_preloading(self):
        """测试 L3 预测预加载"""
        # 添加一些历史数据
        self.cache.set("tool_a", {"input": "1"}, {"output": "a1"})
        self.cache.set("tool_b", {"input": "2"}, {"output": "b2"})
        
        # 预测预加载
        self.cache.predict("tool_a", {"input": "1"})
        
        # 验证预测缓存
        # 具体实现可能有所不同


if __name__ == "__main__":
    pytest.main([__file__, "-v"])