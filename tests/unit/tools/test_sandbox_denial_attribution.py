# -*- coding: utf-8 -*-
"""P1-4 沙箱拒绝归因 + 升级审批链。

- 归因启发式：exit≠0 且输出含沙箱关键词（permission denied / read-only file
  system / seccomp / sandbox / landlock / access is denied…）→ 判沙箱拒绝；
  先排除 2/126/127（shell 自身错误）；Linux 128+SIGSYS(=159) 直接判定
- 编排：SANDBOX 裁决下执行失败且归因命中 → 创建升级审批请求
  （metadata 带 sandbox_denial+原始 params，批准后经既有 approve 重放链
  skip_governance 沙箱外重跑）；归因不命中 → 保持原样（普通失败）
"""
import pytest


class TestAttributionSandboxDenial:
    def test_permission_denied_hit(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        hit = attribution_sandbox_denial({
            "returncode": 1,
            "stdout": "",
            "stderr": "touch: cannot touch '/etc/hosts': Permission denied",
        })
        assert hit is not None
        assert hit["reason"] == "permission denied"
        assert "Permission denied" in hit["snippet"]

    def test_read_only_filesystem_hit(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        assert attribution_sandbox_denial({
            "returncode": 1, "stdout": "Read-only file system: '/usr'",
        }) is not None

    def test_seccomp_and_landlock_hit(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        assert attribution_sandbox_denial({"returncode": 1, "stderr": "seccomp denied syscall"}) is not None
        assert attribution_sandbox_denial({"returncode": 1, "stderr": "landlock: operation blocked"}) is not None

    def test_success_and_none_returncode_never_hit(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        assert attribution_sandbox_denial({"returncode": 0, "stdout": "permission denied"}) is None
        assert attribution_sandbox_denial({"returncode": None, "stderr": "sandbox"}) is None
        assert attribution_sandbox_denial({}) is None

    @pytest.mark.parametrize("code", [2, 126, 127])
    def test_shell_own_errors_excluded(self, code):
        """2/126/127 是 shell 自身错误（找不到命令/权限），不归因沙箱。"""
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        assert attribution_sandbox_denial({
            "returncode": code,
            "stderr": "bash: /x/run.sh: Permission denied",
        }) is None

    def test_sigsys_exit_direct_hit(self):
        """Linux 128+SIGSYS(31)=159：seccomp 杀进程，无需关键词。"""
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        hit = attribution_sandbox_denial({"returncode": 159, "stdout": ""})
        assert hit is not None

    def test_plain_failure_not_attributed(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        assert attribution_sandbox_denial({
            "returncode": 1, "stderr": "cat: no.txt: No such file or directory",
        }) is None

    def test_snippet_truncated_512(self):
        from neurova.sandbox.exec_sandbox import attribution_sandbox_denial

        hit = attribution_sandbox_denial({
            "returncode": 1, "stderr": "permission denied " + "x" * 2000,
        })
        assert len(hit["snippet"]) <= 512


class TestEscalationOrchestration:
    @pytest.mark.asyncio
    async def test_sandbox_failure_with_attribution_creates_escalation(self, tmp_path, monkeypatch):
        from neurova.security.approval_manager import ApprovalManager, ApprovalLevel
        from neurova.sandbox import exec_sandbox as es
        from neurova import tool_executor as te

        am = ApprovalManager(str(tmp_path / "ws"), approval_level=ApprovalLevel.SMART)
        monkeypatch.setattr(te, "_get_approval_manager", lambda: am)

        class _FakeVerdict:
            decision = type("D", (), {"SANDBOX": "sandbox"}).SANDBOX
            severity = None
            reasons = ["policy: 命令执行"]

            def to_dict(self):
                return {"decision": "sandbox", "reasons": self.reasons}

        class _FakeGov:
            def evaluate_tool_call(self, *a, **k):
                return _FakeVerdict()

        monkeypatch.setattr(
            "neurova.security.governance.get_governance", lambda: _FakeGov()
        )
        from neurova.security.governance import GovernanceDecision as _GD

        _FakeVerdict.decision = _GD.SANDBOX

        async def _fake_sandbox(command, severity=None, **k):
            return {"success": False, "returncode": 1,
                    "stdout": "", "stderr": "touch: Permission denied"}

        monkeypatch.setattr(es, "execute_in_sandbox_async", _fake_sandbox)

        from neurova.tool_executor import ToolExecutor
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.config.user_id = "u1"
        agent.config.agent_id = "a1"
        executor = ToolExecutor(agent)

        result = await executor._governance_precheck(
            "computer_shell", {"command": "echo hi"}
        )
        assert result is not None
        assert result.get("pending_approval") is True
        assert result.get("approval_id")
        assert result["sandbox_denial"]["reason"] == "permission denied"
        # 审批请求落库且 metadata 可重放
        req = am.get_request(result["approval_id"])
        assert req is not None
        assert req.metadata.get("tool_name") == "computer_shell"
        assert req.metadata.get("sandbox_denial", {}).get("reason") == "permission denied"

    @pytest.mark.asyncio
    async def test_sandbox_failure_without_attribution_no_escalation(self, tmp_path, monkeypatch):
        from neurova.security.approval_manager import ApprovalManager, ApprovalLevel
        from neurova.sandbox import exec_sandbox as es
        from neurova import tool_executor as te

        am = ApprovalManager(str(tmp_path / "ws"), approval_level=ApprovalLevel.SMART)
        monkeypatch.setattr(te, "_get_approval_manager", lambda: am)

        from neurova.security.governance import GovernanceDecision

        class _FakeVerdict:
            decision = GovernanceDecision.SANDBOX
            severity = None
            reasons = ["policy"]

            def to_dict(self):
                return {"decision": "sandbox"}

        class _FakeGov:
            def evaluate_tool_call(self, *a, **k):
                return _FakeVerdict()

        monkeypatch.setattr(
            "neurova.security.governance.get_governance", lambda: _FakeGov()
        )

        async def _fake_sandbox(command, severity=None, **k):
            return {"success": False, "returncode": 1,
                    "stdout": "", "stderr": "cat: no.txt: No such file or directory"}

        monkeypatch.setattr(es, "execute_in_sandbox_async", _fake_sandbox)

        from neurova.tool_executor import ToolExecutor
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.config.user_id = "u1"
        agent.config.agent_id = "a1"
        executor = ToolExecutor(agent)

        result = await executor._governance_precheck(
            "computer_shell", {"command": "cat no.txt"}
        )
        # 归因不命中 → 沙箱结果原样返回，无审批请求
        assert result is not None
        assert result.get("pending_approval") is None
        assert result.get("approval_id") is None
        assert am.get_pending_requests() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
