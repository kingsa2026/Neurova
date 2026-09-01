# -*- coding: utf-8 -*-
"""睡眠冲突解决端点去 mock + 真写回测试（补课 5.1）。"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def sc():
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord

    mm = MagicMock()
    records = [
        MemoryRecord(
            id="m1",
            agent_id="a1",
            content="long content " * 10,
            created_at=datetime(2026, 9, 1, 12, 0, 0),
        ),
        MemoryRecord(
            id="m2",
            agent_id="a1",
            content="short",
            created_at=datetime(2026, 9, 2, 12, 0, 0),
        ),
    ]

    def get_memory(mid):
        return next((r for r in records if r.id == mid), None)

    mm.get_memory.side_effect = get_memory
    mm.delete_memory_soft.return_value = True
    mm.update_memory.return_value = True

    sc_obj = SleepConsolidation(memory_manager=mm)
    sc_obj._conflict_resolutions.insert(
        0,
        {
            "id": "cr-1",
            "agent_id": "a1",
            "field": "content",
            "local_value": "long content",
            "remote_value": "short",
            "resolved": False,
            "resolution": "keep_longest",
            "source_memories": ["m1", "m2"],
            "created_at": datetime.now().isoformat(),
        },
    )
    return sc_obj, mm, records


def test_resolve_keep_newest_soft_deletes_loser(sc):
    sc_obj, mm, records = sc
    updated = sc_obj.resolve_conflict("cr-1", "keep_newest", apply_to_store=True)
    assert updated["resolved"] is True
    assert updated["applied_to_store"] is True
    # newest = m2（created 09-02）胜出 → m1 被软删
    deleted_ids = [c.args[0] for c in mm.delete_memory_soft.call_args_list]
    assert deleted_ids == ["m1"]


def test_resolve_merge_rewrites_winner(sc):
    sc_obj, mm, records = sc
    updated = sc_obj.resolve_conflict("cr-1", "merge", apply_to_store=True)
    assert updated["applied_to_store"] is True
    # winner=最长 m1 被重写为拼接内容，m2 软删
    call = mm.update_memory.call_args
    assert call.args[0] == "m1"
    assert "short" in call.kwargs["content"]
    assert "long content" in call.kwargs["content"]
    assert mm.delete_memory_soft.call_args.args[0] == "m2"


def test_resolve_invalid_returns_none(sc):
    sc_obj, _, _ = sc
    assert sc_obj.resolve_conflict("cr-1", "bogus", apply_to_store=True) is None
    assert sc_obj.resolve_conflict("unknown-id", "merge") is None


def test_resolve_without_store_only_updates_audit(sc):
    sc_obj, mm, _ = sc
    updated = sc_obj.resolve_conflict("cr-1", "keep_longest")
    assert updated["resolved"] is True
    assert "applied_to_store" not in updated
    mm.delete_memory_soft.assert_not_called()
