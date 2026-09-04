"""VoicePrecheck — 渠道语音消息预转写（P1-12，OpenClaw 音频预检启发）

OC 语义：「音频预检——先转录再判断是否需要 @ 提及，群语音消息不漏」。
语音消息在各渠道解析层只留下 "[语音]" 占位，@提及/关键词判定都拿不到真实
内容。本模块在 ChannelManager 收口处（handler 链之前）把带 audio_bytes 的
voice/audio 消息先转写为文本，替换占位——下游 @提及判定、关键词路由、
agent 记忆链路拿到的都是真实文本。

纪律：
- 转写失败/超时一律降级保留占位并标注 metadata，绝不阻断消息处理链；
- 无 audio_bytes 的消息行为完全不变（适配器送字节即自动启用，增量扩展点）；
- 原始 audio_bytes 保留在 metadata，agent 侧语音链路（agent_core）兜底不受影响。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 语音消息类型白名单（各渠道统一标记 voice；feishu 原生用 audio）
_VOICE_TYPES = {"voice", "audio"}
# 预转写超时（秒）：群语音通常 <60s，本地 funasr 推理秒级；超时即降级占位
_TRANSCRIBE_TIMEOUT_SECONDS = 20.0


def _get_asr_transcriber() -> Callable[..., Any]:
    """返回 ASR 转写协程函数（延迟导入，测试可 patch 此函数替换依赖）。

    与 /audio/transcribe 端点同口径：VoiceEngine 优先，降级 ASRManager。
    """
    from neurova.api.endpoints.audio import _get_asr_manager

    manager = _get_asr_manager()
    if manager is None or not hasattr(manager, "transcribe"):
        raise RuntimeError("ASR 不可用")
    return manager.transcribe


async def transcribe_voice_message(message):
    """对语音消息做预转写（原对象原地修改并返回）。

    条件：message_type ∈ {voice, audio} 且 metadata 带 audio_bytes。
    成功 → content 替换为转写文本 + metadata["voice_transcribed"]=True；
    失败 → 保留占位 + metadata["voice_transcribe_failed"]=原因。
    """
    mtype = (getattr(message, "message_type", "") or "").lower()
    if mtype not in _VOICE_TYPES:
        return message

    metadata: Dict[str, Any] = getattr(message, "metadata", None) or {}
    audio_bytes = metadata.get("audio_bytes")
    if not audio_bytes:
        # 适配器未送字节：保持历史行为（"[语音]" 占位直通）
        return message

    try:
        transcriber = _get_asr_transcriber()
        result = await asyncio.wait_for(
            transcriber(audio_bytes), timeout=_TRANSCRIBE_TIMEOUT_SECONDS
        )
        text = ""
        if isinstance(result, dict):
            text = (result.get("text") or "").strip()
        if text:
            message.content = text
            metadata["voice_transcribed"] = True
            metadata["voice_transcript"] = text
            logger.info("渠道语音预转写成功: channel=%s, len=%s", message.channel_type, len(text))
        else:
            metadata["voice_transcribe_failed"] = "empty_result"
            logger.warning("渠道语音预转写空结果，保留占位: channel=%s", message.channel_type)
    except asyncio.TimeoutError:
        metadata["voice_transcribe_failed"] = "timeout"
        logger.warning("渠道语音预转写超时（%ss），保留占位", _TRANSCRIBE_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001 - 预检故障绝不阻断消息链
        metadata["voice_transcribe_failed"] = str(e)[:200]
        logger.warning("渠道语音预转写失败，保留占位: %s", e)

    message.metadata = metadata
    return message
