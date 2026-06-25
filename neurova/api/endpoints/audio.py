"""
Audio API - 音频端点

功能：
1. TTS 语音合成 (POST /api/v1/audio/synthesize)
2. TTS 流式合成 (POST /api/v1/audio/synthesize-stream)
3. 语音识别 ASR (POST /api/v1/audio/transcribe)
4. 引擎状态 (GET /api/v1/audio/status)
5. 引擎列表 (GET /api/v1/audio/engines)
"""

import base64
from neurova.core.logger import get_logger
import time
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()

# 模块级导入（避免重复导入）
from neurova.api.endpoints import get_app_state


class SynthesizeRequest(BaseModel):
    """TTS 合成请求"""

    text: str = Field(..., description="要合成的文本", max_length=5000)
    voice: Optional[str] = Field(default=None, description="音色名称")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")
    format: str = Field(default="wav", description="音频格式 (wav/mp3)")
    # 声音克隆参数
    voice_ref_audio: Optional[str] = Field(default=None, description="参考音频 base64 (WAV)")
    voice_ref_text: Optional[str] = Field(default=None, description="参考文本")


class TranscribeRequest(BaseModel):
    """ASR 转写请求"""

    language: str = Field(default="zh", description="语言 (zh/en/auto)")


class AudioAPIResponse(BaseModel):
    """统一 API 响应"""

    code: int = 0
    message: str = "success"
    data: Optional[dict] = None
    request_id: str = ""


def _get_voice_engine(engine_type: str):
    """获取 VoiceEngine

    Args:
        engine_type: 引擎类型 ("tts" 或 "asr")

    Returns:
        VoiceEngine 或 None
    """
    state = get_app_state()
    if state and isinstance(state, dict):
        voice_engines = state.get("voice_engines", {})
        if voice_engines and engine_type in voice_engines:
            return voice_engines[engine_type]
    return None


def _get_tts_manager():
    """获取 TTS Manager (向后兼容)"""
    # 优先使用 VoiceEngine
    voice_engine = _get_voice_engine("tts")
    if voice_engine:
        return voice_engine

    # 降级到旧的 TTSManager
    state = get_app_state()
    if state:
        return state.get("tts_manager")
    return None


def _get_asr_manager():
    """获取 ASR Manager (向后兼容)"""
    # 优先使用 VoiceEngine
    voice_engine = _get_voice_engine("asr")
    if voice_engine:
        return voice_engine

    # 降级到旧的 ASRManager
    state = get_app_state()
    if state:
        return state.get("asr_manager")
    return None


@router.post("/synthesize")
async def synthesize_speech(request: Request, body: SynthesizeRequest):
    """
    TTS 语音合成

    将文本合成为语音，返回音频字节流。
    支持声音克隆（提供参考音频和文本）。
    """
    request_id = str(uuid.uuid4())[:8]

    # 优先使用 VoiceEngine 统一接口
    voice_engine = _get_voice_engine("tts")
    if voice_engine and voice_engine.is_available():
        try:
            # 解码参考音频
            ref_audio_bytes = None
            if body.voice_ref_audio:
                try:
                    ref_audio_bytes = base64.b64decode(body.voice_ref_audio)
                except Exception:
                    raise HTTPException(status_code=400, detail="参考音频 base64 格式错误")

            # 构建 kwargs
            kwargs = {
                "voice": body.voice,
                "speed": body.speed,
                "format": body.format,
            }
            if ref_audio_bytes:
                kwargs["voice_ref_audio"] = ref_audio_bytes
            if body.voice_ref_text:
                kwargs["voice_ref_text"] = body.voice_ref_text

            # 使用 VoiceEngine 统一接口
            result = await voice_engine.process(input_data=body.text, operation="synthesize", **kwargs)

            if result.error:
                raise HTTPException(status_code=500, detail=result.error)

            if not result.audio_data:
                raise HTTPException(status_code=500, detail="合成失败")

            # Detect audio format from magic bytes
            audio_bytes = result.audio_data
            if audio_bytes[:4] == b"RIFF":
                media_type = "audio/wav"
            elif audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3") or audio_bytes[:3] == b"ID3":
                media_type = "audio/mpeg"
            else:
                media_type = "audio/wav"

            return Response(
                content=audio_bytes,
                media_type=media_type,
                headers={
                    "X-Request-ID": request_id,
                    "X-TTS-Engine": voice_engine.get_info().get("engine_class", "unknown"),
                },
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"VoiceEngine TTS 合成失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"合成失败: {str(e)}")

    # 降级到旧的 TTSManager
    tts = _get_tts_manager()
    if not tts or not tts.is_initialized:
        raise HTTPException(status_code=503, detail="TTS 引擎未就绪")

    try:
        # 解码参考音频
        ref_audio_bytes = None
        if body.voice_ref_audio:
            try:
                ref_audio_bytes = base64.b64decode(body.voice_ref_audio)
            except Exception:
                raise HTTPException(status_code=400, detail="参考音频 base64 格式错误")

        # 合成
        kwargs = {}
        if ref_audio_bytes:
            kwargs["voice_ref_audio"] = ref_audio_bytes
        if body.voice_ref_text:
            kwargs["voice_ref_text"] = body.voice_ref_text

        audio_bytes = await tts.synthesize(body.text, **kwargs)

        if not audio_bytes:
            raise HTTPException(status_code=500, detail="合成失败")

        # Detect audio format from magic bytes
        if audio_bytes[:4] == b"RIFF":
            media_type = "audio/wav"
        elif audio_bytes[:2] == b"\xff\xfb" or audio_bytes[:2] == b"\xff\xf3" or audio_bytes[:3] == b"ID3":
            media_type = "audio/mpeg"
        else:
            media_type = "audio/wav"

        logger.info("TTS format: %s, first bytes: %s", media_type, audio_bytes[:4].hex())

        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={
                "X-Request-ID": request_id,
                "X-TTS-Engine": tts.get_engine_name() or "unknown",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS 合成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"合成失败: {str(e)}")


@router.post("/synthesize-stream")
async def synthesize_speech_stream(request: Request, body: SynthesizeRequest):
    """
    TTS 流式语音合成

    将文本流式合成为语音，返回 chunked 音频流。
    """
    tts = _get_tts_manager()
    if not tts or not tts.is_initialized:
        raise HTTPException(status_code=503, detail="TTS 引擎未就绪")

    async def audio_generator():
        async for chunk in tts.synthesize_stream(body.text):
            yield chunk

    return StreamingResponse(
        audio_generator(),
        media_type="audio/wav",
        headers={
            "X-TTS-Engine": tts.get_engine_name() or "unknown",
            "Transfer-Encoding": "chunked",
        },
    )


@router.post("/transcribe")
async def transcribe_audio(
    request: Request,
    audio_file: UploadFile = File(..., description="音频文件"),
    language: str = Form(default="zh", description="语言"),
):
    """
    语音识别（ASR）

    将音频文件转换为文字。
    """
    # 优先使用 VoiceEngine 统一接口
    voice_engine = _get_voice_engine("asr")
    if voice_engine and voice_engine.is_available():
        try:
            audio_bytes = await audio_file.read()

            # 使用 VoiceEngine 统一接口
            result = await voice_engine.process(input_data=audio_bytes, operation="transcribe", language=language)

            if result.error:
                raise HTTPException(status_code=500, detail=result.error)

            return {
                "code": 0,
                "data": {
                    "text": result.text,
                    "confidence": result.confidence,
                    "metadata": result.metadata,
                },
                "request_id": str(uuid.uuid4())[:8],
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"VoiceEngine ASR 转写失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"转写失败: {str(e)}")

    # 降级到旧的 ASRManager
    asr_manager = _get_asr_manager()
    if not asr_manager or not asr_manager.is_initialized:
        raise HTTPException(status_code=503, detail="ASR 引擎未就绪")

    try:
        audio_bytes = await audio_file.read()
        result = await asr_manager.transcribe(audio_bytes, language=language)

        return {
            "code": 0,
            "data": result,
            "request_id": str(uuid.uuid4())[:8],
        }

    except Exception as e:
        logger.error(f"转写失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"转写失败: {str(e)}")


@router.get("/status")
async def audio_status():
    """
    音频系统状态

    返回 TTS 和 ASR 引擎的状态信息。
    """
    # 优先使用 VoiceEngine
    tts_voice_engine = _get_voice_engine("tts")
    asr_voice_engine = _get_voice_engine("asr")

    if tts_voice_engine:
        tts_stats = {
            "initialized": tts_voice_engine.is_available(),
            "engine_info": tts_voice_engine.get_info(),
        }
    else:
        tts = _get_tts_manager()
        tts_stats = tts.stats if tts else {"initialized": False}

    if asr_voice_engine:
        asr_stats = {
            "initialized": asr_voice_engine.is_available(),
            "engine_info": asr_voice_engine.get_info(),
        }
    else:
        asr_manager = _get_asr_manager()
        asr_stats = asr_manager.stats if asr_manager else {"initialized": False}

    return {
        "code": 0,
        "data": {
            "tts": tts_stats,
            "asr": asr_stats,
            "timestamp": time.time(),
        },
    }


@router.get("/engines")
async def list_engines():
    """列出所有可用的音频引擎"""
    # 优先使用 VoiceEngine
    tts_voice_engine = _get_voice_engine("tts")
    asr_voice_engine = _get_voice_engine("asr")

    engines = []

    if tts_voice_engine:
        tts_info = tts_voice_engine.get_info()
        engines.append(
            {
                "name": "tts",
                "type": "text-to-speech",
                "engine": tts_info.get("engine_class", "unknown"),
                "initialized": tts_voice_engine.is_available(),
                "voice_engine": True,
            }
        )
    else:
        tts = _get_tts_manager()
        if tts:
            engines.append(
                {
                    "name": "tts",
                    "type": "text-to-speech",
                    "engine": tts.get_engine_name(),
                    "initialized": tts.is_initialized,
                    "voice_engine": False,
                }
            )

    if asr_voice_engine:
        asr_info = asr_voice_engine.get_info()
        engines.append(
            {
                "name": "asr",
                "type": "speech-to-text",
                "engine": asr_info.get("engine_class", "unknown"),
                "initialized": asr_voice_engine.is_available(),
                "voice_engine": True,
            }
        )
    else:
        asr_manager = _get_asr_manager()
        if asr_manager:
            engines.append(
                {
                    "name": "asr",
                    "type": "speech-to-text",
                    "engine": asr_manager.get_engine_name(),
                    "initialized": asr_manager.is_initialized,
                    "voice_engine": False,
                }
            )

    return {
        "code": 0,
        "data": engines,
    }
