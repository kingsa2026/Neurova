# -*- coding: utf-8 -*-
"""DATA-P1-3（审计 2026-09-11）回归：flush 后恢复文件不再无条件清空。

竞态场景：flush 快照 nodes → 并发 store() 追加节点 X（恢复文件 + 缓冲）→
flush 写入正文 → 收敛恢复文件。原实现把 X 的记录一并抹掉——X 尚未写正文，
崩溃即永久丢失。修复后按"已并入正文的 id"收敛，X 的记录必须保留。

双根收口后"写入正文"这一步是 `MemoryManager.persist_memory_batch`，
第二格 accordingly 改为断言行落进正文库，而不是引擎自己那张表。
"""
from __future__ import annotations

import json
from pathlib import Path

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
from tests.cognitive_body_store import bodyManager, cognitiveEngine

AGENT = "itest"


def _makeBody(tmp_path: Path):
    manager = bodyManager(tmp_path, agentId=AGENT)
    return manager, cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)


def _node(nid: str, content: str) -> UnifiedMemoryNode:
    return UnifiedMemoryNode(id=nid, content=content)


def _walIds(engine) -> set:
    return {
        json.loads(line)["id"]
        for line in engine._wal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_flush_keeps_wal_entries_not_in_batch(tmp_path):
    manager, eng = _makeBody(tmp_path)
    n1 = _node("id-1", "first")
    eng._walAppend(n1)
    eng._l0_buffer = [n1]

    # 竞态窗口模拟：store() 已把 X 追加进恢复文件，但 flush 的缓冲快照
    # 未包含它（生产时序：_walAppend 与 buffer append 之间被 flush 抢入）
    eng._walAppend(_node("id-2", "concurrent"))

    eng._flushL0ToBody()

    assert "id-1" not in _walIds(eng), "已并入正文的条目应从恢复文件收敛掉"
    assert "id-2" in _walIds(eng), "不在本批快照内的条目必须保留（崩溃恢复依据）"
    assert all(n.id != "id-1" for n in eng._l0_buffer)


def test_flush_writes_batch_to_body(tmp_path):
    manager, eng = _makeBody(tmp_path)
    n1 = _node("id-a", "aaa")
    eng._walAppend(n1)
    eng._l0_buffer = [n1]

    eng._flushL0ToBody()

    mem = manager.bodyMemoryById("id-a")
    assert mem is not None and mem.content == "aaa", "本批节点没落进正文库"
