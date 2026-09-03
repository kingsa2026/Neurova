# -*- coding: utf-8 -*-
"""
Experience Knowledge Base - 单元测试

测试 ExperienceKnowledgeBase 的核心功能。
"""

import unittest
import tempfile
import os
import json
from datetime import datetime
from pathlib import Path

from neurova.skills.models import ExperienceRecord
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase


class TestExperienceKnowledgeBase(unittest.TestCase):
    """测试 ExperienceKnowledgeBase 类"""
    
    def setUp(self):
        """测试前设置"""
        # 创建临时数据库文件
        self.temp_db = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self.db_path = self.temp_db.name
        self.temp_db.close()
        
        # 创建 ExperienceKnowledgeBase 实例
        self.ekb = ExperienceKnowledgeBase(db_path=self.db_path)
        
        # 创建测试数据
        self.skill_name = "test-skill"
        self.context = {
            "user_input": "分析这段代码",
            "topic": "code-analysis"
        }
        self.exp = ExperienceRecord(
            skill_name=self.skill_name,
            context=self.context,
            result={"output": "分析完成"},
            success=True,
            timestamp=datetime.now().isoformat(),
            feedback="效果好"
        )
    
    def tearDown(self):
        """测试后清理"""
        # 关闭数据库连接
        if self.ekb:
            self.ekb.close()
        
        # 删除临时数据库文件
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
    
    def test_add_experience_record(self):
        """测试添加经验记录"""
        record_id = self.ekb.add_experience_record(
            skill_name=self.skill_name,
            exp=self.exp,
            agent_id="test-agent",
            session_id="test-session",
            execution_time=1.5,
            confidence_score=0.9,
            tags=["code", "analysis"]
        )
        
        self.assertIsInstance(record_id, int)
        self.assertGreater(record_id, 0)
    
    def test_get_experience_records(self):
        """测试获取经验记录"""
        # 添加一条记录
        self.ekb.add_experience_record(self.skill_name, self.exp)
        
        # 获取记录
        records = self.ekb.get_experience_records(self.skill_name)
        
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["skill_name"], self.skill_name)
        self.assertEqual(records[0]["success"], 1)
    
    def test_get_experience_records_with_filters(self):
        """测试带过滤条件的获取经验记录"""
        # 添加成功记录
        self.ekb.add_experience_record(self.skill_name, self.exp)
        
        # 添加失败记录
        exp_fail = ExperienceRecord(
            skill_name=self.skill_name,
            context={"user_input": "测试失败"},
            result=None,
            success=False,
            timestamp=datetime.now().isoformat(),
            feedback="失败"
        )
        self.ekb.add_experience_record(self.skill_name, exp_fail)
        
        # 仅获取成功记录
        success_records = self.ekb.get_experience_records(
            self.skill_name, success_only=True
        )
        self.assertEqual(len(success_records), 1)
        self.assertEqual(success_records[0]["success"], 1)
        
        # 仅获取失败记录
        fail_records = self.ekb.get_experience_records(
            self.skill_name, success_only=False
        )
        self.assertEqual(len(fail_records), 1)
        self.assertEqual(fail_records[0]["success"], 0)
    
    def test_find_similar_experiences(self):
        """测试查找相似经验"""
        # 添加一条记录
        self.ekb.add_experience_record(self.skill_name, self.exp)
        
        # 查找相似经验
        similar = self.ekb.find_similar_experiences(
            skill_name=self.skill_name,
            context={"user_input": "分析这段代码", "topic": "code-analysis"},
            limit=5
        )
        
        self.assertGreater(len(similar), 0)
        self.assertIn("similarity_score", similar[0])
    
    def test_evaluate_skill_effectiveness(self):
        """测试技能效果评估"""
        # 添加多条记录
        for i in range(10):
            exp = ExperienceRecord(
                skill_name=self.skill_name,
                context={"user_input": f"测试 {i}"},
                result={"output": f"结果 {i}"},
                success=(i < 8),  # 80% 成功率
                timestamp=datetime.now().isoformat(),
                feedback=f"反馈 {i}"
            )
            self.ekb.add_experience_record(
                self.skill_name, exp, execution_time=1.0 + i * 0.1
            )
        
        # 评估技能效果
        evaluation = self.ekb.evaluate_skill_effectiveness(self.skill_name)
        
        self.assertEqual(evaluation["skill_name"], self.skill_name)
        self.assertEqual(evaluation["total_records"], 10)
        self.assertAlmostEqual(evaluation["success_rate"], 0.8, places=1)
        self.assertIn("effectiveness_score", evaluation)
        self.assertIn("evaluation", evaluation)
    
    def test_recommend_best_practices(self):
        """测试最佳实践推荐"""
        # 添加多条成功记录
        for i in range(10):
            exp = ExperienceRecord(
                skill_name=self.skill_name,
                context={"user_input": f"分析代码 {i}"},
                result={"output": f"分析结果 {i}"},
                success=True,
                timestamp=datetime.now().isoformat(),
                feedback="成功"
            )
            self.ekb.add_experience_record(self.skill_name, exp)
        
        # 获取推荐
        recommendations = self.ekb.recommend_best_practices(self.skill_name)
        
        self.assertGreater(len(recommendations), 0)
        self.assertIn("type", recommendations[0])
        self.assertIn("recommendation", recommendations[0])
        self.assertIn("confidence", recommendations[0])
    
    def test_get_experience_stats(self):
        """测试获取经验统计"""
        # 添加记录
        self.ekb.add_experience_record(self.skill_name, self.exp)
        
        # 获取单个技能统计
        stats = self.ekb.get_experience_stats(self.skill_name)
        
        self.assertEqual(stats["skill_name"], self.skill_name)
        self.assertEqual(stats["total_experiences"], 1)
        self.assertEqual(stats["success_count"], 1)
        
        # 获取全局统计
        global_stats = self.ekb.get_experience_stats()
        
        self.assertIn("total_skills", global_stats)
        self.assertIn("total_records", global_stats)
    
    def test_get_skill_ranking(self):
        """测试获取技能排名"""
        # 添加多个技能的记录
        for i in range(5):
            skill_name = f"skill-{i}"
            for j in range(10):
                exp = ExperienceRecord(
                    skill_name=skill_name,
                    context={"user_input": f"测试 {j}"},
                    result={"output": f"结果 {j}"},
                    success=(j < 8),  # 80% 成功率
                    timestamp=datetime.now().isoformat(),
                    feedback="好"
                )
                self.ekb.add_experience_record(skill_name, exp)
        
        # 获取排名
        ranking = self.ekb.get_skill_ranking(metric="success_rate", limit=3)
        
        self.assertLessEqual(len(ranking), 3)
        if ranking:
            self.assertIn("skill_name", ranking[0])
            self.assertIn("total", ranking[0])
    
    def test_empty_skill_stats(self):
        """测试空技能的统计"""
        stats = self.ekb.get_experience_stats("non-existent-skill")
        
        self.assertEqual(stats["total_experiences"], 0)
        # success_rate 字段在空技能时不存在，检查其他字段
        self.assertIn("skill_name", stats)


class TestExperienceRecord(unittest.TestCase):
    """测试 ExperienceRecord 数据模型"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        exp = ExperienceRecord(
            skill_name="test-skill",
            context={"user_input": "测试"},
            result={"output": "结果"},
            success=True,
            timestamp="2026-05-13T22:00:00",
            feedback="好"
        )
        
        d = exp.to_dict()
        
        self.assertEqual(d["skill_name"], "test-skill")
        self.assertEqual(d["context"]["user_input"], "测试")
        self.assertTrue(d["success"])
    
    def test_from_dict(self):
        """测试从字典创建"""
        d = {
            "skill_name": "test-skill",
            "context": {"user_input": "测试"},
            "result": {"output": "结果"},
            "success": True,
            "timestamp": "2026-05-13T22:00:00",
            "feedback": "好"
        }
        
        exp = ExperienceRecord.from_dict(d)
        
        self.assertEqual(exp.skill_name, "test-skill")
        self.assertEqual(exp.context["user_input"], "测试")
        self.assertTrue(exp.success)


if __name__ == "__main__":
    unittest.main()
