"""
TDD RED：暴露 AutoSkillImprover.apply_improvement 空骨架 + SkillGenerator 模拟 LLM（P0-B4）

验证两个核心问题：
1. AutoSkillImprover.apply_improvement 是 TODO 空骨架
   - 当前：仅 logger.info + return True，不记录应用状态、不更新 suggested_changes
   - 期望：应标记 improvement 为已应用（applied 字段）并保留持久化痕迹
2. SkillGenerator._analyze_requirement 在 llm_client 可用时仍返回硬编码模拟数据
   - 当前：检查 `if self.llm_client:` 后仍然跳过 LLM 调用，返回静态 dict
   - 期望：当 llm_client 提供时，应实际调用 LLM 进行需求分析

根因：
    neurova/skills/auto_skill_improver.py:71-75
        def apply_improvement(self, improvement: SkillImprovement) -> bool:
            # TODO: 实现自动应用改进的逻辑
            logger.info("Applying improvement for %s: %s", ...)
            return True
    neurova/skills/skill_generator.py:232-257
        if self.llm_client:
            # 模拟 LLM 调用  ← 注释直接承认是模拟
            analysis = { 硬编码 dict }
            return analysis
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestAutoSkillImproverApplyImprovement:
    """P0-B4 Part 1: AutoSkillImprover.apply_improvement 不应是空骨架"""

    def test_apply_improvement_records_applied_state(self):
        """apply_improvement 应记录改进的应用状态

        场景：构造 SkillImprovement 并调用 apply_improvement
        期望：improvement 上有 applied 标记（或 improvement_history 中有应用记录）
        当前：apply_improvement 仅日志 + return True，无任何状态变更
        """
        from neurova.skills.auto_skill_improver import AutoSkillImprover, SkillImprovement

        improver = AutoSkillImprover()
        improvement = SkillImprovement(
            skill_id="test_skill",
            improvement_type="accuracy",
            description="测试改进",
            confidence=0.8,
            suggested_changes={"threshold": 0.9},
        )

        result = improver.apply_improvement(improvement)

        # 应返回 True 表示应用成功
        assert result is True, "apply_improvement 应返回 True 表示应用成功"

        # 改进应被标记为已应用（不能只是日志 + return True）
        # 检查方式 1: improvement 对象上的 applied 字段
        # 检查方式 2: improver 上的 applied_history 或 improvement_history 中的状态
        has_applied_marker = (
            getattr(improvement, "applied", False) is True
            or hasattr(improver, "applied_improvements")
            or any(
                getattr(record, "applied", False)
                for record in improver.improvement_history
            )
        )
        assert has_applied_marker, (
            "apply_improvement 应留下应用痕迹（improvement.applied=True 或 "
            "improver.applied_improvements 列表），而非仅 logger.info + return True"
        )


class TestSkillGeneratorUsesLLMClient:
    """P0-B4 Part 2: SkillGenerator 在 llm_client 可用时应实际调用 LLM"""

    def test_analyze_requirement_calls_llm_when_client_provided(self):
        """_analyze_requirement 应实际调用 llm_client 而非返回硬编码模拟数据

        场景：构造 SkillGenerator(llm_client=mock_client)，调用 _analyze_requirement
        期望：mock_client.chat 被调用
        当前：检查 if self.llm_client 后仍返回硬编码 dict，不调用 LLM
        """
        from neurova.skills.skill_generator import SkillGenerator

        # 构造 mock LLM client
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value='{"功能描述":"LLM分析结果","输入输出格式":{"input":"str","output":"str"},"依赖项":[],"复杂度评估":"低","安全考虑":[]}')

        generator = SkillGenerator(llm_client=mock_llm)

        result = asyncio.run(generator._analyze_requirement("测试需求", context={}))

        # mock_llm.chat 应被调用过
        assert mock_llm.chat.called, (
            "SkillGenerator._analyze_requirement 在 llm_client 可用时应实际调用 LLM，"
            "实际未调用（仍是模拟实现）。"
        )

        # 返回结果应来自 LLM（包含 "LLM分析结果"），而非硬编码 "中等"
        assert result.get("功能描述") == "LLM分析结果", (
            f"分析结果应来自 LLM 调用，实际: {result}（仍是硬编码模拟数据）"
        )
