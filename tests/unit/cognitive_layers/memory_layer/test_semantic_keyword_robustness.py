# -*- coding: utf-8 -*-
"""D7 评测暴露的文本通道缺陷与修复：词法候选空时的稠密相似度兜底。

红灯依据：关键词倒排用**不重叠 2~4 字窗口**——查询"仓库的温湿度传感器
是什么型号"与正文"仓库温湿度传感器型号是 SHT31"仅一个"的"字之差，
窗口整体错位、零交集，search_by_keywords 返回空 → 文本通道恒 0 条 →
温度通道噪声独占融合结果（D7 三态基准 MRR≈0.03 的根因之一）。

修复取舍：关键词倒排保持精确（不动——放宽会让联想线索通道的
"只加分不减分"契约失守，净 HEAD 实测）；文本通道在词法候选为空时
按真实相似度（嵌入余弦）对全量快照兜底打分，≥0.5 才入选。
"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

QUERY = "仓库的温湿度传感器是什么型号"
CONTENT = "仓库温湿度传感器型号是 SHT31"


@pytest.fixture()
def engine_with_corpus(tmp_path):
    from neurova.core.cancel_token import clearTurnCancelToken

    clearTurnCancelToken()
    manager = MemoryManager(
        db_path=str(tmp_path / "kw.db"), agent_id="kw", enable_buffer=False
    )
    mem_id = manager.remember(
        content=CONTENT, memory_type="semantic", metadata={"chat_scope": "direct"}
    )
    engine = NeurovaRecallEngine(memory_manager=manager, use_plugins=False)
    yield manager, engine, mem_id
    clearTurnCancelToken()


def test_keyword_lane_stays_precise_on_particle_shift(engine_with_corpus):
    """倒排本身保持精确：错位查询在词法候选里就是 0（不放宽）。"""
    manager, engine, mem_id = engine_with_corpus
    from neurova.cognitive_layers.memory_layer.semantic_search import (
        get_semantic_search,
    )

    search = get_semantic_search()
    assert search.search_by_keywords(QUERY, limit=5) == []


def test_text_channel_dense_fallback_finds_target(engine_with_corpus):
    """词法候选为空 → 稠密相似度兜底必须找到目标记忆。"""
    manager, engine, mem_id = engine_with_corpus
    out = engine._channel_text(QUERY, limit=5)
    ids = [m.memory_id for m in out]
    assert mem_id in ids, f"兜底未找到目标：{ids}"
    assert out[0].memory_id == mem_id
    assert all(m.score >= 0.5 for m in out)


def test_fallback_channel_is_text(engine_with_corpus):
    manager, engine, mem_id = engine_with_corpus
    out = engine._channel_text(QUERY, limit=5)
    assert all(m.channel.value == "text" for m in out)
