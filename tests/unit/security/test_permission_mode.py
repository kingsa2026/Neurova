"""权限模式语义化（P1-4）：plan/build/edit/yolo/guarded（+auto 预留）。

- inheritPermissionMode：限制型父模式（plan/guarded）对子代理**只收窄不升级**——
  guarded 父把子代理 yolo 压回 guarded（ZCode 同款判据），plan 父同理；
- 解析优先级：继承上下文 > 治理设置 per-agent 覆写 > 默认 build；
- 模式落到治理裁决：yolo 把 ASK 放行（DENY/SANDBOX 不动）、edit 只对工作区
  文件编辑三工具放行 ASK、plan 把非只读工具的 ALLOW 收成 ASK、auto 诚实按 build；
- guarded 模式强制语法门：即使设置项被关，guarded 上下文里危险命令仍降级 ASK。
"""

import unittest
from unittest.mock import MagicMock, patch

from neurova.security.governance import (
    GovernanceDecision,
    GovernancePolicy,
    GovernanceResult,
    reset_governance,
)
from neurova.security.permission_mode import (
    PermissionMode,
    inheritedModeScope,
    inheritPermissionMode,
    resolveEffectivePermissionMode,
    resolvePermissionModeFor,
)
from neurova.tool_executor import ToolExecutor


def _verdict(decision: GovernanceDecision) -> GovernanceResult:
    return GovernanceResult(decision=decision, reasons=["测试裁决"])


def _makeExecutor(agentId: str = "a1") -> ToolExecutor:
    agent = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = agentId
    agent.config.agent_id = agentId
    return ToolExecutor(agent)


class TestInheritPermissionMode(unittest.TestCase):
    def test_guarded_parent_clamps_yolo_child(self):
        self.assertIs(
            inheritPermissionMode(PermissionMode.GUARDED, PermissionMode.YOLO),
            PermissionMode.GUARDED,
        )

    def test_plan_parent_clamps_permissive_children(self):
        for child in (PermissionMode.YOLO, PermissionMode.EDIT, PermissionMode.BUILD):
            self.assertIs(
                inheritPermissionMode(PermissionMode.PLAN, child),
                PermissionMode.PLAN,
                child,
            )

    def test_permissive_parent_keeps_child(self):
        for parent in (PermissionMode.BUILD, PermissionMode.EDIT, PermissionMode.YOLO):
            self.assertIs(
                inheritPermissionMode(parent, PermissionMode.YOLO),
                PermissionMode.YOLO,
                parent,
            )

    def test_same_mode_passthrough(self):
        self.assertIs(
            inheritPermissionMode(PermissionMode.GUARDED, PermissionMode.GUARDED),
            PermissionMode.GUARDED,
        )


class TestResolvePermissionMode(unittest.TestCase):
    def test_default_is_build(self):
        self.assertIs(resolvePermissionModeFor("a1", {}), PermissionMode.BUILD)

    def test_override_wins(self):
        settings = {"permission_mode_overrides": {"a1": "yolo"}}
        self.assertIs(resolvePermissionModeFor("a1", settings), PermissionMode.YOLO)

    def test_invalid_override_falls_back_to_build(self):
        settings = {"permission_mode_overrides": {"a1": "nuclear"}}
        self.assertIs(resolvePermissionModeFor("a1", settings), PermissionMode.BUILD)

    def test_inherited_context_clamps_override(self):
        executor = _makeExecutor("a1")
        settings = {"permission_mode_overrides": {"a1": "yolo"}}
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value=settings,
        ):
            with inheritedModeScope(PermissionMode.GUARDED):
                self.assertIs(
                    resolveEffectivePermissionMode(executor._agent),
                    PermissionMode.GUARDED,
                )

    def test_no_inheritance_uses_override(self):
        executor = _makeExecutor("a1")
        settings = {"permission_mode_overrides": {"a1": "yolo"}}
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value=settings,
        ):
            self.assertIs(
                resolveEffectivePermissionMode(executor._agent),
                PermissionMode.YOLO,
            )


class TestApplyModeToVerdict(unittest.TestCase):
    def test_yolo_autoallows_ask_but_not_deny(self):
        executor = _makeExecutor("a1")
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value={"permission_mode_overrides": {"a1": "yolo"}},
        ):
            allowed = executor._applyPermissionMode(
                "exec_command", _verdict(GovernanceDecision.ASK)
            )
            self.assertIs(allowed.decision, GovernanceDecision.ALLOW)
            denied = executor._applyPermissionMode(
                "exec_command", _verdict(GovernanceDecision.DENY)
            )
            self.assertIs(denied.decision, GovernanceDecision.DENY)

    def test_plan_asks_for_non_readonly_allow(self):
        executor = _makeExecutor("a1")
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value={"permission_mode_overrides": {"a1": "plan"}},
        ):
            asked = executor._applyPermissionMode(
                "exec_command", _verdict(GovernanceDecision.ALLOW)
            )
            self.assertIs(asked.decision, GovernanceDecision.ASK)
            readonlyAllowed = executor._applyPermissionMode(
                "web_search", _verdict(GovernanceDecision.ALLOW)
            )
            self.assertIs(readonlyAllowed.decision, GovernanceDecision.ALLOW)

    def test_edit_autoallows_file_edit_tools_only(self):
        executor = _makeExecutor("a1")
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value={"permission_mode_overrides": {"a1": "edit"}},
        ):
            fileEdit = executor._applyPermissionMode(
                "file_write", _verdict(GovernanceDecision.ASK)
            )
            self.assertIs(fileEdit.decision, GovernanceDecision.ALLOW)
            shell = executor._applyPermissionMode(
                "exec_command", _verdict(GovernanceDecision.ASK)
            )
            self.assertIs(shell.decision, GovernanceDecision.ASK)

    def test_auto_honestly_behaves_as_build(self):
        executor = _makeExecutor("a1")
        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value={"permission_mode_overrides": {"a1": "auto"}},
        ):
            result = executor._applyPermissionMode(
                "exec_command", _verdict(GovernanceDecision.ASK)
            )
            self.assertIs(result.decision, GovernanceDecision.ASK)


class TestGuardedForcesSyntaxGate(unittest.TestCase):
    """guarded 上下文里，语法门即使被设置关闭也强制生效。"""

    def tearDown(self):
        reset_governance()

    def _policy(self):
        return GovernancePolicy(
            ask_on_high=True,
            whitelist_entries=[{"id": "w1", "pattern": "rm", "match_type": "prefix"}],
        )

    def test_guarded_context_keeps_gate(self):
        policy = self._policy()
        with patch(
            "neurova.security.governance_settings.resolve_flag", return_value=False
        ):
            with inheritedModeScope(PermissionMode.GUARDED):
                result = policy.evaluate("rm -rf /tmp/build", tool_name="exec_command")
        self.assertIs(result.decision, GovernanceDecision.ASK)

    def test_build_context_respects_disabled_gate(self):
        policy = self._policy()
        with patch(
            "neurova.security.governance_settings.resolve_flag", return_value=False
        ):
            with inheritedModeScope(PermissionMode.BUILD):
                result = policy.evaluate("rm -rf /tmp/build", tool_name="exec_command")
        self.assertIs(result.decision, GovernanceDecision.ALLOW)


if __name__ == "__main__":
    unittest.main()
