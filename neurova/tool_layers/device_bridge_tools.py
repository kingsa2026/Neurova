# -*- coding: utf-8 -*-
"""设备桥工具族（2026-11-23 计划 B3）——从 neurova.tool_executor 拆出。

七工具统一薄委托；归一/身份/能力协商/幂等派发/结果契约都在
`neurova.device_bridge.executor`。`_builtin_dispatch` 目标方法名不变；
`ToolExecutor._execute_builtin_tool` 的 `device_*` 治理/审计咽喉不在此改。

不顶层 import `neurova.tool_executor`；`executeDeviceTool` 保持方法内惰性 import。
"""
from typing import Dict

__all__ = ["DeviceBridgeToolsMixin"]


class DeviceBridgeToolsMixin:
    """device_* built-in tools; dispatch names remain `_execute_device_*`."""

    async def _execute_device_open_url(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_open_url", params)

    async def _execute_device_open_app(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_open_app", params)

    async def _execute_device_clipboard_read(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_clipboard_read", params)

    async def _execute_device_clipboard_write(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_clipboard_write", params)

    async def _execute_device_app_list(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_app_list", params)

    async def _execute_device_env(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_env", params)

    async def _execute_device_notification_read(self, params: Dict) -> Dict:
        from neurova.device_bridge.executor import executeDeviceTool

        return await executeDeviceTool("device_notification_read", params)
