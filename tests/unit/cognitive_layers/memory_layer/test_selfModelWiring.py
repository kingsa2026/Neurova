"""自我模型模块接线判据（读取面消费 + 写入面生产）。

断点背景（2026-11-21 审计）：SelfModelModule 的读取面
（get_self_description / assess_task / get_capability_confidence）在仓内
零消费方——模块只被 profile API 写入，不注入 prompt、不参与运行期判断，
属"注册了消费者却无人读"的断链。本批接线：

- 写入面：工具执行咽喉按成败更新能力置信度（recordCapabilityOutcome）；
- 读取面：build_context 的 system 指令注入 promptSection() 摘要；
- 顺手修复：profile API 对 manager.update_self_model 的位置传参 TypeError。
"""

import pytest

from neurova.cognitive_layers.memory_layer.modules.self_model_module import SelfModelModule


class TestRecordCapabilityOutcome:
    """写入面：经验式能力置信度更新（成功 +0.05 / 失败 -0.10，夹 [0,1]）。"""

    def test_recordCapabilityOutcome_raisesOnSuccess(self):
        module = SelfModelModule(agent_id="t")
        module.recordCapabilityOutcome("web_search", True)
        assert module.get_capability_confidence("web_search") == pytest.approx(0.55)

    def test_recordCapabilityOutcome_lowersOnFailure(self):
        module = SelfModelModule(agent_id="t")
        module.recordCapabilityOutcome("web_search", False)
        assert module.get_capability_confidence("web_search") == pytest.approx(0.40)

    def test_recordCapabilityOutcome_unknownStartsAtHalf(self):
        module = SelfModelModule(agent_id="t")
        # 未记录过的能力，判据基线是 0.5（get_capability_confidence 的既有缺省）
        assert module.get_capability_confidence("file_write") == pytest.approx(0.5)

    def test_recordCapabilityOutcome_clampsToUnitInterval(self):
        module = SelfModelModule(agent_id="t")
        for _ in range(30):
            module.recordCapabilityOutcome("always_fail", False)
        assert module.get_capability_confidence("always_fail") == 0.0
        for _ in range(30):
            module.recordCapabilityOutcome("always_win", True)
        assert module.get_capability_confidence("always_win") <= 1.0

    def test_recordCapabilityOutcome_rejectsEmptyCapability(self):
        module = SelfModelModule(agent_id="t")
        with pytest.raises(ValueError):
            module.recordCapabilityOutcome("", True)


class TestPromptSection:
    """读取面：prompt 注入段（有数据才产出文本，无数据返回空串零注入）。"""

    def test_promptSection_emptyWithoutData(self):
        module = SelfModelModule(agent_id="t")
        assert module.promptSection() == ""

    def test_promptSection_listsCapabilitiesAndKnowledge(self):
        module = SelfModelModule(agent_id="t")
        module.update_capability("web_search", 0.8)
        module.update_capability("file_write", 0.6)
        module.update_knowledge("数据库", 0.7)
        section = module.promptSection()
        assert section.startswith("[自我模型]")
        assert "web_search" in section and "0.80" in section
        assert "file_write" in section and "0.60" in section
        assert "数据库" in section

    def test_promptSection_knowledgeOnly(self):
        module = SelfModelModule(agent_id="t")
        module.update_knowledge("前端", 0.9)
        section = module.promptSection()
        assert "[自我模型]" in section and "前端" in section


class TestManagerWiring:
    """MemoryManager 门面委托通路。"""

    def _manager(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        return MemoryManager(agent_id="t", db_path=str(tmp_path / "mem.db"))

    def test_managerRecordCapabilityOutcomeDelegates(self, tmp_path):
        manager = self._manager(tmp_path)
        manager.recordCapabilityOutcome("file_write", False)
        module = manager._ensure_self_model_module()
        assert module.get_capability_confidence("file_write") == pytest.approx(0.40)

    def test_managerUpdateSelfModelAcceptsApiContract(self, tmp_path):
        """profile API 以 **updates 展开传参：str 与 list 字段都必须落库不炸。

        回归钉子：manager.update_self_model(self, **kwargs) 只认 int/float/str，
        list 值（values/goals/capabilities/limitations）会被静默丢弃——
        接线后 list 以逗号 join 进知识域，不再丢字段。
        """
        manager = self._manager(tmp_path)
        assert manager.update_self_model(
            narrative_identity="可靠的执行者",
            values=["诚实", "高效"],
            capabilities=["搜索", "写文件"],
        )
        module = manager._ensure_self_model_module()
        assert module.get_expertise("narrative_identity") == pytest.approx(0.5)
        assert module.get_expertise("values") == pytest.approx(0.8)
        assert module.get_expertise("capabilities") == pytest.approx(0.8)


class _StubDecomposer:
    """规则可控的任务分解桩：固定 required_skills，不触 LLM/市场。"""

    def __init__(self, skills):
        self._skills = list(skills)

    def decompose(self, request):
        from types import SimpleNamespace

        return SimpleNamespace(
            subtasks=[SimpleNamespace(required_skills=list(self._skills))],
            required_skills=[],
        )


class _StubRegistry:
    """已安装判定桩：list_skills 返回 dict 形态（与 registry 契约一致）。"""

    def __init__(self, names):
        self._names = list(names)

    def list_skills(self):
        return [{"name": n} for n in self._names]


class TestTaskAssessmentWiring:
    """任务需求分解 → 自我模型任务自评（assess_task 活消费入口）接线判据。"""

    def _analyzer(self, tmp_path, skills, provider):
        from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer

        manager = TestManagerWiring()._manager(tmp_path)
        module = manager._ensure_self_model_module()
        module.update_capability(skills[0], 0.8) if skills else None
        analyzer = SkillNeedAnalyzer(
            decomposer=_StubDecomposer(skills),
            searcher=object(),
            importer=object(),
            skill_registry=_StubRegistry(skills),
            self_model_provider=provider,
        )
        return analyzer, manager, module

    def test_analyzeAndAcquire_recordsTaskAssessment(self, tmp_path):
        analyzer, manager, module = self._analyzer(
            tmp_path, ["搜索"], lambda: manager.assessTaskCapabilities
        )
        result = analyzer.analyze_and_acquire("帮我搜索文件")
        assert result["can_execute"] is True
        stats = module.get_stats()
        assert stats["assessments_count"] == 1
        assessment = module._assessments[-1]
        assert assessment["coverage"] == pytest.approx(1.0)
        assert ("搜索", "搜索", 0.8) in [
            (req, cap, conf) for req, cap, conf in assessment["capability_matches"]
        ]

    def test_analyzeAndAcquire_noSkillNeed_skipsAssessment(self, tmp_path):
        """无技能需求的轮次（纯聊天/无需能力的任务）不得产生任务自评——防噪音。

        空required_skills若也评估，会以 coverage=1.0/confidence=0.5 的空自评
        落历史并顶掉上一次有意义自评（promptSection 只显示最近一条）。
        """
        analyzer, _manager, module = self._analyzer(tmp_path, [], lambda: _manager.assessTaskCapabilities)
        result = analyzer.analyze_and_acquire("你好")
        assert result["required_skills"] == []
        assert module.get_stats()["assessments_count"] == 0

    def test_analyzeAndAcquire_withoutProvider_skipsAssessment(self, tmp_path):
        analyzer, _manager, module = self._analyzer(tmp_path, ["搜索"], None)
        result = analyzer.analyze_and_acquire("帮我搜索文件")
        assert result["can_execute"] is True
        assert module.get_stats()["assessments_count"] == 0

    def test_analyzeAndAcquire_providerFailure_failSoft(self, tmp_path):
        def _boom():
            raise RuntimeError("self model unavailable")

        analyzer, _manager, module = self._analyzer(tmp_path, ["搜索"], _boom)
        result = analyzer.analyze_and_acquire("帮我搜索文件")
        assert result["can_execute"] is True
        assert module.get_stats()["assessments_count"] == 0

    def test_agentSkillManager_forwardsProvider(self):
        from neurova.skills.agent_skill_manager import AgentSkillManager

        provider = lambda: None  # noqa: E731
        manager = AgentSkillManager(agent_id="t", self_model_provider=provider)
        assert manager.analyzer._self_model_provider is provider

    def test_promptSection_includesLatestAssessment(self, tmp_path):
        manager = TestManagerWiring()._manager(tmp_path)
        module = manager._ensure_self_model_module()
        module.update_capability("搜索", 0.8)
        module.assess_task("帮我搜索文件", ["搜索"])
        section = module.promptSection()
        assert "最近任务自评" in section
        assert "100%" in section and "0.80" in section
