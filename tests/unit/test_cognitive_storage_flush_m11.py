"""回归测试：M-11 CognitiveStorageEngine._flush_l0_to_l1 先清后写丢数据。

修复前：先 ``self._l0_buffer.clear()`` 再在锁内写入；写入中途抛异常时缓冲已
清空、节点永久丢失，且内存态与 WAL 不一致。修复后：写入并提交成功后才按 id
剔除已写入节点；写入失败则保留缓冲并上抛，等待重试 + WAL 崩溃恢复兜底。

本测试锁定"失败时数据必须保留"这一根因行为，防止回归为静默丢失。
"""
import datetime
from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
)


class _FakeNode:
    """最小化记忆节点替身，仅提供 _flush_l0_to_l1 读取的字段。"""

    def __init__(self, nid):
        now = datetime.datetime.now(datetime.timezone.utc)

        class _E:
            value = "EPISODIC"

        class _L:
            value = "L0"

        self.id = nid
        self.content = f"content-{nid}"
        self.memory_type = _E()
        self.category = "chat"
        self.temperature = 50.0
        self.layer = _L()
        self.metadata = {}
        self.embedding = None
        self.created_at = now
        self.updated_at = now
        self.access_count = 0
        self.trace_id = f"trace-{nid}"


def _make_engine(tmp_path):
    return CognitiveStorageEngine(agent_id="m11", data_dir=str(tmp_path / "store"))


def test_flush_failure_retains_buffer(tmp_path):
    """写入失败必须保留 L0 缓冲，不得清空（根因修复核心）。"""
    engine = _make_engine(tmp_path)
    engine._l0_buffer = [_FakeNode("a"), _FakeNode("b")]

    # 模拟 DB 写入失败（磁盘满 / 约束冲突 / 连接中断）
    engine._db = MagicMock()
    engine._db.execute.side_effect = RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        engine._flush_l0_to_l1()

    # 关键断言：写入失败后缓冲未被清空，数据可被重试或 WAL 恢复兜底
    assert len(engine._l0_buffer) == 2
    assert {n.id for n in engine._l0_buffer} == {"a", "b"}


def test_flush_success_clears_only_written(tmp_path):
    """写入成功后才按 id 移除已写入节点；DB 调用次数正确。"""
    engine = _make_engine(tmp_path)
    engine._l0_buffer = [_FakeNode("a"), _FakeNode("b")]

    engine._db = MagicMock()  # execute / commit 皆为 no-op

    engine._flush_l0_to_l1()

    assert len(engine._l0_buffer) == 0
    # 每条节点一次 INSERT OR REPLACE + 一次 commit
    assert engine._db.execute.call_count == 2
    engine._db.commit.assert_called_once()
