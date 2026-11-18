"""T3 跨域碰撞 sweeper——行为/语义双空间判据与 core schema 归纳

记忆模型论文启发 T3（docs/04-plans/2026-11-18-memory-model-inspiration-plan.md）：
对 schema 节点做双空间扫描——行为描述嵌入相似（cos>θ_beh）**且**语义嵌入
遥远（cos<θ_sem）判为碰撞（行为像、话题远），union-find 聚合后由 LLM 归纳
更高层 core schema。论文消融实验中该机制贡献最大单项（4.1 分）。

钉住的契约：
- 判据是**双空间同时成立**：行为像但话题也近（平凡冗余）不碰撞；
  行为不像不碰撞；
- 同作用域内才扫描（跨作用域永不碰撞——隔离纪律）；
- core schema 节点带 member_schemas + evidence 并集 + HIERARCHICAL 边连到
  每个成员；
- LLM 失败 fail-soft：不产 core、如实计数、不抛；
- 门控与 T2 同一开关（NEUROVA_SLEEP_INDUCTION）。
"""

import copy

import pytest

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph,
    DependencyType,
    EntityNode,
    reset_dependency_graph,
)
from neurova.cognitive_layers.memory_layer.sleep_induction import (
    SCHEMA_ENTITY_TYPE,
    buildSyncLlmFn,
    runCrossDomainSweep,
    runInductionPhase,
    sleepInductionEnabled,
)

SCOPE_A = ("ag", "n1", "u1")


class _FakeManager:
    """get_all_memories + get_memory（agent_wide 系统面口径）桩。"""

    def __init__(self, rows):
        self._rows = {str(r["id"]): r for r in rows}

    def get_all_memories(self, scoped=False):
        return list(self._rows.values())

    def get_memory(self, memory_id, agent_wide=False):
        row = self._rows.get(str(memory_id))
        if row is None:
            return None
        return copy.deepcopy(row)


def _schema(graph, entity_id, name, pattern, evidence, scope=SCOPE_A):
    graph.add_entity(EntityNode(
        id=entity_id, name=name, entity_type=SCHEMA_ENTITY_TYPE,
        metadata={"pattern": pattern, "evidence": list(evidence),
                  "scope": list(scope)},
    ))


def _synonymEmbedder(*groups):
    """确定性假嵌入器：第 i 组任一同义词命中 → 单位向量 e_i；全不命中 → 零向量。

    同义行为词（回滚/退回/重来/恢复）共享同一维——真实嵌入器对同义句也会
    给出相近向量，这里是可控确定性的等价物。
    """
    def _embed(text):
        vec = [0.0] * len(groups)
        for i, synonyms in enumerate(groups):
            if any(kw in text for kw in synonyms):
                vec[i] = 1.0
        return vec
    return _embed


def _row(rid, content, embedding, scope=SCOPE_A):
    agent_id, neuser_id, user_id = scope
    return {"id": rid, "content": content, "embedding": list(embedding),
            "lifecycle_stage": "active", "memory_type": "semantic",
            "category": "general", "agent_id": agent_id,
            "neuser_id": neuser_id, "user_id": user_id, "temperature": 50.0}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_dependency_graph()
    monkeypatch.delenv("NEUROVA_SLEEP_INDUCTION", raising=False)
    yield
    reset_dependency_graph()


# ────────────────────────────────────────────────────────────
# 判据
# ────────────────────────────────────────────────────────────


def test_collision_behavior_same_topic_far(monkeypatch):
    """行为像（回滚≈退回）+ 话题远（部署 vs 厨艺）→ 碰撞 → core schema。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚到上一版本", ["m1"])
    _schema(graph, "schema:s2", "重来纪律", "做砸了就退回上一个可用版本", ["m2"])
    manager = _FakeManager([
        _row("m1", "部署失败回滚", [1.0, 0.0, 0.0]),   # 话题：部署
        _row("m2", "炒菜咸了加水", [0.0, 1.0, 0.0]),   # 话题：厨艺
    ])
    embed = _synonymEmbedder(["回滚", "退回", "重来", "恢复"], ["切菜", "备菜"])

    stats = runCrossDomainSweep(
        manager, graph, embed_fn=embed,
        llm_fn=lambda p: '{"name": "止损重试", "pattern": "受挫后退回上一可用状态重来"}')
    assert stats["collisions"] == 1
    assert stats["core_schemas"] == 1
    core = stats["entities"][0]
    assert core.entity_type == "core_schema"
    assert set(core.metadata["member_schemas"]) == {"schema:s1", "schema:s2"}
    assert set(core.metadata["evidence"]) == {"m1", "m2"}
    # HIERARCHICAL 边：core → 每个成员；成员之间不连边
    edge_pairs = {(e.source_id, e.target_id) for e in graph.edges}
    assert ("schema:s1", "schema:s2") not in edge_pairs
    assert (core.id, "schema:s1") in edge_pairs
    assert (core.id, "schema:s2") in edge_pairs
    for e in graph.edges:
        if e.source_id == core.id:
            assert e.dep_type == DependencyType.HIERARCHICAL


def test_trivial_redundancy_does_not_collide(monkeypatch):
    """行为像且话题也像（同域冗余）→ 不碰（两个空间都高的是平凡对）。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚到上一版本", ["m1"])
    _schema(graph, "schema:s2", "回滚纪律二", "发布出错时回滚上一版本", ["m2"])
    manager = _FakeManager([
        _row("m1", "部署失败回滚", [1.0, 0.0, 0.0]),
        _row("m2", "发布回滚", [1.0, 0.0, 0.0]),  # 同话题
    ])
    embed = _synonymEmbedder(["回滚", "退回"], ["切菜", "备菜"])

    stats = runCrossDomainSweep(manager, graph, embed_fn=embed, llm_fn=None)
    assert stats["collisions"] == 0
    assert stats["core_schemas"] == 0


def test_behavior_differs_no_collision(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚到上一版本", ["m1"])
    _schema(graph, "schema:s2", "备菜纪律", "周末把菜先切好分装", ["m2"])
    manager = _FakeManager([
        _row("m1", "部署失败回滚", [1.0, 0.0, 0.0]),
        _row("m2", "周末备菜", [0.0, 1.0, 0.0]),
    ])
    embed = _synonymEmbedder(["回滚", "退回"], ["切菜", "备菜"])

    stats = runCrossDomainSweep(manager, graph, embed_fn=embed, llm_fn=None)
    assert stats["collisions"] == 0
    assert stats["core_schemas"] == 0


def test_cross_scope_never_collides(monkeypatch):
    """同 pattern 同行为，但分属两个作用域 → 永不碰撞（隔离纪律）。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚", ["m1"],
            scope=("ag", "n1", "u1"))
    _schema(graph, "schema:s2", "回滚纪律", "遇到失败先回滚", ["m2"],
            scope=("ag", "n2", "u2"))
    manager = _FakeManager([
        _row("m1", "部署失败回滚", [1.0, 0.0, 0.0], scope=("ag", "n1", "u1")),
        _row("m2", "部署失败回滚", [1.0, 0.0, 0.0], scope=("ag", "n2", "u2")),
    ])
    embed = _synonymEmbedder(["回滚", "退回"])

    stats = runCrossDomainSweep(manager, graph, embed_fn=embed, llm_fn=None)
    assert stats["collisions"] == 0
    assert stats["core_schemas"] == 0


# ────────────────────────────────────────────────────────────
# 归纳与防御
# ────────────────────────────────────────────────────────────


def test_llm_failure_is_fail_soft(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚到上一版本", ["m1"])
    _schema(graph, "schema:s2", "重来纪律", "做砸了就退回上一个可用版本", ["m2"])
    manager = _FakeManager([
        _row("m1", "部署失败回滚", [1.0, 0.0, 0.0]),
        _row("m2", "炒菜咸了加水", [0.0, 1.0, 0.0]),
    ])
    embed = _synonymEmbedder(["回滚", "退回", "重来", "恢复"], ["切菜", "备菜"])

    def _boom(_prompt):
        raise RuntimeError("llm down")

    stats = runCrossDomainSweep(manager, graph, embed_fn=embed, llm_fn=_boom)
    assert stats["core_schemas"] == 0
    assert stats["failed"] == 1


def test_gate_off_is_noop():
    stats = runCrossDomainSweep(_FakeManager([]), DependencyGraph(),
                                embed_fn=_synonymEmbedder(["x"]), llm_fn=None)
    assert stats["enabled"] is False


def test_three_way_collision_unions_into_one_core(monkeypatch):
    """三 schema 碰撞链（s1~s2、s2~s3）→ union-find 并成一簇 → 一个 core。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    _schema(graph, "schema:s1", "回滚纪律", "遇到失败先回滚", ["m1"])
    _schema(graph, "schema:s2", "重来纪律", "做砸了退回上一版重来", ["m2"])
    _schema(graph, "schema:s3", "复原纪律", "搞砸了恢复到上个能用的状态", ["m3"])
    manager = _FakeManager([
        _row("m1", "部署回滚", [1.0, 0.0, 0.0]),
        _row("m2", "炒菜加水", [0.0, 1.0, 0.0]),
        _row("m3", "代码回退", [0.0, 0.0, 1.0]),
    ])
    embed = _synonymEmbedder(["回滚", "退回", "重来", "恢复"], ["炒菜"], ["回退"])

    stats = runCrossDomainSweep(
        manager, graph, embed_fn=embed,
        llm_fn=lambda p: '{"name": "止损重来", "pattern": "受挫后退回上一可用状态"}')
    assert stats["collisions"] == 3  # 三者行为同维 → 三对全碰撞
    assert stats["core_schemas"] == 1
    assert len(stats["entities"]) == 1
    assert set(stats["entities"][0].metadata["member_schemas"]) == {
        "schema:s1", "schema:s2", "schema:s3"}


def test_build_sync_llm_fn_returns_none_for_clientless():
    assert buildSyncLlmFn(None) is None

    class _NoGenerate:
        pass

    assert buildSyncLlmFn(_NoGenerate()) is None


def test_run_induction_phase_combines_both(monkeypatch):
    """runInductionPhase = T2 归纳 + T3 扫描的一次性入口（两触发点共用）。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    manager = _FakeManager([
        _row("m1", "部署失败后回滚到上一版本", [1.0, 0.0]),
        _row("m2", "发布出错时回滚上一版本", [0.99, 0.1]),
    ])
    graph = DependencyGraph()
    stats = runInductionPhase(
        manager, lambda p: '{"name": "回滚", "pattern": "失败后回滚上一版"}',
        graph=graph, embed_fn=_synonymEmbedder(["回滚", "退回"], ["部署", "发布"]))
    assert stats["induction"]["schemas"] == 1
    assert stats["sweep"]["core_schemas"] == 0  # 单 schema 无碰撞可言
    assert sleepInductionEnabled() is True
