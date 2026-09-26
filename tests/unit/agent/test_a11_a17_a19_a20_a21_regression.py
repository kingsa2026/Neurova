"""A-11 / A-17 / A-19 / A-20 / A-21 回归测试（Agent 管线/循环组）。

红绿说明（修复缺位时为红）：
- A-11: `BaseAgentLoop.predict_step` 方法体只有 docstring，未覆写时静默
  返回 None（用户拿到空回复）。修复后必须 raise NotImplementedError。
  用 `__abstractmethods__ = frozenset()` 绕过 ABC 实例化检查，复现
  "绕过静态检查后调用基类实现" 的路径（插件热加载/动态构造的真实形态）。
- A-17: `_auto_continue` 的 `MAX_TOTAL_CHARS = getattr(cfg, "max_tokens", 8192) * 10`
  ——getattr 默认值只兜属性缺失不兜属性值为 None → None*10 → TypeError，
  整个续写段炸穿。修复后 None 回落 8192。
- A-19: 流式路径硬编码 `self._tool_rounds <= 10`，非流式已用可配置的
  `_max_tool_rounds`（与 IterationGate 同源）。修复后两处口径单源：
  配置 `_max_tool_rounds=1` 时流式第 2 轮必须停止递归并产出 done 事件
  （修复前会继续递归到停滞终止/10 轮上限）。
- A-20: 观察者任务 `asyncio.ensure_future(...)` 无强引用——事件循环对
  Task 只持弱引用，观察者可能被 GC 静默吞掉（pending hints 永不投递）。
  修复后强引用挂在 `_background[task_id]["observer"]`，观察者收尾自行清理。
- A-21: 命令分发轮 `_step_llm_call` 提前 return，跳过全文件唯一
  `_clear_vision_routing(ctx)` 调用点 → ContextVar 视觉路由覆盖漏清，
  同任务后续 LLM 调用串到视觉模型。修复后提前返回路径也过清理点；
  正常轮结尾清理行为不变。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent.tool_coordinator import ToolCoordinator
from neurova.llm_client import LLMResponse


# ═══════════════════════════════════════════════════════════════
# A-11: 基类 predict_step 必须 raise NotImplementedError
# ═══════════════════════════════════════════════════════════════


class TestA11BasePredictStepContract:
    def test_unimplemented_predict_step_raises(self):
        """未覆写 predict_step 时调用必须抛 NotImplementedError，不得静默返回 None。"""

        class IncompleteLoop(BaseAgentLoop):
            """未覆写 predict_step 的子类（模拟动态构造/热加载绕过 ABC 检查）"""

        # 绕过 ABC 的实例化检查——这正是"未覆写还活着"的唯一路径
        IncompleteLoop.__abstractmethods__ = frozenset()
        loop = IncompleteLoop(SimpleNamespace(llm_client=SimpleNamespace()))

        with pytest.raises(NotImplementedError):
            asyncio.run(loop.predict_step([{"role": "user", "content": "hi"}], None))


# ═══════════════════════════════════════════════════════════════
# A-17: _auto_continue 对 max_tokens=None 回落 8192
# ═══════════════════════════════════════════════════════════════


class _ContinuationLoop:
    """predict_step 一次后给出正常收尾响应的假 Loop。"""

    def __init__(self):
        self.calls = 0

    async def predict_step(self, messages=None, tools=None, stream=False, thinking_effort="", **kwargs):
        self.calls += 1
        return SimpleNamespace(
            content="这是自动续写的内容，长度足够通过最短护栏检查。",
            finish_reason="stop",
            tool_calls=None,
            reasoning_content="",
        )


class TestA17AutoContinueMaxTokensNone:
    def _make_pipeline(self, max_tokens):
        pipe = ChatPipeline.__new__(ChatPipeline)
        pipe._agent = SimpleNamespace(
            llm_client=SimpleNamespace(config=SimpleNamespace(max_tokens=max_tokens)),
            detect_content_loop=lambda *a, **k: False,
            # loop 为读 agent 的 property
            loop=_ContinuationLoop(),
        )
        return pipe

    def test_max_tokens_none_falls_back_to_8192(self):
        """max_tokens 属性存在但值为 None 时必须回落 8192，不得 None*10 炸 TypeError。"""
        pipe = self._make_pipeline(None)
        ctx = SimpleNamespace(user_input="写一篇长文", context=[], metadata={})
        truncated = SimpleNamespace(content="开头段落", finish_reason="length", tool_calls=None)

        reply = asyncio.run(pipe._auto_continue(ctx, truncated, "开头段落", None))

        assert pipe.loop.calls == 1
        assert reply == "开头段落这是自动续写的内容，长度足够通过最短护栏检查。"

    def test_max_tokens_int_path_unchanged(self):
        """max_tokens 为正常 int 时续写行为不变（护栏不被误触）。"""
        pipe = self._make_pipeline(2048)
        ctx = SimpleNamespace(user_input="写一篇长文", context=[], metadata={})
        truncated = SimpleNamespace(content="开头段落", finish_reason="length", tool_calls=None)

        reply = asyncio.run(pipe._auto_continue(ctx, truncated, "开头段落", None))

        assert reply == "开头段落这是自动续写的内容，长度足够通过最短护栏检查。"


# ═══════════════════════════════════════════════════════════════
# A-19: 流式工具轮次上限与非流式同源（_max_tool_rounds）
# ═══════════════════════════════════════════════════════════════


def _tool_round_chunks():
    return [
        LLMResponse(
            tool_calls=[
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{\"query\": \"x\"}"},
                }
            ],
            finish_reason="tool_calls",
        ),
    ]


class _RoundsLLM:
    """按调用轮次产出预设 chunk 序列的假客户端（轮次用尽复用末轮）。

    同时具备 `chat_stream`（流式）与 `chat`（非流式）两个模型边界契约，
    同一个脚本驱动两条路径，便于比对它们是否停在同一轮。
    """

    def __init__(self, rounds):
        self.config = SimpleNamespace(
            temperature=None, max_tokens=None, top_p=None,
            frequency_penalty=None, model="gpt-4o",
        )
        self.rounds = rounds
        self.calls = []

    def _next(self, messages):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        return self.rounds[idx]

    async def chat_stream(self, messages, **kwargs):
        for chunk in self._next(messages):
            yield chunk

    async def chat(self, messages, **kwargs):
        chunks = self._next(messages)
        for chunk in chunks:
            if isinstance(chunk, LLMResponse):
                return chunk
        return LLMResponse(content="", finish_reason="stop")


async def _collect(gen):
    return [event async for event in gen]


def _tools_payload():
    return [{
        "type": "function",
        "function": {"name": "web_search", "parameters": {"type": "object", "properties": {}}},
    }]


class TestA19StreamRoundLimitSingleSource:
    """流式与非流式的工具轮上限必须同源（A-19）。

    配置口径单源在 `security/agent_limits_settings`：`max_loop_rounds // 2`
    （`max_loop_rounds // 2`）。判据是**两条路径在同一配置下
    停在同一轮**——修复前流式硬编码 `<=10`：配置轮次上限 2 时非流式 2 次调用
    收尾、流式继续到第 3 次。
    """

    def _make_loop(self, llm, max_rounds_env="2"):
        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        agent.tool_router = SimpleNamespace(
            execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
        )
        loop = OpenAILoop(agent)
        loop.llm_client = llm
        loop.agent.llm_client = llm
        return loop

    @pytest.fixture(autouse=True)
    def _rounds_budget(self, monkeypatch):
        """经生产配置点设定轮次上限 2 → 工具轮上限 1。"""
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", "2")
        from neurova.security.agent_limits_settings import get_effective_limits

        assert get_effective_limits()["max_loop_rounds"] // 2 == 1, (
            "测试前提：配置点解析出的工具轮上限为 1"
        )

    def test_stream_and_normal_stop_at_same_round(self):
        stream_llm = _RoundsLLM([_tool_round_chunks(), _tool_round_chunks()])
        stream_loop = self._make_loop(stream_llm)
        asyncio.run(
            _collect(stream_loop._predict_stream({"messages": [{"role": "user", "content": "hi"}], "stream": True}))
        )

        normal_llm = _RoundsLLM([_tool_round_chunks(), _tool_round_chunks()])
        normal_loop = self._make_loop(normal_llm)
        asyncio.run(
            normal_loop.predict_step([{"role": "user", "content": "hi"}], tools=_tools_payload())
        )

        assert len(stream_llm.calls) == len(normal_llm.calls), (
            "A-19: 同一配置下流式与非流式的 LLM 调用次数必须一致，"
            f"实际 流式 {len(stream_llm.calls)} 次 / 非流式 {len(normal_llm.calls)} 次"
        )
        assert len(stream_llm.calls) == 2, (
            f"A-19: 工具轮上限=1 时流式应恰好 2 次 LLM 调用，实际 {len(stream_llm.calls)} 次"
        )


# ═══════════════════════════════════════════════════════════════
# A-20: 后台观察者任务强引用
# ═══════════════════════════════════════════════════════════════


class TestA20ObserverStrongReference:
    @pytest.mark.asyncio
    async def test_observer_task_strongly_referenced_while_running(self):
        """转后台后观察者任务必须被强引用（entry['observer']），收尾自行清理。"""
        coordinator = ToolCoordinator()

        async def slow():
            await asyncio.sleep(0.3)
            return {"late": True}

        result = await coordinator.run_with_timeout("web_search", slow, timeout=0.02)
        assert result["status"] == "background"
        task_id = result["task_id"]

        entry = coordinator._background.get(task_id)
        assert entry is not None
        observer = entry.get("observer")
        assert isinstance(observer, asyncio.Task), (
            "A-20: 观察者任务必须挂强引用（_background[task_id]['observer']），"
            "否则事件循环只持弱引用，观察者可能被 GC 静默吞掉"
        )
        assert not observer.done()

        # 收尾：观察者完成后清理引用、entry 移入 _completed、hints 投递
        await asyncio.wait_for(observer, timeout=2.0)
        assert coordinator._background.get(task_id) is None
        assert coordinator._completed[task_id]["task"] is None
        assert coordinator._completed[task_id]["observer"] is None
        hints = coordinator.pop_pending_hints()
        assert any(h["task_id"] == task_id and h["success"] for h in hints)

    @pytest.mark.asyncio
    async def test_observer_survives_gc_and_delivers_hint(self):
        """丢弃调用方引用并强制 GC 后，观察者仍完成并把结果推入 pending hints。"""
        import gc

        coordinator = ToolCoordinator()

        async def slow():
            await asyncio.sleep(0.25)
            return {"late": True}

        result = await coordinator.run_with_timeout("web_search", slow, timeout=0.02)
        task_id = result["task_id"]
        # 修复后强引用经 entry 取得——观察者生命周期由 coordinator 负责
        observer = coordinator._background[task_id]["observer"]

        gc.collect()
        await asyncio.sleep(0.4)

        assert not observer.cancelled()
        assert observer.done()
        hints = coordinator.pop_pending_hints()
        assert any(h["task_id"] == task_id and h["success"] for h in hints), (
            "A-20: 观察者被 GC 吞掉时 hints 永不投递——强引用缺失"
        )


# ═══════════════════════════════════════════════════════════════
# A-21: 命令分发轮提前返回也必须清理视觉路由覆盖
# ═══════════════════════════════════════════════════════════════


class TestA21VisionRoutingClearedOnCommandRound:
    def _patch_overlay(self, monkeypatch):
        import neurova.llm.llm_routing_overlay as overlay

        cleared = []
        monkeypatch.setattr(overlay, "clear_vision_override", lambda token: cleared.append(token))
        return cleared

    def test_command_dispatch_round_clears_vision_routing(self, monkeypatch):
        """command_dispatched 提前返回路径必须清理 _vision_override_token。"""
        cleared = self._patch_overlay(monkeypatch)
        pipe = ChatPipeline.__new__(ChatPipeline)
        pipe._agent = SimpleNamespace()

        ctx = SimpleNamespace(metadata={"command_dispatched": True}, user_input="/cmd")
        ctx._vision_override_token = "tok-a21"

        asyncio.run(pipe._step_llm_call(ctx))

        assert cleared == ["tok-a21"], (
            "A-21: 命令轮提前返回跳过了 _clear_vision_routing，"
            "ContextVar 视觉路由覆盖泄漏到同任务后续 LLM 调用"
        )
        assert ctx._vision_override_token is None

    def test_normal_round_still_clears_at_end(self, monkeypatch):
        """正常 LLM 轮结尾清理行为不变（回归保护）。"""
        cleared = self._patch_overlay(monkeypatch)
        pipe = ChatPipeline.__new__(ChatPipeline)
        pipe._agent = SimpleNamespace(
            llm_client=SimpleNamespace(config=SimpleNamespace(max_tokens=1024)),
            get_tool_messages_snapshot=lambda: [],
            set_current_reasoning=lambda v: None,
            # loop/context_orchestrator/tool_executor 均为读 agent 的 property
            context_orchestrator=SimpleNamespace(
                build_tools_for_llm=AsyncMock(return_value=[]),
                mark_last_view_seen=lambda: None,
            ),
            loop=SimpleNamespace(),
            tool_executor=SimpleNamespace(
                execute_text_tool_calls=AsyncMock(return_value="ok"),
                tool_coordinator=None,
            ),
        )

        async def fake_predict(**kwargs):
            return SimpleNamespace(content="ok", reasoning_content=None)

        pipe._agent.loop.predict_step = fake_predict

        ctx = SimpleNamespace(
            metadata={}, user_input="hi", context=[], stream=False,
            tool_decision=None, event_emitter=None,
        )
        ctx._vision_override_token = "tok-normal"

        asyncio.run(pipe._step_llm_call(ctx))

        assert ctx.reply == "ok"
        assert cleared == ["tok-normal"]
        assert ctx._vision_override_token is None
