# -*- coding: utf-8 -*-
"""截断续写段与 legacy 直连组都住在独立模块里，管线只留薄委托。

## 为什么有这条判据

`scripts/ci/perf_gate.py` 的 `hot-path-file-size` 把 `agent/chat_pipeline.py`
钉在 160000B（每轮对话必经，越过就拖慢 review 与重构）。`continuation_hint` 只抽走了
两个纯函数，续写循环本身还留在管线里，于是文件停在 160523B——门禁红在
"160523B > 160000B"，与本次任务的改动毫无关系。

处置口径与门禁自己的话一致：**新逻辑抽到独立模块后再接线**。这段续写循环与管线状态
无关，只吃 `loop` / `agent.detect_content_loop` / 本轮上下文快照，整块能搬。

## 判据要钉的不是"少了几行"

搬走实现很容易搬出个半成品：循环漏了某条护栏、`ctx` 的记账不再写回、或者
`continue_round == 1` 才带工具的细节丢了。这些都不会让导入失败，只会让
截断续写在线上悄悄退化。所以本判据全部走**真调用**：
真 `ChatPipeline` 实例 + 逐步变化的 `predict_step` 返回值，钉住

- 三条护栏（过短 / 重叠 / 语义循环）各自单独生效；
- 工具只在第一轮带、续写轮不再带（重复带工具会重复执行副作用）；
- 上界 `MAX_CONTINUE_ROUNDS` / `MAX_TOTAL_CHARS` 真被读；
- `ctx_snapshot` 每轮把 assistant 正文与提示词追加进消息；
- 收尾的 `finish_reason` 记账与 `ctx.execution_completed` 判定仍在；
- 管线侧只剩薄委托（不留第二份实现，AGENTS.md 教义第 6、7 条）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

ROUNDS_MODULE = "continuation_rounds"


class _FakeLoop:
    """按脚本吐响应的 `predict_step`：script 每项是一次调用的返回值。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def predict_step(self, messages, tools=None, stream=False, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.script.pop(0)


def _truncated(content: str, split_chars: int = 100):
    """被长度掐断的响应。

    切点要落在护栏 A 之上（`MIN_CONTINUE_LEN`）：真实链路上每轮续写都是一大段，
    脚本若吐十几个字，命中过短护栏按设计就停——那是另一条判据的事。
    """
    cut_at = len(content) - split_chars
    return SimpleNamespace(content=content[:cut_at], finish_reason="length", tool_calls=None)


def _finished(content: str):
    return SimpleNamespace(content=content, finish_reason="stop", tool_calls=None)


def _pipeline(script, detect_loop=None):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    loop = _FakeLoop(script)
    seen = {}

    def _detect(content_list, threshold):
        seen["args"] = (list(content_list), threshold)
        return bool(detect_loop(content_list, threshold)) if detect_loop else False

    # `llm_client` 是只读 property（走 agent_ref）：替身必须挂在 agent 上
    agent = SimpleNamespace(
        detect_content_loop=_detect,
        turn_count=0,
        set_current_reasoning=lambda *_a, **_k: None,
        llm_client=SimpleNamespace(config=SimpleNamespace(max_tokens=1000)),
        loop=loop,
    )
    pipeline._agent = agent
    pipeline._last_outcome = seen
    return pipeline, loop


def _ctx():
    return ChatContext(
        user_input="讲个长故事",
        context=[{"role": "user", "content": "讲个长故事"}],
        metadata={},
    )


TOOLS = [{"type": "function", "function": {"name": "demo"}}]


def test_continuationKeepsAppendingUntilStop():
    """正常路径：截断 → 续写若干轮 → stop。消息快照逐轮累积。"""
    script = [_truncated("第一段正文" * 40), _truncated("第二段正文" * 40), _finished("收尾")]
    pipeline, loop = _pipeline(list(script))
    ctx = _ctx()
    reply = asyncio.run(pipeline._auto_continue(ctx, _truncated("开头正文"), "开头正文", TOOLS))

    assert reply == "开头正文" + script[0].content + script[1].content
    assert len(loop.calls) == 3
    # 工具只在该函数第一轮带
    assert loop.calls[0]["tools"] == TOOLS
    assert all(call["tools"] is None for call in loop.calls[1:])
    # 每帧都追加了 assistant 正文 + 带 <previous-tail> 的续写提示
    second_frame = loop.calls[1]["messages"]
    assert second_frame[-2]["role"] == "assistant"
    assert second_frame[-2]["content"] == script[0].content
    assert second_frame[-1]["role"] == "user"
    assert "<previous-tail>" in second_frame[-1]["content"]
    assert ctx.execution_completed is True


def test_shortContinuationStopsTheLoop():
    """护栏 A：续写过短即停，不再追加。"""
    pipeline, loop = _pipeline([_truncated("短")])
    ctx = _ctx()
    reply = asyncio.run(pipeline._auto_continue(ctx, _truncated("开头正文"), "开头正文", TOOLS))
    assert reply == "开头正文"
    assert len(loop.calls) == 1
    assert ctx.execution_completed is False


def test_overlapGuardStopsTheLoop():
    """护栏 B：新正文开头与本轮已有尾部高度重叠即停（重复输出不拼进回复）。"""
    head = "甲" * 400
    pipeline, loop = _pipeline([_truncated(head)])
    ctx = _ctx()
    reply = asyncio.run(pipeline._auto_continue(ctx, _truncated(head), head, TOOLS))
    assert reply == head
    assert len(loop.calls) == 1


def test_semanticLoopGuardStopsTheLoop():
    """护栏 C：语义循环判定命中即停，且判据收到的是最近三轮正文。"""
    script = [_truncated(f"第{n}段正文" * 40) for n in range(5)]
    pipeline, loop = _pipeline(script, detect_loop=lambda _contents, _threshold: True)
    ctx = _ctx()
    asyncio.run(pipeline._auto_continue(ctx, _truncated("开头正文"), "开头正文", TOOLS))

    # 护栏 C 要攒满窗口才判：前两轮照常进循环，第三轮判命中、该轮正文不并入回复
    assert len(loop.calls) == 3
    contents, threshold = pipeline._last_outcome["args"]
    assert threshold == 0.8
    assert len(contents) == 3


def test_roundCeilingIsEnforced():
    """上界：`MAX_CONTINUE_ROUNDS` 真被读——把总字数上界放宽，只留轮次上界生效。"""
    from neurova.agent import continuation_rounds

    # 判重比的是开头那 200 字，语义循环判的是最近三轮全篇，
    # 故每段都用互不相同的字符填满前 200 字（重复填同一个字会命中护栏 C）
    script = [_truncated(f"{chr(0x4E00 + n)}" * 400) for n in range(200)]
    pipeline, loop = _pipeline(script)
    # 只动换算出的大数字，不动判据本身：让 len(reply) 永远够不到上界
    pipeline._agent.llm_client.config.max_tokens = 10**6
    ctx = _ctx()
    asyncio.run(pipeline._auto_continue(ctx, _truncated("开头正文"), "开头正文", TOOLS))
    assert len(loop.calls) == continuation_rounds.MAX_CONTINUE_ROUNDS


def test_charCeilingIsEnforced():
    """上界：`MAX_TOTAL_CHARS` 真被读——max_tokens*10 到顶就不再续。"""
    chunk = "字" * 3000
    script = [_truncated(f"{n}" + chunk) for n in range(50)]  # noqa: F841 - 脚本长度须超过上界
    pipeline, loop = _pipeline(script)
    ctx = _ctx()
    reply = asyncio.run(pipeline._auto_continue(ctx, _truncated("开头正文"), "开头正文", TOOLS))
    assert len(reply) < 1000 * 10 + 3001 + len("开头正文")


def test_pipelineKeepsOnlyThinDelegation():
    """同功能不留第二份实现：循环体不在管线，模块里才是实现。"""
    import inspect

    source = inspect.getsource(ChatPipeline._auto_continue)
    assert ROUNDS_MODULE in source, (
        "`ChatPipeline._auto_continue` 已不再委托到 `continuation_rounds`——"
        "要么实现被搬回管线（尺寸门禁会立刻红），要么委托断了"
    )
    assert "while (" not in source, "续写循环体又长回管线里了"
