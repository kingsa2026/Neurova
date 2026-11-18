"""T4b 依赖图收口单源——全仓只有一份 DependencyGraph

DCPM 启发 T4（docs/04-plans/2026-11-18-dcpm-memory-inspiration-plan.md T4）：
此前三套互不相通的图实例——conversation_rule_extractor 用的模块单例
（agent.dependency_graph = get_dependency_graph()）、neuron.py 的
``_shared_graph`` DCL 单例、neurova_recall 的 ``DependencyGraph()`` 自建——
图谱类归纳产物没有统一读面。拍板：收口单源到 ``get_dependency_graph()``。

钉住三条契约：
- neuron 的 ``get_shared_graph()`` 就是模块单例（同一对象）；
- ``reset_shared_graph()`` 重置的也是同一单源（兼容名，语义不分裂）；
- NeurovaRecallEngine 的 NEURON 组件（CascadeEngine/AbsenceReasoner）
  挂在同一份图上——neuron API 写入的边，recall 侧推理读得到。
"""

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    get_dependency_graph,
    reset_dependency_graph,
)


def setup_function(_):
    reset_dependency_graph()


def teardown_function(_):
    reset_dependency_graph()


def test_neuron_shared_graph_is_the_module_singleton():
    from neurova.api.endpoints.neuron import get_shared_graph

    assert get_shared_graph() is get_dependency_graph()


def test_neuron_reset_resets_the_same_source():
    from neurova.api.endpoints.neuron import get_shared_graph, reset_shared_graph

    first = get_shared_graph()
    reset_shared_graph()
    second = get_shared_graph()
    assert second is not first
    assert second is get_dependency_graph()


def test_recall_neuron_components_hang_off_the_singleton():
    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

    engine = NeurovaRecallEngine()
    assert engine._ensure_neuron_components() is True
    assert engine._dependency_graph is get_dependency_graph()


def test_edges_written_via_singleton_are_visible_to_recall_components():
    """同源的价值：一侧写入，另一侧读到（此前三套实例各写各的、互相看不见）。"""
    from neurova.cognitive_layers.memory_layer.dependency_graph import (
        DependencyEdge,
        DependencyType,
        EntityNode,
    )
    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

    graph = get_dependency_graph()
    graph.add_entity(EntityNode(id="ent_a", name="实体A", entity_type="concept"))
    graph.add_entity(EntityNode(id="ent_b", name="实体B", entity_type="concept"))
    graph.add_dependency(
        DependencyEdge(
            id="edge_ab",
            source_id="ent_a",
            target_id="ent_b",
            dep_type=DependencyType.CAUSAL,
        )
    )

    engine = NeurovaRecallEngine()
    assert engine._ensure_neuron_components() is True
    assert engine._dependency_graph is graph
    assert "ent_a" in graph.entities and "ent_b" in graph.entities
    assert graph.get_downstream("ent_a") == ["ent_b"]
