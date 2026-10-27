"""A1 因果推理接线（§6-379）。

`causal_reasoning.py` 是唯一的多跳因果实现，但从未被生产读取。本次：
- 补认 live `RelationType.CAUSE` 的单数形 `cause`（此前只认 `causes`）；
- `MemoryManager.analyze_causal` 用与 `traverse_relations` 同源的 `_ensure_graph_traversal()`；
- 现有 `/relations/{id}/traverse` 增加 `method=causal`（链/效应/根因/解释/可选环检测）。
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager  # noqa: E402


def _manager(tmp_path):
    mm = MemoryManager(
        str(tmp_path / "memory.db"),
        agent_id="causal",
        neuser_id="default",
        user_id="default",
    )
    a = mm.remember(content="机房断电", memory_type="semantic", category="knowledge")
    b = mm.remember(content="服务器停机", memory_type="semantic", category="knowledge")
    c = mm.remember(content="订单丢失", memory_type="semantic", category="knowledge")
    mm.add_relation(source_id=a, target_id=b, relation_type="cause", strength=0.9)
    mm.add_relation(source_id=b, target_id=c, relation_type="cause", strength=0.8)
    return mm, a, b, c


def test_causalEffectsAndRootCausesUseLiveGraph(tmp_path):
    mm, a, b, c = _manager(tmp_path)

    result = mm.analyze_causal(a)

    effect_ids = {row["memory_id"] for row in result["effects"]}
    assert effect_ids == {b, c}
    assert result["summary"]["total_forward_effects"] == 2

    roots = mm.analyze_causal(c)["root_causes"]
    assert {row["memory_id"] for row in roots} == {a, b}


def test_causalChainAndExplanation(tmp_path):
    mm, a, b, c = _manager(tmp_path)

    result = mm.analyze_causal(a, target_id=c)

    assert result["chains"] == [[a, b, c]]
    assert "导致" in result["explanation"]
    assert a in result["explanation"] and c in result["explanation"]


def test_causalLoopDetectionIsOptIn(tmp_path):
    mm, a, b, c = _manager(tmp_path)
    assert mm.analyze_causal(a)["causal_loops"] == []

    mm.add_relation(source_id=c, target_id=a, relation_type="cause", strength=0.7)
    loops = mm.analyze_causal(a, includeLoops=True)["causal_loops"]

    assert loops, "加入 c→a 后必须检出因果环"


def test_traverseEndpointCausalBranch(monkeypatch):
    from neurova.api.endpoints.memory import crud

    seen = {}

    class FakeManager:
        def analyze_causal(self, memory_id, target_id=None, includeLoops=False):
            seen.update(memory_id=memory_id, target_id=target_id, includeLoops=includeLoops)
            return {"source": memory_id, "target": target_id,
                    "causal_loops": [["m1", "m2"]] if includeLoops else []}

    monkeypatch.setattr(crud, "get_memory_manager", lambda *a, **k: FakeManager())
    app = FastAPI()
    app.include_router(crud.router, prefix="/api/v1/memory")
    # 身份走生产签的真 JWT：记忆面的门挂在 router 级依赖上，判的是"请求有没有凭证"，
    # `dependency_overrides` 只能替掉处理器级解析、替不掉这道门（本仓记在
    # `tests/auth_headers.py` 的开头，§6-426 那批也是同一条）。2026-10-26 点单甲之后
    # 读侧同样要凭证，原先靠 override + 匿名请求的写法会停在 401。
    from tests.auth_headers import bearerHeaders

    with TestClient(app, headers=bearerHeaders("causal-probe"),
                   raise_server_exceptions=False) as client:
        resp = client.get(
            "/api/v1/memory/relations/m1/traverse",
            params={"method": "causal", "target_id": "m2", "include_loops": "true"},
        )

    assert resp.status_code == 200, resp.text
    assert seen == {"memory_id": "m1", "target_id": "m2", "includeLoops": True}
    assert resp.json()["data"]["target"] == "m2"
