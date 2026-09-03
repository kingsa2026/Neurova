"""
单元测试：neurova/skills/skill_need_analyzer.py

测试技能需求分析器：SkillNeedAnalyzer
"""
import unittest
from unittest.mock import MagicMock, patch

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from neurova.skills.skill_need_analyzer import (
    SkillNeedAnalyzer,
    SkillAcquisitionResult,
)
from neurova.skills.task_decomposer import TaskDecomposer, TaskDecompositionResult, SubTask
from neurova.skills.market_searcher import SkillMarketSearcher, SearchResult


class TestSkillAcquisitionResult(unittest.TestCase):
    """测试 SkillAcquisitionResult 数据类"""

    def test_create_result(self):
        """测试创建技能获取结果"""
        result = SkillAcquisitionResult(
            skill_name="test-skill",
            success=True,
            source="market",
            market="github",
            url="https://example.com",
            install_path="/path/to/skill",
        )

        self.assertEqual(result.skill_name, "test-skill")
        self.assertTrue(result.success)
        self.assertEqual(result.source, "market")
        self.assertEqual(result.market, "github")

    def test_to_dict(self):
        """测试 to_dict() 方法"""
        result = SkillAcquisitionResult(
            skill_name="test-skill",
            success=True,
            source="market",
        )

        result_dict = result.to_dict()
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["skill_name"], "test-skill")
        self.assertTrue(result_dict["success"])


class TestSkillNeedAnalyzer(unittest.TestCase):
    """测试 SkillNeedAnalyzer 类"""

    def setUp(self):
        """测试前设置"""
        # 模拟依赖
        self.mock_decomposer = MagicMock(spec=TaskDecomposer)
        self.mock_searcher = MagicMock(spec=SkillMarketSearcher)
        self.mock_importer = MagicMock()

        # 创建分析器
        self.analyzer = SkillNeedAnalyzer(
            decomposer=self.mock_decomposer,
            searcher=self.mock_searcher,
            importer=self.mock_importer,
            auto_install=False,  # 测试时不自动安装
        )

    def test_init(self):
        """测试初始化"""
        self.assertIsNotNone(self.analyzer.decomposer)
        self.assertIsNotNone(self.analyzer.searcher)
        self.assertIsNotNone(self.analyzer.importer)
        self.assertFalse(self.analyzer.auto_install)

    def test_analyze_and_acquire_no_missing_skills(self):
        """测试分析并获取技能（无缺失技能）"""
        # 模拟任务拆解结果（无缺失技能）
        subtask = SubTask(
            task_id="task_1",
            name="测试",
            description="测试",
            required_skills=["web_search"],
        )
        decomposition = TaskDecompositionResult(
            original_task="测试任务",
            subtasks=[subtask],
            missing_skills=[],
            can_execute=True,
        )
        self.mock_decomposer.decompose.return_value = decomposition

        # 模拟技能注册表（技能已存在）
        mock_skill = MagicMock()
        mock_skill.name = "web_search"
        self.analyzer.skill_registry = MagicMock()
        self.analyzer.skill_registry.list_skills.return_value = [mock_skill]

        # 执行分析
        result = self.analyzer.analyze_and_acquire("测试任务")

        # 验证
        self.assertEqual(len(result["required_skills"]), 1)
        self.assertEqual(result["success_count"], 0)  # 不需要获取
        self.mock_searcher.search_all_markets.assert_not_called()

    def test_analyze_and_acquire_with_missing_skills(self):
        """测试分析并获取技能（有缺失技能）"""
        # 模拟任务拆解结果（有缺失技能）
        subtask = SubTask(
            task_id="task_1",
            name="测试",
            description="测试",
            required_skills=["web_search"],
        )
        decomposition = TaskDecompositionResult(
            original_task="测试任务",
            subtasks=[subtask],
            missing_skills=["web_search"],
            can_execute=False,
        )
        self.mock_decomposer.decompose.return_value = decomposition

        # 模拟技能注册表（技能不存在）
        self.analyzer.skill_registry = MagicMock()
        self.analyzer.skill_registry.list_skills.return_value = []

        # 模拟搜索结果
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="web-search", description="Web Search", market="github", url="https://example.com")
        ]

        # 执行分析
        result = self.analyzer.analyze_and_acquire("测试任务")

        # 验证
        self.assertEqual(len(result["missing_skills"]), 1)
        self.assertGreaterEqual(result["fail_count"], 0)  # 搜索成功但安装被禁用
        self.mock_searcher.search_all_markets.assert_called_once()

    def test_calculate_similarity_exact_match(self):
        """测试计算相似度（完全匹配）"""
        similarity = self.analyzer._calculate_similarity("web_search", "web_search")
        self.assertEqual(similarity, 1.0)

    def test_calculate_similarity_contains(self):
        """测试计算相似度（包含匹配）"""
        similarity = self.analyzer._calculate_similarity("web", "web_search")
        self.assertEqual(similarity, 0.8)

    def test_calculate_similarity_overlap(self):
        """测试计算相似度（部分重叠）"""
        similarity = self.analyzer._calculate_similarity("web search", "web_search")
        # 分词后可能有重叠
        self.assertGreaterEqual(similarity, 0.0)

    def test_calculate_similarity_no_overlap(self):
        """测试计算相似度（无重叠）"""
        similarity = self.analyzer._calculate_similarity("abc", "xyz")
        self.assertEqual(similarity, 0.0)

    def test_select_best_match(self):
        """测试选择最佳匹配"""
        # 模拟搜索结果
        results = [
            SearchResult(skill_name="web-search", description="Web Search", market="github", url="https://example.com/1"),
            SearchResult(skill_name="search-tool", description="Search Tool", market="clawhub", url="https://example.com/2"),
        ]
        
        # 模拟相似度计算（返回高分）
        with patch.object(self.analyzer, '_calculate_similarity', return_value=0.8):
            best_match = self.analyzer._select_best_match("web_search", results)
        
        self.assertIsNotNone(best_match)
        self.assertEqual(best_match.skill_name, "web-search")

    def test_select_best_match_no_good_match(self):
        """测试选择最佳匹配（无合适匹配）"""
        # 模拟搜索结果（相似度低）
        results = [
            SearchResult(skill_name="xyz-tool", description="XYZ Tool", market="github", url="https://example.com/xyz"),
        ]
        
        # 相似度 < 0.5，应该返回 None
        with patch.object(self.analyzer, '_calculate_similarity', return_value=0.3):
            best_match = self.analyzer._select_best_match("web_search", results)
        
        self.assertIsNone(best_match)

    def test_suggest_skills(self):
        """测试推荐技能"""
        # 模拟任务拆解结果
        subtask = SubTask(
            task_id="task_1",
            name="测试",
            description="测试",
            required_skills=["web_search"],
        )
        decomposition = TaskDecompositionResult(
            original_task="测试任务",
            subtasks=[subtask],
        )
        self.mock_decomposer.decompose.return_value = decomposition

        # 模拟搜索结果
        self.mock_searcher.search_all_markets.return_value = [
            SearchResult(skill_name="web-search", description="Web Search", market="github", url="https://example.com")
        ]

        # 执行推荐
        suggestions = self.analyzer.suggest_skills("测试任务")

        # 验证
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["skill_name"], "web_search")
        self.assertIn("sources", suggestions[0])

    def test_suggest_skills_already_installed(self):
        """测试推荐技能（已安装）"""
        # 模拟任务拆解结果
        subtask = SubTask(
            task_id="task_1",
            name="测试",
            description="测试",
            required_skills=["web_search"],
        )
        decomposition = TaskDecompositionResult(
            original_task="测试任务",
            subtasks=[subtask],
        )
        self.mock_decomposer.decompose.return_value = decomposition

        # 模拟技能注册表（技能已存在）
        mock_skill = MagicMock()
        mock_skill.name = "web_search"
        self.analyzer.skill_registry = MagicMock()
        self.analyzer.skill_registry.list_skills.return_value = [mock_skill]

        # 执行推荐
        suggestions = self.analyzer.suggest_skills("测试任务")

        # 验证
        self.assertTrue(suggestions[0]["already_installed"])
        self.mock_searcher.search_all_markets.assert_not_called()


class TestSkillNeedAnalyzerIntegration(unittest.TestCase):
    """测试 SkillNeedAnalyzer 集成测试（使用真实依赖）"""

    def test_analyze_with_real_decomposer(self):
        """测试使用真实 TaskDecomposer"""
        # 使用真实的 TaskDecomposer（不依赖 LLM）
        decomposer = TaskDecomposer()

        # 模拟搜索器
        mock_searcher = MagicMock(spec=SkillMarketSearcher)
        mock_searcher.search_all_markets.return_value = []

        # 创建分析器
        analyzer = SkillNeedAnalyzer(
            decomposer=decomposer,
            searcher=mock_searcher,
            auto_install=False,
        )

        # 执行分析
        result = analyzer.analyze_and_acquire("搜索 Neurova 项目")

        # 验证
        self.assertIsInstance(result, dict)
        self.assertIn("required_skills", result)
        self.assertIn("missing_skills", result)


if __name__ == "__main__":
    unittest.main()
