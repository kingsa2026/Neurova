"""工具侧四断点修复契约测试（§6 P0/P0.5：C3/C4/C5；A2 留待行为面评审）。

断点 C3（生命周期双实例）：a.tool_lifecycle 必须与 a.evolution.tool_lifecycle 是
同一实例——主链（tool_executor.touch）、后处理链（post_chat evaluate）、肌肉记忆
降级检查、on_before_tool_selection 过滤器消费同一份活跃度数据。

断点 C4（facade 死调用）：EvolutionFacade.get_frequent_patterns 透传
pattern_miner.get_top_patterns，不再调用不存在的方法静默返 []。

断点 C5（熔断器/参数守卫零装配）：bootstrap_evolution_protections() 按 env 门控
显式装配（NEUROVA_TOOL_CIRCUIT_BREAKER=1 / NEUROVA_TOOL_PARAM_GUARD=1，
默认关）；未设 env 时零副作用，start_server 调用点幂等。
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestC3LifecycleSingleton(unittest.TestCase):
    """断点 C3：agent 生命周期实例与 orchestrator 过滤器实例同一。"""

    def _make_agent(self):
        import neurova.agent_core as ac

        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.enable_evolution = True
        agent.config.enable_experience_summary = True
        agent.config.enable_skill_packer = False
        agent._skill_registry = None
        agent.tool_memory = MagicMock()
        agent._router = None
        return agent, ac

    def _init(self, agent, ac):
        container = ac.SubSystemContainer(agent)
        container.init_evolution()

    def test_same_instance_as_orchestrator(self):
        agent, ac = self._make_agent()
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            with patch.object(ac, "ToolLifecycleManager") as tlm:
                self._init(agent, ac)
            # a.tool_lifecycle 不再是新建实例，而是 orchestrator 的同一实例
            self.assertIs(agent.tool_lifecycle, orch.tool_lifecycle)
            tlm.assert_not_called()

    def test_tool_memory_gets_orchestrator_instance(self):
        """tool_memory.tool_lifecycle 也指向 orchestrator 实例（肌肉记忆降级检查同源）。"""
        agent, ac = self._make_agent()
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            self._init(agent, ac)
            self.assertIs(agent.tool_memory.tool_lifecycle, orch.tool_lifecycle)

    def test_post_chat_dependency_resolves_same_instance(self):
        """post_chat _get_dependency("tool_lifecycle") 经 agent 属性拿到同一实例。"""
        agent, ac = self._make_agent()
        with patch("neurova.evolution.closed_loop.get_evolution_orchestrator") as go:
            orch = go.return_value
            self._init(agent, ac)

        from neurova.post_chat_pipeline import PostChatPipeline

        pipeline = PostChatPipeline(agent)
        self.assertIs(pipeline._get_dependency("tool_lifecycle"), orch.tool_lifecycle)


class TestC4FacadePassthrough(unittest.TestCase):
    """断点 C4：facade.get_frequent_patterns 返回真实模式而非恒空。"""

    def test_passthrough_returns_top_patterns(self):
        from neurova.evolution.evolution_facade import EvolutionFacade
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner()
        miner.add_sequence(["a", "b", "c"])
        miner.add_sequence(["a", "b"])
        miner.add_sequence(["a", "b"])
        miner.mine()

        facade = EvolutionFacade()
        facade._orchestrator = MagicMock()
        facade._orchestrator.pattern_miner = miner

        patterns = facade.get_frequent_patterns(top_n=5)
        self.assertTrue(patterns, "透传后应返回非空模式列表")
        self.assertEqual(patterns[0]["tools"] if isinstance(patterns[0], dict) else patterns[0].tools, ["a", "b"])

    def test_no_orchestrator_returns_empty(self):
        from neurova.evolution.evolution_facade import EvolutionFacade

        facade = EvolutionFacade()
        self.assertEqual(facade.get_frequent_patterns(), [])


class TestC5EnvGatedProtections(unittest.TestCase):
    """断点 C5：env 门控装配熔断器/参数守卫（默认关）。"""

    def test_no_env_no_install(self):
        from neurova.evolution.closed_loop import bootstrap_evolution_protections
        from neurova.security import tool_circuit_breaker, tool_param_guard

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEUROVA_TOOL_CIRCUIT_BREAKER", None)
            os.environ.pop("NEUROVA_TOOL_PARAM_GUARD", None)
            tool_circuit_breaker.uninstall_tool_circuit_breaker()
            tool_param_guard.uninstall_tool_param_guard()
            result = bootstrap_evolution_protections()
        self.assertEqual(result, {"circuit_breaker": False, "param_guard": False})
        self.assertIsNone(tool_circuit_breaker.get_installed_handle())
        self.assertIsNone(tool_param_guard.get_param_guard())

    def test_env_gated_install(self):
        from neurova.evolution.closed_loop import bootstrap_evolution_protections
        from neurova.security import tool_circuit_breaker, tool_param_guard

        tool_circuit_breaker.uninstall_tool_circuit_breaker()
        tool_param_guard.uninstall_tool_param_guard()
        with patch.dict(
            os.environ,
            {"NEUROVA_TOOL_CIRCUIT_BREAKER": "1", "NEUROVA_TOOL_PARAM_GUARD": "1"},
        ):
            result = bootstrap_evolution_protections()
        self.assertTrue(result["circuit_breaker"])
        self.assertTrue(result["param_guard"])
        self.assertIsNotNone(tool_circuit_breaker.get_installed_handle())
        self.assertIsNotNone(tool_param_guard.get_param_guard())
        # 清理
        tool_circuit_breaker.uninstall_tool_circuit_breaker()
        tool_param_guard.uninstall_tool_param_guard()


if __name__ == "__main__":
    unittest.main()
