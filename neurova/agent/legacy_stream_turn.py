# -*- coding: utf-8 -*-
"""legacy 流式回落这一路的读取循环（从 `chat_pipeline` 抽出）。

单独成模块：这段循环留在 `ChatPipeline` 里会让每轮对话必经的文件继续膨胀（性能门禁
对它设了尺寸上限）。边界取"与 Agent 无关的那部分"：本模块只认上游产流、事件发射器、
citation 缓冲，不 import Agent、也不 import `chat_pipeline`。

守卫与主路共用 `ReasoningStreamGuard`。这条路不转发思考，退化不刷屏，但照样把输出预算
吃满，而这里没有恢复轮也没有交代，于是安静地交付一个空回复（§6-397 的形状）。
"""
from __future__ import annotations

from typing import AsyncIterator, Callable, List, Optional

from neurova.agent.loops.reasoning_degeneracy import (
    DEGENERATE_STREAM_STOPPED_NOTICE,
    ReasoningStreamGuard,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)


async def consumeLegacyStream(
    source: AsyncIterator,
    *,
    eventEmitter: Optional[Callable] = None,
    metadata: Optional[dict] = None,
    citationRegistry=None,
    buildLLMError: Optional[Callable[[dict], Exception]] = None,
) -> str:
    """消费 legacy 上游流并聚合成正文。

    `source` 由调用方给出；`buildLLMError` 把错误 dict 分类成异常，分类口径归调用方。
    `citationRegistry` 非空且本轮有 emitter 时启用流式 citation 缓冲（同主路）。
    """
    # ④ 流式 citation 缓冲：仅本轮有句柄才启用，且缓冲必须与服务端共用同一份注册表
    citationBuffer = None
    if eventEmitter is not None and citationRegistry is not None and not citationRegistry.is_empty():
        from neurova.memory.citation import StreamCitationBuffer

        citationBuffer = StreamCitationBuffer(citationRegistry)
    replyParts: List[str] = []
    guard = ReasoningStreamGuard()
    # 显式迭代器：`async for` 里 break 不会立刻关掉上游生成器，得自己收尾（形态 393）。
    iterator = source.__aiter__()
    try:
        while True:
            try:
                chunk = await iterator.__anext__()
            except StopAsyncIteration:
                break
            if isinstance(chunk, dict):
                if chunk.get("retry_status"):
                    # 429 重试/切换过程事件：仅 reset 时清空半截回复
                    if (chunk.get("retry_status") or {}).get("reset"):
                        replyParts.clear()
                        guard.reset()
                    continue
                if chunk.get("error"):
                    if buildLLMError is None:
                        raise RuntimeError(str(chunk.get("error")))
                    raise buildLLMError(chunk)
                if chunk.get("stream_status"):
                    if (
                        eventEmitter is not None
                        and isinstance(metadata, dict)
                        and metadata.get("emit_status_events")
                    ):
                        try:
                            eventEmitter("upstream_status", chunk["stream_status"])
                        except Exception as e:  # noqa: BLE001 - 转发失败不影响主流程
                            logger.debug("legacy 转发 upstream_status 失败: %s", e)
                continue
            content = getattr(chunk, "content", "") or ""
            if content:
                replyParts.append(content)
                if eventEmitter is not None:
                    try:
                        outText = citationBuffer.feed(content) if citationBuffer else content
                        if outText:
                            eventEmitter("content", outText)
                    except Exception as e:  # noqa: BLE001 - 转发失败不影响主流程
                        logger.debug("legacy 流式 emitter 转发失败: %s", e)
                continue
            reasoningText = getattr(chunk, "reasoning_content", None)
            if reasoningText:
                guard.consume(reasoningText)  # 只判定，不转发
                if guard.aborted:
                    logger.warning(
                        "[REASONING_DEGENERACY] legacy 流式思考退化，停止消费这一路：%r 连发 %d 次",
                        guard.found.unit, guard.found.repeats,
                    )
                    break
    finally:
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception as e:  # noqa: BLE001 - 收尾失败不该打断本轮
                logger.debug("legacy 上游流关闭失败: %s", e)
    if citationBuffer is not None and eventEmitter is not None:
        try:
            tailText = citationBuffer.flush()
            if tailText:
                eventEmitter("content", tailText)
        except Exception:  # noqa: BLE001
            logger.debug("citation 缓冲结清失败", exc_info=True)
    body = "".join(replyParts)
    if guard.aborted and not body.strip():
        # 空气泡禁令不分路径：截断了就要留一句为什么没有正文
        body = DEGENERATE_STREAM_STOPPED_NOTICE
        if eventEmitter is not None:
            try:
                eventEmitter("content", body)
            except Exception as e:  # noqa: BLE001 - 交代发不出去也不该打断收尾
                logger.debug("legacy 退化交代转发失败: %s", e)
    return body
