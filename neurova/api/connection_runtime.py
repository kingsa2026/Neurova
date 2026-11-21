# -*- coding: utf-8 -*-
"""多端连接运行时单源（G4）：心跳 / 断线重放窗口 / 订阅范围的唯一出处。

PC Web、鸿蒙、安卓三端共用同一条连接语义。重连退避已在
``neurova/api/subscription_resume.py`` 单源（``reconnectBackoff``）；本模块
补齐其余三件。三端客户端按服务端握手/订阅应答里下发的
:func:`describeForClients` 契约实现，不再各自手抄数值：

- **心跳/探活间隔**：:data:`HEARTBEAT_INTERVAL_S`（env
  ``NEUROVA_HEARTBEAT_INTERVAL_S`` 可覆盖，非法回落默认）——SSE 通知流的
  keep-alive 周期（``realtime_push.ssePushStream``）与各 WS 的 ping 周期同源；
- **断线重放窗口**：:data:`REPLAY_WINDOW_S`，与全局事件库
  ``swarm_event_store.DEFAULT_KEEP_WINDOW_S``（保留 1 天）同口径——游标落在
  窗口外时经 ``subscription_resume.resolveResume`` 诚实降级快照，绝不部分回放；
- **订阅范围**：按需订阅（"看一个线程不付全部线程的账"）——
  :func:`parseSubscriptionScope` 解析校验 ``scope + scope_key``，
  :func:`inScope` 对帧做归属判定。**解析失败的帧一律 fail-closed 不下发**
  （宁可少发由重放/快照补，不可多发越权数据）。

纯函数为主，仅依赖标准库 + 同层单源模块（subscription_resume），可独立测试。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from neurova.api.subscription_resume import (
    RECONNECT_BACKOFF_BASE_S,
    RECONNECT_BACKOFF_CAP_S,
    RECONNECT_BACKOFF_JITTER_FRACTION,
)

__all__ = [
    "CONNECTION_RUNTIME_VERSION",
    "HEARTBEAT_INTERVAL_S",
    "REPLAY_WINDOW_S",
    "HEARTBEAT_INTERVAL_ENV",
    "REPLAY_WINDOW_ENV",
    "SUBSCRIPTION_SCOPES",
    "SUBSCRIPTION_SCOPE_SESSION",
    "SUBSCRIPTION_SCOPE_THREAD",
    "SUBSCRIPTION_SCOPE_GLOBAL",
    "SubscriptionScope",
    "parseSubscriptionScope",
    "inScope",
    "heartbeat_interval_s",
    "replay_window_s",
    "describeForClients",
]

#: 客户端契约版本（describeForClients 的 version 字段；语义变更加一）
CONNECTION_RUNTIME_VERSION = 1

#: 心跳/探活间隔（秒）。SSE 通知流 keep-alive 与各 WS ping 的共同周期；
#: 与 realtime_push 改前签名硬编码的 15.0 一致（收口行为零差异）。
HEARTBEAT_INTERVAL_S = 15.0
#: 断线重放窗口（秒）：1 天，与 A2 全局事件库保留窗（DEFAULT_KEEP_WINDOW_S）
#: 同口径——窗口外的游标诚实降级快照。
REPLAY_WINDOW_S = 86400.0

#: 心跳间隔的 env 覆盖名（合法正数生效，非法回落默认）
HEARTBEAT_INTERVAL_ENV = "NEUROVA_HEARTBEAT_INTERVAL_S"
#: 重放窗口的 env 覆盖名（合法正数生效，非法回落默认）
REPLAY_WINDOW_ENV = "NEUROVA_REPLAY_WINDOW_S"

#: 订阅范围枚举：会话 / 线程 / 全局
SUBSCRIPTION_SCOPE_SESSION = "session"
SUBSCRIPTION_SCOPE_THREAD = "thread"
SUBSCRIPTION_SCOPE_GLOBAL = "global"
SUBSCRIPTION_SCOPES = (SUBSCRIPTION_SCOPE_SESSION, SUBSCRIPTION_SCOPE_THREAD, SUBSCRIPTION_SCOPE_GLOBAL)

#: session/thread 范围在帧上的归属字段（inScope 按此判定；缺字段/空值 fail-closed）
_SCOPE_KEY_FIELDS = {
    SUBSCRIPTION_SCOPE_SESSION: "session_id",
    SUBSCRIPTION_SCOPE_THREAD: "thread_id",
}


def _positiveFloatFromEnv(env_name: str, default: float) -> float:
    """读 env 里的正数浮点配置：缺省/空/非数值/非有限/非正数一律回落 default。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    try:
        value = float(text)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def heartbeat_interval_s() -> float:
    """心跳/探活间隔（秒）：env ``NEUROVA_HEARTBEAT_INTERVAL_S`` 可覆盖，
    非法回落 :data:`HEARTBEAT_INTERVAL_S`。"""
    return _positiveFloatFromEnv(HEARTBEAT_INTERVAL_ENV, HEARTBEAT_INTERVAL_S)


def replay_window_s() -> float:
    """断线重放窗口（秒）：env ``NEUROVA_REPLAY_WINDOW_S`` 可覆盖，
    非法回落 :data:`REPLAY_WINDOW_S`。"""
    return _positiveFloatFromEnv(REPLAY_WINDOW_ENV, REPLAY_WINDOW_S)


@dataclass(frozen=True)
class SubscriptionScope:
    """一条订阅的范围：``scope`` ∈ :data:`SUBSCRIPTION_SCOPES` + 归属键。

    - ``session``：只收 ``session_id == scope_key`` 的帧；
    - ``thread``：只收 ``thread_id == scope_key`` 的帧；
    - ``global``：全收（scope_key 为空）。

    不可变（frozen）：订阅登记后不得被就地改写（防止"登记的是 session、
    运行中被改成 global"这类越权漂移）。
    """

    scope: str
    scope_key: str = ""

    @property
    def isGlobal(self) -> bool:
        return self.scope == SUBSCRIPTION_SCOPE_GLOBAL


def parseSubscriptionScope(scope: Any, scope_key: Any = "") -> SubscriptionScope:
    """解析并校验订阅范围；非法输入抛 ``ValueError``（fail-closed，不猜）。

    - ``scope`` 必须是 :data:`SUBSCRIPTION_SCOPES` 之一（大小写/首尾空白宽容）；
    - ``session``/``thread`` 必须带非空 ``scope_key``；
    - ``global`` 不需要 ``scope_key``（给了一律归空，避免"global + 半个键"
      这类半吊子语义）。
    """
    name = str(scope or "").strip().lower()
    if name not in SUBSCRIPTION_SCOPES:
        raise ValueError(
            f"非法订阅范围 {scope!r}：必须是 {'/'.join(SUBSCRIPTION_SCOPES)} 之一"
        )
    if name == SUBSCRIPTION_SCOPE_GLOBAL:
        return SubscriptionScope(SUBSCRIPTION_SCOPE_GLOBAL, "")
    key = str(scope_key or "").strip()
    if not key:
        raise ValueError(f"订阅范围 {name} 必须携带非空 scope_key")
    return SubscriptionScope(name, key)


def inScope(frame: Any, sub: Any) -> bool:
    """帧是否落在订阅范围内；**解析失败的帧一律 False（fail-closed 不下发）**。

    判定规则：
    - ``sub`` 不是 :class:`SubscriptionScope`（含 None/裸元组）→ False；
    - ``global`` → True（全收）；
    - ``session``/``thread`` → 帧必须是 dict 且带非空字符串 ``session_id`` /
      ``thread_id``，且与 ``scope_key`` 严格相等；
    - 帧不是 dict、归属字段缺失/为空/非字符串 → False（宁可少发、由
      重放或快照补齐，不可多发越权数据）。
    """
    if not isinstance(sub, SubscriptionScope):
        return False
    if sub.isGlobal:
        return True
    field = _SCOPE_KEY_FIELDS.get(sub.scope)
    if field is None or not isinstance(frame, dict):
        return False
    value = frame.get(field)
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value:
        return False
    return value == sub.scope_key


def describeForClients() -> dict:
    """给三端客户端的下发契约描述（握手/订阅应答携带）。

    汇总连接运行时的全部客户端可见语义：心跳周期、重连退避（引用
    subscription_resume 的退避常量单源）、重放窗口与降级语义、订阅范围。
    数值随 env 覆盖联动（每次调用现算，不缓存）。
    """
    heartbeat = heartbeat_interval_s()
    window = replay_window_s()
    return {
        "version": CONNECTION_RUNTIME_VERSION,
        "heartbeat": {
            "interval_s": heartbeat,
            "note": "服务端按该周期发 keep-alive/pong；客户端探活与心跳同周期",
        },
        "reconnect": {
            "backoff_base_s": RECONNECT_BACKOFF_BASE_S,
            "backoff_cap_s": RECONNECT_BACKOFF_CAP_S,
            "backoff_jitter": RECONNECT_BACKOFF_JITTER_FRACTION,
            "formula": "min(base_s * 2^attempt, cap_s)，再乘 [1-jitter, 1+jitter] 抖动",
        },
        "replay": {
            "window_s": window,
            "note": "断线重连按游标增量重放；游标过旧/非法/超预算降级全量快照，绝不部分回放",
        },
        "subscription": {
            "scopes": list(SUBSCRIPTION_SCOPES),
            "note": "按需订阅：session/thread 须带 scope_key，global 全收；范围外帧不下发",
        },
    }
