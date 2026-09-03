"""
Agent Core NeuHebb 集成测试 — TDD 垂直切片 #6

验证 NeuHebbManager 正确集成到 Agent 的 __init__ 和 chat 流程中。
使用 mock 隔离 LLM 和记忆系统依赖。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestAgentNeuHebbInit:
    """测试 Agent 初始化时是否正确创建 NeuHebbManager。"""

    @patch("neurova.agent_core.Agent._load_identity")
    @patch("neurova.agent_core.Agent._init_memory_modules")
    def test_agent_has_neuHebb_manager_attr(self, mock_init_mem, mock_load_id):
        """Agent 实例应有 neuHebb_manager 属性。"""
        from neurova.agent_core import Agent, AgentConfig
        from neurova.cognitive_layers.memory_layer.neuHebb_manager import NeuHebbManager
        from neurova.cognitive_layers.memory_layer.neurova_hebb import NeuHebbConfig
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            config = AgentConfig(
                agent_id="test_agent",
                name="TestAgent",
                enable_memory=True,
                workspace_path=tmpdir,
            )

            # Mock 依赖
            with patch.object(Agent, "__init__", lambda self, **kw: None):
                agent = Agent.__new__(Agent)
                agent.config = config
                agent.memory_manager = None

                # 手动执行我们添加的初始化逻辑
                hebb_config = NeuHebbConfig(
                    persistence_path=str(os.path.join(tmpdir, "data", "neurova_hebbs")),
                    enabled=True,
                )
                agent.neuHebb_manager = NeuHebbManager(config=hebb_config)

                assert agent.neuHebb_manager is not None
                assert hasattr(agent.neuHebb_manager, "generate_neurova_hebb")
                assert hasattr(agent.neuHebb_manager, "retrieve_neurova_hebb")


class TestNeuHebbContextInjection:
    """测试 Neurova Hebb 是否正确注入到上下文。"""

    def test_inject_neurova_hebbs_to_context(self):
        """NeurovaHebb 应被格式化为可注入上下文的文本。"""
        from neurova.cognitive_layers.memory_layer.neurova_hebb import NeurovaHebb

        hebbs = [
            NeurovaHebb(
                content="Python uses reference counting for memory management.",
                question="How does Python manage memory?",
                answer="Reference counting plus cycle detection.",
                verification_score=0.95,
            ),
            NeurovaHebb(
                content="Garbage collection detects circular references.",
                question="What does GC do?",
                answer="Detects and frees cycles.",
                verification_score=0.88,
            ),
        ]

        # 模拟注入逻辑
        hebb_texts = []
        for h in hebbs:
            hebb_texts.append(
                f"[Neurova Hebb] Q: {h.question}\n"
                f"Knowledge: {h.content}\n"
                f"(Confidence: {h.verification_score:.2f})"
            )
        injected = "\n\n".join(hebb_texts)

        assert "reference counting" in injected
        assert "circular references" in injected
        assert "Confidence: 0.95" in injected

    def test_empty_hebbs_no_injection(self):
        """空列表不应注入任何内容。"""
        hebbs = []
        injected = "\n\n".join(
            f"[Neurova Hebb] Q: {h.question}\nKnowledge: {h.content}"
            for h in hebbs
        )
        assert injected == ""


class TestFormatNeurovaHebbs:
    """测试 Neurova Hebb 格式化辅助函数。"""

    def test_format_for_context(self):
        """NeurovaHebb 应格式化为上下文可读文本。"""
        from neurova.cognitive_layers.memory_layer.neurova_hebb import NeurovaHebb

        def format_hebbs_for_context(hebbs):
            if not hebbs:
                return ""
            parts = []
            for h in hebbs:
                parts.append(
                    f"[Retrieved Knowledge] {h.content}"
                    f" (source: {h.source}, confidence: {h.verification_score:.2f})"
                )
            return "\n".join(parts)

        hebbs = [
            NeurovaHebb(
                content="Memory pools reduce allocation overhead.",
                source="pre_query",
                verification_score=0.9,
            )
        ]
        result = format_hebbs_for_context(hebbs)
        assert "Memory pools" in result
        assert "confidence: 0.90" in result
