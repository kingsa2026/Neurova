# -*- coding: utf-8 -*-
"""设备桥（移动端执行端）：后端 → 已配对手机的命令派发与回执收敛。

职责切分（计划 §2）：后端只做决策与治理（选设备、校验能力、记账、判终态）；
手机端只做执行与上报。本包是后端侧的唯一实现：

- ``registry``：在线设备连接登记（pairing_id → LedgerWs + 能力快照）；
- ``router``：命令派发（幂等登记 → 经账本下发 → 等回执 → 终态收敛）；
- ``executor``：``device_*`` 工具的统一入口（参数归一 + 身份读取）；
- ``config``：总闸与超时口径（单一事实源）。

帧型/能力词表/错误码单源在 ``neurova/tunnel/protocol.py``；结果契约复用
``computer_use/action_result``（route=device）。不在这里造第二份词表。
"""
from neurova.device_bridge.registry import (
    DeviceConnection,
    DeviceConnectionRegistry,
    getDeviceBridgeRegistry,
    resetDeviceBridgeRegistry,
)
from neurova.device_bridge.router import (
    DeviceBridgeRouter,
    getDeviceBridgeRouter,
    resetDeviceBridgeRouter,
)

__all__ = [
    "DeviceConnection",
    "DeviceConnectionRegistry",
    "getDeviceBridgeRegistry",
    "resetDeviceBridgeRegistry",
    "DeviceBridgeRouter",
    "getDeviceBridgeRouter",
    "resetDeviceBridgeRouter",
]
