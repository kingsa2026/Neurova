from __future__ import annotations

"""
生成接口 - Generation Endpoint

功能:
1. 文本生成 (POST /api/v1/generation/text)
2. 图像生成 (POST /api/v1/generation/image)
3. 音频生成 (POST /api/v1/generation/audio)
4. 视频生成 (POST /api/v1/generation/video)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.endpoints import get_agent_instance, get_app_state

logger = get_logger(__name__)

router = APIRouter()


class TextGenerationRequest(BaseModel):
    """文本生成请求"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    max_tokens: int = Field(default=1000, description="最大 token 数")
    temperature: float = Field(default=0.7, description="温度参数")
    stream: bool = Field(default=False, description="是否流式输出")


class ImageGenerationRequest(BaseModel):
    """图像生成请求"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    width: int = Field(default=512, description="图像宽度")
    height: int = Field(default=512, description="图像高度")
    num_images: int = Field(default=1, description="生成数量")


class AudioGenerationRequest(BaseModel):
    """音频生成请求"""

    text: str = Field(..., description="文本内容")
    model: Optional[str] = Field(default=None, description="指定模型")
    voice: str = Field(default="default", description="语音")
    speed: float = Field(default=1.0, description="语速")


class VideoGenerationRequest(BaseModel):
    """视频生成请求"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    duration: int = Field(default=5, description="视频时长(秒)")
    resolution: str = Field(default="720p", description="分辨率")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    return get_agent_instance(agent_id)


@router.post("/text")
async def generate_text(request: Request, body: TextGenerationRequest):
    """文本生成"""
    request_id = _get_request_id(request)

    agent = _get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not available")

    try:
        # 使用 Agent 的 chat 方法进行文本生成
        response = await agent.chat(
            user_input=body.prompt,
            metadata={
                "history": [],
                "generation_type": "text",
                "max_tokens": body.max_tokens,
                "temperature": body.temperature,
            },
        )

        return {
            "code": 0,
            "data": {
                "text": response,
                "model": body.model or "auto",
                "request_id": request_id,
            },
        }
    except Exception as e:
        logger.error(f"Text generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@router.post("/image")
async def generate_image(request: Request, body: ImageGenerationRequest):
    """图像生成"""
    request_id = _get_request_id(request)

    # TODO: 实现图像生成
    return {
        "code": 0,
        "data": {
            "message": "Image generation not yet implemented",
            "prompt": body.prompt,
            "request_id": request_id,
        },
    }


@router.post("/audio")
async def generate_audio(request: Request, body: AudioGenerationRequest):
    """音频生成（TTS 语音合成）"""
    from fastapi.responses import Response

    request_id = _get_request_id(request)

    try:
        state = get_app_state()

        # 优先使用 VoiceEngine 统一接口
        voice_engines = state.get("voice_engines", {}) if state else {}
        tts_voice_engine = voice_engines.get("tts")

        if tts_voice_engine and tts_voice_engine.is_available():
            result = await tts_voice_engine.process(
                input_data=body.text,
                operation="synthesize",
                voice=body.voice,
                speed=body.speed,
            )

            if result.error:
                return {
                    "code": -1,
                    "message": result.error,
                    "data": {"request_id": request_id},
                }

            if not result.audio_data:
                return {
                    "code": -1,
                    "message": "合成失败",
                    "data": {"request_id": request_id},
                }

            return Response(
                content=result.audio_data,
                media_type="audio/wav",
                headers={"X-Request-ID": request_id},
            )

        # 降级到旧的 TTSManager
        tts_manager = state.get("tts_manager") if state else None

        if not tts_manager or not tts_manager.is_initialized:
            return {
                "code": -1,
                "message": "TTS 引擎未就绪",
                "data": {"request_id": request_id},
            }

        audio_bytes = await tts_manager.synthesize(body.text, voice=body.voice, speed=body.speed)

        if not audio_bytes:
            return {
                "code": -1,
                "message": "合成失败",
                "data": {"request_id": request_id},
            }

        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"X-Request-ID": request_id},
        )

    except Exception as e:
        logger.error(f"Audio generation error: {e}", exc_info=True)
        return {
            "code": -1,
            "message": f"Audio generation failed: {str(e)}",
            "data": {"request_id": request_id},
        }


@router.post("/video")
async def generate_video(request: Request, body: VideoGenerationRequest):
    """视频生成"""
    request_id = _get_request_id(request)

    # TODO: 实现视频生成
    return {
        "code": 0,
        "data": {
            "message": "Video generation not yet implemented",
            "prompt": body.prompt,
            "request_id": request_id,
        },
    }
