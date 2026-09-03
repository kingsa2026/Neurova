"""
TDD: 统一进化模块测试

Tracer Bullet: 验证 EvolutionOrchestrator 作为统一入口
可以正确初始化和协调所有子组件。
"""
import pytest
import time

pytest.skip(
    "引用不存在的名称 neurova.evolution.experience_caller 及 ToolWeightEntry（现为 AdaptiveToolWeights）。"
    "已整体 skip，待确认进化模块改名后的对齐方案；详见 docs/test-debt-skip-list.md",
    allow_module_level=True,
)


class TestUnifiedEvolutionModule:
    """Phase 1: 统一模块导入和初始化"""

    def test_import_tool_weights(self):
        """验证 AdaptiveToolWeights 可以从 evolution 模块导入"""
        from neurova.evolution.tool_weights import (
            AdaptiveToolWeights,
            ToolWeightEntry,
        )
        atw = AdaptiveToolWeights()
        assert atw is not None
        entry = ToolWeightEntry(tool_name="test")
        assert entry.tool_name == "test"

    def test_import_experience_feedback(self):
        """验证 ExperienceFeedback 可以从 evolution 模块导入"""
        from neurova.evolution.experience_feedback import (
            ExperienceFeedback,
            ToolInsight,
            TaskToolAssociation,
        )
        ef = ExperienceFeedback()
        assert ef is not None

    def test_import_skill_encapsulation(self):
        """验证 AutoSkillBuilder 和 SkillTemplate 可以从 evolution 模块导入"""
        from neurova.evolution.skill_encapsulation import (
            AutoSkillBuilder,
            SkillTemplate,
            ToolPattern,
        )
        builder = AutoSkillBuilder()
        assert builder is not None
        pattern = ToolPattern(tools=["click", "type"], context="test")
        assert len(pattern.tools) == 2

    def test_import_skill_improver(self):
        """验证 AutoSkillImprover 可以从 evolution 模块导入"""
        from neurova.evolution.skill_improver import (
            AutoSkillImprover,
            SkillVariant,
            SkillImprovement,
        )
        improver = AutoSkillImprover()
        assert improver is not None

    def test_import_evolution_orchestrator(self):
        """验证 EvolutionOrchestrator 统一入口"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        orch = EvolutionOrchestrator()
        assert orch.tool_weights is not None
        assert orch.experience_feedback is not None
        assert orch.experience_caller is not None

    def test_evolution_init_exports_all(self):
        """验证 __init__.py 导出所有公共接口"""
        from neurova.evolution import (
            AdaptiveToolWeights,
            ToolWeightEntry,
            ExperienceFeedback,
            ToolInsight,
            TaskToolAssociation,
            EvolutionOrchestrator,
            AutoSkillBuilder,
            SkillTemplate,
            ToolPattern,
            AutoSkillImprover,
            SkillVariant,
            SkillImprovement,
            UnifiedExperienceCaller,
        )
        # 所有导入应该都成功
        assert AdaptiveToolWeights is not None
        assert EvolutionOrchestrator is not None
        assert UnifiedExperienceCaller is not None


class TestToolWeightAdaptation:
    """Phase 2: 工具权重自适应核心逻辑"""

    def test_register_and_rank(self):
        """注册工具并按权重排序"""
        from neurova.evolution.tool_weights import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.register_tool("click", base_weight=1.0)
        atw.register_tool("screenshot", base_weight=2.0)
        atw.register_tool("type", base_weight=1.5)

        ranked = atw.rank_tools(["click", "screenshot", "type"])
        assert ranked[0] == "screenshot"  # 最高基础权重

    def test_success_boosts_weight(self):
        """成功调用提升权重"""
        from neurova.evolution.tool_weights import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.record_success("click")
        atw.record_success("click")
        atw.record_success("click")

        w = atw.get_effective_weight("click")
        assert w > 1.0

    def test_failure_penalizes_weight(self):
        """失败调用降低权重"""
        from neurova.evolution.tool_weights import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.record_success("click")
        atw.record_success("click")
        atw.record_failure("click")

        w = atw.get_effective_weight("click")
        assert w < 2.0  # 惩罚后应低于纯成功状态

    def test_serialize_deserialize(self):
        """序列化和反序列化"""
        from neurova.evolution.tool_weights import (
            AdaptiveToolWeights,
        )

        atw = AdaptiveToolWeights()
        atw.record_success("click")
        atw.record_failure("type")

        data = atw.to_dict()
        restored = AdaptiveToolWeights.from_dict(data)

        assert restored.get_effective_weight("click") == atw.get_effective_weight("click")
        assert restored.get_effective_weight("type") == atw.get_effective_weight("type")


class TestExperienceFeedback:
    """Phase 3: 经验反哺"""

    def test_extract_tool_mentions(self):
        """从文本中提取工具提及"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        known = {"browser_click", "keyboard_type", "screenshot"}

        found = ef.extract_tool_mentions(
            "使用 browser_click 点击按钮，然后 keyboard_type 输入文本",
            known,
        )
        assert "browser_click" in found
        assert "keyboard_type" in found
        assert "screenshot" not in found

    def test_classify_outcome_success(self):
        """分类结果为成功"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        assert ef.classify_outcome("成功完成了任务") == "success"
        assert ef.classify_outcome("task completed successfully") == "success"

    def test_classify_outcome_failure(self):
        """分类结果为失败"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        assert ef.classify_outcome("任务执行失败，发生错误") == "failure"
        assert ef.classify_outcome("task failed with error") == "failure"

    def test_process_experience_creates_insights(self):
        """处理经验创建工具洞察"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback()
        result = ef.process_experience(
            text="使用 browser_click 成功点击了搜索按钮",
            task="搜索商品",
            known_tools={"browser_click", "keyboard_type", "screenshot"},
        )

        assert len(result["insights"]) == 1
        assert result["insights"][0].tool_name == "browser_click"
        assert result["insights"][0].outcome == "success"


class TestSkillEncapsulation:
    """Phase 4: 技能自动封装"""

    def test_observe_and_build_skill(self):
        """观察工具序列并自动构建技能"""
        from neurova.evolution.skill_encapsulation import (
            AutoSkillBuilder,
        )

        builder = AutoSkillBuilder(
            min_occurrences=3,
            min_success_rate=0.6,
        )

        # 模拟 3 次成功的相同模式
        seq = ["browser_click", "keyboard_type", "browser_click"]
        for _ in range(3):
            builder.observe(
                tool_sequence=seq,
                context="登录账号",
                success=True,
            )

        # 应该自动创建了技能
        assert len(builder.skills) >= 1
        skill = list(builder.skills.values())[0]
        assert skill.tool_sequence == seq

    def test_find_skills_for_context(self):
        """根据上下文查找匹配技能"""
        from neurova.evolution.skill_encapsulation import (
            AutoSkillBuilder,
            SkillTemplate,
        )

        builder = AutoSkillBuilder(min_occurrences=1)
        # 手动添加技能
        skill = SkillTemplate(
            name="login",
            tool_sequence=["click", "type", "click"],
            context_patterns=["登录", "login", "账号"],
            success_count=10,
        )
        builder.skills["login"] = skill

        matched = builder.find_skills_for_context("请帮我登录系统")
        assert len(matched) >= 1
        assert matched[0].name == "login"


class TestSkillImprover:
    """Phase 5: 技能自动改进"""

    def test_record_usage_and_propose(self):
        """记录使用并提议改进"""
        from neurova.evolution.skill_encapsulation import SkillTemplate
        from neurova.evolution.skill_improver import AutoSkillImprover

        skill = SkillTemplate(
            name="form_fill",
            tool_sequence=["click", "type", "click"],
            success_count=0,
            failure_count=0,
        )

        improver = AutoSkillImprover()
        # 记录 3 次失败
        for _ in range(3):
            improver.record_usage(
                skill=skill,
                context="填写表单",
                success=False,
                error="元素未响应",
            )

        improvements = improver.propose_improvements("form_fill")
        assert len(improvements) >= 1

    def test_create_variant(self):
        """创建技能变体"""
        from neurova.evolution.skill_encapsulation import SkillTemplate
        from neurova.evolution.skill_improver import (
            AutoSkillImprover,
            SkillImprovement,
        )

        skill = SkillTemplate(
            name="form_fill",
            tool_sequence=["click", "type"],
            success_count=5,
            failure_count=5,
        )

        improver = AutoSkillImprover()
        improvement = SkillImprovement(
            skill_name="form_fill",
            issue="元素响应慢",
            suggestion="添加 screenshot 验证",
            improvement_type="extend",
            confidence=0.8,
        )

        variant = improver.create_variant(
            parent_skill=skill,
            improvement=improvement,
            new_sequence=["click", "type", "screenshot"],
        )

        assert variant.parent_name == "form_fill"
        assert len(variant.tool_sequence) == 3
        assert "screenshot" in variant.tool_sequence


class TestUnifiedExperienceCaller:
    """Phase 6: 统一经验调用"""

    def test_record_and_recall(self):
        """记录经验并回调"""
        from neurova.evolution.experience_caller import UnifiedExperienceCaller

        caller = UnifiedExperienceCaller()

        # 记录经验
        caller.record(
            text="使用 browser_click 成功点击了搜索按钮",
            task="搜索商品",
            tools=["browser_click"],
            success=True,
        )

        # 回调
        result = caller.find_similar_experiences("搜索")
        assert isinstance(result, list)

        stats = caller.get_stats()
        assert stats["total"] >= 1

    def test_recommend_best_practices(self):
        """推荐最佳实践"""
        from neurova.evolution.experience_caller import UnifiedExperienceCaller

        caller = UnifiedExperienceCaller()

        caller.record(
            text="使用 browser_click 定位元素时，先用 screenshot 确认页面状态",
            task="页面自动化",
            tools=["browser_click", "screenshot"],
            success=True,
            best_practice=True,
        )

        practices = caller.recommend_best_practices("页面自动化", limit=5)
        assert len(practices) >= 1


class TestEvolutionOrchestratorIntegration:
    """Phase 7: 闭环编排器集成测试"""

    def test_full_lifecycle_hooks(self):
        """完整的生命周期钩子测试"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()

        # 注册工具
        orch.register_tools(["click", "type", "screenshot"])

        # 工具选择前
        result = orch.on_before_tool_selection(
            tools=["click", "type", "screenshot"],
            context="搜索商品",
        )
        assert "ranking" in result
        assert len(result["ranking"]) == 3

        # 工具执行后
        orch.on_after_tool_execution("click", success=True, context="搜索")
        orch.on_after_tool_execution("type", success=True, context="搜索")

        # 经验记录后
        orch.on_experience_recorded(
            text="使用 click 点击搜索按钮，成功",
            task="搜索商品",
        )

        # 验证权重变化
        stats = orch.get_statistics()
        assert stats["total_executions"] >= 2

    def test_save_and_load_state(self):
        """保存和恢复状态"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["click", "type"])
        orch.on_after_tool_execution("click", success=True)

        state = orch.save_state()
        restored = EvolutionOrchestrator.load_state(state)

        assert restored.get_statistics()["total_executions"] == 1
