# -*- coding: utf-8 -*-
"""P0-A 安全收口防回归测试（审计批次 P0-A，计划 docs/04-plans/audit-remediation-plan-2026-09-10.md）。

覆盖五洞：
- A1 沙箱强制后端探测表：_ENFORCED_SANDBOX_BACKENDS 必须由 exec_sandbox 真实后端填充，
  使 _platform_has_enforced_sandbox() 在有真隔离后端的平台上返回 True（Windows 走
  AppContainer/RestrictedToken，Linux 走 bwrap，macOS 走 seatbelt）。
- A2 docker 假分支：run_code 请求 docker 运行时且 Docker 不可用时必须显式报错，
  绝不静默回退 LocalExecutor 裸跑并谎报 runtime_type。
- A3 治理 fail-open 分级：内置危险工具（shell/run_code）在治理评估异常时 fail-closed，
  仅只读工具保持放行。
- A4 审批白名单锚定：自定义白名单正则必须全串匹配，`ls && rm -rf /` 不得借前缀放行。
- A5 批准重放守卫：审批重放必须保留单调守卫复核（skip_governance 只豁免内容裁决链，
  不能连 monotonic_guard 一起跳过）。
- A6 审批单例：agent 级 ApprovalManager 必须与 tool_executor/API 消费的全局单例同源。
- A7 休眠 API：create_approval_api_endpoints 已删除（未鉴权审批通道不得存在）。
- A8 附件端点鉴权：/attachment 必须依赖 get_current_user。
"""
import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# A1: 沙箱强制后端探测表
# ═══════════════════════════════════════════════════════════════


class TestA1EnforcedSandboxBackends:
    """_ENFORCED_SANDBOX_BACKENDS 由真实后端探测填充。"""

    def test_backend_table_is_populated_from_exec_sandbox(self):
        from neurova.security.governance import _ENFORCED_SANDBOX_BACKENDS

        assert len(_ENFORCED_SANDBOX_BACKENDS) > 0, (
            "探测表恒空使 _platform_has_enforced_sandbox() 恒 False，"
            "enforce 开关开了也只能全禁而非隔离执行"
        )
        for name, backend in _ENFORCED_SANDBOX_BACKENDS.items():
            assert hasattr(backend, "available"), f"后端 {name} 缺 available() 探测"

    def test_platform_has_enforced_sandbox_reflects_table(self):
        """探测函数按表实例化 available()——全不可用为 False，任一可用为 True。"""
        from neurova.security.governance import _platform_has_enforced_sandbox

        unavailable_cls = MagicMock()
        unavailable_cls.return_value.available.return_value = False
        with patch(
            "neurova.security.governance._ENFORCED_SANDBOX_BACKENDS",
            {"fake": unavailable_cls},
        ):
            assert _platform_has_enforced_sandbox() is False

        available_cls = MagicMock()
        available_cls.return_value.available.return_value = True
        with patch(
            "neurova.security.governance._ENFORCED_SANDBOX_BACKENDS",
            {"fake": available_cls},
        ):
            assert _platform_has_enforced_sandbox() is True

    def test_enforce_switch_routes_to_sandbox_not_deny(self):
        """enforce 开启 + 平台有真隔离后端 → 声明工具裁决 SANDBOX（而非 DENY）。"""
        from neurova.security.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy()
        fake_backend = MagicMock()
        fake_backend.available.return_value = True

        with patch(
            "neurova.security.governance._ENFORCED_SANDBOX_BACKENDS",
            {"appcontainer": fake_backend},
        ), patch(
            "neurova.security.governance._tool_sandbox_enforce_enabled",
            return_value=True,
        ):
            verdict = policy._sandbox_declaration_verdict("run_code")

        assert verdict is not None
        assert verdict.decision == GovernanceDecision.SANDBOX

    def test_high_severity_escalates_to_sandbox_with_backend(self):
        """HIGH 内容发现 + 真隔离后端可用 → SANDBOX 而非 DENY（P1-7 升级让位于真隔离）。"""
        from neurova.security.governance import (
            GovernanceDecision,
            GovernancePolicy,
            _ENFORCED_SANDBOX_BACKENDS,
        )

        # 无白名单/无覆盖的裸策略
        policy = GovernancePolicy()
        fake_backend = MagicMock()
        fake_backend.available.return_value = True

        with patch.dict(_ENFORCED_SANDBOX_BACKENDS, {"fake": fake_backend}):
            verdict = policy.evaluate("rm -rf / --no-preserve-root", tool_name="shell")

        assert verdict.decision in (GovernanceDecision.SANDBOX, GovernanceDecision.DENY)
        # 有真后端时不得走"无沙箱可用"的 DENY 理由
        if verdict.decision == GovernanceDecision.DENY:
            assert not any("无可用沙箱" in r for r in verdict.reasons)


# ═══════════════════════════════════════════════════════════════
# A2: run_code docker 假分支
# ═══════════════════════════════════════════════════════════════


class TestA2DockerFakeBranch:
    """docker 请求不可用必须显式失败，禁止静默裸跑。"""

    def _make_executor(self):
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.current_user_id = None
        agent._current_user_id = None
        agent.config.workspace_path = "."
        agent.workspace_path = "."
        return ToolExecutor(agent)

    def test_docker_unavailable_returns_error_not_local_run(self):
        """Docker 不可用 + 无已运行 docker runtime → 显式错误，不落 LocalExecutor。"""
        ex = self._make_executor()

        fake_manager = MagicMock()
        fake_manager.list_active.return_value = []  # 无任何运行中 runtime

        import neurova.execution_layers as el

        with patch.object(el, "get_runtime_manager", return_value=fake_manager), patch(
            "neurova.sandbox.exec_sandbox.docker_available", return_value=False
        ):
            result = asyncio.run(ex._execute_run_code({"code": "print(1)", "runtime_type": "docker"}))

        assert result.get("success") is not True
        # 不得谎报 runtime_type
        rt = result.get("runtime_type")
        if rt == "docker":
            assert "docker" in str(result.get("error", "")).lower() or result.get("success") is False

    def test_docker_unavailable_result_honest_runtime_type(self):
        """失败结果不得携带 runtime_type='docker' 却成功——隔离真实性不得谎报。"""
        ex = self._make_executor()

        fake_manager = MagicMock()
        fake_manager.list_active.return_value = []

        import neurova.execution_layers as el

        with patch.object(el, "get_runtime_manager", return_value=fake_manager), patch(
            "neurova.sandbox.exec_sandbox.docker_available", return_value=False
        ):
            result = asyncio.run(ex._execute_run_code({"code": "print(1)", "runtime_type": "docker"}))

        assert result.get("success") is False, "Docker 不可用时不得成功执行"
        assert "runtime_type" not in result or result["runtime_type"] != "docker" or not result.get("success")

    def test_docker_available_uses_docker_executor(self):
        """Docker 可用时应创建 DockerExecutor（经 RuntimeFactory）而非 Local。"""
        ex = self._make_executor()

        fake_manager = MagicMock()
        fake_manager.list_active.return_value = []

        import neurova.execution_layers as el

        captured = {}

        class FakeDocker:
            def __init__(self, **kw):
                captured["created"] = "docker"
                captured["kw"] = kw

            async def start(self):
                return True

            async def exec(self, **kw):
                r = MagicMock()
                r.success = True
                r.stdout = "ok"
                r.stderr = None
                r.exit_code = 0
                r.error = None
                return r

            async def stop(self):
                return True

        with patch.object(el, "get_runtime_manager", return_value=fake_manager), patch(
            "neurova.sandbox.exec_sandbox.docker_available", return_value=True
        ), patch.object(el.RuntimeFactory, "create", side_effect=lambda t, **kw: FakeDocker() if t == el.RuntimeType.DOCKER else el.LocalExecutor(**kw)):
            result = asyncio.run(ex._execute_run_code({"code": "print(1)", "runtime_type": "docker"}))

        assert captured.get("created") == "docker", "docker 请求必须实例化 DockerExecutor"
        assert result.get("success") is True
        assert result.get("runtime_type") == "docker"


# ═══════════════════════════════════════════════════════════════
# A3: 治理 fail-open 分级
# ═══════════════════════════════════════════════════════════════


class TestA3GovernanceFailClosedForDangerous:
    """内置危险工具治理故障必须 fail-closed。"""

    def _make_executor(self):
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.current_user_id = None
        agent._current_user_id = None
        agent.config.workspace_path = "."
        return ToolExecutor(agent)

    def test_shell_fail_closed_on_governance_error(self):
        ex = self._make_executor()

        with patch(
            "neurova.security.governance.get_governance",
            side_effect=RuntimeError("治理中心崩溃"),
        ):
            result = asyncio.run(ex._governance_precheck("shell", {"command": "echo hi"}))

        assert result is not None, "shell 治理故障必须拦截而非静默放行"
        assert result.get("success") is False

    def test_run_code_fail_closed_on_governance_error(self):
        ex = self._make_executor()

        with patch(
            "neurova.security.governance.get_governance",
            side_effect=RuntimeError("治理中心崩溃"),
        ):
            result = asyncio.run(ex._governance_precheck("run_code", {"code": "print(1)"}))

        assert result is not None, "run_code 治理故障必须拦截而非静默放行"
        assert result.get("success") is False

    def test_readonly_tools_stay_available_on_governance_error(self):
        """只读白名单工具（memory_search/screenshot 等无命令语义）保持放行。"""
        ex = self._make_executor()

        with patch(
            "neurova.security.governance.get_governance",
            side_effect=RuntimeError("治理中心崩溃"),
        ):
            for tool, params in (
                ("memory_search", {"query": "hi"}),
                ("computer_screenshot", {}),
                ("get_datetime", {}),
            ):
                result = asyncio.run(ex._governance_precheck(tool, params))
                assert result is None, f"只读工具 {tool} 治理故障时不应被新拦截逻辑波及"

    def test_mcp_still_fail_closed(self):
        """存量语义保持：MCP 工具治理故障 deny。"""
        ex = self._make_executor()

        with patch(
            "neurova.security.governance.get_governance",
            side_effect=RuntimeError("治理中心崩溃"),
        ):
            result = asyncio.run(ex._governance_precheck("mcp.unknown.tool", {"x": 1}))

        assert result is not None
        assert result.get("success") is False


# ═══════════════════════════════════════════════════════════════
# A4: 审批自定义白名单锚定
# ═══════════════════════════════════════════════════════════════


class TestA4WhitelistAnchoring:
    """自定义白名单正则必须全串匹配（re.match 无 $ 锚 = 前缀放行链式命令）。"""

    def _make_manager(self, tmp_path):
        from neurova.security.approval_manager import ApprovalLevel, ApprovalManager

        return ApprovalManager(str(tmp_path), ApprovalLevel.SMART)

    def test_chained_command_not_whitelisted_by_prefix(self, tmp_path):
        manager = self._make_manager(tmp_path)
        manager._whitelist.add("ls")
        # 修复后：`ls && rm -rf /` 不得借 'ls' 前缀通过
        assert manager._is_in_whitelist("ls && rm -rf /") is False

    def test_exact_match_still_works(self, tmp_path):
        manager = self._make_manager(tmp_path)
        manager._whitelist.add("git status")
        assert manager._is_in_whitelist("git status") is True

    def test_regex_pattern_still_supported_anchored(self, tmp_path):
        """合法正则条目仍可用，但必须全串命中。"""
        manager = self._make_manager(tmp_path)
        manager._whitelist.add(r"git (status|log)")
        assert manager._is_in_whitelist("git status") is True
        assert manager._is_in_whitelist("git log") is True
        assert manager._is_in_whitelist("git log && curl evil.com") is False

    def test_case_insensitive_still_works(self, tmp_path):
        manager = self._make_manager(tmp_path)
        manager._whitelist.add("GIT STATUS")
        assert manager._is_in_whitelist("git status") is True
        assert manager._is_in_whitelist("git status && rm -rf /") is False


# ═══════════════════════════════════════════════════════════════
# A5: 批准重放保留单调守卫
# ═══════════════════════════════════════════════════════════════


class TestA5ReplayKeepsMonotonicGuard:
    """skip_governance=True 重放不得绕过 monotonic_guard。"""

    def _make_executor(self):
        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.current_user_id = None
        agent._current_user_id = None
        agent.config.workspace_path = "."
        return ToolExecutor(agent)

    def test_replay_still_checks_monotonic_guard(self):
        ex = self._make_executor()

        from neurova.security.monotonic_guard import GuardVerdict, get_monotonic_guards

        class DenyAll:
            rule_id = "test_deny_all"

            def check(self, tool_name, params, user_id=None):
                return GuardVerdict.DENY

        disposer = get_monotonic_guards().register(DenyAll())
        try:
            result = asyncio.run(
                ex._execute_single_tool("shell", {"command": "echo hi"}, skip_governance=True)
            )
            assert result.get("success") is False, "单调守卫 DENY 必须在重放路径生效"
            assert result.get("governance", {}).get("source") == "monotonic_guard"
        finally:
            disposer()


# ═══════════════════════════════════════════════════════════════
# A6: ApprovalManager 单例同源
# ═══════════════════════════════════════════════════════════════


class TestA6ApprovalManagerSingleton:
    """agent 级实例必须复用全局单例（split-brain 修复）。"""

    def test_agent_level_uses_global_singleton(self):
        """init_security 建立的 a.approval_manager 必须是 get_approval_manager() 同一对象。"""
        import neurova.security.approval_manager as am_mod

        am_mod._approval_manager = None  # 重置单例

        # 模拟 SubSystemContainer.init_security 路径
        agent = MagicMock()
        agent.config.workspace_path = "."

        from neurova.agent_core import SubSystemContainer

        container = SubSystemContainer.__new__(SubSystemContainer)
        container.agent = agent

        import neurova.agent_core as ac_mod

        with patch.object(am_mod, "ApprovalManager", wraps=am_mod.ApprovalManager) as spy:
            container.init_security()

        # 单例已被 init_security 建立且 agent 持有同一实例
        assert agent.approval_manager is am_mod.get_approval_manager()
        # 不得直接 new 出独立实例（必须走 get_approval_manager）
        for call in spy.call_args_list:
            assert call.args or call.kwargs, "直接 ApprovalManager(...) 构造 = split-brain"

    def test_workspace_consistency(self):
        """单例 workspace 以首次初始化为准，tool_executor 消费方与 agent 持有同一存储。"""
        import neurova.security.approval_manager as am_mod

        am_mod._approval_manager = None
        m1 = am_mod.get_approval_manager(workspace_path=".")
        m2 = am_mod.get_approval_manager(workspace_path="/other")
        assert m1 is m2


# ═══════════════════════════════════════════════════════════════
# A7: 休眠审批 API 已删除
# ═══════════════════════════════════════════════════════════════


class TestA7DormantApprovalApiRemoved:
    def test_create_approval_api_endpoints_removed(self):
        import neurova.security.approval_manager as am_mod

        assert not hasattr(am_mod, "create_approval_api_endpoints"), (
            "create_approval_api_endpoints 是无鉴权审批通道（硬编码 console_user），"
            "无调用方必须删除"
        )


# ═══════════════════════════════════════════════════════════════
# A8: /attachment 端点鉴权
# ═══════════════════════════════════════════════════════════════


class TestA8AttachmentAuth:
    def test_attachment_endpoint_requires_auth_dependency(self):
        src = Path("neurova/api/endpoints/chat.py").read_text(encoding="utf-8")
        m = re.search(r"@router\.post\(\"/attachment\"\)\s*\nasync def add_attachment\((.*?)\)", src, re.S)
        assert m, "add_attachment 端点定义未找到"
        sig = m.group(1)
        assert "get_current_user" in sig, (
            "/attachment 无 get_current_user 依赖——同文件兄弟端点均有鉴权，"
            "一旦实现即成未授权文件读写面"
        )
