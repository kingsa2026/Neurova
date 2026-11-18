"""T5/T6——identity 打标+晋升接通 与 intention 图节点

T5（拍板：归纳打标+晋升接通）：归纳 LLM 对每簇判定 kind（identity=在说
用户是谁/稳定偏好；behavior=一般行为规律）；identity 簇的证据行打
``metadata.is_identity=true``（写入单点）；召回侧不动热路径——晋升门
``run_promotion_cycle`` 的确定性硬信号增加 identity 一条（复用既有晋升/
结晶机制，让身份事实优先常驻）。

T6（拍板：图节点+现有读面）：归纳时 LLM 可选给出 intention（这组事实提示
的、值得主动跟进的未来事项）；有则额外落 entity_type="intention" 图节点
（带证据回指与关联 schema），经既有 /neuron API 可查；无 intention 不产节点。
"""

import os
import shutil
import tempfile

import pytest

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph,
    reset_dependency_graph,
)
from neurova.cognitive_layers.memory_layer.sleep_induction import (
    runSleepInduction,
)


class _FakeManager:
    """get_all_memories + get_memory + update_memory 桩（记录打标调用）。"""

    def __init__(self, rows):
        self._rows = {str(r["id"]): r for r in rows}
        self.updated: dict = {}

    def get_all_memories(self, scoped=False):
        import copy

        return [copy.deepcopy(r) for r in self._rows.values()]

    def get_memory(self, memory_id, agent_wide=False):
        import copy

        row = self._rows.get(str(memory_id))
        return copy.deepcopy(row) if row else None

    def update_memory(self, memory_id, **kwargs):
        self.updated.setdefault(str(memory_id), {}).update(kwargs)
        row = self._rows.get(str(memory_id))
        if row is None:
            return False
        if "metadata" in kwargs:
            merged = dict(row.get("metadata") or {})
            merged.update(kwargs["metadata"] or {})
            row["metadata"] = merged
        return True


def _row(rid, content, embedding, scope=("a1", "n1", "u1")):
    agent_id, neuser_id, user_id = scope
    return {"id": rid, "content": content, "embedding": list(embedding),
            "lifecycle_stage": "active", "memory_type": "semantic",
            "category": "general", "agent_id": agent_id,
            "neuser_id": neuser_id, "user_id": user_id, "temperature": 50.0}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_dependency_graph()
    monkeypatch.delenv("NEUROVA_SLEEP_INDUCTION", raising=False)
    monkeypatch.setenv("NEUROVA_SLEEP_INDUCTION", "1")
    yield
    reset_dependency_graph()


# ────────────────────────────────────────────────────────────
# T5：identity 打标
# ────────────────────────────────────────────────────────────


def test_identity_cluster_tags_evidence_rows():
    graph = DependencyGraph()
    manager = _FakeManager([
        _row("m1", "用户对花生过敏", [1.0, 0.0]),
        _row("m2", "用户吃花生会起疹子", [0.99, 0.1]),
    ])

    def _llm(_prompt):
        return ('{"name": "花生过敏", "pattern": "用户对花生过敏",'
                ' "kind": "identity", "intention": ""}')

    stats = runSleepInduction(manager, _llm, graph=graph)
    assert stats["schemas"] == 1
    entity = stats["entities"][0]
    assert entity.metadata["kind"] == "identity"
    # 证据行打上 identity 标（写入单点，供晋升门识别）
    tagged = {mid: (kwargs.get("metadata") or {}).get("is_identity")
              for mid, kwargs in manager.updated.items()}
    assert tagged == {"m1": True, "m2": True}


def test_behavior_kind_is_default_and_not_tagged():
    graph = DependencyGraph()
    manager = _FakeManager([
        _row("m1", "部署失败后回滚到上一版本", [1.0, 0.0]),
        _row("m2", "发布出错时回滚上一版本", [0.99, 0.1]),
    ])

    def _llm(_prompt):
        return '{"name": "回滚纪律", "pattern": "失败后回滚上一版"}'

    stats = runSleepInduction(manager, _llm, graph=graph)
    assert stats["schemas"] == 1
    assert stats["entities"][0].metadata["kind"] == "behavior"
    assert manager.updated == {}  # behavior 簇不打 identity 标


def test_invalid_kind_falls_back_to_behavior():
    graph = DependencyGraph()
    manager = _FakeManager([
        _row("m1", "事实甲", [1.0, 0.0]),
        _row("m2", "事实乙", [1.0, 0.01]),
    ])
    stats = runSleepInduction(
        manager, lambda p: '{"name": "n", "pattern": "p", "kind": "whatever"}',
        graph=graph)
    assert stats["entities"][0].metadata["kind"] == "behavior"


# ────────────────────────────────────────────────────────────
# T6：intention 图节点
# ────────────────────────────────────────────────────────────


def test_intention_node_written_with_evidence_and_link():
    graph = DependencyGraph()
    manager = _FakeManager([
        _row("m1", "用户提到下季度想换城市", [1.0, 0.0]),
        _row("m2", "用户在看的房源都在别的城市", [0.99, 0.1]),
    ])

    def _llm(_prompt):
        return ('{"name": "迁移迹象", "pattern": "用户在筹备换城市",'
                ' "kind": "identity",'
                ' "intention": "主动了解用户换城市的进展与需求"}')

    stats = runSleepInduction(manager, _llm, graph=graph)
    assert stats["intentions"] == 1
    intentions = [e for e in graph.entities.values()
                  if e.entity_type == "intention"]
    assert len(intentions) == 1
    node = intentions[0]
    assert node.metadata["evidence"] == ["m1", "m2"]
    assert node.metadata["related_schema"] == stats["entities"][0].id
    assert graph.get_entity(node.id) is not None


def test_no_intention_no_node():
    graph = DependencyGraph()
    manager = _FakeManager([
        _row("m1", "事实甲", [1.0, 0.0]),
        _row("m2", "事实乙", [1.0, 0.01]),
    ])
    stats = runSleepInduction(
        manager, lambda p: '{"name": "n", "pattern": "p", "intention": ""}',
        graph=graph)
    assert stats["intentions"] == 0
    assert [e for e in graph.entities.values() if e.entity_type == "intention"] == []


# ────────────────────────────────────────────────────────────
# T5：晋升门 identity 硬信号（真 MemoryManager）
# ────────────────────────────────────────────────────────────


def test_promotion_cycle_promotes_identity_rows():
    """is_identity 行即使温度/召回未达标，也走晋升（身份事实优先常驻）。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = MemoryManager(
            db_path=os.path.join(tmpdir, "identity_promo.db"),
            agent_id="agent_identity", user_id="user_identity",
        )
        mem_id = mgr.remember("用户对花生过敏", auto_analyze_emotion=False,
                              auto_classify=False, emotion="neutral")
        mgr.update_memory(mem_id, metadata={"is_identity": True})

        promoted = mgr.run_promotion_cycle(max_memories=None, min_interval_seconds=0.0)
        assert promoted >= 1
        row = mgr.get_memory(mem_id)
        assert row["metadata"].get("is_important") is True
        assert row["lifecycle_stage"] == "consolidated"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_promotion_cycle_ignores_non_identity_cold_rows():
    """无 identity 标且无硬信号的冷行不因本批改动被误晋升。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    tmpdir = tempfile.mkdtemp()
    try:
        mgr = MemoryManager(
            db_path=os.path.join(tmpdir, "cold_row.db"),
            agent_id="agent_identity", user_id="user_identity",
        )
        mem_id = mgr.remember("普通一次性事实", auto_analyze_emotion=False,
                              auto_classify=False, emotion="neutral")
        before = mgr.get_memory(mem_id)
        mgr.run_promotion_cycle(max_memories=None, min_interval_seconds=0.0)
        after = mgr.get_memory(mem_id)
        assert after["metadata"].get("is_important") in (False, None) or not after["metadata"].get("is_important")
        assert before["temperature"] == after["temperature"] or after["metadata"].get("is_important") is not True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
