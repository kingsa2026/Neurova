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
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _route_model_for_request(request_type: str):
    """按请求类型经 LLMRouter 自动选模型（model=auto/缺省时）。

    Returns:
        (model_id, provider_name)；路由不可用时 (None, None)。
    """
    try:
        from neurova.llm.llm_router import RequestType, select_model_for_request

        rt = RequestType(request_type)
        result = select_model_for_request(rt)
        if result is None:
            return None, None
        return result.model, result.provider_name
    except Exception as e:
        logger.warning("Auto route failed (%s), degrade to agent default: %s", request_type, e)
        return None, None


class TextGenerationRequest(BaseModel):
    """文本生成请求"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    max_tokens: int = Field(default=1000, description="最大 token 数")
    temperature: float = Field(default=0.7, description="温度参数")
    stream: bool = Field(default=False, description="是否流式输出")
    session_id: Optional[str] = Field(default=None, description="会话ID（用于历史连续性）")


class ImageGenerationRequest(BaseModel):
    """图像生成请求（B2-a：真实协议矩阵 + 按提供商凭据）"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    width: int = Field(default=1024, description="图像宽度")
    height: int = Field(default=1024, description="图像高度")
    num_images: int = Field(default=1, description="生成数量")
    protocol: Optional[str] = Field(default=None, description="协议标签 openai_compat/ark/dashscope（含中文）")
    provider_id: Optional[str] = Field(default=None, description="使用已配置服务商的凭据")
    api_key: Optional[str] = Field(default=None, description="显式凭据（优先于服务商配置）")
    base_url: Optional[str] = Field(default=None, description="显式端点")
    ref_images: list = Field(default_factory=list, description="参考图（URL 或本地路径）")
    negative_prompt: Optional[str] = Field(default=None, description="负向提示")


class AudioGenerationRequest(BaseModel):
    """音频生成请求"""

    text: str = Field(..., description="文本内容")
    model: Optional[str] = Field(default=None, description="指定模型")
    voice: str = Field(default="default", description="语音")
    speed: float = Field(default=1.0, description="语速")


class VideoGenerationRequest(BaseModel):
    """视频生成请求（B2-a：wan/seedance2/veo 异步协议 + 任务账本）"""

    prompt: str = Field(..., description="生成提示")
    model: Optional[str] = Field(default=None, description="指定模型")
    duration: int = Field(default=5, description="视频时长(秒)")
    resolution: str = Field(default="1080p", description="分辨率")
    protocol: Optional[str] = Field(default=None, description="协议标签 wan/seedance2/veo（含中文）")
    provider_id: Optional[str] = Field(default=None, description="使用已配置服务商的凭据")
    api_key: Optional[str] = Field(default=None, description="显式凭据（优先于服务商配置）")
    base_url: Optional[str] = Field(default=None, description="显式端点")
    ref_images: list = Field(default_factory=list, description="参考图/首帧（URL 或本地路径）")
    audio: Optional[bool] = Field(default=None, description="是否生成音频（wan3）")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    return get_agent_instance(agent_id)


# ── B2-b/c：按提供商凭据解析 + 媒体落盘 + 任务账本 ─────────────────────────

_GENERATION_OUTPUT_DIR = "data/generations"


def _resolve_generation_creds(
    protocol_hint: str,
    model: Optional[str],
    provider_id: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    default_base: str,
) -> "ProtocolCredentials":
    """凭据解析（B2-b）：显式凭据 > provider_id 配置 > 协议匹配服务商。"""
    from neurova.llm.generators.protocols import ProtocolCredentials

    if api_key and base_url:
        return ProtocolCredentials(api_key=api_key, base_url=base_url,
                                   model=model or "", protocol=protocol_hint or "")

    from neurova.llm.provider_manager import get_provider_manager

    manager = get_provider_manager()
    provider = manager.get_provider(provider_id) if provider_id else None
    if provider is None and not provider_id:
        # 按协议启发在启用服务商里找：base_url host 匹配
        for p in manager.list_providers(enabled_only=True):
            host = (getattr(p, "base_url", "") or "").lower()
            if ("dashscope" in host and "dashscope" in (protocol_hint or "").lower()) or (
                "volces.com" in host and ("ark" in (protocol_hint or "").lower() or "seedance" in (protocol_hint or "").lower() or "volcengine" in (protocol_hint or "").lower())
            ) or ("googleapis.com" in host and "veo" in (protocol_hint or "").lower()):
                provider = p
                break
    if provider is not None:
        try:
            from neurova.llm.providers.secret_store import decrypt_api_key

            key = decrypt_api_key(getattr(provider, "api_key", "") or "")
        except Exception:
            key = getattr(provider, "api_key", "") or ""
        if key:
            return ProtocolCredentials(
                api_key=key,
                base_url=base_url or getattr(provider, "base_url", "") or default_base,
                model=model or getattr(provider, "default_model", "") or "",
                protocol=protocol_hint or "",
            )
    # 显式 base_url 无 key（自托管网关可无鉴权）
    if base_url:
        return ProtocolCredentials(api_key="", base_url=base_url, model=model or "",
                                   protocol=protocol_hint or "")
    raise HTTPException(
        status_code=400,
        detail="缺少生成凭据：请传 api_key+base_url，或 provider_id，或先在模型页配置并启用对应服务商（填 API Key）",
    )


async def _persist_media(url_or_data: str, kind: str, task_id: str, index: int) -> str:
    """结果 URL 临时有效 → 立即下载本地化（data/generations/）。"""
    import aiohttp
    import base64 as _b64
    from pathlib import Path

    out_dir = Path(_GENERATION_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    if url_or_data.startswith("data:"):
        header, _, payload = url_or_data.partition(",")
        ext = "png" if "image" in header else ("mp4" if "video" in header else "bin")
        path = out_dir / f"{task_id}_{index}.{ext}"
        path.write_bytes(_b64.b64decode(payload))
        return str(path)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.get(url_or_data) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"产物下载失败 HTTP {resp.status}")
            content_type = resp.headers.get("content-type", "")
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                   "video/mp4": "mp4"}.get(content_type.split(";")[0], "bin")
            path = out_dir / f"{task_id}_{index}.{ext}"
            path.write_bytes(await resp.read())
    return str(path)


def _local_url(path: str, request: Request) -> str:
    """本地文件 → 可访问的静态 URL（/generation/files 挂载）。"""
    from pathlib import Path

    name = Path(path).name
    return f"/api/v1/generation/files/{name}"


@router.post("/text")
async def generate_text(request: Request, body: TextGenerationRequest):
    """文本生成（model 缺省/"auto" → LLMRouter 按 CHAT 自动路由）"""
    request_id = _get_request_id(request)

    agent = _get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not available")

    try:
        # model=auto/None：LLMRouter 按请求类型选模型；路由失败降级 agent 默认模型
        routed_model: Optional[str] = None
        routed_provider: Optional[str] = None
        requested_model = (body.model or "").strip()
        if not requested_model or requested_model.lower() == "auto":
            routed_model, routed_provider = _route_model_for_request("chat")
            effective_model = routed_model
            routed = routed_model is not None
        else:
            effective_model = requested_model
            routed = False

        # 使用 Agent 的 chat 方法进行文本生成
        # S7 修复 (B-2 #10): 不注入 "history": [],保留其他 metadata 字段,
        # 让 agent.chat() 自行从 session 恢复历史.
        response = await agent.chat(
            user_input=body.prompt,
            session_id=body.session_id,
            metadata={
                "generation_type": "text",
                "max_tokens": body.max_tokens,
                "temperature": body.temperature,
                **({"model": effective_model} if effective_model else {}),
            },
        )

        return {
            "code": 0,
            "data": {
                "text": response,
                "model": effective_model or "auto",
                "routed": routed,
                "routed_model": routed_model,
                "routed_provider": routed_provider,
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

    # B2-a/c：真实协议实现（OPENAI_COMPAT/ARK/DASHSCOPE 实测矩阵）
    from neurova.llm.generators.protocols import (
        ProtocolCredentials,
        generate_image,
        resolve_image_protocol,
    )

    protocol = resolve_image_protocol(body.protocol or "", body.model or "", body.base_url or "")
    creds = _resolve_generation_creds(
        protocol.value, body.model, body.provider_id, body.api_key, body.base_url,
        default_base="https://api.openai.com/v1",
    )
    size = f"{body.width}x{body.height}"
    try:
        result = await generate_image(
            creds, body.prompt, size=size, n=body.num_images,
            ref_images=list(body.ref_images or []),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — 诚实 5xx，不伪造成功
        logger.warning("图像生成失败: %s", e)
        raise HTTPException(status_code=502, detail=f"图像生成失败: {str(e)[:300]}")

    task_id = _get_request_id(request)
    images = []
    for i, item in enumerate(result.get("images") or []):
        try:
            path = await _persist_media(item, "image", task_id, i)
            images.append({"url": _local_url(path, request), "path": path})
        except Exception as e:  # noqa: BLE001 — 单图下载失败不影响其余
            images.append({"url": item if item.startswith("http") else "", "error": str(e)[:200]})
    if not images:
        raise HTTPException(status_code=502, detail="图像生成未返回产物")
    return {"code": 0, "message": "success", "data": {"images": images, "task_id": task_id}}


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

    # B2-a/c：wan/seedance2/veo 异步协议提交 + 持久任务账本
    import asyncio as _asyncio

    from neurova.llm.generators.protocols import (
        resolve_video_protocol,
        submit_video,
    )
    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    protocol = resolve_video_protocol(body.protocol or "", body.model or "", body.base_url or "")
    creds = _resolve_generation_creds(
        protocol.value, body.model, body.provider_id, body.api_key, body.base_url,
        default_base="https://dashscope.aliyuncs.com/api/v1",
    )
    try:
        submitted = await submit_video(
            creds, body.prompt, duration=body.duration, resolution=body.resolution,
            ref_images=list(body.ref_images or []), audio=body.audio,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("视频任务提交失败: %s", e)
        raise HTTPException(status_code=502, detail=f"视频任务提交失败: {str(e)[:300]}")

    remote_task_id = str(submitted.get("task_id") or "")
    if not remote_task_id:
        raise HTTPException(status_code=502, detail="提交未返回 task_id（协议响应异常）")
    record = get_generation_task_ledger().add(TaskRecord(
        kind="video",
        provider_id=body.provider_id or "",
        protocol=protocol.value,
        model=creds.model,
        base_url=creds.base_url,
        status="submitted",
        remote_task_id=remote_task_id,
        poll_url=str(submitted.get("poll_url") or ""),
        prompt=body.prompt[:500],
    ))
    return {
        "code": 0,
        "message": "success",
        "data": {"task_id": record.task_id, "status": "submitted", "protocol": protocol.value},
    }


# ── B2-c：任务轮询 / 任务列表 / 产物静态文件 ────────────────────────────────


@router.get("/video/status/{task_id}")
async def get_generation_video_status(request: Request, task_id: str):
    """轮询视频任务（账本 + 远程协议轮询；成功即下载本地化）。"""
    from neurova.api.endpoints import get_app_state  # noqa: F401 — 保持模块一致

    from neurova.core.identity_context import get_request_user_id
    from neurova.llm.generators.protocols import ProtocolCredentials, poll_video
    from neurova.llm.generators.task_ledger import get_generation_task_ledger

    _ = request
    ledger = get_generation_task_ledger()
    record = ledger.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if record.status in ("succeeded", "failed"):
        return {
            "code": 0,
            "message": "success",
            "data": {"task_id": task_id, "status": record.status,
                     "url": _local_url(record.local_path, request) if record.local_path else record.result_url,
                     "error": record.error},
        }

    creds = ProtocolCredentials(api_key="", base_url=record.base_url, model=record.model,
                                protocol=record.protocol)
    # 凭据：账本不落 api_key（敏感），轮询前按 provider_id 重新解析
    if record.provider_id:
        try:
            creds = _resolve_generation_creds(
                record.protocol, record.model, record.provider_id, None, None,
                default_base=record.base_url or "https://dashscope.aliyuncs.com/api/v1",
            )
        except HTTPException:
            pass
    try:
        result = await poll_video(creds, record.remote_task_id, record.poll_url)
    except Exception as e:  # noqa: BLE001
        result = {"status": "failed", "error": str(e)[:300]}

    if result["status"] == "succeeded":
        video_url = result.get("video_url") or ""
        if video_url.startswith("http"):
            try:
                path = await _persist_media(video_url, "video", task_id, 0)
                ledger.update(task_id, status="succeeded", result_url=video_url, local_path=path)
                return {"code": 0, "message": "success", "data": {
                    "task_id": task_id, "status": "succeeded", "url": _local_url(path, request)}}
            except Exception as e:  # noqa: BLE001 — 下载失败仍回成功+远端 URL（可能已过期）
                ledger.update(task_id, status="succeeded", result_url=video_url)
                return {"code": 0, "message": "success", "data": {
                    "task_id": task_id, "status": "succeeded", "url": video_url,
                    "warning": f"本地化失败: {str(e)[:200]}"}}
        ledger.update(task_id, status="succeeded", result_url=video_url)
        return {"code": 0, "message": "success", "data": {
            "task_id": task_id, "status": "succeeded", "url": video_url}}
    if result["status"] == "failed":
        ledger.update(task_id, status="failed", error=str(result.get("error") or "")[:300])
        return {"code": 0, "message": "success", "data": {
            "task_id": task_id, "status": "failed", "error": str(result.get("error") or "")[:300]}}
    ledger.update(task_id, status="running")
    return {"code": 0, "message": "success", "data": {"task_id": task_id, "status": "running"}}


@router.get("/tasks")
async def list_generation_tasks(request: Request, status: Optional[str] = None):
    """生成任务列表（账本快照，后台任务面板数据源之一）。"""
    _ = request
    from neurova.llm.generators.task_ledger import get_generation_task_ledger

    tasks = [
        {
            "task_id": t.task_id, "kind": t.kind, "protocol": t.protocol,
            "model": t.model, "status": t.status, "prompt": t.prompt,
            "submitted_at": t.submitted_at, "local_path": t.local_path,
            "error": t.error,
        }
        for t in get_generation_task_ledger().list(status=status)
    ]
    return {"code": 0, "message": "success", "data": {"tasks": tasks}}
