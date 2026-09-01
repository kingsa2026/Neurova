# -*- coding: utf-8 -*-
"""
遗留③ AppContainer 真实现防回归网（Windows 专属）

探针实证锚点（S-1-16-4096 Low integrity + Administrators deny-only）。
锁定契约：
- available() 现在返回 True（诚实化翻转：占位→真实现）
- execute 结果 isolated=True / isolation_kind=appcontainer
- 网络隔离属 enforced_severities（默认 deny-all 无 internetClient）
- verify_restriction_marker：沙箱内 whoami 含 S-1-16-4096
"""
import os
import sys

import pytest

from neurova.sandbox.appcontainer import AppContainerSandbox

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 专属语义")


class TestAppContainerReal:
    def test_available_now_true(self):
        """P1-7 诚实化的翻转：真实现落地后 available 诚实为 True"""
        sb = AppContainerSandbox()
        assert sb.available() is True
        assert sb.backend_name() == "appcontainer"

    def test_execute_echo(self):
        sb = AppContainerSandbox()
        result = sb.execute("echo hello-ac", timeout=30, cwd=os.environ["TEMP"])
        assert result["success"] is True, result["error"]
        assert "hello-ac" in result["output"]
        assert result["isolated"] is True
        assert result["isolation_kind"] == "appcontainer"

    def test_restriction_marker_low_integrity(self):
        """真隔离自证：沙箱内 whoami /groups 含 Low integrity S-1-16-4096"""
        sb = AppContainerSandbox()
        assert sb.verify_restriction_marker() is True

    def test_enforced_severities_include_network_off(self):
        from neurova.sandbox.exec_sandbox import SandboxSeverity

        sb = AppContainerSandbox()
        assert SandboxSeverity.NETWORK_OFF in sb.enforced_severities()

    def test_timeout_terminates_runaway(self):
        """无网 runaway（choice /t 内建计时）超时强制终止"""
        sb = AppContainerSandbox()
        result = sb.execute("cmd /c choice /c yn /n /t 60 /d y", timeout=4)
        assert result["success"] is False
        assert "timed out" in result["error"], result["error"]

    def test_network_is_denied_by_default(self):
        """默认无 internetClient capability → ping 报"无法联系 IP 驱动程序"
        （网络隔离生效的正向证据，QP 无此能力）"""
        sb = AppContainerSandbox()
        result = sb.execute("cmd /c ping -n 1 127.0.0.1", timeout=15)
        assert result["success"] is False
        assert ("IP 驱动" in result["output"] or "IP driver" in result["output"] or
                "TRANSMIT" in result["output"].upper() or result["return_code"] == 1)

    def test_factory_prefers_appcontainer_now(self):
        """工厂：Windows + API 可达 → appcontainer 优先于 restricted_token"""
        from neurova.sandbox.exec_sandbox import SandboxSeverity, _detect_backend

        if not AppContainerSandbox().available():
            pytest.skip("AppContainer API 不可达")
        backend = _detect_backend(SandboxSeverity.NETWORK_OFF)
        assert backend.backend_name() == "appcontainer"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
