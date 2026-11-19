# -*- coding: utf-8 -*-
"""AD-6（agent-desktop 对照工单后置项拍板立项）· 三平台适配骨架（第一期）。

Windows 已实证（UIA）；macOS AX / Linux AT-SPI 本轮交付**结构化骨架**：
平台探测单一源 + 三态可用性 + 预留 backend（诚实 NotImplemented）+ 真机待办登记。
不谎称支持——非 Windows 的 reason 必须指明平台与缺什么。
"""

import pytest

from neurova.computer_use import desktop_uia, platform as cu_platform


class TestPlatformDetection:
    def test_platform_names(self, monkeypatch):
        for raw, name in (("win32", "windows"), ("darwin", "macos"),
                          ("linux", "linux"), ("freebsd12", "unknown")):
            monkeypatch.setattr(cu_platform.sys, "platform", raw)
            assert cu_platform.desktopPlatform() == name

    def test_availability_three_states_on_windows_host(self, monkeypatch):
        """本机（Windows）：windows=available，macos/linux=not_configured 且 reason 指明平台。"""
        monkeypatch.setattr(cu_platform.sys, "platform", "win32")
        states = cu_platform.desktopBackendAvailability()
        assert states["windows"]["state"] == "available"
        for plat in ("macos", "linux"):
            assert states[plat]["state"] == "not-configured", states[plat]
            assert plat in states[plat]["reason"], f"{plat} 的 reason 必须点名平台"

    def test_macos_state_demands_pyobjc(self, monkeypatch):
        monkeypatch.setattr(cu_platform.sys, "platform", "darwin")
        states = cu_platform.desktopBackendAvailability()
        assert states["macos"]["state"] == "not-configured"
        assert "ApplicationServices" in states["macos"]["reason"] or "pyobjc" in states["macos"]["reason"]

    def test_linux_state_demands_atspi(self, monkeypatch):
        monkeypatch.setattr(cu_platform.sys, "platform", "linux")
        states = cu_platform.desktopBackendAvailability()
        assert states["linux"]["state"] == "not-configured"
        assert "AT-SPI" in states["linux"]["reason"] or "pyatspi" in states["linux"]["reason"]


class TestAvailabilitySingleSource:
    def test_desktop_uia_availability_derives_from_platform_module(self, monkeypatch):
        """desktop_uia.availabilityDetail 必须从 platform 单源派生（不再自判 os.name）。"""
        monkeypatch.setattr(cu_platform.sys, "platform", "darwin")
        detail = desktop_uia.availabilityDetail()
        states = cu_platform.desktopBackendAvailability()
        assert detail == states["windows"], "desktop_uia 必须取 platform 单源的 windows 位"
        assert detail["available"] is False
        assert "windows" in detail["reason"]

    def test_windows_path_unchanged(self, monkeypatch):
        monkeypatch.setattr(cu_platform.sys, "platform", "win32")
        detail = desktop_uia.availabilityDetail()
        assert detail["available"] is True and detail["platform"] == "windows"
        assert desktop_uia.is_available() is detail["available"]


class TestReservedBackends:
    def test_reserved_backends_honest_on_wrong_host(self):
        """预留 backend 在非本平台必须 available=False（不谎称可用）。"""
        from neurova.computer_use.backends_macos import MacAccessibilityBackend
        from neurova.computer_use.backends_linux import AtspiBackend

        assert MacAccessibilityBackend().is_available() is False
        assert AtspiBackend().is_available() is False

    def test_reserved_backend_actions_refuse_to_implement(self):
        from neurova.computer_use.backends_macos import MacAccessibilityBackend

        b = MacAccessibilityBackend()
        with pytest.raises(NotImplementedError):
            b.walk({}, 10, 5)
        with pytest.raises(NotImplementedError):
            b.set_value({}, "x")

    def test_manager_refuses_on_macos_with_platform_reason(self, monkeypatch):
        """macOS 语义快照：拒绝且 reason 点名平台（不是笼统 unsupported）。"""
        monkeypatch.setattr(cu_platform.sys, "platform", "darwin")
        mgr = desktop_uia.DesktopUIAManager(backend=None)
        out = mgr.snapshot()
        assert out["success"] is False
        assert out["action_result"]["refusal_code"] == "unsupported_method"
        assert "macOS" in out["error"] or "macos" in out["error"]
