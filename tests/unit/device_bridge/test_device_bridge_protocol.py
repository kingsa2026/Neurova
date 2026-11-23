# -*- coding: utf-8 -*-
"""B2/B3 帧族单源与工具面接线红灯判据。

计划卡 B2/B3：
- 帧型常量单源落 `neurova/tunnel/protocol.py`（device: 前缀，六个帧型）；
- 能力词表封闭集（12 项）；
- action_result 契约新增 route=device 与 device 侧拒绝码（含重试建议）；
- 七个 device_* 工具进 `_BUILTIN_SCHEMAS` + ToolExecutor 分派表 +
  `_NON_REPRODUCIBLE_TOOLS`（对齐 computer_* 的"外部状态瞬时读/写不可重放"口径）。
"""
import inspect

from neurova.builtin_tools import _BUILTIN_SCHEMAS, _NON_REPRODUCIBLE_TOOLS
from neurova.computer_use import action_result
from neurova.tunnel import protocol


class TestDeviceFrameFamily:
    def test_device_frame_constants_exist_and_distinct(self):
        frames = {
            protocol.FRAME_DEVICE_HELLO,
            protocol.FRAME_DEVICE_HELLO_OK,
            protocol.FRAME_DEVICE_EXECUTE,
            protocol.FRAME_DEVICE_CANCEL,
            protocol.FRAME_DEVICE_RESULT,
            protocol.FRAME_DEVICE_EVENT,
        }
        assert len(frames) == 6
        assert all(name.startswith("device:") for name in frames)

    def test_device_frame_types_tuple_matches_constants(self):
        assert set(protocol.DEVICE_FRAME_TYPES) == {
            protocol.FRAME_DEVICE_HELLO, protocol.FRAME_DEVICE_HELLO_OK,
            protocol.FRAME_DEVICE_EXECUTE, protocol.FRAME_DEVICE_CANCEL,
            protocol.FRAME_DEVICE_RESULT, protocol.FRAME_DEVICE_EVENT,
        }

    def test_device_capabilities_closed_vocabulary(self):
        assert protocol.DEVICE_CAPABILITIES == (
            "open_url", "open_app", "clipboard_read", "clipboard_write",
            "app_list", "device_env", "notification_read",
            "screen_observe", "screen_gesture",
            "calendar_read", "calendar_write", "contacts_read",
        )

    def test_device_error_codes_declared(self):
        assert {"device_offline", "device_timeout", "device_bridge_disabled",
                "unknown_capabilities"} <= set(protocol.DEVICE_BRIDGE_ERROR_CODES)


class TestActionResultDeviceContract:
    def test_device_route_registered(self):
        assert "device" in action_result.ROUTES

    def test_device_refusal_codes_registered_with_retry_advice(self):
        for code in ("device_offline", "device_timeout", "device_bridge_disabled"):
            assert code in action_result.REFUSAL_CODES
            assert code in action_result.REFUSAL_RETRY_ADVICE

    def test_build_device_confirmed_roundtrip(self):
        card = action_result.build("device", "confirmed", delivery="background",
                                   evidence=["delivery_ack"])
        assert card["route"] == "device" and card["effect"] == "confirmed"

    def test_build_device_refused_roundtrip(self):
        card = action_result.refused("device", "device_offline")
        assert card["refusal_code"] == "device_offline"
        assert card["retry"] == "retry"


class TestDeviceToolSchemas:
    def test_seven_device_tools_declared(self):
        expected = {
            "device_open_url", "device_open_app", "device_clipboard_read",
            "device_clipboard_write", "device_app_list", "device_env",
            "device_notification_read",
        }
        assert expected <= set(_BUILTIN_SCHEMAS)
        for name in expected:
            schema = _BUILTIN_SCHEMAS[name]
            assert schema.get("description"), name
            assert "parameters" in schema, name

    def test_required_params_declared(self):
        assert _BUILTIN_SCHEMAS["device_open_url"]["parameters"]["required"] == ["url"]
        assert _BUILTIN_SCHEMAS["device_clipboard_write"]["parameters"]["required"] == ["text"]
        assert _BUILTIN_SCHEMAS["device_clipboard_read"]["parameters"]["required"] == []

    def test_device_tools_marked_non_reproducible(self):
        expected = {
            "device_open_url", "device_open_app", "device_clipboard_read",
            "device_clipboard_write", "device_app_list", "device_env",
            "device_notification_read",
        }
        assert expected <= set(_NON_REPRODUCIBLE_TOOLS)


class TestToolExecutorDispatch:
    def test_dispatch_table_maps_all_device_tools(self):
        from neurova.tool_executor import ToolExecutor

        expected = {
            "device_open_url", "device_open_app", "device_clipboard_read",
            "device_clipboard_write", "device_app_list", "device_env",
            "device_notification_read",
        }
        mapped = {name for name, method in ToolExecutor._builtin_dispatch.items()
                  if name.startswith("device_")}
        assert expected <= mapped
        for name in expected:
            method = ToolExecutor._builtin_dispatch[name]
            assert hasattr(ToolExecutor, method), name
            assert inspect.iscoroutinefunction(getattr(ToolExecutor, method)), name
