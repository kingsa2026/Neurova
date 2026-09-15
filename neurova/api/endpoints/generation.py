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
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user
from neurova.api.endpoints import get_agent_instance, get_app_state
from neurova.core.logger import get_logger
# 批次0（三栈收敛）：凭据解析/产物落盘/路径常量单源在 llm.generators.runtime，
# 端点保留同名薄包装（tests/api/test_generation_security.py 的模块全局 patch 面不变）
from neurova.llm.generators.runtime import (
    GENERATION_OUTPUT_DIR,
    PROJECT_ROOT,
    GenerationCredsError,
    local_url_for,
    safe_task_name,
)

if TYPE_CHECKING:  # 仅类型检查期：运行期不需要（避免端点导入面加宽）
    from neurova.llm.generators.protocols import ProtocolCredentials

logger = get_logger(__name__)

# P0-2（审计 2026-09-11）：/generation/* 一律需登录——原实现匿名可达且
# _resolve_generation_creds 会动用服务端已配置的付费凭据（凭据盗刷面）。
router = APIRouter(dependencies=[Depends(get_current_user)])

# P1-8：产物目录以仓库根为基准（runtime 单源常量，不再本地重复计算）
_GENERATION_OUTPUT_DIR = str(GENERATION_OUTPUT_DIR)

# P0-1：task_id 是落盘文件名的组成部分，禁止复用客户端可控的 X-Request-ID。
_safe_task_name = safe_task_name


def _validate_ref_images(refs: list) -> None:
    """P1-6：参考图只接受 http(s)/data URI，或允许根内的本地文件。

    原实现接受任意本地路径并被服务端读取后随请求发往 base_url——
    攻击者自建端点即可外泄任意本地文件。允许根：生成产物目录 + agent 工作区
    + 用户上传目录（批次3：/files/upload 落盘于此，上传→参考图引用闭环）。
    """
    allowed_roots = (
        GENERATION_OUTPUT_DIR.resolve(),
        (PROJECT_ROOT / "agent_workspaces").resolve(),
        (PROJECT_ROOT / "storage").resolve(),
    )
    for ref in refs or []:
        r = str(ref or "").strip()
        if not r:
            continue
        if r.lower().startswith(("http://", "https://", "data:")):
            continue
        p = Path(r)
        if not p.is_absolute():
            raise HTTPException(status_code=400, detail=f"ref_images 非法本地路径: {r}")
        resolved = p.resolve()
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise HTTPException(
                status_code=400,
                detail=f"ref_images 本地路径不在允许目录（生成产物/agent 工作区）内: {r}",
            )
        if not resolved.is_file():
            raise HTTPException(status_code=400, detail=f"ref_images 文件不存在: {r}")


def _route_selection(request_type: str):
    """按请求类型经 LLMRouter 选模的原始结果（ModelSelectionResult 或 None）。"""
    try:
        from neurova.llm.llm_router import RequestType, select_model_for_request

        return select_model_for_request(RequestType(request_type))
    except Exception as e:
        logger.warning("Auto route failed (%s), degrade to default: %s", request_type, e)
        return None


def _route_model_for_request(request_type: str):
    """按请求类型经 LLMRouter 自动选模型（model=auto/缺省时）。

    Returns:
        (model_id, provider_name)；路由不可用时 (None, None)。
    """
    result = _route_selection(request_type)
    if result is None:
        return None, None
    return result.model, result.provider_name


def _derive_selection(kind: str, model: str, provider_id: Optional[str],
                      protocol_label: Optional[str], base_url: Optional[str]):
    """自适应推导 (provider_id, 协议枚举)——委托 runtime.derive_generation_protocol 单源。

    2026-09-15 顺序根因修：原实现在凭据解析前用 resolve_*_protocol 推导，
    入参 base_url 恒为 body.base_url（前端服务商经 provider_id 上报、从不传
    base_url）→ OpenAI/Sora 2 Pro 等具名模型全落默认支（视频 WAN/图像
    OPENAI_COMPAT），请求发错端点。现先定位 provider base_url（pid 缺省按
    模型反查启用服务商）再推导；显式协议标签仍最优先，旧请求行为不变。
    """
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ImageProtocol, VideoProtocol

    pid, value = gen_runtime.derive_generation_protocol(
        kind, model or "", provider_id, protocol_label or "", base_url or "")
    cls = ImageProtocol if kind == "image" else VideoProtocol
    return (pid or None), cls(value)


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
    # R2 能力自适应路由：按协议支持面透传，不支持的参数进账本 ignored_params
    seed: Optional[int] = Field(default=None, description="随机种子（ARK/DASHSCOPE 支持）")
    strength: Optional[float] = Field(default=None, description="图生图变化强度（暂无实测通道，会被显式忽略并标注）")


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
    # L5 尾帧通道：Seedance first+last 插值；WAN 无通道 → ignored_params 标注
    last_frame: Optional[str] = Field(default=None, description="尾帧（URL 或本地路径，Seedance i2v 支持）")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    return get_agent_instance(agent_id)


# ── B2-b/c：按提供商凭据解析 + 媒体落盘 + 任务账本 ─────────────────────────
# （产物目录统一用模块顶部的 GENERATION_OUTPUT_DIR/_GENERATION_OUTPUT_DIR——
#   P1-8 仓库根绝对路径；此处不得再赋值，否则覆盖 P1-8 修复致挂载分裂）


def _resolve_generation_creds(
    protocol_hint: str,
    model: Optional[str],
    provider_id: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    default_base: str,
) -> "ProtocolCredentials":
    """凭据解析（B2-b）：显式凭据 > provider_id 配置 > 协议匹配服务商。

    批次0：实现体已上移 llm.generators.runtime（单源），此处仅映射 HTTP 400。
    """
    from neurova.llm.generators.runtime import resolve_generation_creds

    try:
        return resolve_generation_creds(
            protocol_hint, model, provider_id, api_key, base_url, default_base)
    except GenerationCredsError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _persist_media(url_or_data: str, kind: str, task_id: str, index: int) -> str:
    """结果 URL 临时有效 → 立即下载本地化（data/generations/）。

    批次0：实现体上移 llm.generators.runtime（与渠道 facade 同源）；
    端点 out_dir 取自身模块全局（安全测试 monkeypatch 面保持）。
    """
    from neurova.llm.generators.runtime import persist_media

    return await persist_media(url_or_data, kind, task_id, index,
                               out_dir=_GENERATION_OUTPUT_DIR)


def _local_url(path: str) -> str:
    """本地文件 → 可访问的静态 URL（批次2：委托 runtime.local_url_for 单源）。"""
    return local_url_for(path)


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
async def generate_image(
    request: Request,
    body: ImageGenerationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """图像生成（批次1：model=auto/缺省 → LLMRouter 按图像生成能力路由；成败均落账本）"""
    request_id = _get_request_id(request)

    # B2-a/c：真实协议实现（OPENAI_COMPAT/ARK/DASHSCOPE 实测矩阵）
    from neurova.llm.generators.protocols import generate_image
    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    # 批次1 根因修复：原实现把前端默认值 "auto" 当真实模型名透传并覆盖服务商
    # 默认模型（`model or default` 中 "auto" 为真值），图像/视频端点从未走过
    # auto 路由 → 默认配置下必然 4xx。与 /text 同口径收口。
    requested_model = (body.model or "").strip()
    routed = None
    if (not requested_model or requested_model.lower() == "auto") and not (
        body.api_key or body.base_url or body.provider_id
    ):
        routed = _route_selection(
            "image_to_image" if body.ref_images else "text_to_image")

    effective_model = (getattr(routed, "model", "") or "") or requested_model
    provider_id = getattr(routed, "provider_id", None) if routed is not None else body.provider_id

    provider_id, protocol = _derive_selection("image", effective_model, provider_id,
                                              body.protocol, body.base_url)
    _validate_ref_images(body.ref_images)
    creds = _resolve_generation_creds(
        protocol.value, effective_model or None, provider_id, body.api_key, body.base_url,
        default_base="https://api.openai.com/v1",
    )
    uid = str(current_user.get("user_id") or "")

    def _ledger_add(status: str, local_path: str = "", error: str = "",
                    ignored: str = "") -> None:
        # 批次1：图像落账本（kind="image"）——历史面板数据源；status 终态直落，
        # 不进 unfinished（无 remote_task_id）。R2：ignored_params 显式标注。
        get_generation_task_ledger().add(TaskRecord(
            kind="image",
            provider_id=str(provider_id or ""),
            protocol=protocol.value,
            model=creds.model or "",
            base_url=creds.base_url or "",
            status=status,
            local_path=local_path,
            error=error[:300],
            prompt=body.prompt[:500],
            owner_user_id=uid,
            ignored_params=ignored,
        ))
        # L4：AIGC 用量统计（张数计 items，写失败静默不阻断主流程）
        from neurova.core.aigc_usage import get_aigc_usage

        get_aigc_usage().record(
            kind="image", user_id=uid, provider=str(provider_id or ""),
            model=creds.model or "", protocol=protocol.value,
            status="success" if status == "succeeded" else "failed",
            items=body.num_images if status == "succeeded" else 0,
            duration_ms=(time.monotonic() - _t0) * 1000)

    _t0 = time.monotonic()
    size = f"{body.width}x{body.height}"
    try:
        result = await generate_image(
            creds, body.prompt, size=size, n=body.num_images,
            ref_images=list(body.ref_images or []),
            seed=body.seed, strength=body.strength,
        )
    except FileNotFoundError as e:
        _ledger_add("failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — 诚实 5xx，不伪造成功
        logger.warning("图像生成失败: %s", e)
        _ledger_add("failed", error=str(e))
        raise HTTPException(status_code=502, detail=f"图像生成失败: {str(e)[:300]}")

    ignored_csv = ",".join(result.get("ignored_params") or [])

    # P0-1：task_id 只用于命名落盘产物，必须服务端生成，与 X-Request-ID 解耦
    task_id = uuid.uuid4().hex
    images = []
    for i, item in enumerate(result.get("images") or []):
        try:
            path = await _persist_media(item, "image", task_id, i)
            images.append({"url": _local_url(path), "path": path})
        except Exception as e:  # noqa: BLE001 — 单图下载失败不影响其余
            images.append({"url": item if item.startswith("http") else "", "error": str(e)[:200]})
    if not images:
        _ledger_add("failed", error="图像生成未返回产物", ignored=ignored_csv)
        raise HTTPException(status_code=502, detail="图像生成未返回产物")
    _ledger_add("succeeded", local_path=str(images[0].get("path") or ""),
                ignored=ignored_csv)
    data: Dict[str, Any] = {"images": images, "task_id": task_id}
    if ignored_csv:
        data["ignored_params"] = ignored_csv
    return {"code": 0, "message": "success", "data": data}


@router.get("/voices")
async def list_generation_voices(request: Request):
    """R2：可用音色列表（前端音频页下拉真实化，替换硬编码 OpenAI 别名假列表）。

    VoiceEngine(tts) 底层引擎（TTSManager 等）支持 list_voices 则归一返回；
    引擎不可用/不支持枚举返回空数组——诚实空，不伪造列表。
    """
    _ = request
    voices: list = []
    try:
        state = get_app_state() or {}
        engine = (state.get("voice_engines") or {}).get("tts")
        inner = getattr(engine, "_engine", None) if engine else None
        lister = getattr(inner, "list_voices", None)
        if engine and engine.is_available() and callable(lister):
            raw = await lister()
        else:
            mgr = state.get("tts_manager")
            raw = await mgr.list_voices() if mgr and mgr.is_initialized else []
        for v in raw or []:
            if not isinstance(v, dict):
                continue
            name = str(v.get("ShortName") or v.get("short_name") or v.get("name") or "")
            if not name:
                continue
            gender = str(v.get("Gender") or v.get("gender") or "")
            locale = str(v.get("Locale") or v.get("locale") or "")
            suffix = " ".join(x for x in (gender, locale) if x)
            voices.append({
                "id": name,
                "label": f"{name}（{suffix}）" if suffix else name,
                "gender": gender,
                "locale": locale,
            })
    except Exception as e:  # noqa: BLE001 — 枚举失败回空列表，前端走默认音色
        logger.warning("音色列表获取失败: %s", e)
        voices = []
    return {"code": 0, "message": "success", "data": {"voices": voices}}


@router.post("/audio")
async def generate_audio(
    request: Request,
    body: AudioGenerationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """音频生成（TTS 语音合成，批次1：统一 JSON 契约 + 落账）

    根因修复：原实现在成功路径返回 audio/wav 二进制，而前端按 JSON 取
    data.url → 恒空串、播放器永不出现。与图像/视频同契约：产物落盘返回 url。
    """
    request_id = _get_request_id(request)

    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    _t0 = time.monotonic()

    def _finish(audio_bytes: bytes):
        task_id = uuid.uuid4().hex
        out_dir = Path(_GENERATION_OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_safe_task_name(task_id)}_0.wav"
        path.write_bytes(audio_bytes)
        get_generation_task_ledger().add(TaskRecord(
            kind="audio",
            status="succeeded",
            protocol="tts",
            model=body.model or "",
            prompt=body.text[:500],
            local_path=str(path),
            owner_user_id=str(current_user.get("user_id") or ""),
        ))
        # L4：AIGC 用量统计（音频条数；写失败静默）
        from neurova.core.aigc_usage import get_aigc_usage

        get_aigc_usage().record(
            kind="audio", user_id=str(current_user.get("user_id") or ""),
            model=body.model or "", protocol="tts", status="success",
            items=1, duration_ms=(time.monotonic() - _t0) * 1000)
        return {
            "code": 0,
            "message": "success",
            "data": {
                "url": _local_url(str(path)),
                "path": str(path),
                "task_id": task_id,
                "request_id": request_id,
            },
        }

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

            return _finish(result.audio_data)

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

        return _finish(audio_bytes)

    except Exception as e:
        logger.error(f"Audio generation error: {e}", exc_info=True)
        return {
            "code": -1,
            "message": f"Audio generation failed: {str(e)}",
            "data": {"request_id": request_id},
        }


@router.post("/video")
async def generate_video(
    request: Request,
    body: VideoGenerationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """视频生成"""
    request_id = _get_request_id(request)

    # B2-a/c：wan/seedance2/veo/sora 异步协议提交 + 持久任务账本
    import asyncio as _asyncio

    from neurova.llm.generators.protocols import submit_video
    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    # 批次1：model=auto/缺省 → 按视频生成能力路由（与 /image 同口径）
    requested_model = (body.model or "").strip()
    routed = None
    if (not requested_model or requested_model.lower() == "auto") and not (
        body.api_key or body.base_url or body.provider_id
    ):
        routed = _route_selection(
            "image_to_video" if body.ref_images else "text_to_video")
    effective_model = (getattr(routed, "model", "") or "") or requested_model
    provider_id = getattr(routed, "provider_id", None) if routed is not None else body.provider_id

    provider_id, protocol = _derive_selection("video", effective_model, provider_id,
                                              body.protocol, body.base_url)
    _validate_ref_images(body.ref_images)
    creds = _resolve_generation_creds(
        protocol.value, effective_model or None, provider_id, body.api_key, body.base_url,
        default_base="https://dashscope.aliyuncs.com/api/v1",
    )
    try:
        submitted = await submit_video(
            creds, body.prompt, duration=body.duration, resolution=body.resolution,
            ref_images=list(body.ref_images or []), audio=body.audio,
            last_frame=body.last_frame or None,
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
    ignored_csv = ",".join(submitted.get("ignored_params") or [])
    record = get_generation_task_ledger().add(TaskRecord(
        kind="video",
        # 账本不存 api_key（敏感），轮询靠 settle_video_record 按 provider_id 重取——
        # 必须写生效值（auto 模式下为 routed.provider_id，body 里是空），否则轮询恒 401。
        provider_id=str(provider_id or ""),
        protocol=protocol.value,
        model=creds.model,
        base_url=creds.base_url,
        status="submitted",
        remote_task_id=remote_task_id,
        poll_url=str(submitted.get("poll_url") or ""),
        prompt=body.prompt[:500],
        owner_user_id=str(current_user.get("user_id") or ""),
        ignored_params=ignored_csv,
    ))
    return {
        "code": 0,
        "message": "success",
        "data": {"task_id": record.task_id, "status": "submitted", "protocol": protocol.value,
                 **({"ignored_params": ignored_csv} if ignored_csv else {})},
    }


@router.get("/resolve")
async def resolve_generation_protocol_for_model(
    request: Request,
    kind: str = "video",
    model: str = "",
    provider_id: str = "",
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """自适应推导查询端点（2026-09-15）：图/视频页选定模型后，前端查询将生效的
    服务商/协议做只读展示——与提交路径同源（derive_generation_protocol），
    前端不重复实现矩阵规则（口径单源）。"""
    _ = request
    kind = (kind or "").lower()
    if kind not in ("image", "video"):
        raise HTTPException(status_code=400, detail="kind 仅支持 image/video")
    pid, protocol = _derive_selection(
        kind, (model or "").strip(), (provider_id or "").strip() or None, None, None)
    return {"code": 0, "message": "success",
            "data": {"kind": kind, "model": model or "",
                     "provider_id": pid or "", "protocol": protocol.value}}


# ── B2-c：任务轮询 / 任务列表 / 产物静态文件 ────────────────────────────────


@router.get("/video/status/{task_id}")
async def get_generation_video_status(
    request: Request,
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """轮询视频任务（批次2：收口逻辑委托 generators.recovery.settle_video_record，
    与后台重启恢复循环同一实现——口径单源）。"""
    _ = request
    from neurova.llm.generators.recovery import settle_video_record
    from neurova.llm.generators.task_ledger import get_generation_task_ledger

    ledger = get_generation_task_ledger()
    record = ledger.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    # P1-9：任务归属校验——新任务落账本时带 owner_user_id；历史无主记录
    # （升级前存量）仅管理员可见，其余一律 403。
    owner = str(getattr(record, "owner_user_id", "") or "")
    uid = str(current_user.get("user_id") or "")
    if owner and owner != uid:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    if not owner and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问该任务")
    if record.status in ("succeeded", "failed"):
        return {
            "code": 0,
            "message": "success",
            "data": {"task_id": task_id, "status": record.status,
                     "url": _local_url(record.local_path) if record.local_path else record.result_url,
                     "error": record.error},
        }

    result = await settle_video_record(record, ledger=ledger)
    data: Dict[str, Any] = {"task_id": task_id, "status": result["status"]}
    for key in ("url", "error", "warning"):
        if result.get(key):
            data[key] = result[key]
    return {"code": 0, "message": "success", "data": data}


@router.get("/usage")
async def generation_usage(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """L4：AIGC 生成用量统计（近 N 天按天/类型聚合；admin 可看全量）。"""
    _ = request
    from neurova.core.aigc_usage import get_aigc_usage

    uid = str(current_user.get("user_id") or "")
    scope = None if current_user.get("role") == "admin" else uid
    return {"code": 0, "message": "success",
            "data": get_aigc_usage().summary(user_id=scope, days=days)}


@router.get("/tasks")
async def list_generation_tasks(
    request: Request,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """生成任务列表（批次2：历史面板数据源——kind 过滤 + 产物可访问 url）。
    仅返回本人任务；无主存量任务仅管理员可见。"""
    _ = request
    from neurova.llm.generators.task_ledger import get_generation_task_ledger

    uid = str(current_user.get("user_id") or "")
    is_admin = current_user.get("role") == "admin"
    visible = [
        t for t in get_generation_task_ledger().list(status=status)
        if (not kind or t.kind == kind)
        and (t.owner_user_id == uid or (not t.owner_user_id and is_admin))
    ]
    tasks = [
        {
            "task_id": t.task_id, "kind": t.kind, "protocol": t.protocol,
            "model": t.model, "status": t.status, "prompt": t.prompt,
            "submitted_at": t.submitted_at, "updated_at": t.updated_at,
            "local_path": t.local_path,
            # C3：保留清理删除文件后账本行仍在——file_missing 显式标注并清空
            # url（历史面板显示「已过期」，不给必 404 的链接装作可用）
            "file_missing": bool(t.local_path)
                            and t.status in ("done", "failed", "succeeded")
                            and not Path(t.local_path).is_file(),
            "url": (_local_url(t.local_path)
                    if t.local_path and Path(t.local_path).is_file()
                    else (t.result_url or "")),
            "source": getattr(t, "source", "rest"),
            "ignored_params": getattr(t, "ignored_params", ""),
            "error": t.error,
        }
        for t in visible
    ]
    return {"code": 0, "message": "success", "data": {"tasks": tasks}}


# 产物文件名白名单（批次3：替代 app.py 匿名 StaticFiles 挂载）
_SAFE_FILE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


@router.get("/files/{name}")
async def serve_generation_file(
    request: Request,
    name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """批次3：产物文件访问（鉴权路由）。

    根因：原 app.py 以匿名 StaticFiles 挂载 data/generations，与路由级鉴权
    不同源——任何知道文件名的人都能匿名读取他人产物。此处收口：
    文件名白名单 + 账本属主反查（无主存量登录即可读，向后兼容）+ 防穿越。
    访问凭证支持 ?access_token=（<img>/<audio> 资源标签无法带 Bearer 头）。
    """
    import mimetypes

    from fastapi.responses import FileResponse

    from neurova.llm.generators.task_ledger import get_generation_task_ledger

    _ = request
    if not name or not _SAFE_FILE_NAME_RE.fullmatch(name) or name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    root = Path(_GENERATION_OUTPUT_DIR).resolve()
    path = (root / name).resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    owner = ""
    for t in get_generation_task_ledger().list():
        if t.local_path and Path(t.local_path).name == name:
            owner = str(t.owner_user_id or "")
            break
    uid = str(current_user.get("user_id") or "")
    if owner and owner != uid and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权访问该产物")
    mime, _ = mimetypes.guess_type(name)
    return FileResponse(path, media_type=mime or "application/octet-stream")
