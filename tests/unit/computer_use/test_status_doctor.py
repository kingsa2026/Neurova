"""R0-4 /status 拆分 + /doctor 端点（CUA 升级方案 Phase 0）

病根（修复前）：desktop_available 只反映截图后端（PIL 可导入），pyautogui
输入能力可能已废却报"可用"——OCU doctor 思想：能力自检必须逐项真实探测。

验收：
- manager.input_available()：pyautogui 导入 + position() 真实探测，异常即 False
- manager.uia_available()：desktop_uia 模块级探测（R1-1 落地前恒 False 不炸）
- /status 拆出 screenshot_available / input_available / uia_available；
  desktop_available 语义收紧为"截图+输入都可用"（保留旧键向后兼容）
- GET /doctor 逐项上报 {pillow, pyautogui_input, uia, dpi_aware, screen_metadata}
"""

from unittest.mock import MagicMock

import pytest

from neurova.computer_use import ComputerUseManager


class TestManagerProbes:
    def test_input_available_true(self, monkeypatch):
        import sys

        fake = MagicMock()
        fake.position.return_value = (0, 0)
        monkeypatch.setitem(sys.modules, "pyautogui", fake)
        manager = ComputerUseManager()
        assert manager.input_available() is True
        fake.position.assert_called_once()

    def test_input_available_false_on_error(self, monkeypatch):
        import sys

        fake = MagicMock()
        fake.position.side_effect = RuntimeError("no desktop session")
        monkeypatch.setitem(sys.modules, "pyautogui", fake)
        manager = ComputerUseManager()
        assert manager.input_available() is False

    def test_input_available_false_when_missing(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "pyautogui", None)  # None → import 报 ImportError
        manager = ComputerUseManager()
        assert manager.input_available() is False

    def test_uia_available_never_raises(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "neurova.computer_use.desktop_uia", None)
        manager = ComputerUseManager()
        assert manager.uia_available() is False


class TestStatusEndpoint:
    @pytest.fixture
    def fake_manager(self):
        manager = MagicMock()
        manager._screenshot_backend = "PIL"
        manager.input_available.return_value = True
        manager.uia_available.return_value = True
        manager.dpi_aware = True
        manager.screen_metadata.return_value = {
            "virtual_origin": (0, 0),
            "screen_size": (1920, 1080),
            "pixel_size": (1920, 1080),
            "scale": 1.0,
        }
        return manager

    @pytest.mark.asyncio
    async def test_status_splits_capabilities(self, monkeypatch, fake_manager):
        from neurova.api.endpoints import computer as computer_api

        monkeypatch.setattr(computer_api, "_get_manager", lambda: fake_manager)
        resp = await computer_api.get_status()
        data = resp["data"]
        assert data["screenshot_available"] is True
        assert data["input_available"] is True
        assert data["uia_available"] is True
        assert data["desktop_available"] is True

    @pytest.mark.asyncio
    async def test_status_input_broken_means_desktop_unavailable(self, monkeypatch, fake_manager):
        """核心回归：截图可用但输入能力废 → desktop_available 必须为 False"""
        from neurova.api.endpoints import computer as computer_api

        fake_manager.input_available.return_value = False
        monkeypatch.setattr(computer_api, "_get_manager", lambda: fake_manager)
        resp = await computer_api.get_status()
        data = resp["data"]
        assert data["screenshot_available"] is True
        assert data["input_available"] is False
        assert data["desktop_available"] is False


class TestDoctorEndpoint:
    @pytest.mark.asyncio
    async def test_doctor_reports_all_probes(self, monkeypatch):
        from neurova.api.endpoints import computer as computer_api

        report = {
            "pillow": True,
            "pyautogui_input": False,
            "uia": False,
            "dpi_aware": True,
            "screen_metadata": None,
        }
        manager = MagicMock()
        manager.doctor_report.return_value = report
        monkeypatch.setattr(computer_api, "_get_manager", lambda: manager)

        resp = await computer_api.doctor()
        assert resp["data"] == report

    @pytest.mark.asyncio
    async def test_doctor_never_raises(self, monkeypatch):
        from neurova.api.endpoints import computer as computer_api

        def broken():
            raise RuntimeError("boom")

        monkeypatch.setattr(computer_api, "_get_manager", broken)
        resp = await computer_api.doctor()
        assert resp["data"]["pillow"] is False
        assert resp["data"]["pyautogui_input"] is False
