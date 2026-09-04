"""tool-call-repair 文本工具调用修复测试（OpenClaw 启发 P0-3）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-3）：
  OpenClaw 的 packages/tool-call-repair 把模型以纯文本"漏出"的工具调用
  流内扫描修复为结构化 ToolCall，保护 code fence 内用户原文，专救
  Ollama/vLLM 类弱端点。三形态文法（grammar.ts）：
    1. XML-ish：<function name="ls">{"path": "."}</function>（命名空间点号容忍）
    2. Harmony：<|channel|>…<|message|>{"path": "."}<|call|>（gpt-oss 系）
    3. 尾标：{"name": "ls", "arguments": {...}}[END_TOOL_REQUEST]
  Neurova 的 _execute_from_text 只认 [TOOL_CALL:name(args)] 一种格式，
  本地小模型（Ollama/vLLM）的文本工具调用会全部漏执行。

落点：tool_executor._execute_from_text 解析入口加一层流内提升器
  （repaired_tool_calls），四种格式统一解析；code fence 内的内容
  不误伤；解析出的调用走既有 _execute_single_tool 执行链。
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from neurova.tool_executor import ToolExecutor


def _executor() -> ToolExecutor:
    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = MagicMock()
    ex._agent._tool_messages_list = []
    ex._execute_single_tool = AsyncMock(return_value={"ok": True})
    return ex


class TestRepairedToolCallsParsing(unittest.TestCase):
    """三形态文法解析（不含既有 [TOOL_CALL:] 格式——已有测试锁定）。"""

    def _parse(self, reply):
        ex = _executor()
        calls = ex._extract_repaired_tool_calls(reply)
        return [(c["name"], c["arguments"]) for c in calls]

    def test_xmlish_function_tag(self):
        reply = '我来查看目录。\n<function name="list_dir">{"path": "."}</function>'
        calls = self._parse(reply)
        self.assertEqual(calls, [("list_dir", {"path": "."})])

    def test_xmlish_namespace_dots_tolerated(self):
        """XML-ish 名称允许命名空间标点（OC isXmlishNameChar）。"""
        reply = '<function name="filesystem.list_dir">{"path": "."}</function>'
        calls = self._parse(reply)
        self.assertEqual(calls, [("filesystem.list_dir", {"path": "."})])

    def test_harmony_channel_markers(self):
        """Harmony 流标记（gpt-oss <|channel|>…<|message|>…<|call|>）。"""
        reply = '<|channel|>commentary<|message|>{"name": "list_dir", "arguments": {"path": "."}}<|call|>'
        calls = self._parse(reply)
        self.assertEqual(calls, [("list_dir", {"path": "."})])

    def test_end_tool_request_trailer(self):
        """JSON 对象 + [END_TOOL_REQUEST] 尾标。"""
        reply = '{"name": "list_dir", "arguments": {"path": "."}}[END_TOOL_REQUEST]'
        calls = self._parse(reply)
        self.assertEqual(calls, [("list_dir", {"path": "."})])

    def test_code_fence_protected(self):
        """code fence 内的示例文本不得被误提为工具调用。"""
        reply = '用法示例：\n```\n<function name="list_dir">{"path": "."}</function>\n```\n'
        self.assertEqual(self._parse(reply), [])

    def test_plain_json_without_marker_not_promoted(self):
        """无任何标记的裸 JSON 不得误提（避免把用户代码/数据当调用）。"""
        reply = '返回结果：{"name": "list_dir", "arguments": {}}'
        self.assertEqual(self._parse(reply), [])

    def test_invalid_arguments_json_skipped(self):
        """arguments 非 JSON 的候选跳过（宁漏勿错，不猜语义）。"""
        reply = '<function name="list_dir">不是JSON</function>'
        self.assertEqual(self._parse(reply), [])

    def test_multiple_calls_and_mixed_formats(self):
        reply = (
            '<function name="a">{"x": 1}</function>\n'
            '{"name": "b", "arguments": {"y": 2}}[END_TOOL_REQUEST]'
        )
        calls = self._parse(reply)
        self.assertEqual(calls, [("a", {"x": 1}), ("b", {"y": 2})])

    def test_legacy_format_still_works(self):
        """既有 [TOOL_CALL:] 格式不受影响（等价性锁定）。"""
        ex = _executor()
        out = asyncio.run(ex._execute_from_text('前文 [TOOL_CALL:ping({"n": 1})] 后文', ""))
        ex._execute_single_tool.assert_called_once_with("ping", {"n": 1})
        self.assertIn("ping 结果", out)


class TestRepairedToolCallsExecution(unittest.TestCase):
    """修复出的调用走既有执行链（_execute_single_tool），结果入 _tool_messages_list。"""

    def test_execute_from_text_promotes_repaired_calls(self):
        ex = _executor()
        reply = '<function name="list_dir">{"path": "."}</function>'
        out = asyncio.run(ex._execute_from_text(reply, ""))

        ex._execute_single_tool.assert_awaited_once_with("list_dir", {"path": "."})
        self.assertIn("list_dir 结果", out)
        self.assertEqual(len(ex._agent._tool_messages_list), 1)
        msg = ex._agent._tool_messages_list[0]
        self.assertEqual(msg["name"], "list_dir")
        self.assertEqual(msg["role"], "tool")

    def test_no_calls_returns_reply_unchanged(self):
        ex = _executor()
        out = asyncio.run(ex._execute_from_text("普通回复，无工具调用", ""))
        ex._execute_single_tool.assert_not_awaited()
        self.assertEqual(out, "普通回复，无工具调用")


if __name__ == "__main__":
    unittest.main()
