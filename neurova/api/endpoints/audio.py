"""
Audio API - 音频端点

功能：
1. TTS 语音合成 (POST /api/v1/audio/synthesize)
2. TTS 流式合成 (POST /api/v1/audio/synthesize-stream)
3. 语音识别 ASR (POST /api/v1/audio/transcribe)
4. 音频理解 (POST /api/v1/audio/understand)
5. 音频描述 (POST /api/v1/audio/caption)
6. 引擎状态 (GET /api/v1/audio/status)
"""

import base64
import io
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


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


class UnderstandRequest(BaseModel):
    """音频理解请求"""
    query: str = Field(default="这段音频说了什么？", description="关于音频的问题")


class AudioAPIResponse(BaseModel):
    """统一 API 响应"""
    code: int = 0
    message: str = "success"
    data: Optional[dict] = None
    request_id: str = ""


def _get_tts_manager():
    """获取 TTS Manager"""
    from neurova.api.endpoints import get_app_state
    state = get_app_state()
    if state:
        return state.get("tts_manager")
    return None


def _get_audio_engine():
    """获取 MOSS Audio Engine"""
    from neurova.api.endpoints import get_app_state
    state = get_app_state()
    if state:
        return state.get("audio_engine")
    return None


@router.post("/synthesize")
async def synthesize_speech(request: Request, body: SynthesizeRequest):
    """
    TTS 语音合成

    将文本合成为语音，返回音频字节流。
    支持声音克隆（提供参考音频和文本）。
    """
    request_id = str(uuid.uuid4())[:8]

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

        return Response(
            content=audio_bytes,
            media_type="audio/wav",
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
    audio_engine = _get_audio_engine()
    if not audio_engine or not audio_engine.initialized:
        raise HTTPException(status_code=503, detail="音频理解引擎未就绪（需要 GPU）")

    try:
        audio_bytes = await audio_file.read()
        result = await audio_engine.transcribe(audio_bytes, language=language)

        return {
            "code": 0,
            "data": result,
            "request_id": str(uuid.uuid4())[:8],
        }

    except Exception as e:
        logger.error(f"转写失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"转写失败: {str(e)}")


@router.post("/understand")
async def understand_audio(
    request: Request,
    audio_file: UploadFile = File(..., description="音频文件"),
    query: str = Form(default="这段音频说了什么？", description="问题"),
):
    """
    音频理解 + 问答

    对音频内容进行理解和问答。
    """
    audio_engine = _get_audio_engine()
    if not audio_engine or not audio_engine.initialized:
        raise HTTPException(status_code=503, detail="音频理解引擎未就绪（需要 GPU）")

    try:
        audio_bytes = await audio_file.read()
        result = await audio_engine.understand(audio_bytes, query=query)

        return {
            "code": 0,
            "data": result,
            "request_id": str(uuid.uuid4())[:8],
        }

    except Exception as e:
        logger.error(f"音频理解失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"理解失败: {str(e)}")


@router.post("/caption")
async def caption_audio(
    request: Request,
    audio_file: UploadFile = File(..., description="音频文件"),
):
    """
    音频描述

    描述音频内容，包括说话人特征、情感、背景声音等。
    """
    audio_engine = _get_audio_engine()
    if not audio_engine or not audio_engine.initialized:
        raise HTTPException(status_code=503, detail="音频理解引擎未就绪（需要 GPU）")

    try:
        audio_bytes = await audio_file.read()
        result = await audio_engine.caption(audio_bytes)

        return {
            "code": 0,
            "data": result,
            "request_id": str(uuid.uuid4())[:8],
        }

    except Exception as e:
        logger.error(f"音频描述失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"描述失败: {str(e)}")


@router.get("/status")
async def audio_status():
    """
    音频系统状态

    返回 TTS 和 Audio 引擎的状态信息。
    """
    tts = _get_tts_manager()
    audio_engine = _get_audio_engine()

    tts_stats = tts.stats if tts else {"initialized": False}
    audio_stats = audio_engine.stats if audio_engine else {"initialized": False}

    return {
        "code": 0,
        "data": {
            "tts": tts_stats,
            "audio_understanding": audio_stats,
            "timestamp": time.time(),
        },
    }


@router.get("/engines")
async def list_engines():
    """列出所有可用的音频引擎"""
    tts = _get_tts_manager()
    audio_engine = _get_audio_engine()

    engines = []
    if tts:
        engines.append({
            "name": "tts",
            "type": "text-to-speech",
            "engine": tts.get_engine_name(),
            "initialized": tts.is_initialized,
        })
    if audio_engine:
        engines.append({
            "name": "audio-understanding",
            "type": "speech-to-text",
            "engine": audio_engine._model_name,
            "initialized": audio_engine._initialized,
        })

    return {
        "code": 0,
        "data": engines,
    }
