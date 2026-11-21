# -*- coding: utf-8 -*-
"""M9（多模态追平批一）：ContextSource 生成物来源 + 活水池语义。

锁定契约：
1. ContextSource 增 GENERATION（生成物）来源值，命名对齐既有枚举风格；
2. SOURCE_PRIORITY 阶梯给值（与 TOOL_CALL 同档：模型可消费的过程产物）；
3. add_context 单源咽喉可写入、query 按 source 命中、draw 语义通道可召回。
"""
from __future__ import annotations

from neurova.context.pool_models import (
    SOURCE_PRIORITY,
    ContextInput,
    ContextSource,
    priorityForSource,
)


def test_generation_source_exists():
    assert ContextSource.GENERATION.value == "generation"


def test_generation_priority_in_ladder():
    """与 TOOL_CALL 同档 60：模型可消费的过程产物，高于情感、低于系统指令。"""
    assert priorityForSource(ContextSource.GENERATION) == 60
    assert SOURCE_PRIORITY[ContextSource.GENERATION] == 60
    assert priorityForSource(ContextSource.GENERATION) == priorityForSource(
        ContextSource.TOOL_CALL)
    assert priorityForSource(ContextSource.GENERATION) > priorityForSource(
        ContextSource.EMOTION)


def test_add_context_stores_generation_entry_with_metadata():
    from neurova.context_pool import ContextPool

    pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
    pool.add_context(ContextInput(
        source=ContextSource.GENERATION,
        content="[生成产物:image] 一只猫 产物: /api/v1/generation/files/x.png",
        metadata={"task_id": "t9", "session_id": "s1", "turn": 3},
        tags=["generation", "image"],
    ))
    hits = pool.query(source=ContextSource.GENERATION)
    assert len(hits) == 1
    assert hits[0].metadata["task_id"] == "t9"
    assert hits[0].metadata["session_id"] == "s1"
    assert hits[0].metadata["turn"] == 3
    # 隔离标签由池写入咽喉注入（不因新来源而破坏隔离语义）
    assert hits[0].metadata.get("user_id") == "u1"
    assert hits[0].metadata.get("agent_id") == "a1"


def test_draw_semantic_channel_hits_generation_entry():
    from neurova.context_pool import ContextPool

    pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
    pool.add_context(ContextInput(
        source=ContextSource.GENERATION,
        content="[生成产物:image] 赛博朋克城市夜景 产物: /api/v1/generation/files/x.png",
        tags=["generation", "image"],
    ))
    hits = pool.draw(need="生成 赛博朋克 城市夜景")
    assert any(getattr(h, "source", None) == ContextSource.GENERATION for h in hits), \
        "生成物必须能经池 draw 语义通道召回"
