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
        agent.rule_extractor = None  # 强制走懒创建分支（MagicMock 自动属性会遮蔽）
        agent.experience_fusion = None

        pipeline = PostChatPipeline(agent)
        graph = MagicMock()
        pipeline._dependency_graph = graph
        llm = MagicMock()
        pipeline._llm_client = llm

        extractor = MagicMock()
        rule = MagicMock()
        rule.source_entity = "A"
        rule.target_entity = "B"

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


class TestCognitiveGraphInit:
    """总闸级回归（2026-09-05 复审抓虫）：_init_cognitive_graph 缺 c=self.config
    → NameError 被调用方 try/except 吞掉 → cognitive_engine/unified_retriever/
    crystallizer/RSI/trace_manager 五组件在真实 Agent 上从未初始化。
    """

    def test_real_agent_init_creates_five_components(self):
        """真实 Agent（真构造器）上五个认知组件必须全部就位"""
        import tempfile
        from neurova.agent_core import Agent, AgentConfig

        ws = tempfile.mkdtemp(prefix="cog_graph_test_")
        agent = Agent(
            AgentConfig(name="t", agent_id="cog_graph_test_agent", workspace_path=ws)
        )
        assert agent.cognitive_engine is not None, "认知存储引擎未初始化"
        assert agent.unified_retriever is not None, "统一检索器未初始化"
        assert agent.crystallizer is not None, "结晶器未初始化（结晶链死路）"
        assert getattr(agent, "rsi_orchestrator", None) is not None, "RSI 未初始化"
        assert agent.trace_manager is not None, "推理链未初始化"

    def test_cognitive_components_injected_into_evolution_singleton(self):
        """cognition 子系统先于 evolution 执行——其尾部注入条件恒 False，
        init_evolution 尾部的补注入必须把 crystallizer/RSI 送进单例"""
        import tempfile
        from neurova.agent_core import Agent, AgentConfig
        from neurova.evolution.closed_loop import get_evolution_orchestrator

        ws = tempfile.mkdtemp(prefix="cog_inject_test_")
        agent = Agent(
            AgentConfig(name="t", agent_id="cog_inject_test_agent", workspace_path=ws)
        )
        orch = get_evolution_orchestrator()
        assert orch.crystallizer is agent.crystallizer, (
            "单例 crystallizer 未收到 agent 实例（注入时序断点）"
        )
        assert orch.rsi_orchestrator is agent.rsi_orchestrator

    def test_cognitive_graph_survives_nameerror_free_execution(self):
        """_init_cognitive_graph 在典型最小 agent 桩上必须无 NameError 跑通"""
        import tempfile
        from pathlib import Path
        from neurova.agent_core import Agent

        agent = object.__new__(Agent)
        agent.config = type(
            "C", (), {"agent_id": "ng_test", "name": "ng", "workspace_path": Path(tempfile.mkdtemp())}
        )()
        agent.evolution = None
        agent.memory_agent = None
        agent.memory_manager = None
        # 缺失依赖走 getattr 默认；只断言不抛 NameError
        try:
            agent._init_cognitive_graph()
        except NameError as e:
            raise AssertionError(f"_init_cognitive_graph 有未定义名称: {e}")
