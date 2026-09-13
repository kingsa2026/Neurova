# -*- coding: utf-8 -*-
"""microcompact 占位寻址化 + recall_history 直取模式（P1 #6 触点4）。

定稿（§5.6）：占位串携带 tool/call/ts 硬地址，recall_history 从"猜子串"
升级为"按指针直取"（call_id 匹配会话 tool_calls 条目；溢出条目顺
offload_path 读回全文）；原子串 FTS 召回保留为兜底。
"""
from types import SimpleNamespace

import pytest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.tool_executor import ToolExecutor

pytestmark = pytest.mark.asyncio


# ── 占位寻址化 ────────────────────────────────────────────────────

def _tool_msg(i, call_id, name, content):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def test_microcompact_placeholder_is_addressable(tmp_path):
    orch = ContextOrchestrator(None, use_pool=False, auto_tag=False, session_id="s1")
    msgs = [
        _tool_msg(0, "call_a1", "file_read", "这是工具输出的正文内容 mixed english words 数字 1234567890。" * 700),
        _tool_msg(1, "call_b2", "web_fetch", "这是工具输出的正文内容 mixed english words 数字 1234567890。" * 700),
        _tool_msg(2, "call_c3", "file_read", "这是工具输出的正文内容 mixed english words 数字 1234567890。" * 700),
        _tool_msg(3, "call_d4", "web_search", "这是工具输出的正文内容 mixed english words 数字 1234567890。" * 700),
        _tool_msg(4, "call_e5", "file_read", "这是工具输出的正文内容 mixed english words 数字 1234567890。" * 700),
    ]
    cleared = orch._clear_old_tool_results(msgs)
    assert cleared[0]["content"] != msgs[0]["content"], "token>8k 且超出保留窗必须占位"
    ph = cleared[0]["content"]
    assert "call_a1" in ph and "file_read" in ph, f"占位必须携带硬地址: {ph}"
    # 最近 3 条保留原文
    for i in (2, 3, 4):
        assert cleared[i]["content"] == msgs[i]["content"]


def test_microcompact_missing_call_id_degrades_not_crash(tmp_path):
    """旧数据/合成条目无 tool_call_id → 占位降级含 name 即可，不抛。"""
    orch = ContextOrchestrator(None, use_pool=False, auto_tag=False, session_id="s1")
    msgs = [{"role": "tool", "name": "file_read", "content": "段落正文 paragraph body 1234567890 " * 700} for _ in range(5)]
    cleared = orch._clear_old_tool_results(msgs)
    assert "file_read" in cleared[0]["content"]


# ── recall_history 直取模式 ───────────────────────────────────────

class _FakeSessionRepo:
    def __init__(self, messages):
        self._m = messages

    def get_history(self, agent_id="", session_id=""):
        return self._m


def _agent_with_history(offload_dir=None):
    """构造带 assistant metadata.tool_calls 的会话历史 + agent 壳。"""
    from pathlib import Path

    tool_calls = [
        {
            "type": "tool_result",
            "tool_name": "file_read",
            "tool_call_id": "call_x9",
            "reproducible": True,
            "result": "[预览: 已溢出至文件]",
            "offload_path": "outputs/tool_offload/big.txt",
            "timestamp": "2026-09-13T08:12:03",
        },
        {
            "type": "tool_result",
            "tool_name": "web_fetch",
            "tool_call_id": "call_y8",
            "reproducible": True,
            "result": "INLINE-FULL-TEXT",
            "offload_path": None,
            "timestamp": "2026-09-13T08:13:00",
        },
    ]
    history = [
        {"role": "user", "content": "read the file"},
        {"role": "assistant", "content": "done", "metadata": {"tool_calls": tool_calls}},
    ]
    ws = Path(offload_dir) if offload_dir else Path("data")
    agent = SimpleNamespace(
        current_session_id="s-direct-1",
        workspace_path=str(ws),
    )
    return agent, history


async def test_recall_history_direct_by_call_id(tmp_path):
    """call_id 直取：命中溢出条目 → 顺 offload_path 读回全文。"""
    agent, history = _agent_with_history(offload_dir=tmp_path)
    (tmp_path / "outputs" / "tool_offload").mkdir(parents=True)
    (tmp_path / "outputs" / "tool_offload" / "big.txt").write_text("FULL-OFFLOADED-TEXT" * 10, encoding="utf-8")

    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = agent
    # 直取实现挂 session 历史注入点（测试注入 repo）
    agent.session_repo = _FakeSessionRepo(history)
    out = await ex._execute_recall_history({"session_id": "s-direct-1", "tool_call_id": "call_x9"})
    assert "FULL-OFFLOADED-TEXT" in str(out)


async def test_recall_history_direct_inline_entry(tmp_path):
    agent, history = _agent_with_history()
    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = agent
    agent.session_repo = _FakeSessionRepo(history)
    out = await ex._execute_recall_history({"session_id": "s-direct-1", "tool_call_id": "call_y8"})
    assert "INLINE-FULL-TEXT" in str(out)


async def test_recall_history_direct_miss_is_honest(tmp_path):
    agent, history = _agent_with_history()
    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = agent
    agent.session_repo = _FakeSessionRepo(history)
    out = await ex._execute_recall_history({"session_id": "s-direct-1", "tool_call_id": "call_nope"})
    assert isinstance(out, dict) and out.get("error"), "指针未命中必须如实报错，不得伪装为空结果"


async def test_recall_history_file_gone_reports_preview(tmp_path):
    """溢出文件已被清理：直取失败但返回预览+指针，告知不可重读原因。"""
    agent, history = _agent_with_history(offload_dir=tmp_path)
    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = agent
    agent.session_repo = _FakeSessionRepo(history)
    out = await ex._execute_recall_history({"session_id": "s-direct-1", "tool_call_id": "call_x9"})
    s = str(out)
    assert "预览" in s or "preview" in s.lower()
    assert "不存在" in s or "missing" in s.lower()
