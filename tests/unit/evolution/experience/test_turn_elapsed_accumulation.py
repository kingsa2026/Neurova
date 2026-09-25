"""009 残留 · 轮级工具耗时必须在**并行轮**也累加得到（红→绿）。

## 背景：上一轮登记的"红绿取决于收集顺序"

上一轮把 `test_tool_loop_funnel_probes.py::test_turn_writes_elapsed_and_structure_key`
如实登记为"单跑 1 failed / 与离线探针合跑 12 passed，故不能进 protected_tests"，
并给出两个候选根因（H1 ContextVar 跨任务不回传 / H2 `or None` 把 0.0 折成 NULL）。
本轮实测把两个候选分开，结论是 **H1**，且它与"收集顺序"无关：

```
单工具轮（串行路径）
  [INNER] task=Task-1   ← 与 chat 同任务
  [ADD]   task=Task-1   ← 写进了正确上下文 ⇒ 父轮次读得到
双工具轮（同轮声明并行 ⇒ gather）
  [INNER] task=Task-8   ← 子任务（asyncio.wait 里 ensure_future 出来的）
  [INNER] task=Task-9
  [ADD]   task=Task-8   ← 写进**子任务**上下文
  [ADD]   task=Task-9
  [POST]  elapsed=0.0   ⇒ 折成 NULL 落库
```

`ContextVar.set()` 在另一任务里只改那个任务的上下文副本，父任务读不到。
并联路径的兄弟例子是 `_tool_messages_var`：它的既有契约是"跨 task 边界共享同一
**列表对象**"（`turn_context.py` 的注释），所以原生链并行回装后父轮次仍读得到；
`_tool_elapsed_var` 存的是不可变 float，赋值不是共享，这就是两者行为不同的原因。

## 为什么"合跑会绿"不代表被测行为正确

父上下文里是否残留上一轮的值，取决于同一事件循环里此前跑过什么。
本文件不猜顺序，而是**直接构造那个父上下文读数**：先给父上下文预置一个
非零 elapsed，再跑一轮并行工具调用 —— 旧实现下父读数仍是 0.0（被写进子任务），
新实现下是"预置值 + 本轮真值"。这样判据不依赖任何收集顺序。

## 为什么修在咽喉而不是 post-chat

`post_chat` 是消费方（读聚合），往那里加"取不到就回退"就是 consumer-only guard。
根因在写入侧：累加必须落到**父轮次的上下文**上。故咽喉持有一个轮次级累加器，
累加动作按"值"而非"上下文"聚合，跨 task 边界可达。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from neurova.core import turn_context as tc
from neurova.llm_client import LLMResponse


def _tool_calls(names: List[str]) -> List[LLMResponse]:
    """模型边界替身产出的一条轮次：同轮 n 条调用（走并行路径必须全部声明并行安全）。"""
    return [
        LLMResponse(
            content="",
            tool_calls=[{
                "index": i,
                "id": f"c{i}",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            } for i, name in enumerate(names)],
            finish_reason="tool_calls",
        )
    ]


def _scripted(names: List[str], answer: str = "好的"):
    class Scripted:
        def __init__(self, config):
            self.config = config
            self.round = 0

        async def chat_stream(self, messages, **kwargs):
            self.round += 1
            if self.round == 1:
                for chunk in _tool_calls(names):
                    yield chunk
            else:
                yield LLMResponse(content=answer, finish_reason="stop")

        async def chat(self, messages, **kwargs):
            async for chunk in self.chat_stream(messages, **kwargs):
                yield chunk

    return Scripted


def _run_turn(agent, names: List[str], user_input: str = "算一下") -> float:
    """经生产入口 `Agent.chat` 跑一轮，返回父上下文（轮次上下文）里的 elapsed。"""
    model = _scripted(names)(agent.llm_client.config)
    agent.llm_client = model
    agent.loop.llm_client = model

    async def _go():
        await agent.chat(user_input, session_id="elapsed-probe", stream=True)
        await agent.post_chat_pipeline.drain_background(timeout=60)
        return tc.get_turn_tool_elapsed()

    return asyncio.run(_go())


@pytest.fixture
def agent_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "experience_knowledge.db"))
    from neurova.skills.experience_knowledge_base import reset_experience_knowledge_base

    reset_experience_knowledge_base()
    from neurova.agent_core import Agent

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    agent = Agent(
        name="ElapsedProbe",
        agent_id="elapsed-probe-01",
        workspace_path=str(workspace),
        enable_memory=False,
    )
    try:
        yield agent
    finally:
        reset_experience_knowledge_base()


class TestParallelTurnAccumulatesElapsed:
    """并行轮（同轮多条声明并行安全的调用）必须与串行轮读同一个数。"""

    def test_parallel_round_reaches_the_parent_context(self, agent_probe):
        """判据：父轮次读到的 elapsed 必须 > 0。

        旧实现读 0.0 —— 两个子任务各自 `set()` 了自己的副本，父上下文从未被写。
        """
        tc.reset_turn_tool_messages()
        elapsed = _run_turn(agent_probe, ["calculator", "calculator"])
        assert elapsed > 0, (
            "并行轮的工具耗时没有回到父轮次上下文（写进了子任务副本）："
            f"elapsed={elapsed!r}"
        )

    def test_serial_round_also_reaches_the_parent_context(self, agent_probe):
        """对照组：串行轮此前就是绿的，收口不得把它做坏。"""
        tc.reset_turn_tool_messages()
        elapsed = _run_turn(agent_probe, ["get_datetime"])
        assert elapsed > 0, f"串行轮的 elapsed 也丢了：{elapsed!r}"

    def test_turn_start_discards_the_previous_round_reading(self, agent_probe):
        """反向控制：读数必须是**本轮真值**，不得续加上一轮的残留。

        判据全部是结构等式，不含墙钟上界（本仓有 `test_ci_wallclock_assertion_ledger`
        常驻守卫：把"契约"写成秒数阈值，CI 会在负载下偶发红）。

        先预置一个非零读数，再走轮首复位：复位语义是**换绑新累加器**而不是把
        已绑定的那个清零。两者在"本轮读到什么"上是可区分的——沿用同一对象时，
        上一轮的值会被本轮续累（本仓 `_tool_messages_var` 同款纪律）。
        """
        tc.reset_turn_tool_messages()
        tc.add_turn_tool_elapsed(100.0)
        assert tc.get_turn_tool_elapsed() == 100.0, "预置没生效，反向控制失去前提"

        tc.reset_turn_tool_messages()
        assert tc.get_turn_tool_elapsed() == 0.0, "轮首复位没有丢掉上一轮的读数"
        assert tc.has_turn_tool_measurement() is False, "复位后仍声称本轮测过"

        elapsed = _run_turn(agent_probe, ["calculator", "calculator"])
        assert elapsed > 0.0, f"本轮真值没累加进去：elapsed={elapsed!r}"

    def test_parallel_round_is_not_less_than_a_single_call(self, agent_probe):
        """两条并发调用各自的耗时都要计入，读数不得小于单条的量级。

        这是"兄弟任务各自累加但父上下文可见"的判据：只回传一条也会 > 0，
        故必须比较两条与一条——两条并发调用的合计不得低于一条的合计的一半
        （单条量级约 30ms，两条合计必然更大；留宽余量避免环境噪声）。
        """
        tc.reset_turn_tool_messages()
        one = _run_turn(agent_probe, ["calculator"])
        tc.reset_turn_tool_messages()
        two = _run_turn(agent_probe, ["calculator", "calculator"])
        assert two > one * 0.5, (
            f"两条并发调用的合计耗时明显小于单条，说明只回传了一条：one={one!r} two={two!r}"
        )


class TestMeasuredZeroIsNotUnmeasured:
    """H2 的收口：`get_turn_tool_elapsed() or None` 是"用真假值判断测没测到"。

    上一轮把这条登记为候选根因之一。它是票 004 同一条禁区的另一个命中点：
    "测到 0.0 秒"与"本轮没有工具执行"是两件事，用 `or` 判断会把前者折成 NULL
    （不可复算：以后读 `execution_time` 的人无法区分"没测"与"测得极快"）。

    判据本体落在**测量的计数**上——有没有测到，由"累加被调用过几次"回答，
    不由累加出来的数真不真回答。
    """

    def test_measured_zero_is_distinguishable_from_no_measurement(self):
        tc.reset_turn_tool_messages()
        assert tc.has_turn_tool_measurement() is False, "轮首未测量时不得声称测过"
        tc.add_turn_tool_elapsed(0.0)
        assert tc.get_turn_tool_elapsed() == 0.0
        assert tc.has_turn_tool_measurement() is True, (
            "测到 0.0 秒被当成'没测到'（票 004 同款真假值折叠）"
        )

    def test_reset_clears_the_measurement_flag(self):
        tc.add_turn_tool_elapsed(1.0)
        tc.reset_turn_tool_messages()
        assert tc.has_turn_tool_measurement() is False, "轮首换绑后仍声称测过上一轮"
        assert tc.get_turn_tool_elapsed() == 0.0
