# -*- coding: utf-8 -*-
"""D8：温度通道相关性门——热但与查询无关的记忆不得作为候选注入。

红灯依据（D7 三态基准实测）：温度通道无论查询相关性注入 Top-30 最热
记忆（score=温度/100，热记忆恒 0.9+），把相关但低温的记忆顶掉——
C 态 MRR 从 0.751（去温度通道）拖到 0.459。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

QUERY = "仓库的温湿度传感器是什么型号"


@pytest.fixture()
def engine_with_rows(tmp_path):
    from neurova.core.cancel_token import clearTurnCancelToken

    clearTurnCancelToken()
    manager = MemoryManager(
        db_path=str(tmp_path / "tc.db"), agent_id="tc", enable_buffer=False
    )
    engine = NeurovaRecallEngine(memory_manager=manager, use_plugins=False)

    def _seed(content: str, temperature: float) -> str:
        mem_id = manager.remember(
            content=content, memory_type="semantic", metadata={"chat_scope": "direct"}
        )
        conn = sqlite3.connect(str(manager._persist_db_path))
        la = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute(
            "UPDATE memories SET temperature = ?, last_accessed_at = ? WHERE id = ?",
            (temperature, la, mem_id),
        )
        conn.commit()
        conn.close()
        return mem_id

    # 热但与查询完全无关（食堂菜单）+ 低温但与查询强相关（仓库传感器）
    hot_id = _seed("食堂周三供应红烧肉", 95.0)
    relevant_id = _seed("仓库温湿度传感器型号是 SHT31", 30.0)
    yield manager, engine, hot_id, relevant_id
    clearTurnCancelToken()


def test_hot_irrelevant_memory_filtered_out(engine_with_rows):
    _, engine, hot_id, relevant_id = engine_with_rows
    out = engine._channel_temperature(QUERY, limit=5)
    ids = [m.memory_id for m in out]
    assert relevant_id in ids, f"相关记忆应保留：{ids}"
    assert hot_id not in ids, f"热但无关的记忆必须被门掉：{ids}"


def test_hot_and_relevant_memory_still_surfaces(engine_with_rows):
    manager, engine, hot_id, relevant_id = engine_with_rows
    # 追加一条又热又相关的记忆
    mem_id = manager.remember(
        content="仓库温湿度传感器备件在库房 B 柜",
        memory_type="semantic",
        metadata={"chat_scope": "direct"},
    )
    conn = sqlite3.connect(str(manager._persist_db_path))
    la = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE memories SET temperature = 97.0, last_accessed_at = ? WHERE id = ?",
        (la, mem_id),
    )
    conn.commit()
    conn.close()

    out = engine._channel_temperature(QUERY, limit=5)
    ids = [m.memory_id for m in out]
    assert mem_id in ids, "又热又相关的记忆必须保留且靠前"
    assert ids[0] == mem_id


def test_empty_query_keeps_old_behavior(engine_with_rows):
    """无查询文本时无法判相关性——保持旧行为（按温度返回）。"""
    manager, engine, hot_id, relevant_id = engine_with_rows
    out = engine._channel_temperature("", limit=5)
    assert len(out) == 2
