# -*- coding: utf-8 -*-
"""设备桥总闸与超时口径（单一事实源；计划红线 6：能力默认关双闸之后端半边）。

- ``NEUROVA_DEVICE_BRIDGE_ENABLED``：总闸，**默认关**。关着时 ``device_*`` 工具
  一律结构化拒绝（``device_bridge_disabled``），手机端连接与 hello 不受影响
  （登记照常，只是不派发命令）。
- ``NEUROVA_DEVICE_COMMAND_TIMEOUT_MS``：单条命令等回执的默认窗口。屏幕类
  长动作在 P1 治理卡里按动作放宽，这里只放全局缺省。
"""
from __future__ import annotations

import os

__all__ = [
    "DEVICE_BRIDGE_ENABLED_ENV",
    "DEVICE_COMMAND_TIMEOUT_ENV",
    "DEFAULT_COMMAND_TIMEOUT_MS",
    "deviceBridgeEnabled",
    "defaultCommandTimeoutMs",
]

DEVICE_BRIDGE_ENABLED_ENV = "NEUROVA_DEVICE_BRIDGE_ENABLED"
DEVICE_COMMAND_TIMEOUT_ENV = "NEUROVA_DEVICE_COMMAND_TIMEOUT_MS"
DEFAULT_COMMAND_TIMEOUT_MS = 10_000


def deviceBridgeEnabled() -> bool:
    """设备桥总闸（默认关：env 显式 =1 才放行命令派发）。"""
    return os.environ.get(DEVICE_BRIDGE_ENABLED_ENV, "").strip() == "1"


def defaultCommandTimeoutMs() -> int:
    """单条命令的默认回执窗口（env 可覆盖；非法值回落缺省，不抛）。"""
    raw = os.environ.get(DEVICE_COMMAND_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_COMMAND_TIMEOUT_MS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_COMMAND_TIMEOUT_MS
    return value if value > 0 else DEFAULT_COMMAND_TIMEOUT_MS
