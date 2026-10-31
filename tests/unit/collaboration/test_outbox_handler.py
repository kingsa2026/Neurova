"""OutboxHandler 持久化契约（交接文档 2026-10-31 R5）。

四条症状都以**磁盘读数**为判据，不看内存 dict：
1. 失败态落盘：retry_count / scheduled_at 重启后仍在；
2. 退避时间被消费：未到 scheduled_at 的事件不得再投；
3. 死信移出 pending：`events/{id}.json` 消失、`dead-letter/{id}.json` 在场；
4. 清理同步删文件：cleanup 后重启不得复活重投。
"""

import json

import pytest

from neurova.collaboration.outbox_handler import (
    OutboxHandler,
    EventStatus,
    reset_outbox_handler,
)


@pytest.fixture()
def outbox(tmp_path):
    reset_outbox_handler()
    handler = OutboxHandler(data_dir=str(tmp_path))
    yield handler
    reset_outbox_handler()


def _fileOf(outbox, folder, eventId):
    return outbox.data_dir / folder / f"{eventId}.json"


def _failing(event):
    return False


def test_mark_failed_persists_retry_state(outbox):
    outbox.register_handler("t", _failing)
    event = outbox.publish("t", "agent-a", {"v": 1})

    outbox.process_pending_events()

    onDisk = json.loads(_fileOf(outbox, "events", event.event_id).read_text(encoding="utf-8"))
    assert onDisk["retry_count"] == 1
    assert onDisk["status"] == EventStatus.PENDING.value
    assert onDisk["scheduled_at"] is not None


def test_backoff_schedule_is_consumed_by_processing_loop(outbox):
    calls = []

    def failing_callback(event):
        calls.append(event.event_id)
        return False

    outbox.register_handler("t", failing_callback)
    event = outbox.publish("t", "agent-a", {"v": 1})

    outbox.process_pending_events()
    assert len(calls) == 1
    assert event.scheduled_at and event.scheduled_at > 0

    # 退避未到期：第二轮必须跳过，不得再调 handler
    outbox.process_pending_events()
    assert len(calls) == 1


def test_dead_letter_removes_pending_file(outbox):
    outbox.register_handler("t", _failing)
    event = outbox.publish("t", "agent-a", {"v": 1})

    for _ in range(3):
        event.scheduled_at = 0  # 视为到期，逐轮触发重试直到耗尽
        outbox.process_pending_events()

    assert event.status == EventStatus.FAILED
    assert not _fileOf(outbox, "events", event.event_id).exists()
    assert _fileOf(outbox, "dead-letter", event.event_id).exists()


def test_restart_does_not_redeliver_dead_letters(tmp_path):
    reset_outbox_handler()
    first = OutboxHandler(data_dir=str(tmp_path))
    first.register_handler("t", _failing)
    event = first.publish("t", "agent-a", {"v": 1})
    for _ in range(3):
        event.scheduled_at = 0
        first.process_pending_events()
    reset_outbox_handler()

    calls = []
    second = OutboxHandler(data_dir=str(tmp_path))
    second.register_handler("t", lambda e: calls.append(e.event_id) or True)
    assert second.process_pending_events() == 0
    assert calls == []
    reset_outbox_handler()


def test_cleanup_removes_event_files(outbox):
    event = outbox.publish("t", "agent-a", {"v": 1})
    event.created_at = 0  # 远超保留期

    assert outbox.cleanup_old_events(keep_days=7) == 1
    assert not _fileOf(outbox, "events", event.event_id).exists()


def test_cleanup_survives_restart(outbox, tmp_path):
    event = outbox.publish("t", "agent-a", {"v": 1})
    event.created_at = 0
    outbox.cleanup_old_events(keep_days=7)
    reset_outbox_handler()

    calls = []
    restarted = OutboxHandler(data_dir=str(tmp_path))
    restarted.register_handler("t", lambda e: calls.append(e.event_id) or True)
    restarted.process_pending_events()
    assert calls == []
    assert restarted.get_stats()["total_events_in_storage"] == 0
    reset_outbox_handler()
