"""单元测试：neurova/skills/agent_skill_manager.py

测试 Agent 技能管理器：AgentSkillManager
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from neurova.skills.agent_skill_manager import AgentSkillManager
from neurova.skills.market_searcher import SkillMarketSearcher, SearchResult
from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer, SkillAcquisitionResult


class TestAgentSkillManager(unittest.TestCase):
    """测试 AgentSkillManager 类"""

    def setUp(self):
        """测试前设置"""
        # 模拟依赖
        self.mock_decomposer = MagicMock()
        self.mock_searcher = MagicMock(spec=SkillMarketSearcher)
        self.mock_importer = MagicMock()

        # 创建管理器
        with patch('neurova.skills.agent_skill_manager.TaskDecomposer', return_value=self.mock_decomposer), \
             patch('neurova.skills.agent_skill_manager.SkillNeedAnalyzer', return_value=MagicMock(spec=SkillNeedAnalyzer)) as mock_analyzer_class, \
             patch('neurova.skills.agent_skill_manager.SkillMarketSearcher', return_value=self.mock_searcher), \
             patch('neurova.skills.agent_skill_manager.SkillMarketImporter', return_value=self.mock_importer):
            self.manager = AgentSkillManager(
                agent_id="test-agent",
                auto_acquire=True,
            )
            self.mock_analyzer = self.manager.analyzer

    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.manager.agent_id, "test-agent")
        self.assertTrue(self.manager.auto_acquire)
        self.assertIsNotNone(self.manager.decomposer)
        self.assertIsNotNone(self.manager.analyzer)
        self.assertIsNotNone(self.manager.searcher)
        self.assertIsNotNone(self.manager.importer)

    def test_analyze_task(self):
        """测试分析任务"""
        # 模拟 analyzer.analyze_and_acquire 返回结果
        self.mock_analyzer.analyze_and_acquire.return_value = {
            "required_skills": ["skill1", "skill2"],
            "success_count": 1,
            "failed_count": 1,
            "install_results": [],
        }

        # 执行分析
        result = self.manager.analyze_task("实现一个计算器")

        # 验证
        self.assertEqual(len(result["required_skills"]), 2)
        self.assertEqual(result["success_count"], 1)
        self.mock_analyzer.analyze_and_acquire.assert_called_once_with("实现一个计算器", None)

    def test_analyze_task_with_context(self):
        """测试分析任务（带上下文）"""
        context = {"user": "test", "priority": "high"}
        self.mock_analyzer.analyze_and_acquire.return_value = {
            "required_skills": ["skill1"],
            "success_count": 1,
            "failed_count": 0,
            "install_results": [],
        }

        result = self.manager.analyze_task("实现一个计算器", context)

        self.assertEqual(len(result["required_skills"]), 1)
        self.mock_analyzer.analyze_and_acquire.assert_called_once_with("实现一个计算器", context)

    def test_suggest_skills_for_task(self):
        """测试推荐技能"""
        # 模拟 analyzer.suggest_skills 返回结果
        self.mock_analyzer.suggest_skills.return_value = [
            {"skill_name": "skill1", "relevance": 0.9},
            {"skill_name": "skill2", "relevance": 0.8},
        ]

        # 执行推荐
        suggestions = self.manager.suggest_skills_for_task("实现一个计算器")

        # 验证
        self.assertEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0]["skill_name"], "skill1")
        self.mock_analyzer.suggest_skills.assert_called_once_with("实现一个计算器", None)

    def test_search_skill_in_markets(self):
        """测试在市场中搜索技能"""
        # 模拟 searcher.search_all_markets 返回结果
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="test/skill1", description="Skill 1", market="github", url="https://example.com/1"),
            SearchResult(skill_name="test/skill2", description="Skill 2", market="clawhub", url="https://example.com/2"),
        ]

        # 执行搜索
        results = self.manager.search_skill_in_markets("calculator", limit_per_market=10)

        # 验证
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].skill_name, "test/skill1")
        self.assertEqual(results[1].skill_name, "test/skill2")
        self.mock_searcher.search_all_markets.assert_called_once_with(
            query="calculator",
            limit_per_market=10,
            markets=None,
        )

    def test_search_skill_in_markets_with_market_filter(self):
        """测试在指定市场中搜索技能"""
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="test/skill1", description="Skill 1", market="github", url="https://example.com/skill1"),
        ]

        results = self.manager.search_skill_in_markets(
            "calculator",
            markets=["github"],
            limit_per_market=5,
        )

        self.assertEqual(len(results), 1)
        self.mock_searcher.search_all_markets.assert_called_once_with(
            query="calculator",
            limit_per_market=5,
            markets=["github"],
        )

    @patch('neurova.skills.agent_skill_manager.SkillAcquisitionResult')
    def test_acquire_skill_success(self, mock_result_class):
        """测试获取技能（成功）"""
        # 模拟搜索结果
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="test/skill1", description="Skill 1", market="github", url="https://example.com/skill1"),
        ]

        # 模拟安装结果（成功）
        self.mock_importer.import_from_market.return_value = {
            "success": True,
            "install_path": "/path/to/skill1",
        }

        # 模拟 SkillAcquisitionResult
        mock_result = MagicMock()
        mock_result_class.return_value = mock_result

        # 执行获取
        result = self.manager.acquire_skill("calculator")

        # 验证
        self.assertIsNotNone(result)
        self.mock_searcher.search_all_markets.assert_called_once()
        self.mock_importer.import_from_market.assert_called_once()

    @patch('neurova.skills.agent_skill_manager.SkillAcquisitionResult')
    def test_acquire_skill_not_found(self, mock_result_class):
        """测试获取技能（未找到）"""
        # 模拟搜索结果（空）
        self.mock_searcher.search_all_markets.return_value = []

        # 模拟 SkillAcquisitionResult
        mock_result = MagicMock()
        mock_result_class.return_value = mock_result

        # 执行获取
        result = self.manager.acquire_skill("nonexistent_skill")

        # 验证
        self.assertIsNotNone(result)
        self.mock_searcher.search_all_markets.assert_called_once()
        self.mock_importer.import_from_market.assert_not_called()

    @patch('neurova.skills.agent_skill_manager.SkillAcquisitionResult')
    def test_acquire_skill_install_failed(self, mock_result_class):
        """测试获取技能（安装失败）"""
        # 模拟搜索结果
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="test/skill1", description="Skill 1", market="github", url="https://example.com/skill1"),
        ]

        # 模拟安装结果（失败）
        self.mock_importer.import_from_market.return_value = {
            "success": False,
            "error": "Installation failed",
        }

        # 模拟 SkillAcquisitionResult
        mock_result = MagicMock()
        mock_result_class.return_value = mock_result

        # 执行获取
        result = self.manager.acquire_skill("calculator")

        # 验证
        self.assertIsNotNone(result)
        self.mock_importer.import_from_market.assert_called_once()

    def test_get_skill_status(self):
        """测试获取技能状态"""
        # 模拟 skill_registry.list_skills 返回结果
        mock_skill = MagicMock()
        mock_skill.name = "skill1"

        self.manager.skill_registry = MagicMock()
        self.manager.skill_registry.list_skills.return_value = [mock_skill]

        # 模拟 searcher.list_markets 返回结果
        self.mock_searcher.list_markets.return_value = [
            {"name": "github"},
            {"name": "clawhub"},
        ]

        # 执行获取状态
        status = self.manager.get_skill_status()

        # 验证
        self.assertEqual(status["agent_id"], "test-agent")
        self.assertEqual(status["auto_acquire"], True)
        self.assertEqual(len(status["available_skills"]), 1)
        self.assertEqual(status["available_skill_count"], 1)
        self.assertEqual(len(status["supported_markets"]), 2)


if __name__ == "__main__":
    unittest.main()
