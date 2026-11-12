# -*- coding: utf-8 -*-
"""P1-10 票 A·MoE 路由作用域隔离红测。

根因（复核实证）：mem_core.py:806-812 给 MoE 建向量索引时按 persist.db 全库
无差别取数（SELECT ... ORDER BY temperature DESC LIMIT 500，不带身份列），
MoEMemoryRouter.retrieve 也不做任何作用域过滤——用户 B 的查询可经 MoE
向量兜底/专家下钻召回用户 A 的记忆（跨人串忆，与 recall_flat 同族）。

修复口径（与 recall 面同族）：
- 索引带上身份（neuser_id/user_id 进 items）；
- MoEMemoryRouter 增 scope_resolver（mem_core 装配时接
  memory_manager.memoryScope——作用域口径单源），retrieve 结果按生效
  作用域过滤；无身份标记的结果按拒绝处理（fail-closed：索引已带身份，
  缺列＝旧索引未重建）。
"""
import asyncio

import pytest


ROWS = [
    {
        "id": "mem_a", "content": "用户A的私有事实：保险箱密码是1qaz2wsx",
        "category": "general", "lifecycle_stage": "active",
        "neuser_id": "ne-a", "user_id": "u-a", "temperature": 90,
        "origin": "owner",
    },
    {
        "id": "mem_b", "content": "用户B的普通笔记：今天买了牛奶",
        "category": "general", "lifecycle_stage": "active",
        "neuser_id": "ne-b", "user_id": "u-b", "temperature": 80,
        "origin": "owner",
    },
]

ITEMS = [
    {"id": r["id"], "content": r["content"],
     "metadata": {"category": r["category"], "lifecycle": r["lifecycle_stage"],
                  "neuser_id": r["neuser_id"], "user_id": r["user_id"]}}
    for r in ROWS
]


class FakeStore:
    """persist.db 替身：专家下钻的 SELECT 原样回构造行"""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, *args, **kwargs):
        class _Cur:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return _Cur(self._rows)


def _contents(rows):
    return [str((r or {}).get("content") or "") for r in rows]


def _build_router(scope):
    from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter
    from neurova.cognitive_layers.memory_layer.unified_vector_store import (
        UnifiedVectorStore,
    )

    vector_store = UnifiedVectorStore(backend="tfidf")
    vector_store.index_memories(ITEMS)
    return MoEMemoryRouter(
        experts={
            "general_expert": {
                "name": "通用记忆",
                "category": "general",
                "centroid_text": "通用对话与事实",
            }
        },
        storage=FakeStore(ROWS),
        vector_store=vector_store,
        scope_resolver=scope,
    )


class TestMoEScopeIsolation:
    def test_user_b_scope_does_not_recall_user_a(self):
        router = _build_router(lambda: ("ne-b", "u-b"))
        results = asyncio.run(router.retrieve("保险箱密码", limit=5))
        assert "1qaz2wsx" not in "".join(_contents(results)), (
            f"MoE 跨人串忆：用户 B 召回了用户 A 的私有记忆：{_contents(results)}"
        )

    def test_owner_recalls_own_via_moe(self):
        router = _build_router(lambda: ("ne-a", "u-a"))
        results = asyncio.run(router.retrieve("保险箱密码", limit=5))
        assert any("1qaz2wsx" in c for c in _contents(results)), (
            f"本人经 MoE 召回不得丢：{_contents(results)}"
        )

    def test_unscoped_context_sees_only_default_bucket(self):
        """作用域缺省（无绑定降级）＝default 桶：两个非 default 用户的行都不可见。"""
        router = _build_router(lambda: ("default", "default"))
        results = asyncio.run(router.retrieve("保险箱密码", limit=5))
        assert "1qaz2wsx" not in "".join(_contents(results))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
