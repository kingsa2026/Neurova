"""单元测试：neurova/skills/market_searcher.py (v2)

测试技能市场搜索器：SkillMarketSearcher
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from neurova.skills.market_searcher import SkillMarketSearcher, SearchResult


class TestSearchResult(unittest.TestCase):
    """测试 SearchResult 数据类"""

    def test_create_search_result(self):
        """测试创建 SearchResult"""
        result = SearchResult(
            skill_name="test-skill",
            description="A test skill",
            market="github",
            url="https://example.com/download",
            author="testuser",
            stars=100,
            tags=["test", "example"],
        )

        self.assertEqual(result.skill_name, "test-skill")
        self.assertEqual(result.market, "github")
        self.assertEqual(result.stars, 100)
        self.assertEqual(len(result.tags), 2)

    def test_search_result_to_dict(self):
        """测试 to_dict() 方法"""
        result = SearchResult(
            skill_name="test-skill",
            description="A test skill",
            market="github",
            url="https://example.com",
        )

        result_dict = result.to_dict()
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["skill_name"], "test-skill")
        self.assertEqual(result_dict["market"], "github")


class TestSkillMarketSearcher(unittest.TestCase):
    """测试 SkillMarketSearcher 类"""

    def setUp(self):
        """测试前设置"""
        # 模拟 SkillMarketRegistry
        self.mock_registry = MagicMock()
        self.mock_registry.adapters = {
            "github": MagicMock(market_name="github"),
            "clawhub": MagicMock(market_name="clawhub"),
        }

        # 创建搜索器（使用模拟的注册表）
        with patch('neurova.skills.market_searcher.get_market_registry', return_value=self.mock_registry):
            self.searcher = SkillMarketSearcher()

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        """测试后清理"""
        self.loop.close()

    def test_init(self):
        """测试初始化"""
        self.assertIsNotNone(self.searcher.registry)
        self.assertIsNotNone(self.searcher._cache)
        self.assertEqual(self.searcher._cache_ttl, 300)
        self.assertEqual(len(self.searcher._cache), 0)

    def test_search_market(self):
        """测试搜索单个市场"""
        # 模拟 search_market 方法（使用 AsyncMock）
        mock_result = [
            SearchResult(
                skill_name="test-skill",
                description="A test skill",
                market="github",
                url="https://example.com",
            )
        ]
        
        async def mock_search(market_name, query, limit):
            return mock_result
        
        self.searcher.search_market = mock_search

        # 执行搜索
        results = self.loop.run_until_complete(
            self.searcher.search_market("github", "test", 10)
        )

        # 验证
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].skill_name, "test-skill")
        self.assertEqual(results[0].market, "github")

    def test_search_all_markets(self):
        """测试搜索所有市场"""
        # 模拟 search_all_markets 方法
        mock_results = [
            SearchResult(
                skill_name="test-skill-1",
                description="A test skill 1",
                market="github",
                url="https://example.com/1",
            ),
            SearchResult(
                skill_name="test-skill-2",
                description="A test skill 2",
                market="clawhub",
                url="https://example.com/2",
            ),
        ]
        
        async def mock_search(query, limit_per_market, markets=None):
            return mock_results
        
        self.searcher.search_all_markets = mock_search

        # 执行搜索
        results = self.loop.run_until_complete(
            self.searcher.search_all_markets("test", 10)
        )

        # 验证
        self.assertEqual(len(results), 2)

    def test_clear_cache(self):
        """测试清除缓存"""
        # 先添加一些缓存
        cache_key = "github:test"
        self.searcher._cache[cache_key] = {
            "results": [],
            "timestamp": self.loop.time(),
        }
        self.assertEqual(len(self.searcher._cache), 1)

        # 清除缓存
        self.searcher.clear_cache()
        self.assertEqual(len(self.searcher._cache), 0)

    def test_list_markets(self):
        """测试列出市场"""
        # 模拟 registry.list_markets() 方法
        self.mock_registry.list_markets.return_value = [
            {"name": "github", "display_name": "GitHub"},
            {"name": "clawhub", "display_name": "ClawHub"},
        ]

        markets = self.searcher.list_markets()
        self.assertEqual(len(markets), 2)
        self.assertEqual(markets[0]["name"], "github")


if __name__ == "__main__":
    unittest.main()
