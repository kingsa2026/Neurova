"""guarded 语法级危险命令门（P1-3）。

三层钉住：
1. tokenizeArgv：引号/转义/重定向切词；
2. classifyArgv：递归删除/git 破坏性子命令/系统级命令/Windows 与 PowerShell
   删除/重定向失格（只读判定）；
3. governance 接线：白名单命中的危险命令降级 ASK（guarded 单次确认，
   危险命令审批先于白名单放行）；只读 argv 自动放行是独立设置项、默认关、
   且内容检测有发现时永不生效。
"""

import unittest
from unittest.mock import patch

from neurova.security.command_syntax import (
    ArgvClass,
    analyzeCommand,
    classifyArgv,
    tokenizeArgv,
)
from neurova.security.governance import GovernanceDecision, GovernancePolicy, reset_governance


class TestTokenizeArgv(unittest.TestCase):
    def test_quotes_and_escapes(self):
        self.assertEqual(tokenizeArgv('rm -rf "/tmp/a b"'), ("rm", "-rf", "/tmp/a b"))
        # shlex 语义：引号内的空白留在同一个 token 里（与 shell 一致）
        self.assertEqual(tokenizeArgv("echo 'x y'"), ("echo", "x y"))

    def test_redirection_tokens_surface(self):
        self.assertEqual(tokenizeArgv("echo hi > /tmp/f"), ("echo", "hi", ">", "/tmp/f"))

    def test_unbalanced_quotes_fallback_split(self):
        self.assertEqual(tokenizeArgv("echo 'unbalanced"), ("echo", "'unbalanced"))


class TestClassifyArgv(unittest.TestCase):
    def test_readonly_verbs(self):
        cases = [
            ("ls", "-la"),
            ("cat", "/tmp/f"),
            ("grep", "-n", "x", "f"),
            ("git", "status"),
            ("git", "log", "--oneline"),
            ("git", "diff", "HEAD~1"),
            ("pip", "list"),
            ("npm", "ls"),
        ]
        for argv in cases:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.READONLY, argv)

    def test_destructive_recursive_delete(self):
        cases = [
            ("rm", "-rf", "/tmp/x"),
            ("rm", "-r", "x"),
            ("rm", "--recursive", "x"),
            ("ri", "-r", "x"),
        ]
        for argv in cases:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.DESTRUCTIVE, argv)

    def test_destructive_git_subcommands(self):
        cases = [
            ("git", "push", "--force"),
            ("git", "push", "-f", "origin", "main"),
            ("git", "reset", "--hard"),
            ("git", "clean", "-fd"),
            ("git", "branch", "-D", "x"),
            ("git", "checkout", "--", "."),
        ]
        for argv in cases:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.DESTRUCTIVE, argv)

    def test_destructive_system_commands(self):
        cases = [
            ("dd", "if=/dev/zero", "of=/dev/sda"),
            ("mkfs", "/dev/sdb"),
            ("shutdown", "now"),
            ("reboot",),
            ("chmod", "777", "/tmp/x"),
            ("truncate", "-s", "0", "f"),
            ("shred", "f"),
            ("kubectl", "delete", "pod", "x"),
        ]
        for argv in cases:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.DESTRUCTIVE, argv)

    def test_destructive_windows_and_powershell(self):
        cases = [
            ("del", "/s", "/q", "x"),
            ("rd", "/s", "x"),
            ("Remove-Item", "-Recurse", "-Force", "x"),
        ]
        for argv in cases:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.DESTRUCTIVE, argv)

    def test_destructive_find(self):
        self.assertEqual(
            classifyArgv(("find", "/tmp", "-name", "x", "-delete")).classification,
            ArgvClass.DESTRUCTIVE,
        )
        self.assertEqual(
            classifyArgv(("find", "/tmp", "-exec", "rm", "{}", ";")).classification,
            ArgvClass.DESTRUCTIVE,
        )

    def test_find_without_delete_is_readonly(self):
        self.assertEqual(
            classifyArgv(("find", "/tmp", "-name", "x")).classification,
            ArgvClass.READONLY,
        )

    def test_output_redirection_disqualifies_readonly(self):
        self.assertEqual(
            classifyArgv(("echo", "hi", ">", "/tmp/f")).classification,
            ArgvClass.UNKNOWN,
        )
        self.assertEqual(
            classifyArgv(("cat", "a", ">>", "b")).classification,
            ArgvClass.UNKNOWN,
        )

    def test_execution_verbs_are_unknown(self):
        for argv in [("python", "-c", "print(1)"), ("node", "x.js"), ("curl", "https://x")]:
            self.assertEqual(classifyArgv(argv).classification, ArgvClass.UNKNOWN, argv)


class TestAnalyzeCommand(unittest.TestCase):
    def test_multi_segment_mixed(self):
        a = analyzeCommand("ls /tmp && rm -rf /tmp/x", segmented=True)
        self.assertEqual(len(a.segments), 2)
        self.assertFalse(a.allReadonly)
        self.assertEqual(len(a.destructiveHits), 1)
        self.assertIn("rm", a.destructiveHits[0].text)

    def test_single_readonly(self):
        a = analyzeCommand("ls -la /tmp", segmented=False)
        self.assertTrue(a.allReadonly)
        self.assertFalse(a.destructiveHits)

    def test_empty_command(self):
        a = analyzeCommand("", segmented=False)
        self.assertFalse(a.allReadonly)
        self.assertFalse(a.destructiveHits)


class TestGovernanceGuardedWiring(unittest.TestCase):
    """白名单放行被语法级危险命令降级为 ASK（危险命令审批先于白名单）。"""

    def tearDown(self):
        reset_governance()

    def test_whitelisted_destructive_downgraded_to_ask(self):
        policy = GovernancePolicy(
            ask_on_high=True,
            whitelist_entries=[{"id": "w1", "pattern": "rm", "match_type": "prefix"}],
        )
        result = policy.evaluate("rm -rf /tmp/build", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ASK)
        self.assertTrue(any("危险" in r for r in result.reasons), result.reasons)

    def test_multi_segment_all_hit_but_destructive_downgraded(self):
        policy = GovernancePolicy(
            ask_on_high=True,
            whitelist_entries=[{"id": "w1", "pattern": "rm", "match_type": "prefix"}],
        )
        result = policy.evaluate("rm -rf /tmp/a && rm -rf /tmp/b", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ASK)

    def test_whitelisted_benign_still_allowed(self):
        policy = GovernancePolicy(
            ask_on_high=True,
            whitelist_entries=[{"id": "w1", "pattern": "git status", "match_type": "prefix"}],
        )
        result = policy.evaluate("git status", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ALLOW)

    def test_guarded_gate_can_be_disabled(self):
        policy = GovernancePolicy(
            ask_on_high=True,
            whitelist_entries=[{"id": "w1", "pattern": "rm", "match_type": "prefix"}],
        )
        with patch(
            "neurova.security.governance_settings.resolve_flag", return_value=False
        ):
            result = policy.evaluate("rm -rf /tmp/build", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ALLOW)


class TestReadonlyArgvAutoallow(unittest.TestCase):
    """只读 argv 自动放行：设置项默认关；开也只在内容检测零发现时生效。"""

    def _policy(self):
        return GovernancePolicy(
            ask_on_high=True,
            default_action=GovernanceDecision.ASK,
            whitelist_entries=[],
        )

    def tearDown(self):
        reset_governance()

    def test_default_off_keeps_ask(self):
        result = self._policy().evaluate("ls -la /tmp", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ASK)

    def test_enabled_autoallows_readonly(self):
        policy = self._policy()
        with patch(
            "neurova.security.governance_settings.resolve_flag", return_value=True
        ):
            result = policy.evaluate("ls -la /tmp", tool_name="exec_command")
        self.assertEqual(result.decision, GovernanceDecision.ALLOW)
        self.assertTrue(any("只读" in r for r in result.reasons), result.reasons)

    def test_enabled_never_overrides_content_findings(self):
        policy = self._policy()
        with patch(
            "neurova.security.governance_settings.resolve_flag", return_value=True
        ):
            result = policy.evaluate("cat /etc/shadow", tool_name="exec_command")
        self.assertNotEqual(result.decision, GovernanceDecision.ALLOW)


if __name__ == "__main__":
    unittest.main()
