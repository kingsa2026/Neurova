"""
P1-2 切片 3 — handle_tool_calls 声明制并行红测

语义：
- 同轮调用按**各自的能力声明**分组：连续资格项成组并发，未声明项各自串行
  （分组形态由 `tests/unit/tools/test_tool_batch_parallelism.py` 逐条测）
- 结果按原 tool_call 顺序回装（tool_call_id 一一对应）；_tool_messages_list
  内 call/result 记录保持相邻（前端配对展示契约）
- 解析错误/未知工具不杀伤同批其他调用

并行资格判据用**事件序**（进门高水位 + 执行区间是否重叠），不用墙钟上界：
墙钟阈值与机器负载强相关，共享 CI 机上会把正确实现读成"未并行"，
且此类判据由 `tests/unit/test_ci_wallclock_assertion_ledger.py` 逐条登记管控。

注：假路由经 MagicMock 附加异步方法（源码不出现 "def execute(" 字面——
Mimosa 对该形态误报 SQL 注入，见环境记忆 18-⑧）。
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Dict, List
from unittest.mock import AsyncMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.tool_executor import ToolExecutor


def _declare_concurrency(monkeypatch, safe_names):
    """把"哪些工具可并行"这一**能力声明面**收窄到本用例的替身工具名。

    并行/串行判据本身（`isParallelEligible` / `planToolBatches`）不在本文件被测
    范围——本文件测的是 `handle_tool_calls` 按声明分组后是否真的 gather / 真的串行。

    替身工具不是内置工具，故这里替换**解析入口**（`resolveToolCapability`）而不是
    任何名单：声明面已无名单可替换（事实源是各工具自己的 schema 声明位）。
    """
    import neurova.agent.tool_coordinator as coordinator
    from neurova.core.tool_capability import ToolCapability, WriteScope

    eligible = ToolCapability(
        readOnly=True, concurrentSafe=True, writeScopes=frozenset({WriteScope.NONE})
    )
    names = {str(n).lower() for n in safe_names}

    monkeypatch.setattr(
        coordinator,
        "resolveToolCapability",
        lambda name: eligible if str(name or "").strip().lower() in names else None,
    )


class _StubSkill:
    """技能替身：执行体 + `config`（取件契约 `get_skill`）。"""

    def __init__(self, name, invoke):
        self.name = name
        self.description = "并行探针技能"
        self.config = {}
        self._invoke = invoke


class _StubRegistry:
    """技能注册表替身：把并行/延迟语义落在技能执行体这一层。"""

    def __init__(self, invoke):
        self._invoke = invoke
        self.skills = {}

    def ensure(self, name):
        if name not in self.skills:
            async def _run(skill_name, params, context=None):
                return await self._invoke(skill_name)

            self.skills[name] = _StubSkill(name, _run)

    async def execute_skill(self, skill_name, params, context=None):
        return await self._invoke(skill_name)

    def get_skill(self, skill_name):
        return self.skills.get(skill_name)

    def has_skill(self, skill_name):
        return skill_name in self.skills

    def list_skills(self):
        return []


class _ConcurrencyProbe:
    """并行资格探针：记「进门/离场」事件序与在飞高水位，**不读墙钟**。

    "两个调用是否同时在做"是事件序的事：同批调用进门即 +1、离场即 -1，
    串行执行时高水位恒为 1、且任一时刻在飞数恒为 1。墙钟阈值与机器负载强相关
    （共享 CI 机上会把正确实现读成"未并行"），故本文件不用它做判据——
    受保护子集内的墙钟上界由 `tests/unit/test_ci_wallclock_assertion_ledger.py`
    逐条管控。
    """

    def __init__(self):
        self.events: List = []          # [("enter"|"exit", 工具名), ...]
        self.live: List = []            # 当前在飞的调用
        self.peak = 0                   # 在飞高水位
        self.overlapped: Dict = {}      # 工具名 → 是否曾与别的调用同时在飞

    def enter(self, tool_name):
        self.events.append(("enter", tool_name))
        if self.live:
            self.overlapped[tool_name] = True
            for other in self.live:
                self.overlapped[other] = True
        self.overlapped.setdefault(tool_name, False)
        self.live.append(tool_name)
        self.peak = max(self.peak, len(self.live))

    def exit(self, tool_name):
        self.events.append(("exit", tool_name))
        if tool_name in self.live:
            self.live.remove(tool_name)


def _enteredAfter(probe, later, earlier):
    """`later` 是否在 `earlier` **离场之后**才进门（串行次序，非秒数）。"""
    return probe.events.index(("enter", later)) > probe.events.index(("exit", earlier))


def _make_registry(tool_names, probe=None, delays=None):
    """假技能注册表：按工具名返回固定结果，可注入延迟与在飞探针。"""
    delays = delays or {}
    executed = []

    async def _invoke(tool_name):
        if probe is not None:
            probe.enter(tool_name)
        try:
            executed.append(tool_name)
            delay = delays[tool_name] if tool_name in delays else 0.0
            if delay:
                await asyncio.sleep(delay)
            return {"tool": tool_name}
        finally:
            if probe is not None:
                probe.exit(tool_name)

    registry = _StubRegistry(_invoke)
    for name in tool_names:
        registry.ensure(name)
    registry.executed = executed
    return registry


def _make_loop(registry):
    # P3-c 收窄：base.handle_tool_calls 经显式 API 回装展示记录；
    # 共享同一列表对象，既有 _tool_messages_list 相邻配对断言继续成立
    tool_messages = []

    def _append_tool_messages(records):
        tool_messages.extend(records or [])

    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t", user_id="u1", agent_id="a1"),
        _current_user_id="u1",
        _tool_messages_list=tool_messages,
        append_tool_messages=_append_tool_messages,
        skill_registry=None,
        _skill_registry=registry,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        tool_router=None,
        workspace_path=".",
    )
    agent.tool_executor = ToolExecutor(agent)
    return OpenAILoop(agent)


def _call(cid, name, args=None):
    return {"id": cid, "function": {"name": name, "arguments": json.dumps(args or {})}}


class TestParallelGather:
    @pytest.mark.asyncio
    async def test_all_safe_tools_run_concurrently(self, monkeypatch):
        """两个已声明项必须**同时在飞**：结构判据（在飞高水位），串行时恒为 1。"""
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        probe = _ConcurrencyProbe()
        registry = _make_registry(
            ["probe_read", "probe_search"],
            probe=probe,
            delays={"probe_read": 0.05, "probe_search": 0.05},
        )
        loop = _make_loop(registry)
        calls = [_call("c1", "probe_read"), _call("c2", "probe_search")]

        msgs = await loop.handle_tool_calls(calls, [])

        assert probe.peak == 2, (
            f"两个已声明项未同时在飞（在飞高水位 {probe.peak}）——串行 await 时恒为 1"
        )
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_undeclaredItemIsSerialAndDoesNotDragSiblings(self, monkeypatch):
        """未声明项自己串行，**不拖累**相邻已声明项——这是本次改造的判据变化。

        改前是 all-or-nothing：`[读, 写]` 里写未声明 ⇒ 读也拿不到并行。
        改后读仍按声明执行；本用例两项都只有 1 次执行，故时序与串行等价，
        这里钉的是**语义**（不再整轮降级），分组本身由
        `tests/unit/tools/test_tool_batch_parallelism.py` 逐形态测。
        """
        _declare_concurrency(monkeypatch, {"probe_read"})
        probe = _ConcurrencyProbe()
        registry = _make_registry(
            ["probe_read", "probe_write"],
            probe=probe,
            delays={"probe_read": 0.05, "probe_write": 0.05},
        )
        loop = _make_loop(registry)
        calls = [_call("c1", "probe_read"), _call("c2", "probe_write")]

        msgs = await loop.handle_tool_calls(calls, [])

        assert probe.peak == 1, (
            f"未声明项与已声明项同时在飞（在飞高水位 {probe.peak}）——未声明项必须串行"
        )
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_mixedBatchRunsEligiblePairConcurrently(self, monkeypatch):
        """[读,读,写]：两个已声明项同时在飞，未声明项在**它们离场之后**才跑。

        旧判据（墙钟上界 `elapsed < 0.75s`）与机器负载强相关，共享 CI 机上会把
        正确实现读成"未并行"；这里改读事件序：并行组的在飞高水位为 2，
        串行项的整段执行期内没有别的调用在飞，且它的进门晚于并行组的离场。
        """
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        probe = _ConcurrencyProbe()
        registry = _make_registry(
            ["probe_read", "probe_search", "probe_write"],
            probe=probe,
            delays={"probe_read": 0.05, "probe_search": 0.05, "probe_write": 0.05},
        )
        loop = _make_loop(registry)
        calls = [
            _call("c1", "probe_read"), _call("c2", "probe_search"), _call("c3", "probe_write"),
        ]

        msgs = await loop.handle_tool_calls(calls, [])

        assert probe.overlapped["probe_read"] and probe.overlapped["probe_search"], (
            f"混合批的已声明两项未同时在飞——旧判据整轮串行；事件序 {probe.events}"
        )
        assert not probe.overlapped["probe_write"], (
            f"未声明项与同批其它调用同时在飞——串行语义被破坏；事件序 {probe.events}"
        )
        assert _enteredAfter(probe, "probe_write", "probe_search"), (
            f"串行项未排在并行组之后；事件序 {probe.events}"
        )
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2", "c3"]

    @pytest.mark.asyncio
    async def test_criterionDetectsSerialDegradation(self, monkeypatch):
        """反向控制：单源上限置 1（合法域下界 = 串行）后，同一批调用必须读成串行。

        两条一起钉住：判据不是恒真的（串行时读数确实变化），且分组真的由
        单源配置键 `max_parallel_tools` 驱动（只写不读即在此判红）。
        """
        monkeypatch.setenv("NEUROVA_AGENT_MAX_PARALLEL_TOOLS", "1")
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        probe = _ConcurrencyProbe()
        registry = _make_registry(
            ["probe_read", "probe_search", "probe_write"],
            probe=probe,
            delays={"probe_read": 0.05, "probe_search": 0.05, "probe_write": 0.05},
        )
        loop = _make_loop(registry)
        calls = [
            _call("c1", "probe_read"), _call("c2", "probe_search"), _call("c3", "probe_write"),
        ]

        await loop.handle_tool_calls(calls, [])

        assert probe.peak == 1, (
            f"上限置 1 后仍有并发在飞（高水位 {probe.peak}）——上限只写不读"
        )
        assert not any(probe.overlapped.values()), (
            f"上限置 1 后仍有调用同时在飞；事件序 {probe.events}"
        )

    @pytest.mark.asyncio
    async def test_single_tool_unaffected(self):
        registry = _make_registry(["probe_read"])
        loop = _make_loop(registry)
        msgs = await loop.handle_tool_calls([_call("c1", "probe_read")], [])
        assert len(msgs) == 1 and msgs[0]["tool_call_id"] == "c1"


class TestResultAssembly:
    @pytest.mark.asyncio
    async def test_results_match_call_ids_in_order(self):
        names = ["probe_one", "probe_two", "probe_three"]
        registry = _make_registry(names)
        loop = _make_loop(registry)
        calls = [_call(f"c{i}", n) for i, n in enumerate(names, start=1)]
        msgs = await loop.handle_tool_calls(calls, [])

        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2", "c3"]
        payloads = [json.loads(m["content"]) for m in msgs]
        assert payloads[0] == {"tool": "probe_one"}
        assert payloads[2] == {"tool": "probe_three"}

    @pytest.mark.asyncio
    async def test_tool_messages_list_adjacent_pairs(self):
        """前端配对契约：_tool_messages_list 内 call/result 记录保持相邻"""
        registry = _make_registry(["probe_read", "probe_search"])
        loop = _make_loop(registry)
        calls = [_call("c1", "probe_read"), _call("c2", "probe_search")]
        await loop.handle_tool_calls(calls, [])

        types = [e["type"] for e in loop.agent._tool_messages_list]
        assert types == ["tool_call", "tool_result", "tool_call", "tool_result"]

    @pytest.mark.asyncio
    async def test_groupedBatchKeepsCallResultPairsAdjacent(self, monkeypatch):
        """分组后回装仍按原序、且 call/result 相邻——前端配对契约无回归。

        混合批（2 个已声明 + 1 个未声明）走分组路径：已声明两项成组并发，
        未声明项串行，但回装次序必须与 `tool_calls` 完全一致。
        """
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        registry = _make_registry(["probe_read", "probe_search", "probe_write"])
        loop = _make_loop(registry)
        calls = [
            _call("c1", "probe_read"), _call("c2", "probe_write"), _call("c3", "probe_search"),
        ]

        msgs = await loop.handle_tool_calls(calls, [])

        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2", "c3"]
        types = [e["type"] for e in loop.agent._tool_messages_list]
        assert types == ["tool_call", "tool_result"] * 3

    @pytest.mark.asyncio
    async def test_parse_error_isolated_in_parallel_batch(self):
        """批次内某条参数非法 JSON：该条回错误，其余照常执行"""
        registry = _make_registry(["probe_read", "probe_search"])
        loop = _make_loop(registry)
        bad = {"id": "cbad", "function": {"name": "probe_read", "arguments": "{invalid json"}}
        calls = [bad, _call("c2", "probe_search")]
        msgs = await loop.handle_tool_calls(calls, [])

        assert len(msgs) == 2
        by_id = {m["tool_call_id"]: m for m in msgs}
        # json.dumps 会转义中文——解析后再断言
        assert "参数 JSON 解析失败" in json.loads(by_id["cbad"]["content"])["error"]
        assert json.loads(by_id["c2"]["content"]) == {"tool": "probe_search"}

    @pytest.mark.asyncio
    async def test_unknown_tool_error_preserved(self):
        """未知工具：router 显式上报失败时必须回传真实错误。

        2026-09-09 修复前该路径因 SimpleNamespace UnboundLocalError 被 except
        吞掉，真实 error 被顶掉为"均未找到该工具"兜底消息（本测试旧断言把
        污染行为固化了）；修复后 router 的真实 error 原样回给 LLM。
        """
        # 工具不在注册表 ⇒ 咽喉诚实回"未知工具"，不得伪造成成功
        registry = _make_registry([])
        loop = _make_loop(registry)
        msgs = await loop.handle_tool_calls([_call("c1", "no_such_tool_anywhere")], [])
        payload = json.loads(msgs[0]["content"])
        assert "no_such_tool_anywhere" in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_user_id_threading_preserved(self):
        """P0-3 语义保持：并行路径 user_id 仍穿透到 router"""
        registry = _make_registry(["probe_read"])
        loop = _make_loop(registry)
        await loop.handle_tool_calls([_call("c1", "probe_read")], [])
        assert registry.executed == ["probe_read"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
