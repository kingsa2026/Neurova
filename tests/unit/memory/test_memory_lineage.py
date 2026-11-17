"""T1 supersedes 链读路径化——memoryLineage 统一链读取函数

DCPM 启发 T1（docs/04-plans/2026-11-18-dcpm-memory-inspiration-plan.md）：
世代链三处写点（S16 世代失效 ``memoryDiscipline.supersededBy``、导入取代
``superseded_by_ingest``、睡眠合并 ``merged_from``）此前**只写不读**——
recall 排除 FORGOTTEN 行后，"这条结论以前是什么、被谁修订"无法回答。

本测试钉住读面契约：
- 链上节点/边从任一代出发都可读出（正向指针 + 反向扫描双达）；
- supersede 边携带 basis/at（可解释），merge 边 relation=merged_into；
- max_depth 有界；成环不死循环；不存在的 id 返回 None（fail-closed）；
- 端点 GET /api/v1/memory/{id}/lineage 接线（404 与成功包络两态）。

边界：行号/字段名以 2026-11-18 工作树为锚。
"""

import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from neurova.cognitive_layers.memory_layer.lineage import (
    LINEAGE_MAX_DEPTH,
    memoryLineage,
)
from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture()
def mgr():
    tmpdir = tempfile.mkdtemp()
    try:
        yield MemoryManager(
            db_path=os.path.join(tmpdir, "lineage_test.db"),
            agent_id="agent_lineage",
            user_id="user_lineage",
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _remember(mgr, content, **kwargs):
    kwargs.setdefault("auto_analyze_emotion", False)
    kwargs.setdefault("auto_classify", False)
    kwargs.setdefault("emotion", "neutral")
    return mgr.remember(content, **kwargs)


def _markSuperseded(mgr, old_id, new_id, basis="同一命题的否证"):
    """按 S16 世代失效的真实落点造数据（memoryDiscipline 浅合并键）。"""
    row = mgr.get_memory(old_id)
    assert row is not None, "造数据前提：旧代行存在"
    disc = dict((row.get("metadata") or {}).get("memoryDiscipline") or {})
    disc.update(
        {
            "status": "superseded",
            "supersededBy": new_id,
            "supersededAt": "2026-11-18T00:00:00+00:00",
            "supersededBasis": basis,
        }
    )
    assert mgr.update_memory(
        old_id, lifecycle_stage="forgotten", metadata={"memoryDiscipline": disc}
    )


def _markIngestSupersede(mgr, old_id, new_id):
    """按导入取代的真实落点造数据（superseded_by_ingest）。"""
    assert mgr.update_memory(
        old_id, lifecycle_stage="forgotten", metadata={"superseded_by_ingest": new_id}
    )


def _markMerged(mgr, product_id, source_ids):
    """按睡眠写回的真实落点造数据（产物行 merged_from）。"""
    assert mgr.update_memory(product_id, metadata={"merged_from": list(source_ids)})


def _edgeTriples(result):
    return [(e["from"], e["to"], e["relation"]) for e in result["edges"]]


# ────────────────────────────────────────────────────────────
# S16 世代失效链
# ────────────────────────────────────────────────────────────


def test_supersede_chain_readable_from_new_generation(mgr):
    """从新代出发能读出被它取代的旧代，依据随边携带。"""
    old_id = _remember(mgr, "用户的项目使用 PostgreSQL")
    new_id = _remember(mgr, "用户的项目已改用 MySQL")
    _markSuperseded(mgr, old_id, new_id, basis="同一属性 project 的取值互斥")

    result = memoryLineage(mgr, new_id)
    assert result is not None
    assert result["root_id"] == new_id
    node_ids = {n["id"] for n in result["nodes"]}
    assert old_id in node_ids and new_id in node_ids
    assert (old_id, new_id, "superseded_by") in _edgeTriples(result)
    edge = next(e for e in result["edges"] if e["to"] == new_id)
    assert edge["basis"] == "同一属性 project 的取值互斥"
    assert edge["at"] == "2026-11-18T00:00:00+00:00"


def test_supersede_chain_readable_from_old_generation(mgr):
    """从旧代出发沿自身指针能读出新代（正向可达）。"""
    old_id = _remember(mgr, "旧结论：接口超时阈值 30 秒")
    new_id = _remember(mgr, "新结论：接口超时阈值 60 秒")
    _markSuperseded(mgr, old_id, new_id)

    result = memoryLineage(mgr, old_id)
    assert result is not None
    assert (old_id, new_id, "superseded_by") in _edgeTriples(result)
    node_ids = {n["id"] for n in result["nodes"]}
    assert node_ids == {old_id, new_id}


# ────────────────────────────────────────────────────────────
# 睡眠合并链
# ────────────────────────────────────────────────────────────


def test_merge_product_links_all_sources(mgr):
    """合并产物的每条源都有 merged_into 边；从源出发反向可达产物。"""
    s1 = _remember(mgr, "咖啡偏好记录一：用户喜欢拿铁")
    s2 = _remember(mgr, "咖啡偏好记录二：用户喜欢拿铁，常加燕麦奶")
    product = _remember(mgr, "咖啡偏好：用户喜欢拿铁，常加燕麦奶（合并版）")
    _markMerged(mgr, product, [s1, s2])

    result = memoryLineage(mgr, product)
    assert result is not None
    triples = _edgeTriples(result)
    assert (s1, product, "merged_into") in triples
    assert (s2, product, "merged_into") in triples

    back = memoryLineage(mgr, s1)
    assert back is not None
    pairs = {(e["from"], e["to"]) for e in back["edges"]}
    # 从任一源出发经产物可达合并家族全部成员（DAG 遍历语义）
    assert (s1, product) in pairs
    assert (s2, product) in pairs


# ────────────────────────────────────────────────────────────
# 导入取代链
# ────────────────────────────────────────────────────────────


def test_ingest_supersede_link(mgr):
    old_id = _remember(mgr, "导入前的事实：仓库地址在深圳")
    new_id = _remember(mgr, "导入后修订：仓库地址已迁东莞")
    _markIngestSupersede(mgr, old_id, new_id)

    result = memoryLineage(mgr, new_id)
    assert result is not None
    assert (old_id, new_id, "superseded_by") in _edgeTriples(result)


# ────────────────────────────────────────────────────────────
# 有界与防御
# ────────────────────────────────────────────────────────────


def test_depth_limit_bounds_traversal(mgr):
    a = _remember(mgr, "第一代结论")
    b = _remember(mgr, "第二代结论")
    c = _remember(mgr, "第三代结论")
    _markSuperseded(mgr, a, b)
    _markSuperseded(mgr, b, c)

    shallow = memoryLineage(mgr, c, max_depth=1)
    assert {n["id"] for n in shallow["nodes"]} == {b, c}
    full = memoryLineage(mgr, c, max_depth=LINEAGE_MAX_DEPTH)
    assert {n["id"] for n in full["nodes"]} == {a, b, c}


def test_cycle_does_not_hang(mgr):
    a = _remember(mgr, "环上甲")
    b = _remember(mgr, "环上乙")
    _markSuperseded(mgr, a, b)
    _markSuperseded(mgr, b, a)  # 人为成环：读面必须终止且不重复吞节点

    result = memoryLineage(mgr, a)
    assert result is not None
    assert {n["id"] for n in result["nodes"]} == {a, b}
    assert len(result["edges"]) == 2


def test_dangling_pointer_yields_no_ghost_node(mgr):
    """指针指向不存在/越权行时不得造出幽灵节点。"""
    only_id = _remember(mgr, "唯一一行，指针悬空")
    assert mgr.update_memory(
        only_id, metadata={"memoryDiscipline": {"supersededBy": "mem_ghost"}}
    )
    result = memoryLineage(mgr, only_id)
    assert result is not None
    assert {n["id"] for n in result["nodes"]} == {only_id}
    assert result["edges"] == []


def test_unknown_id_returns_none(mgr):
    assert memoryLineage(mgr, "mem_not_exists") is None


def test_node_content_is_previewed_not_infinite(mgr):
    from neurova.cognitive_layers.memory_layer.lineage import (
        LINEAGE_CONTENT_PREVIEW_CHARS,
    )

    long_text = "长" * (LINEAGE_CONTENT_PREVIEW_CHARS * 3)
    mid = _remember(mgr, long_text)
    result = memoryLineage(mgr, mid)
    node = next(n for n in result["nodes"] if n["id"] == mid)
    assert len(node["content"]) <= LINEAGE_CONTENT_PREVIEW_CHARS + 1  # +1 为省略号


# ────────────────────────────────────────────────────────────
# 端点接线（GET /api/v1/memory/{memory_id}/lineage）
# ────────────────────────────────────────────────────────────


class _StubManager:
    """只提供 lineage 读取所需的两只读方法的桩。"""

    def __init__(self, rows):
        self._rows = {str(r["id"]): r for r in rows}

    def get_memory(self, memory_id, agent_wide=False):
        return self._rows.get(str(memory_id))

    def get_all_memories(self, scoped=False):
        return list(self._rows.values())


def _endpoint_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import requireIdentityForMemoryFace
    from neurova.api.endpoints.memory import router as memory_router

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/v1/memory")
    # 与主 app 同款异常处理器：APIError.not_found → 404 包络（否则裸 app 下变 500）
    from neurova.api.error_handlers import register_error_handlers

    register_error_handlers(app)
    app.dependency_overrides[requireIdentityForMemoryFace] = lambda: {
        "user_id": "u1",
        "neuser_id": "n1",
        "role": "user",
        "username": "u1",
    }
    return TestClient(app)


def test_lineage_endpoint_success_and_404():
    from neurova.api.endpoints.memory import lineage as lineage_ep

    rows = [
        {
            "id": "m_old",
            "content": "旧代",
            "lifecycle_stage": "forgotten",
            "created_at": "2026-11-17T00:00:00",
            "metadata": {
                "memoryDiscipline": {
                    "status": "superseded",
                    "supersededBy": "m_new",
                    "supersededBasis": "依据X",
                }
            },
        },
        {
            "id": "m_new",
            "content": "新代",
            "lifecycle_stage": "active",
            "created_at": "2026-11-18T00:00:00",
            "metadata": {},
        },
    ]
    client = _endpoint_client()
    with patch.object(lineage_ep, "get_memory_manager", return_value=_StubManager(rows)):
        resp = client.get("/api/v1/memory/m_new/lineage")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["root_id"] == "m_new"
        assert ("m_old", "m_new", "superseded_by") in _edgeTriples(body["data"])

        resp404 = client.get("/api/v1/memory/m_missing/lineage")
        assert resp404.status_code == 404
