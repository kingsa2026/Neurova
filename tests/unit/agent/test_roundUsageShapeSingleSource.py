"""流式 usage 的两种进料形状只在基类归一次（§6-77，H1 活体抓出）。

`LLMResponse.usage` 声明是 `Dict[str, int]`，但流式路径上有一批 chunk 是**原样透传的
SDK 对象**（`neurova/llm_client.py:554` 的注释就写着"原样 yield 给消费方，
multi_model/openai_loop 按 chunk.usage 读取"）。于是同一个数有两种读法：
`OpenAILoop` 自己用 `getattr` 归一，基类的 `_accumulateRoundUsage` 只认 `.get()`。

后果不是报错而是两种静默形态，都实测过：
- Anthropic 环（A 批才接上 usage 累计）遇到真网关的 SDK 对象 → `AttributeError`，
  H1 的 OpenRouter 活体就是这么撞上的；
- `multi_model_client` 的流式记账把 `.get()` 包在 `try/except` 里 → 异常被吞，
  usage 记 0，看起来"一切正常"。

本文件钉的是"归一只有一处"：两种进料都要得到同一份 dict 读数，且 OpenAI 环不得
再自带第二份聚合。
"""

import inspect
from types import SimpleNamespace

from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent.loops.turn_run_state import TurnRunState


class _Agent:
    pass


def _loop(cls):
    loop = cls.__new__(cls)
    loop.agent = _Agent()
    return loop


def _state() -> TurnRunState:
    return TurnRunState.forTurn(agentId="usage-shape")


class TestBothUsageShapesAccumulate:
    def test_dict_usage_still_accumulates(self):
        loop = _loop(AnthropicLoop)
        state = _state()
        loop._accumulateRoundUsage({"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}, state)
        assert state.roundUsage == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}

    def test_sdk_object_usage_accumulates_not_raises(self):
        """真网关（OpenRouter/AMD 实测）给的是 SDK 对象，不是 dict。"""
        loop = _loop(AnthropicLoop)
        state = _state()
        loop._accumulateRoundUsage(
            SimpleNamespace(prompt_tokens=11, completion_tokens=4, total_tokens=15), state)
        assert state.roundUsage == {
            "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
        }, "流式 usage 原样透传的 SDK 形状必须被归一，AttributeError 会掐死整条流"

    def test_accumulation_is_additive_across_rounds(self):
        loop = _loop(AnthropicLoop)
        state = _state()
        loop._accumulateRoundUsage(SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3), state)
        loop._accumulateRoundUsage({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}, state)
        assert state.roundUsage == {
            "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10,
        }

    def test_missing_fields_do_not_poison_the_counter(self):
        """网关只回部分字段时按 0 记账，而不是让 `int(None)` 抛异常。"""
        loop = _loop(AnthropicLoop)
        state = _state()
        loop._accumulateRoundUsage(SimpleNamespace(prompt_tokens=9, completion_tokens=None, total_tokens=None), state)
        assert state.roundUsage["prompt_tokens"] == 9
        assert state.roundUsage["completion_tokens"] == 0


class TestAggregationHasOneImplementation:
    def test_openai_loop_delegates_instead_of_inlining(self):
        """同一件事的第二份聚合不得留在 OpenAI 环里（教义第 7 条：接通后退役）。"""
        src = inspect.getsource(OpenAILoop)
        assert "_accumulateRoundUsage(" in src, "OpenAI 环没走基类那份归一"
        assert 'prev.get("prompt_tokens", 0) +' not in src, (
            "OpenAI 环还在就地拼第二轮计数：两份实现迟早漂移成"
            "「某条环的闸恒不触发」"
        )
