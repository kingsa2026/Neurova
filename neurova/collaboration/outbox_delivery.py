"""协作生命周期事件的出件口：把 Outbox 待投事件投递到站内通知单入口。

Outbox 的退避／死信／清理／重启不重投四件早在 R5 批修好并进了受保护子集，**可投递器从未注册**：
全仓 `_handlers` 只有 `OutboxHandler.register_handler` 一处写，而生产侧零调用方 ⇒
`_process_event` 取不到 handler 就返回 False，任何事件唯一的结局是按退避重试到过期、
落进 `dead-letter/`。本模块补的就是缺的这两段——读侧消费者与排空调度。

落点不是新造的产品语义：`task_completed` 在生产里已经走 `notify_admins` 做站内镜像
（`collaborate/workflow/scheduler.py` 的 `_on_scheduler_task_event`，接收人=管理员、
无注册管理员兜底 `default`）。这里把**同一个入口**接给 Outbox 的三个生命周期事件类型，
事件类型名单与判据共用本模块那张表，别处不再各写一份字面量。

兜底扫描（推送韧性四件套之一，对齐 Linger due-notifier）：投递链上
`notify_user` 吞异常、`notify_admins` 只报目标数，"投出去了"的判据若取自生产方
返回值，通知面写失败也会被标成已投递——通知丢了事件就丢了。故本模块做两件事：
1. `deliverEvent` 投递后**回读通知面**核实（data.outbox_event_id 反查），
   核实不到即判失败，交还既有退避/死信口径；
2. `sweepUndeliveredEvents` 周期扫描已标 SENT/DELIVERED 但通知面缺失的未过期
   事件并补投——快路径漏掉或事后丢失的通知，一个扫描周期内必达。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional, Tuple

from neurova.collaboration.outbox_handler import EventStatus
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 出件口对接的事件类型（单源：注册面与判据都从这张表取）
OUTBOX_EVENT_TYPES = ("agent_created", "session_started", "task_completed")

#: 排空间隔秒数——具名单源。此前"重投"唯一的驱动点是人手调 `/outbox/process-pending`，
#: 没人调就等于没有重试；env 只改节奏，不改"间隔只许一处定义"这件事。
OUTBOX_DRAIN_INTERVAL_SECONDS = 60.0
OUTBOX_DRAIN_INTERVAL_ENV = "NEUROVA_OUTBOX_DRAIN_INTERVAL"

#: 兜底扫描开关 env（默认开）。扫描与排空同循环同节奏：一个排空周期内必达。
OUTBOX_SWEEP_ENV = "NEUROVA_OUTBOX_SWEEP"

#: 事件类型 → （通知标题, 正文模板）。正文只念事件里已有的身份字段，不臆造。
_TEMPLATES: Dict[str, Tuple[str, str]] = {
    "agent_created": ("协作 Agent 已创建", "Agent「{agent_id}」已创建"),
    "session_started": ("协作会话已开始", "Agent「{agent_id}」的会话「{session_id}」已开始"),
    "task_completed": ("协作任务已完成", "Agent「{agent_id}」的任务已完成"),
}

#: 通知面 data 里挂 outbox 事件 id 的键（投递核实与补投共用这一个键名）
_OUTBOX_EVENT_ID_KEY = "outbox_event_id"


def drainIntervalSeconds() -> float:
    """排空间隔：env 覆盖；非正数或不可解析时回落常量单源（不把配置错误读成"立刻停"）。"""
    raw = (os.environ.get(OUTBOX_DRAIN_INTERVAL_ENV) or "").strip()
    if not raw:
        return OUTBOX_DRAIN_INTERVAL_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        logger.warning("%s=%r 不是数字，回落到 %ss",
                       OUTBOX_DRAIN_INTERVAL_ENV, raw, OUTBOX_DRAIN_INTERVAL_SECONDS)
        return OUTBOX_DRAIN_INTERVAL_SECONDS
    if parsed <= 0:
        logger.warning("%s=%s 非正数，回落到 %ss", OUTBOX_DRAIN_INTERVAL_ENV,
                       parsed, OUTBOX_DRAIN_INTERVAL_SECONDS)
        return OUTBOX_DRAIN_INTERVAL_SECONDS
    return parsed


def sweepEnabled() -> bool:
    """兜底扫描开关：默认开；env 显式 off 才停（配置错误不静默改语义）。"""
    return (os.environ.get(OUTBOX_SWEEP_ENV) or "on").strip().lower() != "off"


def renderEvent(event: Any) -> Tuple[str, str]:
    """事件 → （标题, 正文）。名单外的类型原样点名，不静默吞掉。"""
    title, template = _TEMPLATES.get(
        event.event_type, ("协作事件", "{event_type}：Agent「{agent_id}」"))
    fields = {
        "event_type": event.event_type,
        "agent_id": event.agent_id,
        "session_id": event.session_id or "-",
    }
    return title, template.format(**fields)


def notificationFaceHasEvent(event: Any) -> bool:
    """通知面是否真有这条 outbox 事件的站内通知（按 data.outbox_event_id 反查）。"""
    from neurova.api.endpoints.notifications import get_notification_manager

    matched = get_notification_manager().findNotificationIdsByData(
        _OUTBOX_EVENT_ID_KEY, event.event_id
    )
    return bool(matched)


def deliverEvent(event: Any) -> bool:
    """一条事件经站内通知单入口投出去；返回是否真落到了通知面。

    成功判据是**投递后回读通知面**，不是 notify_admins 的返回值——后者统计的是
    "目标个数"（无注册管理员时兜底 default，恒 >= 1），且 notify_user 吞异常，
    都不能证明通知真落了盘。判据咬合事实源，通知写失败如实返回 False，
    交还 Outbox 既有退避/死信口径。
    """
    from neurova.api.endpoints.notifications import notify_admins

    title, message = renderEvent(event)
    notify_admins(
        title,
        message,
        "info",
        {
            "event_type": event.event_type,
            "agent_id": event.agent_id,
            "session_id": event.session_id,
            _OUTBOX_EVENT_ID_KEY: event.event_id,
        },
    )
    return notificationFaceHasEvent(event)


def registerOutboxHandlers(outbox: Optional[Any] = None) -> int:
    """把事件类型名单接到投递函数上（幂等；返回注册条数）。

    参数 `outbox` 缺省取门面单例——装配点走的正是这条缺省腿，测试才递得进自己的实例。
    """
    target = outbox if outbox is not None else _getOutbox()
    for eventType in OUTBOX_EVENT_TYPES:
        target.register_handler(eventType, deliverEvent)
    return len(OUTBOX_EVENT_TYPES)


def drainOutboxOnce(outbox: Optional[Any] = None) -> int:
    """排空一轮：先确保投递器在位，再走 Outbox 自己的退避/死信口径。"""
    target = outbox if outbox is not None else _getOutbox()
    registerOutboxHandlers(target)
    return target.process_pending_events()


def sweepUndeliveredEvents(outbox: Optional[Any] = None) -> int:
    """兜底扫描一轮：已标 SENT/DELIVERED 但通知面缺失的未过期事件，补投一轮。

    只认通知面这个事实源：事件状态说"已投递"而通知面查无此件，即视为丢失。
    补投成功或核实到在位后打 `sweep_confirmed_at` 标记并落盘——已确认的事件
    之后即使用户主动删除通知也不再复活（至少一次送达，不是无限重发）。
    PENDING 事件仍归排空快路径管（避免两条路重复投递）；过期事件交还
    退避/死信口径。返回补投成功的条数。
    """
    target = outbox if outbox is not None else _getOutbox()
    redelivered = 0
    now = time.time()
    for event in target.get_all_events():
        if event.event_type not in OUTBOX_EVENT_TYPES:
            continue
        if event.status not in (EventStatus.SENT, EventStatus.DELIVERED):
            continue
        if event.expires_at is not None and event.expires_at < now:
            continue
        if event.metadata.get("sweep_confirmed_at"):
            continue
        if notificationFaceHasEvent(event):
            event.metadata["sweep_confirmed_at"] = now
            target.saveEvent(event)
            continue
        if deliverEvent(event):
            redelivered += 1
            logger.warning(
                "Outbox 兜底扫描补投丢失事件 %s（type=%s）——通知面此前查无此件",
                event.event_id, event.event_type,
            )
    return redelivered


async def runOutboxDrainLoop(
    stopEvent: Optional[asyncio.Event] = None,
    outbox: Optional[Any] = None,
) -> None:
    """排空循环：与知识索引周期维护同一条启停成对纪律（关停时 cancel，不靠线程自灭）。

    每轮先排空待投事件（快路径），再做兜底扫描（慢路径兜底）——丢失的通知
    一个扫描周期内必达。参数 `outbox` 供测试递入独立实例；生产取门面单例。
    """
    logger.info("Outbox 排空循环启动（间隔 %ss，兜底扫描%s）",
                drainIntervalSeconds(), "开" if sweepEnabled() else "关")
    while stopEvent is None or not stopEvent.is_set():
        try:
            delivered = await asyncio.to_thread(drainOutboxOnce, outbox)
            if delivered:
                logger.info("Outbox 排空投递 %d 条事件", delivered)
            if sweepEnabled():
                redelivered = await asyncio.to_thread(sweepUndeliveredEvents, outbox)
                if redelivered:
                    logger.warning("Outbox 兜底扫描补投 %d 条丢失通知", redelivered)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 排空故障不拖垮应用，但必须留痕
            logger.warning("Outbox 排空失败（下轮再试）: %s", e)
        await asyncio.sleep(drainIntervalSeconds())


def _getOutbox():
    """门面单例——只在装配点与无人传实例时取；判据不许从这里反查事件。"""
    from neurova.collaboration.outbox_handler import get_outbox_handler

    return get_outbox_handler()
