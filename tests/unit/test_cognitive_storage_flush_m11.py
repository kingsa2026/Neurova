"""回归测试：M-11 并进正文时「先清后写」会丢数据。

修复前：先 ``self._l0_buffer.clear()`` 再写入；写入中途抛异常时缓冲已清空、
节点永久丢失，且内存态与恢复文件不一致。修复后：写入成功后才按 id 剔除已写入
节点；写入失败则保留缓冲并上抛，等待重试 + 崩溃恢复文件兜底。

双根收口后写入面是 `MemoryManager.persist_memory_batch`（唯一写入口），
两格判据 accordingly 改指：失败保缓冲与恢复记录、成功只清真被写掉的那批。
"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode
from tests.cognitive_body_store import bodyManager, cognitiveEngine

AGENT = "m11"


def _makeBody(tmp_path):
    manager = bodyManager(tmp_path, agentId=AGENT)
    return manager, cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)


def _seed(engine, *ids):
    engine._l0_buffer = [UnifiedMemoryNode(id=nid, content=f"content-{nid}") for nid in ids]


def test_flushFailureRetainsBuffer(tmp_path, monkeypatch):
    """写入失败必须同时保住 L0 缓冲与恢复文件里的记录（根因修复核心）。"""
    manager, engine = _makeBody(tmp_path)
    engine.store(UnifiedMemoryNode(id="a", content="content-a"))
    engine.store(UnifiedMemoryNode(id="b", content="content-b"))

    def _raise(_mems):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager, "persist_memory_batch", _raise)

    with pytest.raises(RuntimeError):
        engine._flushL0ToBody()

    assert len(engine._l0_buffer) == 2, "写入失败后缓冲被清空——节点将永久丢失"
    assert {n.id for n in engine._l0_buffer} == {"a", "b"}
    recorded = engine._wal_path.read_text(encoding="utf-8")
    assert '"id": "a"' in recorded and '"id": "b"' in recorded, (
        "flush 失败却把恢复文件也收敛了——崩溃后这两条无从恢复"
    )


def test_flushSuccessClearsOnlyWritten(tmp_path):
    """写入成功后按 id 移除，且真行确实落进了正文库。"""
    manager, engine = _makeBody(tmp_path)
    _seed(engine, "a", "b")

    engine._flushL0ToBody()

    assert engine._l0_buffer == [], "flush 成功后缓冲仍留有已写入的节点"
    assert manager.bodyMemoryCount() == 2, "两条节点没进正文库——写入口没被真正走到"
    assert sorted(mem.id for mem in manager.iterBodyMemories()) == ["a", "b"]
