"""
单元测试：neurova/skills/task_decomposer.py

测试任务拆解器：TaskDecomposer (CogArch 1.0.0 实现)

契约来源：neurova/skills/task_decomposer.py 当前实现
- SubTask 字段: id, description, task_type, required_skills, dependencies, priority, estimated_time, metadata
- TaskDecompositionResult 字段: original_request, subtasks, required_skills, decomposition_strategy, confidence, metadata
- TaskDecomposer.__init__(llm_client=None, config=None)  # 无 skill_registry 参数
- _identify_required_skills(request)  # 单参数
- analyze_skill_needs(request) -> List[str]  # 返回列表
- 任务类型 token: analysis, creation, modification, deletion, search, communication, automation
- 技能 ID: web-development, database, ai-ml, data-analysis, file-management, network, security
- LLM JSON 子任务字段: id, description, task_type, required_skills, dependencies
"""
import unittest
from unittest.mock import MagicMock

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from neurova.skills.task_decomposer import (
    TaskDecomposer,
    SubTask,
    TaskDecompositionResult,
)


class TestSubTask(unittest.TestCase):
    """测试 SubTask 数据类 (1.0)"""

    def test_create_subtask(self):
        """测试创建子任务"""
        subtask = SubTask(
            id="task_1",
            description="这是一个测试子任务",
            task_type="search",
            required_skills=["web-development"],
            priority=8,
            estimated_time=1.5,
        )

        self.assertEqual(subtask.id, "task_1")
        self.assertEqual(subtask.description, "这是一个测试子任务")
        self.assertEqual(subtask.task_type, "search")
        self.assertEqual(len(subtask.required_skills), 1)
        self.assertEqual(subtask.priority, 8)
        self.assertEqual(subtask.estimated_time, 1.5)

    def test_subtask_defaults(self):
        """测试默认值"""
        subtask = SubTask(id="task_1", description="测试")
        self.assertEqual(subtask.task_type, "general")
        self.assertEqual(subtask.required_skills, [])
        self.assertEqual(subtask.dependencies, [])
        self.assertEqual(subtask.priority, 0)
        self.assertEqual(subtask.estimated_time, 0.0)
        self.assertEqual(subtask.metadata, {})

    def test_subtask_to_dict(self):
        """测试 to_dict() 方法"""
        subtask = SubTask(
            id="task_1",
            description="这是一个测试子任务",
            task_type="search",
        )

        result = subtask.to_dict()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], "task_1")
        self.assertEqual(result["description"], "这是一个测试子任务")
        self.assertEqual(result["task_type"], "search")

    def test_subtask_from_dict(self):
        """测试 from_dict() 类方法"""
        data = {
            "id": "task_1",
            "description": "这是一个测试子任务",
            "task_type": "search",
            "required_skills": ["web-development"],
            "priority": 8,
        }

        subtask = SubTask.from_dict(data)
        self.assertEqual(subtask.id, "task_1")
        self.assertEqual(subtask.description, "这是一个测试子任务")
        self.assertEqual(subtask.task_type, "search")
        self.assertEqual(len(subtask.required_skills), 1)
        self.assertEqual(subtask.priority, 8)


class TestTaskDecompositionResult(unittest.TestCase):
    """测试 TaskDecompositionResult 数据类 (1.0)"""

    def test_create_result(self):
        """测试创建任务拆解结果"""
        subtasks = [
            SubTask(id="task_1", description="子任务1"),
            SubTask(id="task_2", description="子任务2"),
        ]

        result = TaskDecompositionResult(
            original_request="测试任务",
            subtasks=subtasks,
            required_skills=["web-development"],
        )

        self.assertEqual(result.original_request, "测试任务")
        self.assertEqual(len(result.subtasks), 2)
        self.assertEqual(len(result.required_skills), 1)
        self.assertEqual(result.decomposition_strategy, "rules")
        self.assertEqual(result.confidence, 0.0)

    def test_result_to_dict(self):
        """测试 to_dict() 方法"""
        subtasks = [
            SubTask(id="task_1", description="子任务1"),
        ]

        result = TaskDecompositionResult(
            original_request="测试任务",
            subtasks=subtasks,
        )

        result_dict = result.to_dict()
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict["original_request"], "测试任务")
        self.assertEqual(len(result_dict["subtasks"]), 1)


class TestTaskDecomposer(unittest.TestCase):
    """测试 TaskDecomposer 类 (1.0)"""

    def setUp(self):
        """测试前设置"""
        self.decomposer = TaskDecomposer()

    def test_init_without_dependencies(self):
        """测试初始化（无依赖）"""
        self.assertIsNone(self.decomposer.llm_client)
        self.assertEqual(self.decomposer.config, {})
        self.assertFalse(self.decomposer._use_llm)

    def test_init_with_config(self):
        """测试初始化（带配置）"""
        config = {"max_subtasks": 5}
        decomposer = TaskDecomposer(config=config)
        self.assertEqual(decomposer.config, config)

    def test_decompose_simple_task(self):
        """测试拆解简单任务"""
        task = "搜索 Neurova 项目"

        result = self.decomposer.decompose(task)

        self.assertEqual(result.original_request, task)
        self.assertGreater(len(result.subtasks), 0)
        self.assertIsInstance(result.subtasks[0], SubTask)

    def test_decompose_complex_task(self):
        """测试拆解复杂任务"""
        task = """实现一个计算器应用：
        1. 创建用户界面
        2. 实现计算逻辑
        3. 添加错误处理"""

        result = self.decomposer.decompose(task)

        self.assertEqual(result.original_request, task)
        self.assertGreater(len(result.subtasks), 0)

    def test_identify_task_types(self):
        """测试识别任务类型 (1.0 token: search/creation/analysis)"""
        # 测试搜索任务
        task_types = self.decomposer._identify_task_types("搜索 Neurova 项目")
        self.assertIn("search", task_types)

        # 测试创建任务 (1.0 使用 "creation" 而非 "create")
        task_types = self.decomposer._identify_task_types("创建一个网页")
        self.assertIn("creation", task_types)

        # 测试分析任务 (1.0 使用 "analysis")
        task_types = self.decomposer._identify_task_types("分析这个数据")
        self.assertIn("analysis", task_types)

    def test_identify_required_skills(self):
        """测试识别所需技能 (1.0 单参数，技能 ID 为 web-development 等)"""
        # 1.0 实现的 _identify_required_skills 是单参数
        skills = self.decomposer._identify_required_skills("搜索网页")

        # 1.0 技能关键词: "网页" -> "web-development"
        self.assertIn("web-development", skills)

    def test_extract_steps(self):
        """测试提取步骤"""
        # 测试编号列表
        task = "1. 第一步\n2. 第二步\n3. 第三步"
        steps = self.decomposer._extract_steps(task)
        self.assertGreater(len(steps), 0)

        # 测试无明确步骤
        task = "这是一个简单的任务。没有明确的步骤。"
        steps = self.decomposer._extract_steps(task)
        self.assertGreater(len(steps), 0)  # 应该按句子拆分

    def test_analyze_skill_needs(self):
        """测试分析技能需求 (1.0 返回 List[str])"""
        task = "搜索 Neurova 项目并分析代码"

        result = self.decomposer.analyze_skill_needs(task)

        # 1.0 实现: analyze_skill_needs 返回 List[str]
        self.assertIsInstance(result, list)
        # 应包含 search 相关技能
        self.assertGreater(len(result), 0)


class TestTaskDecomposerWithLLM(unittest.TestCase):
    """测试 TaskDecomposer（使用 LLM）"""

    def test_decompose_with_llm_success(self):
        """测试使用 LLM 拆解任务（成功）- 1.0 JSON 契约: id/description/task_type"""
        # 模拟 LLM 客户端
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '''{
            "subtasks": [
                {
                    "id": "task-1",
                    "description": "在 GitHub 上搜索 Neurova 项目",
                    "task_type": "search",
                    "required_skills": ["web-development"],
                    "dependencies": []
                }
            ],
            "required_skills": ["web-development"],
            "decomposition_strategy": "llm"
        }'''

        decomposer = TaskDecomposer(llm_client=mock_llm)
        task = "搜索 Neurova 项目"

        result = decomposer.decompose(task)

        self.assertEqual(len(result.subtasks), 1)
        # 1.0 SubTask 字段是 id (不是 name)
        self.assertEqual(result.subtasks[0].id, "task-1")
        self.assertEqual(result.subtasks[0].description, "在 GitHub 上搜索 Neurova 项目")
        self.assertEqual(result.decomposition_strategy, "llm")
        mock_llm.generate.assert_called_once()

    def test_decompose_with_llm_failure_fallback(self):
        """测试使用 LLM 拆解任务（失败，回退到规则方法）"""
        # 模拟 LLM 客户端（抛出异常）
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("LLM error")

        decomposer = TaskDecomposer(llm_client=mock_llm)
        task = "搜索 Neurova 项目"

        # 应该回退到规则方法，不抛出异常
        result = decomposer.decompose(task)

        self.assertIsNotNone(result)
        # 1.0 字段是 original_request (不是 original_task)
        self.assertEqual(result.original_request, task)


if __name__ == "__main__":
    unittest.main()
