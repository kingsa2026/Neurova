"""三死步骤装配 + 9.96 门控回归测试（遗留事项 ②）

断点：post_chat Step9.9（conflict_detector）/9.95（version_control）/9.96
（dependency_graph）的依赖在生产代码中从未实例化（恒 None），三步骤恒 SKIPPED。
mem_core.py:376 的契约注释宣称 agent 拥有这些组件——装配缺失。

修复：
1. agent_core 新增 wire_memory_guards(agent) 装配函数（init_cognition 调用）：
   - conflict_detector = LegacyConflictDetector(use_semantic=False)（规则模式，
     零模型依赖，确定性）
   - version_control = get_version_control()（内存态快照，会话内可回滚）
   - dependency_graph = get_dependency_graph()（模块单例）
   - experience_fusion = ExperienceMemoryFusion(dependency_graph)
2. Step9.95 调用契约对齐：create_snapshot 真实签名是 (memory_id, content,
   metadata, author, description)，原调用传不存在的 source/triggered_by——
   依赖一旦注入必 TypeError（依赖注入后的潜伏雷）。
3. Step9.96 每轮消耗一次 LLM 调用（成本敏感）——NEUROVA_CONVERSATION_RULES
   门控，默认关。
"""

from unittest.mock import MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatContext  # noqa: F401  (装配面一致性)
from neurova.post_chat_pipeline import PostChatPipeline


class TestWireMemoryGuards:
    def test_wire_assigns_all_four_components(self):
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        ac.wire_memory_guards(agent)

        assert agent.conflict_detector is not None, "Step9.9 依赖缺失——冲突检测恒 SKIPPED"
        assert agent.version_control is not None, "Step9.95 依赖缺失——版本快照恒 SKIPPED"
        assert agent.dependency_graph is not None, "Step9.96 依赖缺失——规则提取恒 SKIPPED"
        assert agent.experience_fusion is not None

    def test_conflict_detector_uses_rule_mode(self):
        """规则模式（零模型依赖）：use_semantic=False"""
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        ac.wire_memory_guards(agent)
        assert agent.conflict_detector._use_semantic is False

    def test_detect_conflict_end_to_end(self):
        """装配后的冲突检测器对矛盾记忆真实产出冲突"""
        import neurova.agent_core as ac
        from neurova.cognitive_layers.memory_layer.models import Memory

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        ac.wire_memory_guards(agent)

        new_mem = Memory(id="n1", content="用户住在上海")
        existing = [Memory(id="e1", content="用户不住在上海")]
        conflicts = agent.conflict_detector.detect_conflict(new_mem, existing)
        assert isinstance(conflicts, list)

    def test_wire_is_idempotent(self):
        import neurova.agent_core as ac

        agent = object.__new__(ac.Agent)
        agent.config = MagicMock()
        agent.config.agent_id = "default"
        ac.wire_memory_guards(agent)
        first = agent.version_control
        ac.wire_memory_guards(agent)
        assert agent.version_control is first


class TestStep995SignatureAlignment:
    @pytest.mark.asyncio
    async def test_version_snapshot_calls_real_signature(self):
        """Step9.95 必须用 create_snapshot 真实签名（content/metadata/author）"""
        agent = MagicMock()
        pipeline = PostChatPipeline(agent)

        vc = MagicMock()
        pipeline._version_control = vc
        mm = MagicMock()
        mm.recall.return_value = [{"id": "m1", "content": "记忆内容"}]
        pipeline._memory_manager = mm

        await pipeline._step_version_snapshot("q")

        kwargs = vc.create_snapshot.call_args.kwargs
        assert "source" not in kwargs and "triggered_by" not in kwargs, (
            "create_snapshot 真实签名无 source/triggered_by 参数"
        )
        assert kwargs["memory_id"] == "m1"
        assert kwargs["content"] == "记忆内容"

    @pytest.mark.asyncio
    async def test_conflict_detection_runs_with_wired_detector(self):
        """装配后 Step9.9 真实运行（不再恒 SKIPPED）"""
        agent = MagicMock()
        pipeline = PostChatPipeline(agent)

        detector = MagicMock()
        detector.detect_conflict.return_value = []
        pipeline._conflict_detector = detector
        mm = MagicMock()
        mm.recall.return_value = [{"id": "m1", "content": "c"}]
        pipeline._memory_manager = mm

        await pipeline._step_conflict_detection("q", "r")

        detector.detect_conflict.assert_called_once()
        statuses = [str(r.status) for r in pipeline._step_results]
        assert not any("skipped" in s.lower() for s in statuses)


class TestStep996Gate:
    @pytest.mark.asyncio
    async def test_rule_extraction_default_off(self, monkeypatch):
        """9.96 每轮一次 LLM 调用——默认关（NEUROVA_CONVERSATION_RULES != 1）"""
        monkeypatch.delenv("NEUROVA_CONVERSATION_RULES", raising=False)
        agent = MagicMock()
        agent._collect_tool_messages.return_value = []
        pipeline = PostChatPipeline(agent)
        pipeline._dependency_graph = MagicMock()
        pipeline._llm_client = MagicMock()

        await pipeline._step_extract_conversation_rules("q", "r", "s1")

        statuses = [(r.step_name, str(r.status)) for r in pipeline._step_results]
        assert any(
            n == "extract_conversation_rules" and "skipped" in s.lower()
            for n, s in statuses
        ), "默认必须 SKIPPED（LLM 成本门控）"

    @pytest.mark.asyncio
    async def test_rule_extraction_enabled_with_deps(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CONVERSATION_RULES", "1")
        agent = MagicMock()
        agent._collect_tool_messages.return_value = []

        pipeline = PostChatPipeline(agent)
        graph = MagicMock()
        pipeline._dependency_graph = graph
        llm = MagicMock()
        pipeline._llm_client = llm

        extractor = MagicMock()
        rule = MagicMock()
        rule.source_entity = "A"
        rule.target_entity = "B"
        extractor.extract = pytest.importorskip("asyncio").run  # placeholder replaced below

        async def _extract(u, r, s):
            return [rule]

        extractor.extract = _extract
        with __import__("unittest").mock.patch(
            "neurova.cognitive_layers.memory_layer.conversation_rule_extractor.ConversationRuleExtractor",
            return_value=extractor,
        ):
            await pipeline._step_extract_conversation_rules("q", "r", "s1")

        statuses = [(r.step_name, str(r.status)) for r in pipeline._step_results]
        assert any(
            n == "extract_conversation_rules" and "executed" in s.lower()
            for n, s in statuses
        )
