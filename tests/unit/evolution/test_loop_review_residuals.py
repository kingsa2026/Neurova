"""复审残余点修复回归测试（2026-09-05 闭环复审）

残余点 A（回环放大 + 隔离破坏）：PatternCrystallizer._try_crystallize 结晶成功后
回调 record_experience 未传 crystallizer——走单例回退路径，把本 agent 的结晶产物
再次喂回单例上可能已换主的 crystallizer（自喂环 + 跨 agent 污染复活）。

残余点 B（连接 churn）：post_chat Step9 与 injector._build_experience_context 每轮
`ExperienceKnowledgeBase()` 新开 SQLite 连接且从不 close（依赖 GC __del__）。
模块单例 get_experience_knowledge_base() 一直存在但零调用——两处改走单例。

残余点 C（最后一米）：_step_rsi_iteration 的 apply_improvement 已有 skill_service
参数但不传——改进落盘通道在此处断开。
"""

from unittest.mock import MagicMock, patch

import pytest

from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.closed_loop import EvolutionOrchestrator


class TestCrystallizerCallbackPassesSelf:
    def _crystallizer(self, engine, evolution):
        return PatternCrystallizer(engine=engine, evolution_orchestrator=evolution)

    def test_crystallize_callback_passes_self(self):
        """结晶成功回调必须显式传 crystallizer=self（agent 级隔离不因回调复活）"""
        mock_engine = MagicMock()
        mock_engine.retrieve.return_value = []
        orch = EvolutionOrchestrator()
        cryst = self._crystallizer(mock_engine, orch)

        captured = {}

        def fake_record(text, task, tools, success, crystallizer=None):
            captured["crystallizer"] = crystallizer
            return {"success": True}

        with patch(
            "neurova.evolution.evolution_facade.EvolutionFacade.record_experience",
            side_effect=fake_record,
        ):
            for _ in range(3):
                cryst.observe(tool_name="w1", context="重复任务模式", success=True)

        assert captured.get("crystallizer") is cryst, (
            "结晶回调必须传 crystallizer=self，否则回退到单例上可能换主的实例"
        )


class TestEkbSingletonUsage:
    def test_post_chat_uses_singleton(self):
        """Step9 EKB 写入必须走模块单例（不每轮新建连接）"""
        import neurova.post_chat_pipeline as pcp

        src = open(pcp.__file__, encoding="utf-8").read()
        seg = src[src.index("async def _step_record_experience"):]
        seg = seg[: seg.index("async def _step_memory_temperature") if "_step_memory_temperature" in seg else seg.index("\n    async def", 10)]
        assert "ExperienceKnowledgeBase()" not in seg, (
            "Step9 不得每轮新建 EKB 连接——改用 get_experience_knowledge_base()"
        )
        assert "get_experience_knowledge_base()" in seg

    def test_injector_uses_singleton(self):
        import neurova.context.injector as inj

        src = open(inj.__file__, encoding="utf-8").read()
        seg = src[src.index("def _build_experience_context"):]
        seg = seg[: seg.index("def _format_experience_from_list")]
        assert "ExperienceKnowledgeBase()" not in seg
        assert "get_experience_knowledge_base()" in seg

    def test_singleton_is_shared_instance(self):
        from neurova.skills.experience_knowledge_base import (
            get_experience_knowledge_base,
        )

        assert get_experience_knowledge_base() is get_experience_knowledge_base()


class TestRsiStepPassesSkillService:
    @pytest.mark.asyncio
    async def test_step_rsi_passes_skill_service_to_apply(self):
        """最后一米：_step_rsi_iteration 必须把 SkillService 传给 apply_improvement"""
        from unittest.mock import patch as _patch

        from neurova.post_chat_pipeline import PostChatPipeline

        agent = MagicMock()
        agent.config.agent_id = "default"
        agent._skill_registry = MagicMock()
        agent._skill_registry.get_skill.return_value = MagicMock(
            config={}, version="1.0.0"
        )

        pipeline = PostChatPipeline(agent)

        improver = MagicMock()
        proposal = MagicMock()
        proposal.applied = False
        improver.propose_pending_improvements.return_value = [proposal]
        improver.apply_improvement.return_value = True

        captured = {}

        def fake_apply(prop, registry, skill_service=None):
            captured["skill_service"] = skill_service
            return True

        improver.apply_improvement.side_effect = fake_apply

        with _patch(
            "neurova.evolution.skill_improver.get_skill_improver",
            return_value=improver,
        ), _patch(
            "neurova.skills.skill_service.SkillService"
        ) as svc_cls:
            svc_instance = svc_cls.return_value
            await pipeline._step_rsi_iteration()

        assert captured.get("skill_service") is svc_instance, (
            "apply_improvement 必须收到 SkillService 实例（改进落盘最后一米）"
        )
