# -*- coding: utf-8 -*-
"""tool_result 记录条目增强：call_id/reproducible 证据/offload 指针（P1 #6 触点2）。

定稿（对比报告 §5.6）：会话 metadata.tool_calls 即全文台账，条目必须携带
硬地址之 call_id + 落盘时生效的 reproducible 证据（防工具改标/删除后
语义漂移）+ 溢出时的 offload_path。经 LoopBase.handle_tool_calls 真实
执行路径测试（records 经 agent.append_tool_messages 捕获）。

工单 003 之后原生链走执行咽喉：工具必须真是"该 agent 注册过的技能"，
故此处注册一条声明 `reproducible` 的 stub 技能，让咽喉一路走到技能执行体
（替身放在技能执行体这一层，不冒充执行链）。
"""
import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.tool_executor import ToolExecutor

pytestmark = pytest.mark.asyncio


class _StubSkill:
    """技能替身：只承载 `config.reproducible` 与描述（取件契约为 `get_skill`）。"""

    def __init__(self, name, reproducible):
        self.name = name
        self.description = "offload 探针技能"
        self.config = {"reproducible": reproducible}


class _StubRegistry:
    """技能注册表替身：`get_skill` / `has_skill` / `execute_skill` 三契约。"""

    def __init__(self, name, reproducible, execute):
        self._skill = _StubSkill(name, reproducible)
        self.skills = {name: self._skill}
        self._execute = execute

    def get_skill(self, skill_name):
        return self._skill if skill_name == self._skill.name else None

    def has_skill(self, skill_name):
        return skill_name == self._skill.name

    def list_skills(self):
        return []

    async def execute_skill(self, skill_name, params, context=None):
        return await self._execute()


class _CapturingAgent:
    def __init__(self, tool_name, reproducible, execute, workspace_path):
        self._records = []
        self.skill_registry = None
        self._skill_registry = _StubRegistry(tool_name, reproducible, execute)
        self.tool_memory = None
        self.tool_lifecycle = None
        self.skill_packer = None
        self.config = SimpleNamespace(name="probe", user_id="u1", agent_id="a1")
        self.tool_router = None
        self.workspace_path = str(workspace_path)
        self._current_user_id = "u1"

    def append_tool_messages(self, records):
        self._records.extend(records)

    @property
    def tool_messages(self):
        return self._records


def _make_loop(tool_name, reproducible, execute, tmp_path):
    agent = _CapturingAgent(tool_name, reproducible, execute, tmp_path)
    # 原生链经执行咽喉（工单 003）：真执行器 + 技能执行体替身
    agent.tool_executor = ToolExecutor(agent)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent
    loop.llm_client = None
    return loop, agent


async def test_record_carries_call_id_reproducible_and_offload(tmp_path, monkeypatch):
    """大结果可重现工具 → 记录含 call_id/reproducible=True/offload_path；
    窗口 tool 消息 content 为预览+指针（全文在文件，一条不丢）。"""
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "8")
    big = "x" * 40000  # 40KB > 8KB 阈值

    async def _execute():
        return {"content": big}

    loop, agent = _make_loop("big_reader", True, _execute, tmp_path)
    tool_msgs = await loop.handle_tool_calls(
        [{"id": "tc-123", "function": {"name": "big_reader", "arguments": "{}"}}], []
    )
    rec = next(r for r in agent.tool_messages if r.get("type") == "tool_result")
    assert rec["tool_call_id"] == "tc-123"
    assert rec["reproducible"] is True
    assert rec.get("offload_path"), "超阈值可重现结果必须落文件留指针"
    assert len(rec["result"]) < len(big)  # 记录也拿预览（文件是全文真相）

    win = tool_msgs[0]
    assert win["role"] == "tool" and win["tool_call_id"] == "tc-123"
    assert len(win["content"]) < len(big)

    from pathlib import Path

    p = Path(rec["offload_path"])
    if not p.is_absolute():
        p = tmp_path / rec["offload_path"]
    assert big in p.read_text(encoding="utf-8")


async def test_record_non_reproducible_offloads_with_head_tail(tmp_path, monkeypatch):
    """run_code 大输出（P0-4 契约变更）：落盘保全全文 + head+tail+截断标注。

    原"不可重现豁免全文直进窗口"会在窗口折叠中整段丢失；现在落盘文件是
    全文真相，消息体保留首尾+指针，reproducible 元数据仍如实记录 False。
    """
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "8")
    big = "y" * 40000

    async def _execute():
        return {"stdout": big}

    loop, agent = _make_loop("code_runner", False, _execute, tmp_path)
    tool_msgs = await loop.handle_tool_calls(
        [{"id": "tc-888", "function": {"name": "code_runner", "arguments": "{}"}}], []
    )
    rec = next(r for r in agent.tool_messages if r.get("type") == "tool_result")
    assert rec["reproducible"] is False
    assert rec.get("offload_path")  # 全文落盘保全
    from pathlib import Path

    p = Path(rec["offload_path"])
    if not p.is_absolute():
        p = tmp_path / rec["offload_path"]
    full = p.read_text(encoding="utf-8")
    assert big in full  # 全文（JSON 包装串内）一条不丢
    assert "截断" in str(rec["result"])
    assert big not in str(rec["result"])  # 消息体不再是全文（head+tail）


async def test_small_result_no_offload(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB", "64")

    async def _execute():
        return {"ok": True}

    loop, agent = _make_loop("small_reader", True, _execute, tmp_path)
    await loop.handle_tool_calls(
        [{"id": "tc-s", "function": {"name": "small_reader", "arguments": "{}"}}], []
    )
    rec = next(r for r in agent.tool_messages if r.get("type") == "tool_result")
    assert rec["reproducible"] is True
    assert rec.get("offload_path") is None
