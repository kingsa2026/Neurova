"""知识图谱 per-agent 隔离回归测试（TDD 红绿）

背景（2026-09-05 用户需求「图谱需要按照 agent 隔离」）：
此前 KnowledgeGraphManager 是全局单例（data/knowledge_graph/），所有
agent 共享同一份节点/边——agent A 抽取的实体在 agent B 的图谱页可见，
与知识条目的 agent 级隔离（repo._items[agent_id]）不对齐。

修复后契约：
- 每 agent 一实例，落盘 agent_workspaces/{agent_id}/knowledge_graph/
- 同一 agent_id 两次获取返回同一实例（进程内单例注册表 + 锁）
- agent_id 路径分量校验（防穿越），非法值 ValueError
- 旧全局布局 data/knowledge_graph/*.json 迁移到 default agent 目录
  （历史数据全部产自 default 的导入链，语义归属正确）；迁移用移动
- API 层 _get_kg_manager fallback 改 per-agent（agent 挂载优先保留）
- 导入抽取链路写入所属 agent 的图谱
"""

import json

import pytest

from neurova.cognitive_layers.knowledge_graph import manager as kg_mod
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    NodeType,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    kg_mod.reset_agent_knowledge_graph_managers()
    yield
    kg_mod.reset_agent_knowledge_graph_managers()


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """把 agent_workspaces 根指到临时目录，避免污染真实工作区。"""
    monkeypatch.setattr(kg_mod, "_agent_graph_root", lambda: tmp_path)
    return tmp_path


def _make_node(manager, label):
    return manager.add_node(label=label, node_type=NodeType.CONCEPT)


# ---------------------------------------------------------------
# 注册表：per-agent 单例 + 目录隔离
# ---------------------------------------------------------------


def test_same_agent_returns_same_instance(ws_root):
    a = kg_mod.get_agent_knowledge_graph_manager("a1")
    b = kg_mod.get_agent_knowledge_graph_manager("a1")
    assert a is b


def test_different_agents_isolated_instances_and_dirs(ws_root):
    a1 = kg_mod.get_agent_knowledge_graph_manager("a1")
    a2 = kg_mod.get_agent_knowledge_graph_manager("a2")
    assert a1 is not a2
    assert a1._storage_dir != a2._storage_dir
    assert a1._storage_dir.name == "knowledge_graph"
    assert a1._storage_dir.parent.name == "a1"
    assert a2._storage_dir.parent.name == "a2"


def test_agent_graphs_do_not_leak(ws_root):
    m1 = kg_mod.get_agent_knowledge_graph_manager("a1")
    m2 = kg_mod.get_agent_knowledge_graph_manager("a2")
    _make_node(m1, "secret-of-a1")
    assert len(m2._nodes) == 0, "agent a2 不得看到 a1 的节点"


def test_invalid_agent_id_rejected(ws_root):
    for bad in ("../evil", "a/b", "", "a" * 100, "."):
        with pytest.raises(ValueError):
            kg_mod.get_agent_knowledge_graph_manager(bad)


# ---------------------------------------------------------------
# 旧全局布局迁移
# ---------------------------------------------------------------


def test_legacy_layout_migrates_to_default_agent(ws_root, tmp_path):
    legacy = tmp_path / "legacy_kg"
    legacy.mkdir()
    (legacy / "nodes.json").write_text(
        json.dumps([{"node_id": "n1", "label": "old", "node_type": "concept", "weight": 1.0}]),
        encoding="utf-8",
    )
    (legacy / "edges.json").write_text("[]", encoding="utf-8")

    mgr = kg_mod.get_agent_knowledge_graph_manager(
        "default", legacy_dir=str(legacy)
    )

    assert "n1" in mgr._nodes, "旧全局数据必须迁移到 default agent 图谱"
    assert (ws_root / "default" / "knowledge_graph" / "nodes.json").exists()
    assert not (legacy / "nodes.json").exists(), "迁移必须是移动（防重复迁移）"


def test_non_default_agent_does_not_claim_legacy_data(ws_root, tmp_path):
    legacy = tmp_path / "legacy_kg"
    legacy.mkdir()
    (legacy / "nodes.json").write_text(
        json.dumps([{"node_id": "n1", "label": "old", "node_type": "concept"}]),
        encoding="utf-8",
    )

    mgr = kg_mod.get_agent_knowledge_graph_manager("other", legacy_dir=str(legacy))

    assert len(mgr._nodes) == 0
    assert (legacy / "nodes.json").exists(), "旧数据只归 default，其他 agent 不得认领"


# ---------------------------------------------------------------
# API 层：fallback 改 per-agent
# ---------------------------------------------------------------


def test_get_kg_manager_falls_back_to_agent_scoped(ws_root):
    from neurova.api.endpoints import knowledge_graph_api as kg_api

    mgr = kg_api._get_kg_manager("a9")
    assert mgr._storage_dir == ws_root / "a9" / "knowledge_graph"


def test_import_extraction_writes_agent_scoped_graph(ws_root, monkeypatch):
    """导入抽取链路必须写所属 agent 的图谱（此前写全局单例）。"""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from neurova.api import endpoints as api_endpoints
    from neurova.api.endpoints import knowledge as kb

    monkeypatch.setattr(kg_mod, "_agent_graph_root", lambda: ws_root)

    client = MagicMock()
    client.chat = AsyncMock(
        return_value=MagicMock(
            content='{"entities": [{"label": "X", "type": "concept"}], "relations": []}'
        )
    )
    api_endpoints.set_app_state(
        {"agents": {"kai": MagicMock(llm_client=client)}}
    )

    class FakeRepo:
        def find_item(self, knowledge_id):
            return ("kai", {"knowledge_id": knowledge_id})

        def update_knowledge(self, agent_id, knowledge_id, updates):
            pass

    monkeypatch.setattr(
        "neurova.knowledge.repository.get_knowledge_repository", lambda: FakeRepo()
    )

    entry = {"knowledge_id": "k1", "title": "T", "content": "C body"}
    asyncio.run(
        asyncio.to_thread(
            kb._try_extract_to_graph, [entry], None, "kai"
        )
    )

    kai_graph = kg_mod.get_agent_knowledge_graph_manager("kai")
    assert any(n.label == "X" for n in kai_graph._nodes.values()), (
        "抽取节点必须落在 kai 的 agent 图谱里"
    )
