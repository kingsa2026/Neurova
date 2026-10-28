"""截断续写循环——对 `finish_reason=length` 的回复原地续写到不再截断。

从 `chat_pipeline.py` 整块搬出的第二笔。第一笔（`continuation_hint`）只带走两个
纯函数，续写循环本身还在管线里，于是文件停在门禁红线之上：`scripts/ci/perf_gate.py`
的 `hot-path-file-size` 报 `chat_pipeline.py 160523B > 160000B`。门禁自己写的
处置就是"新逻辑应抽到独立模块后再接线"，这一块正好只吃 `loop`、`agent` 的语义
循环判据与本轮上下文快照，整块可搬。

**归属不变**：`ChatPipeline._auto_continue` 仍留着同名方法作薄委托，调用点与
测试面一行不用改——搬走的是实现，不是接口（AGENTS.md 教义第 7 条）。

## 三条护栏与两条上界（读代码前先知道这里在防什么）

- 护栏 A 过短：续写只吐几个字就停，拼上去等于把空气泡拉长；
- 护栏 B 重叠：新一轮开头与已有尾部高度重合，说明模型在复述，拼上去就是自重复；
- 护栏 C 语义循环：最近三轮正文互相高度相似，靠 `agent.detect_content_loop` 判定；
- `MAX_CONTINUE_ROUNDS` / `MAX_TOTAL_CHARS`：单轮对话的续写次数与总字数上界，
  两者都在 `while` 条件里被读（不是声明完就没人看的那种常量）。

工具只在**第一轮**带上：续写轮再给工具，模型会把已经执行过的副作用再执行一遍。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from neurova.agent.continuation_hint import build_continue_hint
from neurova.core.logger import get_logger

if TYPE_CHECKING:  # 只为注解：实体在 chat_pipeline，反向导入会成环
    from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

logger = get_logger(__name__)

#: 单次 `_auto_continue` 最多续写多少轮（防「每次都被截断」把一轮对话拖成几十次调用）。
MAX_CONTINUE_ROUNDS = 100
#: 重叠判定的取样长度与阈值：新正文开头 / 已有尾部各取这么多字符比字面重合率。
OVERLAP_CHECK_LEN = 200
OVERLAP_THRESHOLD = 0.6
#: 过短护栏：续写正文去空白后短于这个长度即视为「没东西可续」。
MIN_CONTINUE_LEN = 10
#: 续写提示里带回的上一轮尾部片段长度。
TAIL_CONTEXT_CHARS = 800
#: 语义循环判定的滑动窗口与相似度阈值。
SIMILARITY_WINDOW = 3
SIMILARITY_THRESHOLD = 0.8
#: 总字数上界的默认值——`llm_client.config.max_tokens` 缺席或为 None 时用它。
DEFAULT_MAX_TOKENS = 8192
#: 总字数 = 单次输出预算 × 该倍数（超过就认为这一轮已经写得够多）。
TOTAL_CHARS_MULTIPLIER = 10


def _is_length_truncated(finish_reason: Any) -> bool:
    """完成态是否属于「被长度掐断」。

    判据表留在管线（`chat_pipeline._TRUNCATED_FINISH_REASONS`）：它同时被流式收尾与
    非流式重试读，搬过来就成了第二份定义。
    """
    from neurova.agent.chat_pipeline import _is_length_truncated as _pipelineJudge

    return _pipelineJudge(finish_reason)


def _recordOutcome(ctx: Any, finish_reason: Any) -> None:
    """收尾记账（拒答事件 + `finish_reason` 写回 metadata），实现在管线。"""
    from neurova.agent.chat_pipeline import _recordFinishOutcome, _recordFinishReason

    _recordFinishOutcome(finish_reason)
    _recordFinishReason(ctx, finish_reason)


def _totalCharsBudget(pipeline: "ChatPipeline") -> int:
    """总字数上界。`max_tokens=None` 时也回落默认值（None*10 会直接 TypeError）。"""
    budget = getattr(getattr(pipeline, "llm_client", None), "config", None)
    max_tokens = getattr(budget, "max_tokens", None) or DEFAULT_MAX_TOKENS
    return max_tokens * TOTAL_CHARS_MULTIPLIER


def _buildFrame(hint: str, tail_text: str) -> str:
    """续写提示 + 带回的尾部片段（尾部为空时只发提示本身）。"""
    if not tail_text:
        return hint
    return f"{hint}\n\n<previous-tail>\n{tail_text}\n</previous-tail>"


def _tooSimilar(previous: str, fresh: str) -> bool:
    """护栏 B：新正文开头与本轮已有尾部字面重合率过高（模型在复述）。"""
    if not previous or not fresh:
        return False
    matches = sum(1 for left, right in zip(previous, fresh) if left == right)
    return matches / max(len(previous), 1) > OVERLAP_THRESHOLD


async def runContinuationRounds(
    pipeline: "ChatPipeline",
    ctx: "ChatContext",
    response: Any,
    reply: str,
    tools_for_llm: Optional[List],
) -> str:
    """把被长度掐断的回复续写到不再截断（或撞上护栏/上界）。"""
    hint = build_continue_hint(ctx.user_input, reply)
    max_total_chars = _totalCharsBudget(pipeline)

    continue_round = 0
    recent_contents: List[str] = []
    ctx_snapshot = list(ctx.context)

    while (
        response
        and _is_length_truncated(getattr(response, "finish_reason", ""))
        and not getattr(response, "tool_calls", None)
        and continue_round < MAX_CONTINUE_ROUNDS
        and len(reply) < max_total_chars
    ):
        continue_round += 1
        tail_text = (response.content or "")[-TAIL_CONTEXT_CHARS:].strip()

        full_hint = _buildFrame(hint, tail_text)
        ctx_snapshot.append({"role": "assistant", "content": response.content})
        ctx_snapshot.append({"role": "user", "content": full_hint})

        # 工具只给第一轮：续写轮再给，模型会把已执行过的副作用再跑一遍。
        round_tools: Optional[List] = tools_for_llm if continue_round == 1 else None

        logger.info(
            "截断续写第 %s 轮 (tools=%s, 已输出 %s 字符)",
            continue_round,
            "on" if round_tools else "off",
            len(reply),
        )

        response = await pipeline.loop.predict_step(
            messages=ctx_snapshot,
            tools=round_tools,
            stream=False,
            thinking_effort=pipeline._effort_of(ctx),
            thinking_enabled=pipeline._thinking_flag_of(ctx),
            thinking_budget=pipeline._thinking_budget_of(ctx),
        )
        new_content = getattr(response, "content", "") if response else ""

        # 护栏 A: 续写过短
        if not new_content or len(new_content.strip()) < MIN_CONTINUE_LEN:
            break

        # 护栏 B: 重叠检测
        prev_tail = reply[-OVERLAP_CHECK_LEN:] if len(reply) >= OVERLAP_CHECK_LEN else reply
        if _tooSimilar(prev_tail, new_content[:OVERLAP_CHECK_LEN]):
            break

        # 护栏 C: 语义循环检测
        recent_contents.append(new_content[:500])
        if len(recent_contents) > SIMILARITY_WINDOW:
            recent_contents.pop(0)
        if len(recent_contents) >= SIMILARITY_WINDOW:
            if pipeline._agent.detect_content_loop(recent_contents, SIMILARITY_THRESHOLD):
                break

        reply += new_content

    _recordOutcome(ctx, getattr(response, "finish_reason", None))
    ctx.execution_completed = getattr(response, "finish_reason", None) in {"stop", "end_turn"}
    return reply

