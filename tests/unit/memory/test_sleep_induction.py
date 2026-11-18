"""T2 睡眠归纳相位——sleep_induction 模块契约

记忆模型论文启发 T2（docs/04-plans/2026-11-18-memory-model-inspiration-plan.md）：
把 论文中的 System2 的"归纳"装进本仓深睡/休眠窗口——对未被任何上层结构引用的
事实按隔离三元组分桶、语义聚类，每簇一次 LLM 归纳出 schema 节点，落统一
依赖图（T4b 收口后的那份）并带证据回指。

钉住的契约：
- 门控 NEUROVA_SLEEP_INDUCTION 默认 off：关闭时 runSleepInduction 直通
  （enabled=False），不选材、不写图、不调 LLM；
- 选材排除已退役行与已被既有 schema 证据引用的行；无嵌入行不参与；
- 按隔离三元组分桶——绝不跨作用域聚成一簇；
- 每簇一次 LLM，产物是 entity_type="schema" 的图节点，metadata 带
  evidence（源记忆 id）+ scope + pattern；
- LLM 失败只跳过该簇（fail-soft），绝不阻断睡眠整理主流程；
- 每周期 schema 产量有具名上限；与既有 schema 同 pattern 不重复归纳。
"""

import threading

import pytest

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph,
    reset_dependency_graph,
)
from neurova.cognitive_layers.memory_layer.sleep_induction import (
    INDUCTION_MAX_SCHEMAS_PER_CYCLE,
    SCHEMA_ENTITY_TYPE,
    runSleepInduction,
    sleepInductionEnabled,
)


class _FakeManager:
    """只提供 get_all_memories 的桩（系统面全量口径）。"""

    def __init__(self, rows):
        self._rows = rows

    def get_all_memories(self, scoped=False):
        return list(self._rows)


def _row(rid, content, embedding, *, scope=("a1", "n1", "u1"),
         stage="active", mtype="semantic"):
    agent_id, neuser_id, user_id = scope
    return {
        "id": rid,
        "content": content,
        "embedding": embedding,
        "lifecycle_stage": stage,
        "memory_type": mtype,
        "category": "general",
        "agent_id": agent_id,
        "neuser_id": neuser_id,
        "user_id": user_id,
        "temperature": 50.0,
    }


@pytest.fixture(autouse=True)
def _clean_graph_and_env(monkeypatch):
    reset_dependency_graph()
    monkeypatch.delenv("NEUROVA_SLEEP_INDUCTION", raising=False)
    yield
    reset_dependency_graph()


# ────────────────────────────────────────────────────────────
# 门控
# ────────────────────────────────────────────────────────────


def test_default_is_off():
    assert sleepInductionEnabled() is False


def test_env_turns_it_on(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    assert sleepInductionEnabled() is True


def test_disabled_run_is_a_noop():
    manager = _FakeManager([
        _row("m1", "事实一", [1.0, 0.0]),
        _row("m2", "事实二", [1.0, 0.01]),
    ])
    calls = []
    stats = runSleepInduction(manager, lambda prompt: calls.append(prompt) or "{}",
                              graph=DependencyGraph())
    assert stats["enabled"] is False
    assert calls == []
    assert stats["schemas"] == 0


# ────────────────────────────────────────────────────────────
# 选材与分桶
# ────────────────────────────────────────────────────────────


def test_candidates_exclude_retired_and_embedless(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    manager = _FakeManager([
        _row("m_active", "活跃事实", [1.0, 0.0]),
        _row("m_forgotten", "已遗忘", [1.0, 0.0], stage="forgotten"),
        _row("m_archived", "已归档", [1.0, 0.0], stage="archived"),
        _row("m_noemb", "没有嵌入", []),
        _row("m_crystal", "已结晶", [1.0, 0.0], stage="crystallized"),
    ])
    stats = runSleepInduction(manager, lambda p: "{}", graph=DependencyGraph())
    assert stats["candidates"] == 1  # 只有 m_active 参选


def test_no_cross_scope_cluster(monkeypatch):
    """同文不同作用域 = 各自成簇各自归纳，evidence 不串域。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    vec = [1.0, 0.0]
    near = [0.99, 0.1]
    manager = _FakeManager([
        _row("a1", "用户偏好周末远程办公", vec, scope=("ag", "n1", "u1")),
        _row("a2", "用户周末习惯在家办公", near, scope=("ag", "n1", "u1")),
        _row("b1", "用户偏好周末远程办公", vec, scope=("ag", "n2", "u2")),
        _row("b2", "用户周末习惯在家办公", near, scope=("ag", "n2", "u2")),
    ])

    def _llm(prompt):
        return '{"name": "办公模式", "pattern": "偏好周末远程办公"}'

    stats = runSleepInduction(manager, _llm, graph=DependencyGraph())
    assert stats["schemas"] == 2
    # 两个 schema 的 evidence 各自只含本作用域的行
    scopes = set()
    for entity in stats["entities"]:
        ev = entity.metadata["evidence"]
        scopes.add(tuple(entity.metadata["scope"]))
        assert set(ev) in ({"a1", "a2"}, {"b1", "b2"})
    assert scopes == {("ag", "n1", "u1"), ("ag", "n2", "u2")}


# ────────────────────────────────────────────────────────────
# 归纳产物
# ────────────────────────────────────────────────────────────


def test_schema_written_with_evidence_and_pattern(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    manager = _FakeManager([
        _row("m1", "部署失败后回滚到上一版本", [1.0, 0.0]),
        _row("m2", "发布出错时回滚上一版本", [0.99, 0.1]),
    ])

    def _llm(prompt):
        return '{"name": "回滚纪律", "pattern": "部署失败后回滚到上一版本"}'

    graph = DependencyGraph()
    stats = runSleepInduction(manager, _llm, graph=graph)
    assert stats["schemas"] == 1
    entity = stats["entities"][0]
    assert entity.entity_type == SCHEMA_ENTITY_TYPE
    assert sorted(entity.metadata["evidence"]) == ["m1", "m2"]
    assert entity.metadata["pattern"] == "部署失败后回滚到上一版本"
    # 产物真的落在了图上
    assert graph.get_entity(entity.id) is not None


def test_llm_failure_skips_cluster_without_raising(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    manager = _FakeManager([
        _row("m1", "事实甲", [1.0, 0.0]),
        _row("m2", "事实乙", [1.0, 0.01]),
    ])

    def _boom(prompt):
        raise RuntimeError("llm down")

    stats = runSleepInduction(manager, _boom, graph=DependencyGraph())
    assert stats["schemas"] == 0
    assert stats["failed"] == 1  # 如实计数，不静默


def test_max_schemas_per_cycle(monkeypatch):
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    rows = []
    for i in range(10):  # 10 个互不相似的簇（每簇两条近邻行，跨簇正交）
        base = [1.0 if j == i else 0.0 for j in range(10)]
        near = list(base)
        near[9] = 0.1
        near[i] = 0.99
        rows.append(_row(f"m{2 * i}", f"独立事实{i}甲", base))
        rows.append(_row(f"m{2 * i + 1}", f"独立事实{i}乙", near))
    seen = {"n": 0}

    def _numbered(_prompt):
        seen["n"] += 1
        return '{"name": "n%d", "pattern": "p%d"}' % (seen["n"], seen["n"])

    stats = runSleepInduction(
        manager=_FakeManager(rows),
        llm_fn=_numbered,
        graph=DependencyGraph(),
        max_schemas=2,
    )
    assert stats["clusters"] == 10
    assert stats["schemas"] == 2
    assert stats["deferred"] == 8  # 10 簇只取 2，余 8 簇顺延且如实计数


def test_existing_schema_evidence_excludes_rows(monkeypatch):
    """已被既有 schema 引用的事实不再重复参选。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    from neurova.cognitive_layers.memory_layer.dependency_graph import EntityNode

    graph.add_entity(EntityNode(
        id="schema:existing", name="既有模式", entity_type=SCHEMA_ENTITY_TYPE,
        metadata={"evidence": ["m1"], "pattern": "既有", "scope": ["a1", "n1", "u1"]},
    ))
    manager = _FakeManager([
        _row("m1", "已被引用的事实", [1.0, 0.0]),
        _row("m2", "未被引用的事实", [0.0, 1.0]),
    ])
    stats = runSleepInduction(manager, lambda p: '{"name":"n","pattern":"p"}',
                              graph=graph)
    assert stats["candidates"] == 1  # m1 被既有证据占用


def test_identical_pattern_not_reinduced(monkeypatch):
    """与既有 schema 同 pattern 的簇跳过（不产重复节点）。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    graph = DependencyGraph()
    from neurova.cognitive_layers.memory_layer.dependency_graph import EntityNode

    graph.add_entity(EntityNode(
        id="schema:existing", name="回滚纪律", entity_type=SCHEMA_ENTITY_TYPE,
        metadata={"evidence": ["old1"], "pattern": "部署失败后回滚到上一版本",
                  "scope": ["a1", "n1", "u1"]},
    ))
    manager = _FakeManager([
        _row("m1", "部署失败后回滚到上一版本", [1.0, 0.0]),
        _row("m2", "发布出错时回滚上一版本", [0.99, 0.1]),
    ])
    stats = runSleepInduction(
        manager, lambda p: '{"name": "回滚纪律", "pattern": "部署失败后回滚到上一版本"}',
        graph=graph)
    assert stats["schemas"] == 0
    assert stats["dedup_skipped"] == 1


def test_default_cap_is_named_constant():
    """runSleepInduction 缺省上限 = 具名常量（不许散落字面量）。"""
    manager = _FakeManager([])
    stats = runSleepInduction(manager, lambda p: "{}", graph=DependencyGraph())
    assert stats["max_schemas"] == INDUCTION_MAX_SCHEMAS_PER_CYCLE


def test_llm_prompt_carries_cluster_content(monkeypatch):
    """归纳提示词必须携带簇内原文（可解释性：schema 从哪几句来）。"""
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    seen = {}

    def _llm(prompt):
        seen["p"] = prompt
        return '{"name": "n", "pattern": "p"}'

    manager = _FakeManager([
        _row("m1", "独有事实甲", [1.0, 0.0]),
        _row("m2", "独有事实乙", [1.0, 0.01]),
    ])
    runSleepInduction(manager, _llm, graph=DependencyGraph())
    assert "独有事实甲" in seen["p"] and "独有事实乙" in seen["p"]
