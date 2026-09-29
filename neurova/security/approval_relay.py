# -*- coding: utf-8 -*-
"""审批终态中继：把"人在别处点了批准/拒绝"唤醒到正在等的那一次调用。

## 为什么必须有这个模块

治理判 `ASK` 时，等待发生在**执行咽喉所在的 asyncio 任务**里；而人工批准发生在
**另一个 HTTP 请求**（另一个线程、另一个事件循环）里。两者之间原本没有任何通路：
`ApprovalManager.register_notification_callback` 就是为这件事写的，但生产侧
零注册方，于是 `_send_approval_result` 的广播遍历的是一个空列表 —— 一个注册了
却无人订阅的通道，与"写出无人读的字段"同形态。

本模块是它的第一个、也是唯一的生产消费者。

## 三条约束决定了它不能写成"回调里直接改状态"

1. **广播在 `ApprovalManager._lock` 之内发生**（`approve_request` 持锁调用
   `_send_approval_result`）。回调里任何回到 manager 的同步调用都是在这颗锁里做事，
   因此中继只登记、不回调 manager。
2. **批准方与等待方可能不在同一个事件循环**。跨循环 `Future.set_result()` 是不合法的，
   必须经 `loop.call_soon_threadsafe` 投回等待方自己的循环。
3. **无人等待不是错误**。超时后咽喉已经放手、或这一条批准本来就走带外重放 ——
   此时静默返回，让投递侧（`deliverApprovedToolResult`）去负责"结果晚到"的那一半。
"""

from __future__ import annotations

import asyncio
import threading
import typing

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "registerApprovalWaiter",
    "unregisterApprovalWaiter",
    "installApprovalRelay",
    "hasApprovalWaiter",
    "pendingWaiterCount",
]

# request_id → (等待方的 loop, 该 loop 上的 Future)
_waiters: typing.Dict[str, typing.Tuple[asyncio.AbstractEventLoop, "asyncio.Future"]] = {}
_lock = threading.RLock()
_installedManagers: typing.List[int] = []  # 已装中继的 manager id，防重复注册


def registerApprovalWaiter(request_id: str) -> typing.Optional["asyncio.Future"]:
    """在当前循环上登记一次等待；无运行循环时返回 None（调用方据此退回不阻塞）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("无运行中的事件循环，审批不阻塞等待: %s", request_id)
        return None
    future = loop.create_future()
    with _lock:
        _waiters[request_id] = (loop, future)
    return future


def unregisterApprovalWaiter(request_id: str, future: typing.Optional["asyncio.Future"] = None) -> None:
    """注销登记。带 future 比对象：超时后同名请求的新一轮登记不能被旧轮误删。"""
    with _lock:
        current = _waiters.get(request_id)
        if current is None:
            return
        if future is not None and current[1] is not future:
            return
        _waiters.pop(request_id, None)


def pendingWaiterCount() -> int:
    """在等裁决的登记数（观测/测试用，不作为业务判据）。"""
    with _lock:
        return len(_waiters)


def hasApprovalWaiter(request_id: str) -> bool:
    """这一次审批是否有人正在等 —— 批准端点据此决定**要不要重放**。

    为什么必须有这个判据：咽喉被唤醒后会在完整管线里执行这一次调用（钩子/超时/
    审计/大输出折叠一样不缺）。若批准端点同时按 metadata 重放，同一条命令就被
    执行了两遍 —— 对 `exec_command` 这类工具，"跑两次"不是性能问题而是正确性问题。
    裁决权必须只有一个主人：有人在等就归咽喉，没人等（超时后人工才点、或本来
    就走带外重放）才归端点。
    """
    with _lock:
        return request_id in _waiters


def _resolve(request_id: str, status: str) -> None:
    entry = None
    with _lock:
        if request_id in _waiters:
            entry = _waiters.pop(request_id)
    if entry is None:
        return  # 无人等待：交给投递侧，本模块不报错
    loop, future = entry

    def _set() -> None:
        if not future.done():
            future.set_result(status)

    try:
        loop.call_soon_threadsafe(_set)
    except RuntimeError:
        # 等待方的循环已关闭（客户端断开/会话结束）——终态本就该丢给投递侧
        logger.debug("审批等待方循环已关闭，唤醒丢弃: %s", request_id)


def _onApprovalEvent(event: str, payload: typing.Dict[str, typing.Any]) -> None:
    """`ApprovalManager` 的通知回调。必须快、不阻塞、不回 call manager（在它的锁里）。"""
    if event != "approval_result":
        return
    try:
        request_id = str(payload.get("request_id") or "")
        status = str(payload.get("status") or "")
        if request_id and status:
            _resolve(request_id, status)
    except Exception as e:  # noqa: BLE001 - 中继故障不得影响审批本身落库
        logger.warning("审批终态中继处理失败（忽略）: %s", e)


def installApprovalRelay(manager: typing.Any) -> bool:
    """把一个 `ApprovalManager` 接上中继（幂等）。

    由 `get_approval_manager()` 在**首次构造单例时**调用，而不是只挂在 API 启动钩子上：
    CLI、Tauri 内嵌、测试夹具这些不跑 `create_app()` 的入口同样会创建审批，
    漏装的表现是"阻塞的咽喉永远等不到唤醒"——比不阻塞更难归因。
    """
    managerId = id(manager)
    with _lock:
        if managerId in _installedManagers:
            return True
    try:
        manager.register_notification_callback(_onApprovalEvent)
    except Exception as e:  # noqa: BLE001
        logger.warning("审批中继安装失败，ASK 将退回不阻塞语义: %s", e)
        return False
    with _lock:
        _installedManagers.append(managerId)
    logger.info("审批终态中继已接入 ApprovalManager")
    return True
