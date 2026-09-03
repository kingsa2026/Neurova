"""P2.1 TDD 测试 — SubSystemContainer 接线 InitializationManager

验证 SubSystemContainer 使用 InitializationManager 管理初始化顺序,
而非硬编码的顺序调用。

依赖关系图 (基于实际代码分析):
  memory:       []
  context:      [memory]
  conversation: []
  management:   []
  voice:        [memory, evolution]  # 使用 a.memory_manager 和 a.evolution
  security:     []
  cognition:    [memory]
  evolution:    [memory, management]  # 使用 a.tool_memory 和 a._skill_registry
  tools:        [memory, management]  # 使用 a.memory_manager 和 a._skill_registry
  pipeline:     [memory, context, tools]
  loop:         [pipeline]
  api_keys:     []
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))


class TestSubSystemContainerWiring:
    """验证 SubSystemContainer 接线 InitializationManager"""

    def test_init_all_uses_initialization_manager(self):
        """init_all 应使用 InitializationManager 而非硬编码顺序"""
        from neurova.agent_core import SubSystemContainer

        # 检查 init_all 方法中是否引用了 InitializationManager
        import inspect

        source = inspect.getsource(SubSystemContainer.init_all)
        assert "InitializationManager" in source or "initialization_manager" in source.lower(), (
            "init_all 应使用 InitializationManager 管理初始化顺序"
        )

    def test_dependency_graph_declared(self):
        """所有 12 个子系统应注册到 InitializationManager 并声明依赖"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()

        # 获取声明的依赖图
        dep_graph = container._build_dependency_graph()

        expected_subsystems = {
            "memory",
            "context",
            "conversation",
            "management",
            "voice",
            "security",
            "cognition",
            "evolution",
            "tools",
            "pipeline",
            "loop",
            "api_keys",
        }
        assert set(dep_graph.keys()) == expected_subsystems, (
            f"依赖图应包含所有 12 个子系统, 实际: {set(dep_graph.keys())}"
        )

    def test_context_depends_on_memory(self):
        """context 依赖 memory (使用 context_orchestrator)"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()
        assert "memory" in dep_graph["context"]

    def test_voice_depends_on_memory_and_evolution(self):
        """voice 依赖 memory 和 evolution (使用 memory_manager 和 evolution_orchestrator)"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()
        assert "memory" in dep_graph["voice"]
        assert "evolution" in dep_graph["voice"], (
            "voice 应依赖 evolution — 修复 evolution_orchestrator=None 的潜在 bug"
        )

    def test_evolution_depends_on_memory_and_management(self):
        """evolution 依赖 memory 和 management"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()
        assert "memory" in dep_graph["evolution"]
        assert "management" in dep_graph["evolution"]

    def test_pipeline_depends_on_memory_context_tools(self):
        """pipeline 依赖 memory, context, tools"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()
        assert "memory" in dep_graph["pipeline"]
        assert "context" in dep_graph["pipeline"]
        assert "tools" in dep_graph["pipeline"]

    def test_loop_depends_on_pipeline(self):
        """loop 依赖 pipeline"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()
        assert "pipeline" in dep_graph["loop"]

    def test_initialization_order_respects_dependencies(self):
        """拓扑排序后的顺序应满足所有依赖约束"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        dep_graph = container._build_dependency_graph()

        # 获取计算出的初始化顺序
        order = container._compute_initialization_order()

        # 验证顺序中包含所有子系统
        assert len(order) == 12

        # 验证依赖约束
        position = {name: i for i, name in enumerate(order)}
        for name, deps in dep_graph.items():
            for dep in deps:
                assert position[dep] < position[name], (
                    f"依赖违规: '{dep}' 应在 '{name}' 之前初始化, "
                    f"但 {dep} 在位置 {position[dep]}, {name} 在位置 {position[name]}"
                )

    def test_evolution_before_voice(self):
        """evolution 应在 voice 之前初始化 (修复 voice_memory_bridge bug)"""
        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = MagicMock()
        container.config = MagicMock()
        order = container._compute_initialization_order()

        pos_evolution = order.index("evolution")
        pos_voice = order.index("voice")
        assert pos_evolution < pos_voice, (
            f"evolution 应在 voice 之前初始化, "
            f"但 evolution 在位置 {pos_evolution}, voice 在位置 {pos_voice}"
        )

    def test_circular_dependency_detected(self):
        """循环依赖应被检测并抛出 ValueError"""
        from neurova.agent.initialization_manager import InitializationManager

        im = InitializationManager()
        im.register("a", lambda: None, deps=["b"])
        im.register("b", lambda: None, deps=["a"])

        with pytest.raises(ValueError, match="Circular dependency"):
            im.get_initialization_order()
