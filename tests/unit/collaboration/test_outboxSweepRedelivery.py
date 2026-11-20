# -*- coding: utf-8 -*-
"""Outbox 兜底扫描（推送韧性四件套之一，对齐 Linger due-notifier）。

现状缺口（动手前逐行实测，非臆造）：
- `notifications.notify_user` 吞掉一切异常（endpoints/notifications.py，except 后仅
  warning）；`NotificationManager._save` 落盘失败同样只 warning。
- `notify_admins` 返回的是"目标个数"不是"成功个数"（无注册管理员时兜底 default，
  恒 >= 1）。
- `outbox_delivery.deliverEvent` 以 `delivered > 0` 判定成功 => 恒 True。
  三者叠加：通知面写失败（磁盘满/JSON 写失败）时事件仍被标 DELIVERED、永久离开
  待投队列——不重试、不进死信，**通知丢了事件就丢了**。
- 即便投递成功，通知也可能事后丢（落盘失败重启后从旧文件装回）——同属丢通知。

本批钉住的契约：凡 outbox 已知类型事件，未过有效期的，通知面缺失即视为未投递；
兜底扫描一个排空周期内补达；扫描确认后用户主动删除不复活。
"""

import asyncio
import time

import pytest

from neurova.collaboration.outbox_handler import EventStatus, OutboxHandler, reset_outbox_handler


@pytest.fixture()
def outbox(tmp_path):
    reset_outbox_handler()
    handler = OutboxHandler(data_dir=str(tmp_path))
    yield handler
    reset_outbox_handler()


@pytest.fixture()
def notificationFace(tmp_path, monkeypatch):
    """独立通知面：不读写仓内真实 data/notifications.json。"""
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    from neurova.notifications.manager import get_notification_manager, reset_notification_manager

    reset_notification_manager()
    yield get_notification_manager()
    reset_notification_manager()


def _eventNotifications(face, eventId):
    """通知面里属于某条 outbox 事件的通知（data.outbox_event_id 核对）。"""
    return [
        n
        for n in face.get_user_notifications("default", limit=100)
        if (n.data or {}).get("outbox_event_id") == eventId
    ]


def _deleteEventNotifications(face, eventId):
    for n in _eventNotifications(face, eventId):
        assert face.delete_notification(n.notification_id, n.user_id)


def test_通知面丢通知_兜底扫描补达(outbox, notificationFace):
    """红灯：事件已标 DELIVERED 后通知被丢，扫描必须把它补回来。"""
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers, sweepUndeliveredEvents

    registerOutboxHandlers(outbox)
    event = outbox.publish("agent_created", "agent-77", {"company_id": "c1"})
    assert outbox.process_pending_events() >= 1, "前提：快路径已投达"
    assert _eventNotifications(notificationFace, event.event_id)

    # 人为丢通知（模拟通知面写失败后丢失 / 落盘回滚）
    _deleteEventNotifications(notificationFace, event.event_id)
    assert not _eventNotifications(notificationFace, event.event_id)

    redelivered = sweepUndeliveredEvents(outbox)

    assert redelivered >= 1, "通知面缺失却未触发补投——兜底扫描没接上"
    assert _eventNotifications(notificationFace, event.event_id), "扫描后通知面仍没有该事件"


def test_通知写失败不得把事件标成已投递(outbox, notificationFace, monkeypatch):
    """红灯（根因格）：notify_user 吞异常 + notify_admins 只报目标数，现状会把
    写失败的事件标成 DELIVERED。投递成功的判据必须咬合通知面事实。"""
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers

    registerOutboxHandlers(outbox)
    event = outbox.publish("session_started", "agent-88", {"user_id": "u1"})

    def _boom(*args, **kwargs):
        raise OSError("disk full（模拟通知面写失败）")

    monkeypatch.setattr(notificationFace, "add_notification", _boom)

    delivered = outbox.process_pending_events()

    assert delivered == 0, "通知没写进去却报成已投递"
    assert event.status is not EventStatus.DELIVERED
    assert event.delivered_at is None


def test_虚标已投递的存量事件也被扫描补达(outbox, notificationFace):
    """红灯：根修前已被误标 DELIVERED 的存量事件（通知面从没有过通知），扫描同样补达。"""
    from neurova.collaboration.outbox_delivery import sweepUndeliveredEvents

    event = outbox.publish("task_completed", "agent-5", {"task_id": "t9"})
    event.mark_sent()
    event.mark_delivered()

    assert sweepUndeliveredEvents(outbox) >= 1
    assert _eventNotifications(notificationFace, event.event_id)


def test_扫描确认后用户删除不复活(outbox, notificationFace):
    """扫描确认过投递之后，用户删掉通知不得被下一轮扫描复活（至少一次送达，
    不是无限重发）。"""
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers, sweepUndeliveredEvents

    registerOutboxHandlers(outbox)
    event = outbox.publish("session_started", "agent-3", {"user_id": "u1"})
    outbox.process_pending_events()

    assert sweepUndeliveredEvents(outbox) == 0, "通知在位时扫描不应补投"

    _deleteEventNotifications(notificationFace, event.event_id)

    assert sweepUndeliveredEvents(outbox) == 0, "已确认投递的通知被删除后不得复活"
    assert not _eventNotifications(notificationFace, event.event_id)


def test_过期事件不进兜底扫描(outbox, notificationFace):
    """补投窗口以事件有效期为界：过期事件交还给既有退避/死信口径，扫描不再管。"""
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers, sweepUndeliveredEvents

    registerOutboxHandlers(outbox)
    event = outbox.publish("task_completed", "agent-4", {"task_id": "t2"})
    outbox.process_pending_events()
    event.expires_at = time.time() - 1.0

    _deleteEventNotifications(notificationFace, event.event_id)

    assert sweepUndeliveredEvents(outbox) == 0, "过期事件不应被兜底扫描补投"
    assert not _eventNotifications(notificationFace, event.event_id)


def test_排空循环一轮内补达丢失通知(outbox, notificationFace, monkeypatch):
    """闭环红：把扫描并进排空循环后，丢失的通知在一个排空周期内必达。"""
    monkeypatch.setenv("NEUROVA_OUTBOX_DRAIN_INTERVAL", "0.05")
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers, runOutboxDrainLoop

    registerOutboxHandlers(outbox)
    event = outbox.publish("task_completed", "agent-9", {"task_id": "t1"})
    assert outbox.process_pending_events() >= 1
    _deleteEventNotifications(notificationFace, event.event_id)
    assert not _eventNotifications(notificationFace, event.event_id)

    async def _drive():
        task = asyncio.create_task(runOutboxDrainLoop(outbox=outbox))
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline:
                await asyncio.sleep(0.05)
                if _eventNotifications(notificationFace, event.event_id):
                    return True
            return False
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert asyncio.run(_drive()), "兜底扫描未在一个排空周期内补达丢失通知"
