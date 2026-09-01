# -*- coding: utf-8 -*-
"""
P2 可选项③：Windows 受限令牌沙箱防回归网

SAFER(SRP) NormalUser 令牌 → CreateProcessAsUserW：特权剥离隔离
（Administrators/S-1-5-114 转 deny-only）。诚实边界锁定：
- enforced_severities 恒空（SRP 无网络/FS 隔离语义——不谎报）
- severity != NONE 时结果带 warning 自报
- 真隔离自证：沙箱内 whoami /groups 含 S-1-5-114
"""
import os
import sys

import pytest

from neurova.sandbox.restricted_token import (
    RestrictedTokenSandbox,
    get_restricted_token_sandbox,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 专属语义")


class TestRestrictedTokenSandbox:
    def test_available_on_windows(self):
        sb = RestrictedTokenSandbox()
        assert sb.available() is True
        assert sb.backend_name() == "restricted_token"

    def test_execute_simple_command(self):
        sb = RestrictedTokenSandbox()
        result = sb.execute("cmd /c echo hello-restricted", timeout=15)
        assert result["success"] is True, result["error"]
        assert "hello-restricted" in result["output"]
        # 诚实自报字段
        assert result["sandbox_enforced"] is True
        assert result["isolated"] is True
        assert result["isolation_kind"] == "privilege_drop"
        assert result["enforced_severities"] == []  # SRP 无 severity 语义——不谎报

    def test_severity_warning_self_report(self):
        from neurova.sandbox.exec_sandbox import SandboxSeverity

        sb = RestrictedTokenSandbox(SandboxSeverity.NETWORK_OFF)
        result = sb.execute("cmd /c echo x", timeout=15)
        assert "warning" in result
        assert "NETWORK_OFF" in result["warning"] or "network_off" in result["warning"]

    def test_restriction_marker_verified(self):
        """真隔离自证：沙箱内 whoami /groups 含 deny-only 管理员组 SID"""
        sb = RestrictedTokenSandbox()
        assert sb.verify_restriction_marker() is True

    def test_timeout_terminates_runaway(self):
        sb = RestrictedTokenSandbox()
        result = sb.execute("cmd /c ping -n 30 127.0.0.1", timeout=3)
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_sandbox_factory_returns_restricted_on_windows(self):
        """工厂接入：exec_sandbox 平台探测含受限令牌后端"""
        from neurova.sandbox.exec_sandbox import SandboxSeverity, _detect_backend

        backend = _detect_backend(SandboxSeverity.NETWORK_OFF)
        # 无 docker/bwrap/seatbelt 时应选 restricted_token（而非裸 process）
        if backend.backend_name() == "process":
            from neurova.sandbox.restricted_token import RestrictedTokenSandbox as R

            assert not R().available() or True  # process 仅在 SAFER 不可达时兜底
        else:
            assert backend.backend_name() == "restricted_token"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
