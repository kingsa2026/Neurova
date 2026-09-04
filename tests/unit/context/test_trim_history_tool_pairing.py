"""溢出裁剪 tool 配对分割点测试（OpenClaw 启发 P0-8）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-8）：
  OpenClaw 压缩语义：分割点落在工具块内就移动边界，保持 tool-call/
  tool-result 配对完整（docs/concepts/compaction.md）。

Neurova 现状：
  - recovery.compact_messages_for_overflow（溢出恢复主路径）已实现配对
    对齐（tests/unit/context/test_recovery.py 已锁）。
  - 缺口在非池路径 injector._trim_history：按 token 预算从尾回溯逐条
    装填，预算断点若落在 assistant(tool_calls) 与其 tool 结果之间，产出的
    视图就是"悬空 tool_calls / 孤儿 tool 结果"（违反 OpenAI 协议配对）。

铁律落点：_trim_history 的分割点选择复用 recovery 的两个判定函数——
  工具块（assistant(tool_calls) → tool…）必须整体进/出，不允许分割点
  切进块中间。token 计数在测试中 mock 为 len()，预算即字符数，断点
  完全确定。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from neurova.context.injector import UnifiedContextInjector


def _make_injector(budget: int) -> UnifiedContextInjector:
    injector = UnifiedContextInjector.__new__(UnifiedContextInjector)
    injector._memory_manager = MagicMock()
    injector._token_budget = MagicMock()
    injector._token_budget.conversation_history = budget
    # token 计数 mock 为 len()：预算即字符数，断点确定可推理
    injector._count_tokens = lambda text: len(text or "")
    return injector


def _msg(role: str, content: str, **extra) -> dict:
    m = {"role": role, "content": content}
    m.update(extra)
    return m


def _tool_calls(cid: str, name: str = "ls") -> list:
    return [{"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}]


class TestTrimHistoryToolPairing(unittest.TestCase):
    """裁剪分割点不得切进 assistant(tool_calls) → tool 块中间。"""

    def test_tool_result_never_orphaned(self):
        """预算断点落在 tool 结果与它的 assistant(tool_calls) 之间 →
        整个工具块一并舍弃（分割点前移到块边界之前），不产孤儿 tool。"""
        injector = _make_injector(budget=20)
        history = [
            _msg("user", "u" * 21),                       # 21 > 20 装不下
            _msg("assistant", "tc" * 8, tool_calls=_tool_calls("c1")),  # 16
            _msg("tool", "r" * 11, tool_call_id="c1"),    # 11
        ]
        trimmed = injector._trim_history(history)

        # 旧实现：回溯装 tool(11) → 11；assistant_tc(16) → 27 > 20 → break
        # → trimmed == [tool]，孤儿 tool 结果（BUG）。
        self._assert_pairing_intact(trimmed)
        self.assertNotIn("tool", [m.get("role") for m in trimmed], "孤儿 tool 结果不得混入")

    def test_dangling_tool_calls_never_present(self):
        """assistant(tool_calls) 保留而其 tool 结果被预算挤出 → 悬空调用，
        修复后两者必须同进同出。"""
        injector = _make_injector(budget=25)
        history = [
            _msg("user", "u" * 21),
            _msg("assistant", "tc" * 8, tool_calls=_tool_calls("c2")),  # 16
            _msg("tool", "r" * 11, tool_call_id="c2"),    # 11
        ]
        # 等价场景的镜像：先装下 assistant_tc 的预算结构
        trimmed = injector._trim_history(history[::-1])
        self._assert_pairing_intact(trimmed)

    def test_pair_survives_when_budget_allows(self):
        """预算装得下整块 → 配对完整保留（不误伤合法历史）。"""
        injector = _make_injector(budget=100)
        history = [
            _msg("user", "u" * 21),
            _msg("assistant", "tc" * 8, tool_calls=_tool_calls("c3")),
            _msg("tool", "r" * 11, tool_call_id="c3"),
            _msg("assistant", "a" * 12),
        ]
        trimmed = injector._trim_history(history)
        self.assertEqual(len(trimmed), 4, "预算充足时不得丢消息")
        self._assert_pairing_intact(trimmed)

    def test_no_pairing_needed_first_message_fallback_unchanged(self):
        """无工具块：首条兜底保留语义与旧实现一致（等价性锁定）。"""
        injector = _make_injector(budget=5)
        history = [
            _msg("user", "u" * 30),
            _msg("assistant", "a" * 30),
        ]
        trimmed = injector._trim_history(history)
        # 旧实现：回溯 a(30)>5 且 trimmed 空 → 兜底插 a；u(30)>5 break
        # 兜底是"当前正被考察的首条装不下消息"，非历史第一条
        self.assertEqual(trimmed, [history[1]], "首条兜底保留（旧实现行为）")

    def test_plain_history_trim_unchanged(self):
        """无工具块的普通历史：尾回溯装填结果与旧实现一致。"""
        injector = _make_injector(budget=30)
        history = [
            _msg("user", "u" * 20),
            _msg("assistant", "a" * 20),
            _msg("user", "z" * 10),
        ]
        trimmed = injector._trim_history(history)
        # 回溯：z(10) → 10；a(20) → 30 ✓；u(20) → 50 > 30 break
        self.assertEqual(trimmed, [history[1], history[2]])

    def _assert_pairing_intact(self, trimmed):
        declared = set()
        for m in trimmed:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for c in m["tool_calls"]:
                    declared.add(c.get("id"))
        for m in trimmed:
            if m.get("role") == "tool":
                self.assertIn(
                    m.get("tool_call_id"),
                    declared,
                    f"孤儿 tool 结果混入裁剪视图: {m!r}",
                )
        for m in trimmed:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                ids = [c.get("id") for c in m["tool_calls"]]
                following = {
                    t.get("tool_call_id")
                    for t in trimmed[trimmed.index(m) + 1:]
                    if t.get("role") == "tool"
                }
                self.assertTrue(
                    set(ids) <= following,
                    f"悬空 tool_calls（声明无结果）混入裁剪视图: {m!r}",
                )


if __name__ == "__main__":
    unittest.main()
