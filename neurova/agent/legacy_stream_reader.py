# -*- coding: utf-8 -*-
"""legacy 流式读取循环（与环侧同一份退化守卫、同一份错误分类）。

`chat_pipeline._call_legacy_stream` 是 Loop 不可用或 Loop 抛非 LLM 错误后的
兜底路径，生产有两个真入口。它的读取循环与环侧的 `predict_step` 是同构的
消费端：都吃 `LLMResponse` 分片、都要「重试事件重置半截回复」「静默状态可见」
「思考退化即停止消费」「错误 dict 转分类异常」。

第 6 条纪律要求这两处不许各写一份判定——分类走 `BaseAgentLoop._raise_for_error_dict`，
退化判定与收尾文案走 `reasoning_degeneracy`，本模块只负责把它们按顺序串起来。
"""

from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.reasoning_degeneracy import (
    DEGENERATE_STREAM_STOPPED_NOTICE,
    ReasoningStreamGuard,
)

logger = get_logger(__name__)


class LegacyStreamReader:
    """把 `llm_client.chat_stream` 的分片消费成本轮正文。

    - `retry_status.reset`：清空半截回复（防重试后内容重复拼接）并重置退化判定
    - `error`：`BaseAgentLoop._raise_for_error_dict` 分类后抛（供应商错误守卫可识别）
    - `stream_status`：仅在本轮要求转发时让出 `upstream_status` 事件
    - `content`：进正文并经 citation 缓冲转发
    - `reasoning_content`：**只用于判定**，这条路不转发思考；判定退化即停止消费
    """

    def __init__(self, emitter: Any = None, citationBuffer: Any = None) -> None:
        self._emitter = emitter
        self._citationBuffer = citationBuffer
        self._parts: List[str] = []
        self.guard = ReasoningStreamGuard()

    def _emit(self, kind: str, payload: Any, note: str) -> None:
        if self._emitter is None:
            return
        try:
            self._emitter(kind, payload)
        except Exception as exc:  # noqa: BLE001 - 转发失败不影响主流程
            logger.debug("%s: %s", note, exc)

    async def consume(self, source: Any, ctx: Any) -> Tuple[str, bool]:
        """读完这一路。返回 (正文, 是否提前收尾)。

        提前收尾指「退化判定命中而主动停止消费」——收尾必须自己关上游
        （`async for` 里 break 不会关；形态 393 的教训，且这里没有别处兜底）。
        """
        iterator = source.__aiter__()
        try:
            while True:
                try:
                    chunk = await iterator.__anext__()
                except StopAsyncIteration:
                    break
                if isinstance(chunk, dict):
                    self._consumeEvent(chunk, ctx)
                    continue
                content = getattr(chunk, "content", "") or ""
                if content:
                    self._parts.append(content)
                    if self._emitter is not None:
                        buffered = (
                            self._citationBuffer.feed(content)
                            if self._citationBuffer is not None
                            else content
                        )
                        if buffered:
                            self._emit("content", buffered, "legacy 流式 emitter 转发失败")
                    continue
                reasoning = getattr(chunk, "reasoning_content", None)
                if reasoning:
                    self.guard.consume(reasoning)  # 只用于判定：这条路不转发思考
                    if self.guard.aborted:
                        logger.warning(
                            "[REASONING_DEGENERACY] legacy 流式思考退化，停止消费这一路：%r 连发 %d 次",
                            self.guard.found.unit,
                            self.guard.found.repeats,
                        )
                        break
            aborted = self.guard.aborted
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as exc:  # noqa: BLE001 - 收尾关闭失败不该打断本轮
                    logger.debug("legacy 上游流关闭失败（收尾）: %s", exc)
        return "".join(self._parts), aborted

    def _consumeEvent(self, chunk: Dict[str, Any], ctx: Any) -> None:
        """消费事件型分片（错误/重试/静默状态），不产出正文。"""
        if chunk.get("retry_status"):
            # 429 重试/切换过程事件：legacy 路径无倒计时 UI，仅 reset
            # 时清空半截回复（防重试后内容重复拼接），不透传
            if (chunk.get("retry_status") or {}).get("reset"):
                self._parts.clear()
                self.guard.reset()
            return
        if chunk.get("error"):
            raise BaseAgentLoop._raise_for_error_dict(chunk)
        if chunk.get("stream_status") and self._emitter is not None:
            # 静默可见性不分路径：legacy 是 claude/弱模型的实际主路，
            # 只在这条路上哑掉就等于"换模型的人永远看不到上游静默"
            if (getattr(ctx, "metadata", None) or {}).get("emit_status_events"):
                self._emit(
                    "upstream_status", chunk["stream_status"], "legacy 转发 upstream_status 失败"
                )

    def finish(self, citationTail: Optional[str], body: str) -> str:
        """结清 citation 缓冲，并在退化截断且无正文时留下一句交代（空气泡禁令）。"""
        if citationTail:
            self._emit("content", citationTail, "legacy citation 尾片转发失败")
        if self.guard.aborted and not body.strip():
            self._emit("content", DEGENERATE_STREAM_STOPPED_NOTICE, "legacy 退化交代转发失败")
            return DEGENERATE_STREAM_STOPPED_NOTICE
        return body
