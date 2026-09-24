# -*- coding: utf-8 -*-
"""T-10a：工具展示记录必须把配对信息带得回来（Issue #90 工单 §11.2 / §11.7）。

缺口（实测，真构造面）：调用侧记录只有 `{type,tool_name,params,timestamp}`，
**没有 `tool_call_id`、也没有协议原文形态的 `arguments`**。而
`post_chat_pipeline._step_save_session` 落进会话 `metadata.tool_calls` 的正是这批
展示记录 —— 于是"哪次调用 ↔ 哪个 id ↔ 哪段 arguments"的对应关系在落盘那一刻
就丢了，读侧再想重建 `assistant.tool_calls` 只能靠猜（§11.2 的硬缺口）。同一契约
的第二处命中点：参数解析失败分支的结果记录连 `tool_call_id` 都没有，
结果侧因此不可寻址。

判据边界（§11.7 第 4 条）：本票**只增键**，`tool_result` 记录的既有键
（`reproducible` / `offload_path` 等）一个都不许动、不许改语义。
"""

from types import SimpleNamespace

import pytest

from neurova.agent.loops.base import BaseAgentLoop
from neurova.tool_executor import ToolExecutor

PROVIDER_ID = "call_provider_0001"
# 原文字符串刻意带空格：provider 回传形态必须逐字节留住，
# 重新序列化（json.dumps）会改写空白，"逐字节对齐"就无从谈起。
RAW_ARGUMENTS = '{"query": "北京 天气", "taskNameActive": "查天气"}'


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "T-10a 配对探针技能"
        self.config = {}


class _StubSkillRegistry:
    """技能注册表替身：只承载取件与执行体（执行链走真咽喉）。"""

    def __init__(self, name, execute):
        self._skill = _StubSkill(name)
        self.skills = {name: self._skill}
        self.execute_skill = execute

    def get_skill(self, skill_name):
        return self._skill if skill_name == self._skill.name else None

    def has_skill(self, skill_name):
        return skill_name == self._skill.name

    def list_skills(self):
        return []


def _make_loop(execute):
    """生产构造点：真 `ToolExecutor`（唯一执行咽喉）+ 技能面替身。"""

    class _StubLoop(BaseAgentLoop):
        async def predict_step(self, messages, tools=None, **kwargs):  # pragma: no cover
            return None

    agent = SimpleNamespace(
        skill_registry=None,
        _skill_registry=_StubSkillRegistry("probe_read", execute),
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        tool_router=None,
        append_tool_messages=lambda records: None,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id="a1"),
        workspace_path=".",
    )
    agent.tool_executor = ToolExecutor(agent)
    loop = _StubLoop.__new__(_StubLoop)
    loop.agent = agent
    return loop


def _records(by_type, records):
    return [r for r in records if r.get("type") == by_type]


class TestCallRecordCarriesPairing:
    @pytest.mark.asyncio
    async def test_tool_call_record_carries_call_id(self):
        """调用侧记录必须带 provider 的 `tool_call_id`，且与结果侧一致。"""

        async def _execute():
            return {"ok": True}

        loop = _make_loop(_execute)
        _, records = await loop._execute_tool_call_worker(
            {"id": PROVIDER_ID, "function": {"name": "probe_read", "arguments": RAW_ARGUMENTS}}
        )

        call_rec = _records("tool_call", records)[0]
        result_rec = _records("tool_result", records)[0]
        assert call_rec.get("tool_call_id") == PROVIDER_ID, (
            "调用侧记录没带 tool_call_id —— 配对信息在落盘那一刻就丢了，"
            f"读侧无从重建（键={sorted(call_rec)}）"
        )
        assert result_rec["tool_call_id"] == call_rec["tool_call_id"]

    @pytest.mark.asyncio
    async def test_tool_call_record_keeps_arguments(self):
        """调用侧必须留住协议原文形态的 `arguments`（与 `params` 分工不同）。"""

        async def _execute():
            return {"ok": True}

        loop = _make_loop(_execute)
        _, records = await loop._execute_tool_call_worker(
            {"id": PROVIDER_ID, "function": {"name": "probe_read", "arguments": RAW_ARGUMENTS}}
        )

        call_rec = _records("tool_call", records)[0]
        assert call_rec.get("arguments") == RAW_ARGUMENTS, (
            "调用侧缺协议原文形态的 arguments（或已被重新序列化改写空白）——"
            f"重建 assistant.tool_calls 无法逐字节对齐（键={sorted(call_rec)}）"
        )
        # 分工锁：`params` 仍是剥掉 taskName* 的解析结果，不被原文串顶替
        assert call_rec["params"] == {"query": "北京 天气"}

    @pytest.mark.asyncio
    async def test_absent_arguments_are_not_fabricated(self):
        """provider 没给 arguments 时不得补一个默认值冒充"它给了"。"""

        async def _execute():
            return {"ok": True}

        loop = _make_loop(_execute)
        _, records = await loop._execute_tool_call_worker(
            {"id": PROVIDER_ID, "function": {"name": "probe_read"}}
        )

        call_rec = _records("tool_call", records)[0]
        assert "arguments" not in call_rec, (
            f"provider 未提供 arguments，记录里不该出现该键（键={sorted(call_rec)}）"
        )

    @pytest.mark.asyncio
    async def test_parse_failure_result_record_is_addressable(self):
        """参数解析失败分支：结果侧同样必须可寻址（同一契约的第二处命中点）。"""

        async def _execute():  # pragma: no cover - 解析失败不执行
            raise AssertionError("参数解析失败时不得执行工具")

        loop = _make_loop(_execute)
        _, records = await loop._execute_tool_call_worker(
            {"id": PROVIDER_ID, "function": {"name": "probe_read", "arguments": "{invalid json"}}
        )

        result_rec = _records("tool_result", records)[0]
        assert result_rec.get("tool_call_id") == PROVIDER_ID, (
            "解析失败分支的结果记录没有 tool_call_id —— 结果侧不可寻址，"
            f"与成功分支契约不一致（键={sorted(result_rec)}）"
        )

    @pytest.mark.asyncio
    async def test_result_record_existing_keys_untouched(self):
        """反向锁：本票只增键，`tool_result` 既有键一个都不许动。"""

        async def _execute():
            return {"ok": True}

        loop = _make_loop(_execute)
        _, records = await loop._execute_tool_call_worker(
            {"id": PROVIDER_ID, "function": {"name": "probe_read", "arguments": RAW_ARGUMENTS}}
        )

        result_rec = _records("tool_result", records)[0]
        assert set(result_rec) == {
            "type", "tool_name", "tool_call_id", "result",
            "success", "timestamp", "reproducible", "offload_path",
        }, (
            "本票只增键：tool_result 的键集合不得增删（reproducible/offload_path 是 "
            f"_recall_by_call_id 与产物卡片注册的依赖）—— 实测键={sorted(result_rec)}"
        )


class TestDirectRecallResolvesOwningAgent:
    """直取寻址必须按**会话真实属主**去读台账（同一契约的第二处命中点）。

    写侧把 call_id 落到 `<sessions>/<agent_id>/` 下；读侧却用空 agent_id 查，
    而空值会被会话管理器当成 `default` 目录 —— 于是"我写下的硬地址我自己读不回来"。
    """

    @pytest.mark.asyncio
    async def test_recall_reads_owning_agent_dir(self):
        seen = {}

        class _Repo:
            def get_history(self, agent_id="", session_id="", max_messages=0):
                seen["agent_id"] = agent_id
                return [{"role": "assistant", "metadata": {"tool_calls": [
                    {"type": "tool_result", "tool_call_id": "c9",
                     "tool_name": "probe_read", "result": "原文"}
                ]}}]

        agent = SimpleNamespace(
            current_session_id="sess_x",
            config=SimpleNamespace(agent_id="a1"),
            session_repo=_Repo(),
            workspace_path=".",
        )
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = agent

        out = await executor._recall_by_call_id("c9", {"session_id": "sess_x"})

        assert seen.get("agent_id") == "a1", (
            "直取读台账用的是空 agent_id（被当成 default 目录）——"
            f"写侧落在会话属主目录下，读侧因此恒读不回来（实测 agent_id={seen.get('agent_id')!r}）"
        )
        assert out.get("result") == "原文" or out.get("content") == "原文"
