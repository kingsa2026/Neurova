# -*- coding: utf-8 -*-
"""AnthropicLoop 的工具批必须整批交给基类调度（M3 前置：路径失明的根修）。

## 根因

`AnthropicLoop.handle_tool_calls` 为了给 `computer` 工具做特殊回装，把**每个**
调用逐条转发给 `super().handle_tool_calls([tool_call], …)`。基类的批处理是按
**整批**分组的，逐条进来就永远只有一项 ⇒ 这条路径上任何能力声明都拿不到成组执行。

后果不是"少个优化"：`claude-*` 模型走的就是这个 Loop（注册表 priority=20），
于是 M1/M2 打开的并行收益在 Claude 侧恒为 0，而这一点在观测面上**看不出来**
（形态读数若不按路径分档，它就被并进总数读成"M3 没有收益"）。

修法：没有 `computer` 调用时整批交给基类；有 `computer` 时保持既有的逐条回装
（`computer` 是共享外设，逐条串行本来就是正确处置，且它的回装形状与基类不同）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.agent.loops.anthropic_loop import AnthropicLoop  # noqa: E402
from neurova.tool_executor import ToolExecutor  # noqa: E402


class _ConcurrencyProbe:
    """在飞高水位探针（事件序，不读墙钟）。"""

    def __init__(self):
        self.live = []
        self.peak = 0

    def enter(self, name):
        self.live.append(name)
        self.peak = max(self.peak, len(self.live))

    def exit(self, name):
        if name in self.live:
            self.live.remove(name)


def _call(index: int, name: str) -> dict:
    return {"id": f"c{index}", "function": {"name": name, "arguments": "{}"}}


def _make_loop(monkeypatch, safe_names, probe=None):
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

    class _StubRegistry:
        def __init__(self):
            self.skills = {}

        def ensure(self, name):
            self.skills.setdefault(name, SimpleNamespace(name=name, description="x", config={}))

        def get_skill(self, name):
            return self.skills.get(name)

        def has_skill(self, name):
            return name in self.skills

        async def execute_skill(self, skill_name, params, context=None):
            if probe is not None:
                probe.enter(skill_name)
            try:
                # 必须让出一次事件循环：没有 await 的执行体在 gather 里也是
                # 原子跑完的，在飞高水位会恒为 1 —— 那样的判据测不出并行度。
                await asyncio.sleep(0.02)
                return {"tool": skill_name}
            finally:
                if probe is not None:
                    probe.exit(skill_name)

    registry = _StubRegistry()
    for name in safe_names:
        registry.ensure(name)

    tool_messages = []
    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t", user_id="u1", agent_id="a1"),
        _current_user_id="u1",
        _tool_messages_list=tool_messages,
        append_tool_messages=lambda records: tool_messages.extend(records or []),
        skill_registry=None,
        _skill_registry=registry,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        tool_router=None,
        workspace_path=".",
    )
    agent.tool_executor = ToolExecutor(agent)
    return AnthropicLoop(agent)


class TestWholeBatchHandsOffToBaseScheduler:
    @pytest.mark.asyncio
    async def test_twoEligibleCallsRunConcurrently(self, monkeypatch):
        """无 `computer` 调用时必须整批交给基类：两个已声明项应同时在飞。"""
        probe = _ConcurrencyProbe()
        loop = _make_loop(monkeypatch, {"probe_read", "probe_search"}, probe=probe)

        await loop.handle_tool_calls(
            [_call("c1", "probe_read"), _call("c2", "probe_search")], []
        )

        assert probe.peak == 2, (
            f"Claude 路径逐条转发 super，成组执行拿不到（在飞高水位 {probe.peak}）"
        )

    @pytest.mark.asyncio
    async def test_shapeReadoutSeesMultiParallel(self, monkeypatch):
        """路径分档的形态读数必须能看见这条路径的成组批（否则读数会说谎）。"""
        from prometheus_client import REGISTRY

        loop = _make_loop(monkeypatch, {"probe_read", "probe_search"})
        await loop.handle_tool_calls(
            [_call("c1", "probe_read"), _call("c2", "probe_search")], []
        )

        seen = {}
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == "neurova_tool_batch_shapes_total":
                    seen[(sample.labels.get("path"), sample.labels.get("shape"))] = sample.value
        assert seen.get(("AnthropicLoop", "multi_parallel"), 0.0) >= 1.0, (
            f"Anthropic 路径的成组批没有落读数：{seen}"
        )

    @pytest.mark.asyncio
    async def test_computerCallKeepsPerCallHandling(self, monkeypatch):
        """反向控制：批里有 `computer` 时不得把它交给基类（回装形状不同、且须串行）。"""
        loop = _make_loop(monkeypatch, {"probe_read"})
        handler_calls = []

        class _Handler:
            async def get_dimensions(self):
                return (100, 100)

            async def screenshot(self):
                handler_calls.append("screenshot")
                return {"image_base64": "AAA"}

            async def click(self, x, y):
                return None

            async def type_text(self, text):
                return None

            async def scroll(self, dx, dy):
                return None

        loop.agent.computer_handler = _Handler()
        calls = [
            _call("c1", "computer"),
            _call("c2", "probe_read"),
        ]
        for call in calls:
            if call["function"]["name"] == "computer":
                call["function"]["arguments"] = json.dumps({"action": "screenshot"})

        msgs = await loop.handle_tool_calls(calls, [])

        assert handler_calls == ["screenshot"], "computer 调用没走 Loop 自己的处理分支"
        assert len(msgs) == 2, f"回装条数不对：{len(msgs)}"
        assert msgs[0]["role"] == "user" and "tool_result" in json.dumps(msgs[0]), (
            f"computer 的回装形状被改成了基类形态：{msgs[0]}"
        )
