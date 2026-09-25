# -*- coding: utf-8 -*-
"""T-10a：工具调用展示记录必须携带配对锚点（Issue #90 工单 §11.2/§11.6）。

根因（施工前提，不是"少个字段"）：一条工具调用在落盘时产出两份东西 ——
provider 消息（`{"role","tool_call_id","name","content"}`）与**展示记录**
（`post_chat_pipeline._step_save_session` 把展示记录写进 assistant 消息的
`metadata.tool_calls`）。而会话库里**不存在** `role="tool"` 行，所以读侧要
重建 provider 合法的 `assistant.tool_calls` + `role="tool"` 对，只能从展示
记录取数。

调用侧展示记录此前只有 `{type, tool_name, params, timestamp, task_name?}`：
既没有 `tool_call_id`，也没有模型原始 `arguments`。于是 **id ↔ arguments 的
对应关系在落盘时就丢了** —— 读侧再怎么改都只能把结果降级成文本注记
（工单 §11.2「硬缺口 → 施工顺序」）。本单只补这两个键，零行为变化。

约束（工单 §11.7 第 4 条）：**只增键**。`tool_result` 记录既有键
（`reproducible` / `offload_path` / `success` / `result`）一个不许动。

放大视角（AGENTS.md 教义第 5 条）：同一契约的第二形态 —— 参数解析失败分支
只产 `tool_result`、且那条结果侧连 `tool_call_id` 都没有，配对信息同样丢失。
本文件对两形态都下判据。
"""

import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.tool_executor import ToolExecutor


class _StubSkill:
    """技能替身：只承载执行体（取件契约为 `get_skill`）。"""

    def __init__(self, name, invoke):
        self.name = name
        self.description = "记录身份探针技能"
        self.config = {}
        self._invoke = invoke


class _StubRegistry:
    def __init__(self, name, invoke):
        self._skill = _StubSkill(name, invoke)
        self._invoke = invoke
        self.skills = {name: self._skill}

    def get_skill(self, name):
        return self._skill if name == self._skill.name else None

    def has_skill(self, name):
        return name == self._skill.name

    def list_skills(self):
        return []

    async def execute_skill(self, name, params, context=None):
        return await self._invoke(params)


class _CapturingAgent:
    """记录捕获面：与生产构造面同形的 agent 壳（真 ToolExecutor）。"""

    def __init__(self, tool_name, invoke):
        self.probe_records = []
        self.skill_registry = None
        self._skill_registry = _StubRegistry(tool_name, invoke)
        self.tool_memory = None
        self.tool_lifecycle = None
        self.skill_packer = None
        self.tool_router = None
        self.config = SimpleNamespace(name="probe", user_id="u1", agent_id="a1")
        self.workspace_path = "."
        self._current_user_id = "u1"

    def append_tool_messages(self, records):
        self.probe_records.extend(records)


def _make_loop(invoke):
    agent = _CapturingAgent("probe_read", invoke)
    agent.tool_executor = ToolExecutor(agent)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent
    loop.llm_client = None
    return loop, agent


def _call(call_id, args):
    return {"id": call_id, "function": {"name": "probe_read", "arguments": args}}


def _callRecord(agent):
    return next(r for r in agent.probe_records if r.get("type") == "tool_call")


def _resultRecord(agent):
    return next(r for r in agent.probe_records if r.get("type") == "tool_result")


@pytest.mark.asyncio
async def test_tool_call_record_carries_call_id():
    """调用侧展示记录必须有 `tool_call_id` —— 它是落盘后唯一能重建配对的锚点。"""

    async def _invoke(params):
        return {"ok": True}

    loop, agent = _make_loop(_invoke)
    await loop.handle_tool_calls([_call("tc-anchor-1", json.dumps({"query": "北京"}))], [])

    record = _callRecord(agent)
    assert record.get("tool_call_id") == "tc-anchor-1", (
        f"调用侧记录缺配对锚点，落盘后无法重建 assistant.tool_calls：{sorted(record)}"
    )
    # 结果侧同理：两侧同源才叫配对（token 名不同即协议非法）
    assert _resultRecord(agent).get("tool_call_id") == "tc-anchor-1"


@pytest.mark.asyncio
async def test_tool_call_record_keeps_arguments():
    """调用侧记录必须有模型**原始** `arguments`（id ↔ arguments 的对应关系）。

    与 `params` 的分工：`params` 是剥离 taskName* 后的执行参数（执行面契约），
    `arguments` 是模型原样传入的串（协议面契约，重建 provider 消息用）。
    """

    async def _invoke(params):
        return {"ok": True}

    raw = json.dumps({"query": "北京", "taskNameActive": "查询中"}, ensure_ascii=False)
    loop, agent = _make_loop(_invoke)
    await loop.handle_tool_calls([_call("tc-args-1", raw)], [])

    record = _callRecord(agent)
    assert "arguments" in record, (
        f"调用侧记录缺模型原始 arguments，读侧无从重建协议消息：{sorted(record)}"
    )
    assert json.loads(record["arguments"])["taskNameActive"] == "查询中", (
        "arguments 必须是模型原样传入的串（含注入的展示参数），不是剥离后的执行参数"
    )
    # 既有契约不破：执行面参数仍不含 taskName*
    assert "taskNameActive" not in record["params"]
    assert record["params"] == {"query": "北京"}


@pytest.mark.asyncio
async def test_arguments_are_model_original_when_provider_passes_dict():
    """provider 直接给 dict 参数时，`arguments` 仍必须是**模型原样**。

    执行面会剥离 taskName*（展示参数不进执行），但 `arguments` 是模型原始载荷，
    剥离不得污染它 —— 两者共用同一个 dict 对象时会互相顶掉。
    """

    async def _invoke(params):
        return {"ok": True}

    loop, agent = _make_loop(_invoke)
    raw = {"query": "北京", "taskNameActive": "查询中"}
    call = {"id": "tc-dict-1", "function": {"name": "probe_read", "arguments": raw}}
    await loop.handle_tool_calls([call], [])

    record = _callRecord(agent)
    assert json.loads(record["arguments"])["taskNameActive"] == "查询中", (
        f"dict 形态下 arguments 被执行面的剥离污染：{record['arguments']}"
    )
    assert record["params"] == {"query": "北京"}
    assert raw.get("taskNameActive") == "查询中", "不得就地改写模型传来的原始载荷对象"


@pytest.mark.asyncio
async def test_parse_failure_result_keeps_call_id():
    """参数解析失败分支：结果侧同样带 `tool_call_id`（同契约第二形态）。"""

    async def _invoke(params):
        return {"ok": True}

    loop, agent = _make_loop(_invoke)
    await loop.handle_tool_calls([_call("tc-bad-1", "{invalid json")], [])

    record = _resultRecord(agent)
    assert record.get("tool_call_id") == "tc-bad-1", (
        f"解析失败分支的结果侧缺 call_id，该工具轮在台账里成为孤儿：{sorted(record)}"
    )
    assert record.get("success") is False


@pytest.mark.asyncio
async def test_existing_result_keys_unchanged():
    """只增键：`tool_result` 既有键一个不许少（工单 §11.7 第 4 条）。"""

    async def _invoke(params):
        return {"ok": True}

    loop, agent = _make_loop(_invoke)
    await loop.handle_tool_calls([_call("tc-keep-1", json.dumps({"query": "x"}))], [])

    record = _resultRecord(agent)
    for key in ("tool_name", "result", "success", "timestamp", "reproducible", "offload_path"):
        assert key in record, f"tool_result 既有键被改动：缺 {key}（键={sorted(record)}）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
