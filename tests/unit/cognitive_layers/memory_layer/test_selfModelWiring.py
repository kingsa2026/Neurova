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
