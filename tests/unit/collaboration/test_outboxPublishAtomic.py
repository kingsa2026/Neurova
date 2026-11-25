"""EVO-12：outbox 发布必须原子落盘且诚实失败（全仓审计批次 B）。

审计点（neurova/collaboration/outbox_handler.py publish/_save_event）：
- publish 忽略 _save_event 的布尔结果：磁盘没写进去也照常返回事件对象——
  接口成功但重启丢事件；
- 直接 ``open("w")`` 覆盖写：写中途崩溃把既有事件文件截成半截 JSON，
  重启恢复读到坏档。

判据：
1. 落盘失败 → publish 向上抛 ``OutboxPersistenceError``，内存索引与统计
   不记账（先落盘后入账）；
2. 写入中途失败 → 既有事件文件保持完整 JSON（原子写：临时文件+替换），
   且无临时文件残留；
3. 落盘走 fsync（数据先钉在盘上再替换目标文件）；
4. 正常发布重启后事件仍在（持久性守卫）。
"""

from __future__ import annotations

import json

import pytest

import neurova.collaboration.outbox_handler as outbox_module
from neurova.collaboration.outbox_handler import (
    OutboxHandler,
    reset_outbox_handler,
)


@pytest.fixture()
def outbox(tmp_path):
    reset_outbox_handler()
    handler = OutboxHandler(data_dir=str(tmp_path))
    yield handler
    reset_outbox_handler()


def test_publish_raises_when_persistence_fails(tmp_path):
    """落盘失败时 publish 不得假报成功：必须向上抛，且内存不记账。"""
    reset_outbox_handler()
    blocked = tmp_path / "outbox-root"
    blocked.write_text("占位文件：data_dir 被文件占位，events/ 目录无法存在", encoding="utf-8")
    handler = OutboxHandler(data_dir=str(blocked))

    with pytest.raises(outbox_module.OutboxPersistenceError):
        handler.publish("agent_created", "agent-1", {"k": "v"})

    # 失败不得记账：内存索引与统计都不得呈现"已发布"
    assert handler.get_agent_events("agent-1") == [], (
        "落盘失败却把事件记进内存索引——调用方拿到失败，状态面却见'已发布'"
    )
    assert handler.get_stats()["total_events"] == 0
    reset_outbox_handler()


def test_failed_rewrite_leaves_existing_event_intact(outbox, tmp_path, monkeypatch):
    """写盘中途崩溃：既有事件文件必须原封不动（原子写），且无临时文件残留。"""
    first = outbox.publish("agent_created", "agent-1", {"n": 1})

    # 注入"写盘中途崩溃"：json.dump 先吐半截再抛错（真实故障形态）。
    # 旧实现 open("w") 先截断既有文件，半截内容直接毁掉第一条事件。
    def halfWriteThenCrash(obj, fp, *args, **kwargs):
        fp.write('{"event_id": "evt_half", "pay')
        raise OSError("模拟写盘中途崩溃")

    monkeypatch.setattr(outbox_module.json, "dump", halfWriteThenCrash)

    with pytest.raises(outbox_module.OutboxPersistenceError):
        outbox.publish("agent_created", "agent-1", {"n": 2})

    # 既有事件文件必须仍是完整 JSON、内容仍是第一条事件
    saved = json.loads(
        (outbox.data_dir / "events" / f"{first.event_id}.json").read_text(encoding="utf-8")
    )
    assert saved["payload"] == {"n": 1}
    # 不得留下临时文件残骸
    assert list((outbox.data_dir / "events").glob("*.tmp")) == []


def test_publish_fsynces_data_before_replace(outbox, monkeypatch):
    """落盘必须 fsync：数据先钉在盘上，再原子替换目标文件。"""
    fsyncCalls = []
    realFsync = outbox_module.os.fsync

    def spyFsync(fd):
        fsyncCalls.append(fd)
        return realFsync(fd)

    monkeypatch.setattr(outbox_module.os, "fsync", spyFsync)

    outbox.publish("agent_created", "agent-1", {"n": 1})

    assert fsyncCalls, "落盘未走 fsync——断电窗口内事件可能只活在页缓存里"


def test_published_event_survives_restart(tmp_path):
    """发布即持久：重启（重建单例）后事件必须还在。"""
    reset_outbox_handler()
    handler = OutboxHandler(data_dir=str(tmp_path))
    event = handler.publish("agent_created", "agent-1", {"n": 1})

    reset_outbox_handler()
    restarted = OutboxHandler(data_dir=str(tmp_path))
    loadedIds = {e.event_id for e in restarted.get_agent_events("agent-1")}
    assert event.event_id in loadedIds, "发布成功重启即丢——落盘契约失效"
    reset_outbox_handler()
