# -*- coding: utf-8 -*-
"""T-10a：调用侧展示记录必须携带 `tool_call_id`（工单 §11.2 硬缺口）。

背景（Issue #90 工单 §11.2 数据契约）：结果侧记录有 `tool_call_id`，调用侧
**没有**。落盘走的是展示记录（`post_chat_pipeline` 把 `_collect_tool_messages()`
写进 assistant 的 `metadata.tool_calls`），所以配对信息**在落盘那一刻就丢了**：
从库里读到的 `metadata.tool_calls` 无法重建 `assistant.tool_calls`（id ↔
arguments 的对应关系不在库里），T-10b 的读侧重建因此没有数据可依。

本文件同时钉住两件事（工单 §11.7 第 4 条「只增键」的反向锁）：

1. 红：调用侧记录缺 `tool_call_id`、缺协议原文形态的 `arguments`；
2. 反向锁：补键**不得改动**结果侧既有键（`reproducible` / `offload_path`
   是 `_recall_by_call_id` 与产物卡片注册的依赖）。

断言取真值来源：`arguments` 必须等于**模型给出的原文串**（逐字节），
不是从 `params` 反序列化重排出来的赝品 —— 重建的 `assistant.tool_calls` 要
与 provider 回传形态对齐，重排键序即对不上。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.tool_executor import ToolExecutor

pytestmark = pytest.mark.asyncio

# 模型原文：含 `taskNameActive`（执行层会剥离出执行面）与多键，键序刻意非字典序，
# 以便"原文串"与"按 params 重排的串"可区分。
_MODEL_ARGUMENTS = '{"query": "北京天气", "limit": 3, "taskNameActive": "查天气"}'
_EXPECTED_PARAMS = {"query": "北京天气", "limit": 3}


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "T-10a 探针技能"
        self.config = {"reproducible": True}


class _StubRegistry:
    def __init__(self, name, execute):
        self._skill = _StubSkill(name)
        self.skills = {name: self._skill}
        self._execute = execute

    def get_skill(self, skill_name):
        return self._skill if skill_name == self._skill.name else None

    def has_skill(self, skill_name):
        return skill_name == self._skill.name

    def list_skills(self):
        return []

    async def execute_skill(self, skill_name, params, context=None):
        return await self._execute(params)


class _CapturingAgent:
    """捕获 `append_tool_messages` 的替身 agent（执行面用真 ToolExecutor）。"""

    def __init__(self, name, execute, workspace_path):
        self._records = []
        self.dispatched_params = None
        self.skill_registry = None
        self._skill_registry = _StubRegistry(name, self._capture(execute))
        self.tool_memory = None
        self.tool_lifecycle = None
        self.skill_packer = None
        self.config = SimpleNamespace(name="probe", user_id="u1", agent_id="a1")
        self.tool_router = None
        self.workspace_path = str(workspace_path)
        self._current_user_id = "u1"

    def _capture(self, execute):
        async def _run(params):
            self.dispatched_params = dict(params or {})
            return await execute(params)
        return _run

    def append_tool_messages(self, records):
        self._records.extend(records)

    @property
    def tool_messages(self):
        return self._records


def _make_loop(tool_name, execute, tmp_path):
    agent = _CapturingAgent(tool_name, execute, tmp_path)
    agent.tool_executor = ToolExecutor(agent)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent
    loop.llm_client = None
    return loop, agent


async def _run_once(tmp_path, tool_name="t10a_probe_tool", call_id="call_t10a_1"):
    async def _execute(params):
        return {"weather": "晴", "echo": params}

    loop, agent = _make_loop(tool_name, _execute, tmp_path)
    await loop.handle_tool_calls(
        [{"id": call_id, "function": {"name": tool_name, "arguments": _MODEL_ARGUMENTS}}], []
    )
    call_rec = next(r for r in agent.tool_messages if r.get("type") == "tool_call")
    result_rec = next(r for r in agent.tool_messages if r.get("type") == "tool_result")
    return agent, call_rec, result_rec


class TestCallRecordCarriesAddressing:
    async def test_tool_call_record_carries_call_id(self, tmp_path):
        """调用侧记录必须带 `tool_call_id`，与结果侧同值（配对键的唯一来源）。"""
        agent, call_rec, result_rec = await _run_once(tmp_path)
        assert call_rec.get("tool_call_id") == "call_t10a_1", (
            f"调用侧记录丢了硬地址（工单 §11.2 硬缺口）：键={sorted(call_rec)}"
        )
        assert call_rec["tool_call_id"] == result_rec["tool_call_id"], (
            "调用侧与结果侧 call_id 必须同源同值，否则配对重建会错配"
        )

    async def test_tool_call_record_keeps_arguments(self, tmp_path):
        """调用侧记录必须带协议原文形态的 `arguments`（JSON 字符串，逐字节）。"""
        agent, call_rec, _ = await _run_once(tmp_path)
        assert "arguments" in call_rec, (
            f"调用侧记录缺 `arguments`（重建 assistant.tool_calls 无原文可用）：键={sorted(call_rec)}"
        )
        assert call_rec["arguments"] == _MODEL_ARGUMENTS, (
            "`arguments` 必须是模型给出的协议原文串（逐字节），"
            f"不是按 params 重排的赝品：实得={call_rec.get('arguments')!r}"
        )
        # 语义咬合：原文剥掉 taskName* 后必须与真正下发给执行面的参数一致
        raw = json.loads(call_rec["arguments"])
        stripped = {k: v for k, v in raw.items() if k not in ("taskNameActive", "taskNameComplete")}
        assert stripped == _EXPECTED_PARAMS
        # 执行咽喉会在参数上再补自己的归属字段（`_caller_user_id` 等）；
        # 判据取"模型给的键值逐一对得上"，不把咽喉补的字段当成记录失真。
        assert _EXPECTED_PARAMS.items() <= (agent.dispatched_params or {}).items(), (
            f"执行面收到的参数与记录里的原文对不上：{agent.dispatched_params}"
        )


class TestResultRecordKeysUnchanged:
    """工单 §11.7 第 4 条反向锁：`tool_result` 既有键一个都不许动。"""

    async def test_result_record_keeps_reproducible_and_offload_path(self, tmp_path):
        _, _, result_rec = await _run_once(tmp_path)
        assert "reproducible" in result_rec, "`reproducible` 是产物卡片注册的依赖，不得移除"
        assert "offload_path" in result_rec, "`offload_path` 是 _recall_by_call_id 的全文指针，不得移除"
        assert result_rec["reproducible"] is True

    async def test_call_record_keeps_existing_keys(self, tmp_path):
        """补键不得挤掉既有键：`params` / `tool_name` / `timestamp` 仍在。"""
        _, call_rec, _ = await _run_once(tmp_path)
        for key in ("params", "tool_name", "timestamp", "type"):
            assert key in call_rec, f"补 `tool_call_id` 时挤掉了既有键 {key!r}：{sorted(call_rec)}"
        assert call_rec["params"] == _EXPECTED_PARAMS, "params 仍是剥离 taskName* 后的执行面真值"


class TestOutboundGateCoversArguments:
    """放大视角（教义第 5 条）：新增 `arguments` 必须与 `params` 同受出口脱敏。

    同一份"调用参数"如今有两个出口形态——`params`（解析后的 dict）与
    `arguments`（协议原文串）。出口脱敏（`redact_tool_messages_for_channel`）
    只认 `params`，新字段就成了一条绕过脱敏的旁路：调用原文里的
    `password`/`token` 会以明文进渠道/WS 广播。补键不补脱敏 = 新开一个泄露面。
    """

    def test_sensitive_arguments_are_redacted(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        rec = {
            "type": "tool_call",
            "tool_name": "login",
            "params": {"password": "hunter2secret", "url": "https://x"},
            "arguments": json.dumps({"password": "hunter2secret", "url": "https://x"}),
            "tool_call_id": "c1",
        }
        out = redact_tool_messages_for_channel([rec])[0]
        blob = json.dumps(out)
        assert "hunter2secret" not in blob, f"`arguments` 绕过了出口脱敏：{blob}"
        assert json.loads(out["arguments"])["url"] == "https://x", "非敏感键不得被误伤"

    def test_private_visibility_drops_arguments(self):
        from neurova.security.privacy_gate import redact_tool_messages_for_channel

        rec = {
            "type": "tool_call",
            "tool_name": "computer_shell",
            "visibility": "private",
            "params": {"command": "ls"},
            "arguments": json.dumps({"command": "ls", "token": "sk-leak"}),
        }
        out = redact_tool_messages_for_channel([rec])[0]
        assert "arguments" not in out, f"private 事件必须整体丢调用原文：{sorted(out)}"
        assert "sk-leak" not in json.dumps(out)
