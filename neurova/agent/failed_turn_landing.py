"""失败轮的会话落点——**这一轮以什么收场，读侧必须看得见**。

从 `chat_pipeline.py` 抽出的独立模块。抽出的理由与 `agent/legacy_call.py` 同源：
那个文件被 `scripts/ci/perf_gate.py` 的 `hot-path-file-size` 点名成每轮对话必经
热路径，越过 160000B 之后每加一条逻辑都在拖慢 review 与重构，而门禁自己写的
处置就是"新逻辑应抽到独立模块后再接线"。

为什么这件事必须存在：后处理（含唯一的会话写点 `post_chat_pipeline._step_save_session`）
只在正常收尾路径上被调，LLM 抛错时异常从 `_step_llm_call` 就离开了管线——于是盘上
只剩提前落好的 user 一条，刷新后的页面挂着"本轮仍在生成中"永远等不到终态。

**归属不变**：`ChatPipeline` 上留同名薄委托，调用点与测试面一行不用改——搬走的
是实现，不是接口（教义第 7 条：同功能先比后合，不留第二份实现各自演化）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neurova.core.logger import get_logger

if TYPE_CHECKING:  # 只为注解：实体在 chat_pipeline，反向导入会成环
    from neurova.agent.chat_pipeline import ChatContext

logger = get_logger(__name__)


async def landFailedTurn(pipeline, ctx: "ChatContext", exc: BaseException) -> None:
    """失败轮的会话落点：这一轮结束了，而且是以失败结束的。

    教义第 2 条：这是**诚实形态**，不是把失败兜成成功——异常照旧外抛，SSE 的
    `error` 帧与 run 台账的 `failed` 终态一概不变；这里只是额外让读侧能看到
    "这一轮以什么收场"。落点走既有单点（`_step_save_session`，同一份围栏与
    owner 口径），不另起第二份写会话的代码。本函数自身失败不外抛、只点名——
    故障路径上的新代码一旦自己抛错，就会顶掉真因。
    """
    if ctx.post_chat_ran or not ctx.save_memory:
        return
    post = pipeline.post_chat_pipeline
    if post is None:
        logger.warning("失败轮无法落点：后处理管线未初始化（本轮盘上仍只有 user）")
        return
    reason = str(exc) or type(exc).__name__

    if isinstance(exc, __import__("asyncio").CancelledError):
        text = f"⚠️ 本轮被中止（未生成回复）：{reason}"
    else:
        text = f"⚠️ 未能生成回复：{reason}"
    try:
        await post._step_save_session(
            ctx.user_input,
            text,
            ctx.session_id,
            ctx.save_memory,
            ctx.metadata,
            writer_claim=ctx.writer_claim,
            user_already_persisted=ctx.user_message_persisted,
        )
    except BaseException as landExc:  # noqa: BLE001 - 落点失败不得顶掉真因
        logger.warning("失败轮落点未成（本轮读侧仍看不到终态）: %s", landExc)
