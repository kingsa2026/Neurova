"""
统一进化模块测试

Tracer Bullet: 验证 EvolutionOrchestrator 作为统一入口
可以正确初始化和协调所有子组件。

历史说明：本文件曾因引用已删除符号（`neurova.evolution.experience_caller`、
`ToolWeightEntry`）整文件 skip。现按 `neurova/evolution` 的实际导出面重写：
权重面在 `closed_loop`（`AdaptiveToolWeights`/`ToolWeight`），经验面在
`experience_feedback`，技能面在 `skill_encapsulation` / `skill_improver`；
统一经验调用器（`UnifiedExperienceCaller`）已随死码清理退役，对应用例一并移除。
"""


class TestUnifiedEvolutionModule:
    """Phase 1: 统一模块导入和初始化"""

    def test_import_tool_weights(self):
        """验证 AdaptiveToolWeights / ToolWeight 可以从 closed_loop 导入"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights, ToolWeight

        atw = AdaptiveToolWeights()
        assert atw is not None
        entry = ToolWeight(tool_name="test")
        assert entry.tool_name == "test"

    def test_import_experience_feedback(self):
        """验证 ExperienceFeedback 可以从 evolution 模块导入"""
        from neurova.evolution.experience_feedback import (
            ExperienceFeedback,
            TaskToolAssociation,
            ToolInsight,
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
        pattern = ToolPattern(tool_sequence=["click", "type"])
        assert len(pattern.tool_sequence) == 2

    def test_import_skill_improver(self):
        """验证 AutoSkillImprover 可以从 evolution 模块导入"""
        from neurova.evolution.skill_improver import (
            AutoSkillImprover,
            SkillImprovement,
            SkillVariant,
        )

        improver = AutoSkillImprover()
        assert improver is not None

    def test_import_evolution_orchestrator(self):
        """验证 EvolutionOrchestrator 统一入口"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        assert orch.tool_weights is not None
        assert orch.experience_feedback is not None
        assert orch.pattern_miner is not None

    def test_evolution_init_exports_all(self):
        """验证 __init__.py 的 __all__ 逐名可导入且非 None（与现实现一致）"""
        import neurova.evolution as evolution_pkg

        exported = set(evolution_pkg.__all__)
        # 统一入口名必须在场；RSI/结晶等其余名单见 __init__.py 的 __all__
        assert {"EvolutionOrchestrator", "AdaptiveToolWeights", "AutoSkillBuilder"} <= exported
        for name in exported:
            assert getattr(evolution_pkg, name) is not None, f"__all__ 里的 {name!r} 未被导出"


class TestToolWeightAdaptation:
    """Phase 2: 工具权重自适应核心逻辑"""

    def test_register_and_rank(self):
        """注册工具并按权重排序"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.register_tool("click", base_weight=1.0)
        atw.register_tool("screenshot", base_weight=2.0)
        atw.register_tool("type", base_weight=1.5)

        ranked = atw.get_ranked_tools(["click", "screenshot", "type"])
        assert ranked[0] == "screenshot"  # 最高基础权重

    def test_success_boosts_weight(self):
        """成功调用提升权重"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        for _ in range(3):
            atw.update_weight("click", True)

        w = atw.get_effective_weight("click")
        assert w > 1.0

    def test_failure_penalizes_weight(self):
        """失败调用降低权重"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.update_weight("click", True)
        atw.update_weight("click", True)
        before = atw.get_effective_weight("click")

        atw.update_weight("click", False)
        w = atw.get_effective_weight("click")
        assert w < before  # 惩罚后应低于纯成功状态

    def test_serialize_deserialize(self, tmp_path):
        """序列化和反序列化（save/load 落盘回读）"""
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.update_weight("click", True)
        atw.update_weight("type", False)

        state_path = tmp_path / "tool_weights.json"
        assert atw.save(state_path) is True

        restored = AdaptiveToolWeights()
        assert restored.load(state_path) is True

        assert restored.get_effective_weight("click") == atw.get_effective_weight("click")
        assert restored.get_effective_weight("type") == atw.get_effective_weight("type")


class TestExperienceFeedback:
    """Phase 3: 经验反哺"""

    def test_extract_tool_mentions(self):
        """从文本中提取工具提及"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        ef = ExperienceFeedback(known_tools=["browser_click", "keyboard_type", "screenshot"])

        found = ef.extract_tool_mentions(
            "使用 browser_click 点击按钮，然后 keyboard_type 输入文本",
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

        ef = ExperienceFeedback(known_tools=["browser_click", "keyboard_type", "screenshot"])
        result = ef.process_experience(
            experience_text="使用 browser_click 成功点击了搜索按钮",
            task_type="搜索商品",
            outcome="success",
        )

        assert result["insights_created"] == 1
        assert result["tools_mentioned"] == ["browser_click"]
        assert result["outcome"] == "success"


class TestSkillEncapsulation:
    """Phase 4: 技能自动封装"""

    def test_observe_and_build_skill(self, tmp_path):
        """观察工具序列并自动构建技能（三轮独立成功证据触发封装）"""
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.skill_service import SkillService

        service = SkillService(agent_id="evolution-unified", skills_dir=str(tmp_path))
        builder = AutoSkillBuilder(
            min_pattern_occurrences=3,
            min_success_rate=0.6,
            evidence_store=service.creation_evidence,
        )

        # 模拟 3 次成功的相同模式（每个任务一份独立证据，过 P1-3 独立成功闸门）
        seq = ["browser_click", "keyboard_type", "screenshot"]
        for task_id in ("t1", "t2", "t3"):
            service.creation_evidence.record(task_id, seq, "登录账号", True)
            builder.observe(
                tool_sequence=seq,
                context="登录账号",
                success=True,
                metadata={"source_key": task_id},
            )

        # 应该自动创建了技能（评审闸默认开启时产物先进待审，但都进模板表）
        templates = builder.get_all_templates()
        assert len(templates) >= 1
        skill = templates[0]
        assert [step["tool"] for step in skill.tool_sequence] == seq

    def test_find_skills_for_context(self):
        """上下文检索技能面已随 `AutoSkillBuilder.find_skills_for_context` 退役（工单 017 B）。

        该方法自身生产零调用方（`similarity_threshold` 那一套关键词打分从未接进
        对话链）。留一条断言在此，钉住这个退役面不回潮。
        """
        from neurova.evolution.skill_encapsulation import AutoSkillBuilder

        assert not hasattr(AutoSkillBuilder, "find_skills_for_context")


class TestSkillImprover:
    """Phase 5: 技能自动改进"""

    def test_record_usage_and_propose(self):
        """记录使用并提议改进"""
        from neurova.evolution.skill_improver import AutoSkillImprover

        improver = AutoSkillImprover(min_records_for_analysis=3)
        # 记录 3 次失败
        for _ in range(3):
            improver.record_usage(
                skill_id="form_fill",
                success=False,
                error_message="元素未响应",
            )

        improvements = improver.propose_improvements("form_fill")
        assert len(improvements) >= 1
        assert improvements[0].skill_id == "form_fill"

    def test_create_variant(self):
        """创建技能变体"""
        from neurova.evolution.skill_improver import AutoSkillImprover

        improver = AutoSkillImprover()
        variant = improver.create_variant(
            skill_id="form_fill",
            name="form_fill_v2",
            changes={"add_steps": ["screenshot"]},
            description="添加 screenshot 验证",
        )

        assert variant.original_skill_id == "form_fill"
        assert variant.name == "form_fill_v2"
        assert "screenshot" in variant.changes["add_steps"]


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
            tools=["click"],
            success=True,
        )

        # 验证统计面反映权重变化
        stats = orch.get_statistics()
        assert stats["tools_with_weights"] >= 2

    def test_save_and_load_state(self, tmp_path):
        """保存和恢复状态（经 AdaptiveToolWeights 落盘/回读）"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        orch.register_tools(["click", "type"])
        orch.on_after_tool_execution("click", success=True)

        state_path = tmp_path / "evolution_state.json"
        assert orch.tool_weights.save(state_path) is True

        restored = EvolutionOrchestrator()
        assert restored.tool_weights.load(state_path) is True
        assert restored.get_statistics()["tools_with_weights"] == 1
