"""对话管线的 legacy 直连调用组——**Agent Loop 不可用时的最后一跳**。

从 `chat_pipeline.py` 抽出的独立模块。抽出的理由不是"文件太长"，是那个文件被
`scripts/ci/perf_gate.py` 的 `hot-path-file-size` 点名成**每轮对话必经热路径**：
越过 160000B 之后，每加一条逻辑都在拖慢 review 与重构，而门禁自己写的处置就是
"新逻辑应抽到独立模块后再接线"。这一组正好是一整块能整体搬走的东西：

- `callLegacy`／`callLegacyNormal`／`callLegacyStream`：绕开 Loop 直接打 `llm_client`；
- `raiseForLlmErrorDict`：错误 dict → 分类异常（供应商错误守卫靠分类决定要不要重试）；
- `isApiConfigError`：API 配置类错误不 fallback。

**归属不变**：`ChatPipeline` 上仍留着同名方法作薄委托，调用点与测试面一行不用改——
搬走的是实现，不是接口（教义第 7 条：同功能先比后合，不留第二份实现各自演化）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from neurova.agent.loops.reasoning_degeneracy import (
    DEGENERATE_STREAM_STOPPED_NOTICE,
    ReasoningStreamGuard,
)
from neurova.core.logger import get_logger

if TYPE_CHECKING:  # 只为注解：实体在 chat_pipeline，反向导入会成环
    from neurova.agent.chat_pipeline import ChatContext

logger = get_logger(__name__)


async def callLegacyNormal(pipeline, ctx: "ChatContext") -> str:
    """非流式 fallback"""
    response = await pipeline.llm_client.chat(ctx.context)
    if isinstance(response, dict):
        if response.get("success"):
            raw = response.get("response", "")
            if hasattr(raw, "content"):
                reply = raw.content
            elif isinstance(raw, dict):
                reply = raw.get("content", raw.get("text", str(raw)))
            else:
                reply = str(raw)
        else:
            reply = f"[LLM Error] {response.get('error', 'Unknown error')}"
    elif hasattr(response, "content"):
        reply = response.content
    else:
        reply = str(response)
    return reply


async def callLegacyStream(pipeline, ctx: "ChatContext") -> str:
    """流式 fallback

    chat_stream 产出 LLMResponse 对象（与 _predict_stream 同契约）：
    content 字段进入回复并向 emitter 转发；错误 dict 按语义分类后抛
    LLMError（供应商错误守卫可识别，不再裸 RuntimeError）——不得把
    对象当字符串 join 掩盖真实 LLM 错误。
    """
    reply_parts = []
    emitter = ctx.event_emitter
    # ④ 流式 citation 缓冲（同 _call_loop_stream：仅本轮有句柄才启用）
    cit_buf = None
    _cit_reg = getattr(ctx, "citation_registry", None)
    if emitter is not None and _cit_reg is not None and not _cit_reg.is_empty():
        from neurova.memory.citation import StreamCitationBuffer

        cit_buf = StreamCitationBuffer(_cit_reg)
    # 退化守卫与主路共用同一份事实源。这条路不转发思考，所以退化**不会**刷屏——
    # 但它照样把输出预算吃满，而这里既没有环侧的恢复轮也没有任何交代，于是
    # 安静地花几分钟交付一个空回复（§6-397 那起事故的形状）。接守卫的实质是
    # "停止消费 + 非空交代"，不是"把思考显示出来"。
    guard = ReasoningStreamGuard()
    # 显式迭代器（与 `multi_model_client` 读取循环同一形态）：`async for` 里 break
    # 不会立刻关掉上游生成器，得自己收尾（形态 393 的教训——漏一次就把泄漏推成
    # 别处的 teardown 报错，且这里没有别处兜底）。
    _source = pipeline.llm_client.chat_stream(ctx.context)
    _iterator = _source.__aiter__()
    try:
        while True:
            try:
                chunk = await _iterator.__anext__()
            except StopAsyncIteration:
                break
            if isinstance(chunk, dict):
                if chunk.get("retry_status"):
                    # 429 重试/切换过程事件：legacy 路径无倒计时 UI，仅 reset
                    # 时清空半截回复（防重试后内容重复拼接），不透传
                    if (chunk.get("retry_status") or {}).get("reset"):
                        reply_parts.clear()
                        guard.reset()
                    continue
                if chunk.get("error"):
                    raise raiseForLlmErrorDict(chunk)
                if chunk.get("stream_status"):
                    # 静默可见性不分路径：legacy 是 claude/弱模型的实际主路，
                    # 只在这条路上哑掉就等于"换模型的人永远看不到上游静默"
                    if (
                        emitter is not None
                        and isinstance(ctx.metadata, dict)
                        and ctx.metadata.get("emit_status_events")
                    ):
                        try:
                            emitter("upstream_status", chunk["stream_status"])
                        except Exception as e:  # noqa: BLE001 - 转发失败不影响主流程
                            logger.debug("legacy 转发 upstream_status 失败: %s", e)
                continue
            content = getattr(chunk, "content", "") or ""
            if content:
                reply_parts.append(content)
                if emitter is not None:
                    try:
                        _out = cit_buf.feed(content) if cit_buf else content
                        if _out:
                            emitter("content", _out)
                    except Exception as e:  # noqa: BLE001 - 转发失败不影响主流程
                        logger.debug("legacy 流式 emitter 转发失败: %s", e)
                continue
            _rtext = getattr(chunk, "reasoning_content", None)
            if _rtext:
                guard.consume(_rtext)  # 只用于判定：这条路不转发思考
                if guard.aborted:
                    logger.warning(
                        "[REASONING_DEGENERACY] legacy 流式思考退化，停止消费这一路：%r 连发 %d 次",
                        guard.found.unit, guard.found.repeats,
                    )
                    break
    finally:
        _aclose = getattr(_source, "aclose", None)
        if _aclose is not None:
            try:
                await _aclose()
            except Exception as e:  # noqa: BLE001 - 收尾关闭失败不该打断本轮
                logger.debug("legacy 上游流关闭失败（收尾）: %s", e)
    if cit_buf is not None and emitter is not None:
        try:
            _tail = cit_buf.flush()
            if _tail:
                emitter("content", _tail)
        except Exception:  # noqa: BLE001
            logger.debug("citation 缓冲结清失败", exc_info=True)
    body = "".join(reply_parts)
    if guard.aborted and not body.strip():
        # 空气泡禁令不分路径：截断了就得留下一句为什么没有正文
        body = DEGENERATE_STREAM_STOPPED_NOTICE
        if emitter is not None:
            try:
                emitter("content", body)
            except Exception as e:  # noqa: BLE001 - 交代发不出去也不该打断收尾
                logger.debug("legacy 退化交代转发失败: %s", e)
    return body


def raiseForLlmErrorDict(chunk: Dict) -> Exception:
    """错误 dict → 分类异常（供应商错误守卫据此不再 fallback 重撞坏模型）。

    `error_type` 五类标准键（multi_model_client 流内编码生产端）优先；
    消息兜底兼容无类型历史 dict。
    """
    from neurova.llm_client import (
        LLMAuthError,
        LLMBadRequestError,
        LLMConnectionError,
        LLMError,
        LLMRateLimitError,
        LLMServiceUnavailableError,
    )

    raw = str(chunk.get("error") or "")
    message = f"LLM 流式调用失败: {chunk.get('error')}"
    error_type = str(chunk.get("error_type") or "")
    typed = {
        "rate_limited": LLMRateLimitError,
        "service_unavailable": LLMServiceUnavailableError,
        "connection_failed": LLMConnectionError,
        "auth_failed": LLMAuthError,
        "bad_request": LLMBadRequestError,
    }
    cls = typed.get(error_type)
    if cls is not None:
        return cls(message)
    low = raw.lower()
    if "404" in low or "not found" in low or "not_found" in low:
        return LLMBadRequestError(message)
    if "429" in low or "rate limit" in low or "too many requests" in low or "限流" in raw:
        return LLMRateLimitError(message)
    if "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low:
        return LLMAuthError(message)
    if "connect" in low or "timeout" in low or "connection" in low:
        return LLMConnectionError(message)
    return LLMError(message)


def isApiConfigError(exc: Exception) -> bool:
    """判断是否为 API 配置类错误（不应 fallback）"""
    try:
        from openai import AuthenticationError, BadRequestError

        if isinstance(exc, (BadRequestError, AuthenticationError)):
            return True
    except ImportError:
        pass
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status in (400, 401, 403)

