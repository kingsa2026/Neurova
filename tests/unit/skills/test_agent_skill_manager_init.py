"""
TDD RED：暴露 AgentSkillManager 初始化崩溃 + analyze_task 调用错误（P0-B1 + P0-B2）

验证 AgentSkillManager 与 SkillNeedAnalyzer 之间的契约一致性：
1. P0-B1: AgentSkillManager.__init__ 不应崩溃
   - 当前：第 53 行 `SkillNeedAnalyzer(skill_registry=skill_registry)` 抛 TypeError
     （SkillNeedAnalyzer.__init__ 只接受 config，不接受 skill_registry）
   - 该 TypeError 未被 except ImportError 捕获，导致 AgentSkillManager 构造失败
2. P0-B2a: analyze_task 不应因 await 同步函数 + kwarg 不匹配而崩溃
   - 当前：第 86 行 `await self.analyzer.analyze_and_acquire(task=, context=, auto_acquire=)`
   - 实际签名：`def analyze_and_acquire(self, request: str) -> List[SkillAcquisitionResult]`（同步）
3. P0-B2b: suggest_skills_for_task 同理
   - 当前：第 115 行 `await self.analyzer.suggest_skills(task=, context=)`
   - 实际签名：`def suggest_skills(self, request: str, max_suggestions: int = 5)`

根因（来源：代码契约不匹配）：
    neurova/skills/agent_skill_manager.py:53
        SkillNeedAnalyzer(skill_registry=skill_registry)  # TypeError
    neurova/skills/skill_need_analyzer.py:62
        def __init__(self, config: Optional[Dict[str, Any]] = None):  # 不接受 skill_registry
    neurova/skills/agent_skill_manager.py:86
        await self.analyzer.analyze_and_acquire(task=, context=, auto_acquire=)  # 同步函数 + 错误 kwarg
    neurova/skills/skill_need_analyzer.py:83
        def analyze_and_acquire(self, request: str):  # 同步，只接受 request
"""

import asyncio
import pytest


class TestAgentSkillManagerInit:
    """测试 AgentSkillManager 初始化与调用契约"""

    def test_init_does_not_crash(self):
        """P0-B1: AgentSkillManager 构造不应崩溃

        场景：传入 agent_id 和 None skill_registry
        期望：构造成功，analyzer/decomposer/searcher/importer 至少之一非 None
        当前：第 53 行 SkillNeedAnalyzer(skill_registry=...) 抛 TypeError
              TypeError 不是 ImportError，不被 except 捕获 → 构造崩溃
        """
        from neurova.skills.agent_skill_manager import AgentSkillManager

        # 不应抛出任何异常
        manager = AgentSkillManager(
            agent_id="test_agent",
            skill_registry=None,
            auto_acquire=False,  # 关闭自动获取避免副作用
        )

        # 子模块应被正确初始化（至少 analyzer 应非 None）
        assert manager.analyzer is not None, (
            "AgentSkillManager.analyzer 应被初始化为 SkillNeedAnalyzer 实例，"
            "实际为 None（说明初始化抛了异常被 except ImportError 吞掉）"
        )

    def test_analyze_task_does_not_crash(self):
        """P0-B2a: analyze_task 不应因 await 同步函数 + kwarg 不匹配而崩溃

        场景：调用 analyze_task(task="...", context=None)
        期望：返回包含 skills_needed 键的 dict（即使为空列表）
        当前：
            - await self.analyzer.analyze_and_acquire(...) 抛 TypeError（kwarg 不匹配）
            - 即使 kwarg 修正，await 同步函数也会抛 TypeError
        """
        from neurova.skills.agent_skill_manager import AgentSkillManager

        manager = AgentSkillManager(
            agent_id="test_agent",
            skill_registry=None,
            auto_acquire=False,
        )

        # 不应抛出任何异常
        result = asyncio.run(manager.analyze_task(task="搜索文件", context=None))

        assert isinstance(result, dict), f"analyze_task 应返回 dict，实际: {type(result)}"
        assert "skills_needed" in result, (
            f"analyze_task 结果应包含 'skills_needed' 键，实际 keys: {list(result.keys())}"
        )

    def test_suggest_skills_for_task_does_not_crash(self):
        """P0-B2b: suggest_skills_for_task 不应因 await 同步函数 + kwarg 不匹配而崩溃

        场景：调用 suggest_skills_for_task(task="...", context=None)
        期望：返回 list（即使为空）
        当前：
            - await self.analyzer.suggest_skills(task=, context=) 抛 TypeError
            - 实际签名是 sync def suggest_skills(self, request: str, max_suggestions: int = 5)
        """
        from neurova.skills.agent_skill_manager import AgentSkillManager

        manager = AgentSkillManager(
            agent_id="test_agent",
            skill_registry=None,
            auto_acquire=False,
        )

        # 不应抛出任何异常
        result = asyncio.run(manager.suggest_skills_for_task(task="搜索文件", context=None))

        assert isinstance(result, list), (
            f"suggest_skills_for_task 应返回 list，实际: {type(result)}"
        )
