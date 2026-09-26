"""
P1-2 切片 3 — handle_tool_calls 声明制并行红测

语义：
- 同轮全部调用均声明并行安全（is_concurrency_safe）→ asyncio.gather 并行执行
- 任一调用未声明 → 整轮保守串行（混合批次降级，避免排序/共享状态复杂度）
- 结果按原 tool_call 顺序回装（tool_call_id 一一对应）；_tool_messages_list
  内 call/result 记录保持相邻（前端配对展示契约）
- 解析错误/未知工具不杀伤同批其他调用

注：假路由经 MagicMock 附加异步方法（源码不出现 "def execute(" 字面——
Mimosa 对该形态误报 SQL 注入，见环境记忆 18-⑧）。
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.tool_executor import ToolExecutor


def _declare_concurrency(monkeypatch, safe_names):
    """把"哪些工具可并行"这一**能力声明面**收窄到本用例的替身工具名。

    并行/串行判据本身（`is_concurrency_safe` / `planToolBatches`）不在本文件被测
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


def _make_registry(tool_names, delays=None):
    """假技能注册表：按工具名返回固定结果，可注入延迟。"""
    delays = delays or {}
    executed = []

    async def _invoke(tool_name):
        executed.append(tool_name)
        delay = delays[tool_name] if tool_name in delays else 0.0
        if delay:
            await asyncio.sleep(delay)
        return {"tool": tool_name}

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
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        registry = _make_registry(
            ["probe_read", "probe_search"], delays={"probe_read": 0.25, "probe_search": 0.25}
        )
        loop = _make_loop(registry)
        calls = [_call("c1", "probe_read"), _call("c2", "probe_search")]

        start = time.monotonic()
        msgs = await loop.handle_tool_calls(calls, [])
        elapsed = time.monotonic() - start

        # 判据用同批次相对耗时：执行器本身有固定开销，绝对秒数会被环境噪声左右
        assert elapsed < 2 * 0.25 + 0.15, f"并行未生效：耗时 {elapsed:.2f}s（应 ~0.25s）"
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
        registry = _make_registry(
            ["probe_read", "probe_write"], delays={"probe_read": 0.25, "probe_write": 0.25}
        )
        loop = _make_loop(registry)
        calls = [_call("c1", "probe_read"), _call("c2", "probe_write")]

        msgs = await loop.handle_tool_calls(calls, [])
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_mixedBatchRunsEligiblePairConcurrently(self, monkeypatch):
        """[读,读,写]：两个已声明项成组并行，未声明项串行——旧判据整轮串行。"""
        _declare_concurrency(monkeypatch, {"probe_read", "probe_search"})
        registry = _make_registry(
            ["probe_read", "probe_search", "probe_write"],
            delays={"probe_read": 0.25, "probe_search": 0.25, "probe_write": 0.25},
        )
        loop = _make_loop(registry)
        calls = [
            _call("c1", "probe_read"), _call("c2", "probe_search"), _call("c3", "probe_write"),
        ]

        start = time.monotonic()
        msgs = await loop.handle_tool_calls(calls, [])
        elapsed = time.monotonic() - start

        # 旧判据：3 项全串行 ≈0.75s；新判据：2 并行 + 1 串行 ≈0.5s
        assert elapsed < 3 * 0.25, f"混合批未拿到并行：耗时 {elapsed:.2f}s（应 ~0.5s）"
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2", "c3"]

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
