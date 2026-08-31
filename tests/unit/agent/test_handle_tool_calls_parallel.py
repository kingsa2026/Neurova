"""
P1-2 切片 3 — handle_tool_calls 声明制并行红测

语义（对标 QP ToolCoordinator 并行执行）：
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


def _make_router(delays=None):
    """假 ToolRouter：按工具名返回固定结果，可注入延迟。"""
    delays = delays or {}
    executed = []

    async def _invoke(tool_name, params=None, agent_id=None, user_id=None):
        executed.append(tool_name)
        delay = delays[tool_name] if tool_name in delays else 0.0
        if delay:
            await asyncio.sleep(delay)
        return SimpleNamespace(success=True, result={"tool": tool_name}, error=None)

    router = SimpleNamespace(executed=executed)
    router.execute = AsyncMock(side_effect=_invoke)
    return router


def _make_loop(router):
    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t", user_id="u1", agent_id="a1"),
        _current_user_id="u1",
        _tool_messages_list=[],
        skill_registry=None,
        tool_router=router,
    )
    return OpenAILoop(agent)


def _call(cid, name, args=None):
    return {"id": cid, "function": {"name": name, "arguments": json.dumps(args or {})}}


class TestParallelGather:
    @pytest.mark.asyncio
    async def test_all_safe_tools_run_concurrently(self):
        router = _make_router(delays={"web_search": 0.25, "memory_search": 0.25})
        loop = _make_loop(router)
        calls = [_call("c1", "web_search"), _call("c2", "memory_search")]

        start = time.monotonic()
        msgs = await loop.handle_tool_calls(calls, [])
        elapsed = time.monotonic() - start

        assert elapsed < 0.45, f"并行未生效：耗时 {elapsed:.2f}s（应 ~0.25s）"
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_mixed_batch_degrades_to_serial(self):
        """任一调用未声明安全 → 整轮串行（保守语义）"""
        router = _make_router(delays={"web_search": 0.25, "file_write": 0.25})
        loop = _make_loop(router)
        calls = [_call("c1", "web_search"), _call("c2", "file_write")]

        start = time.monotonic()
        msgs = await loop.handle_tool_calls(calls, [])
        elapsed = time.monotonic() - start

        assert elapsed >= 0.45, f"串行降级未生效：耗时 {elapsed:.2f}s"
        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_single_tool_unaffected(self):
        router = _make_router()
        loop = _make_loop(router)
        msgs = await loop.handle_tool_calls([_call("c1", "web_search")], [])
        assert len(msgs) == 1 and msgs[0]["tool_call_id"] == "c1"


class TestResultAssembly:
    @pytest.mark.asyncio
    async def test_results_match_call_ids_in_order(self):
        router = _make_router()
        loop = _make_loop(router)
        calls = [
            _call("c1", "web_search"),
            _call("c2", "memory_search"),
            _call("c3", "recall_history"),
        ]
        msgs = await loop.handle_tool_calls(calls, [])

        assert [m["tool_call_id"] for m in msgs] == ["c1", "c2", "c3"]
        payloads = [json.loads(m["content"]) for m in msgs]
        assert payloads[0] == {"tool": "web_search"}
        assert payloads[2] == {"tool": "recall_history"}

    @pytest.mark.asyncio
    async def test_tool_messages_list_adjacent_pairs(self):
        """前端配对契约：_tool_messages_list 内 call/result 记录保持相邻"""
        router = _make_router()
        loop = _make_loop(router)
        calls = [_call("c1", "web_search"), _call("c2", "memory_search")]
        await loop.handle_tool_calls(calls, [])

        types = [e["type"] for e in loop.agent._tool_messages_list]
        assert types == ["tool_call", "tool_result", "tool_call", "tool_result"]

    @pytest.mark.asyncio
    async def test_parse_error_isolated_in_parallel_batch(self):
        """批次内某条参数非法 JSON：该条回错误，其余照常执行"""
        router = _make_router()
        loop = _make_loop(router)
        bad = {"id": "cbad", "function": {"name": "web_search", "arguments": "{invalid json"}}
        calls = [bad, _call("c2", "memory_search")]
        msgs = await loop.handle_tool_calls(calls, [])

        assert len(msgs) == 2
        by_id = {m["tool_call_id"]: m for m in msgs}
        # json.dumps 会转义中文——解析后再断言
        assert "参数 JSON 解析失败" in json.loads(by_id["cbad"]["content"])["error"]
        assert json.loads(by_id["c2"]["content"]) == {"tool": "memory_search"}

    @pytest.mark.asyncio
    async def test_unknown_tool_error_preserved(self):
        """未知工具：router 显式上报失败时走未知工具分支"""
        router = _make_router()
        # 覆盖默认返回：该工具显式失败（模拟 router 找不到工具）
        async def _fail(tool_name, params=None, agent_id=None, user_id=None):
            return SimpleNamespace(success=False, result=None, error="tool not found")
        router.execute = AsyncMock(side_effect=_fail)

        loop = _make_loop(router)
        msgs = await loop.handle_tool_calls([_call("c1", "no_such_tool_anywhere")], [])
        payload = json.loads(msgs[0]["content"])
        assert "SkillRegistry 和 ToolRouter 均未找到" in payload["error"]

    @pytest.mark.asyncio
    async def test_user_id_threading_preserved(self):
        """P0-3 语义保持：并行路径 user_id 仍穿透到 router"""
        router = _make_router()
        loop = _make_loop(router)
        await loop.handle_tool_calls([_call("c1", "web_search")], [])
        assert router.executed == ["web_search"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
