from __future__ import annotations

"""
模型管理接口 - Model Endpoint

功能:
1. 列出可用模型 (GET /api/v1/models)
2. 获取当前活跃模型 (GET /api/v1/models/active)
3. 切换模型 (POST /api/v1/models/switch)
4. 模型多模态探测 (POST /api/v1/models/probe-multimodal)
5. 模型连接检查 (POST /api/v1/models/check-connection)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_optional_user, get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# ---- 模型下载（双源选择 + 后台触发 + 进度轮询）----
# 提示框数据面：前端启动/进语音页时查 pending-downloads 渲染对话框，
# 用户选源 POST download-source，触发 POST download，轮询 download-progress。
_downloader = None  # 惰性初始化（测试注入点）
_service = None


def _get_downloader():
    global _downloader
    if _downloader is None:
        from neurova.tts.model_downloader import get_model_downloader

        _downloader = get_model_downloader()
    return _downloader


def _get_service():
    global _service
    if _service is None:
        from neurova.tts.download_service import ModelDownloadService

        _service = ModelDownloadService(downloader=_get_downloader())
    return _service

# canonical 能力词表(与 capability_detector.CAPABILITY_ORDER 核心六类对齐)
_VALID_CAPABILITIES = frozenset(
    {
        "text",
        "reasoning",
        "vision",
        "video",
        "image_generation",
        "video_generation",
        "audio",
        "tts",
        "stt",
        "tool_use",
        "multimodal",
    }
)


class ModelInfo(BaseModel):
    """模型信息"""

    model_id: str
    name: str
    provider: str = ""
    capabilities: List[str] = []
    context_window: Optional[int] = None
    max_tokens: Optional[int] = None
    is_active: bool = False
    status: str = "unknown"


class SwitchModelRequest(BaseModel):
    """切换模型请求"""

    model_id: str = Field(..., description="模型 ID")
    agent_id: str = Field(default="default", description="Agent ID")


class ProbeRequest(BaseModel):
    """探测请求"""

    model_id: str = Field(..., description="模型 ID")
    probe_type: str = Field(default="multimodal", description="探测类型")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _clean_limit(value: Any) -> Optional[int]:
    """4096/0/None 视为未设置(占位值不外发,前端据此隐藏限额标记)。"""
    if value in (None, 0, 4096, "", "4096"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_provider_manager(current_user: Optional[Dict[str, Any]] = None):
    """获取(按用户隔离的)Provider 管理器。

    - 有用户身份:admin → 全局;普通用户 → 自己的 scope
    - 无身份(直接调用/未认证):app_state 全局实例(存量兼容)
    """
    if isinstance(current_user, dict):
        from neurova.llm.provider_manager import get_provider_manager_for_user

        return get_provider_manager_for_user(current_user)
    from neurova.api.endpoints import get_provider_manager

    return get_provider_manager()


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


@router.get("", response_model=List[ModelInfo])
async def list_models(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """列出可用模型(按用户 scope 隔离;未认证 → 全局)"""
    """列出可用模型"""
    _get_request_id(request)

    models = []
    provider_manager = _get_provider_manager(current_user)

    if provider_manager:
        try:
            if hasattr(provider_manager, "get_all_models"):
                all_models = provider_manager.get_all_models()
                for model in all_models:
                    # PydanticModelInfo uses 'owned_by' for provider_id
                    # 能力标记兜底:元数据缺失时即时推断,响应永不缺 capabilities(AIGC 下拉/路由依赖)
                    caps = [str(c) for c in (getattr(model, "capabilities", None) or [])]
                    if not caps:
                        from neurova.llm.capability_detector import detect_model_capabilities

                        caps = detect_model_capabilities(
                            getattr(model, "id", ""),
                            display_name=getattr(model, "name", "") or "",
                        )
                    models.append(
                        ModelInfo(
                            model_id=getattr(model, "id", "unknown"),
                            name=getattr(model, "name", "Unknown"),
                            provider=getattr(model, "owned_by", ""),
                            capabilities=caps,
                            # 限额透传(预埋兜底已在 get_all_models 完成;4096 占位不外发)
                            context_window=_clean_limit(getattr(model, "context_window", None)),
                            max_tokens=_clean_limit(getattr(model, "max_tokens", None)),
                            is_active=getattr(model, "is_active", False),
                            status=getattr(model, "status", "available"),
                        )
                    )
        except Exception as e:
            logger.warning("List models error: %s", e)

    # 如果没有找到模型，返回默认列表
    if not models:
        models = [
            ModelInfo(
                model_id="auto",
                name="Auto (自动选择)",
                provider="system",
                capabilities=["text"],
                is_active=True,
                status="available",
            ),
        ]

    return models


class DetectCapabilitiesRequest(BaseModel):
    """能力批量检测请求"""

    provider_id: Optional[str] = Field(default=None, description="服务商 ID(缺省=全部)")
    model_id: Optional[str] = Field(default=None, description="模型 ID(缺省=该商全部)")
    force: bool = Field(default=False, description="已有标记时是否强制重检")


@router.post("/detect-capabilities")
async def detect_capabilities(
    request: Request,
    body: DetectCapabilitiesRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """批量自动检测模型能力(文本/推理/图片理解/视频理解/图片生成/视频生成)并持久化。

    检测顺序:显式元数据 > 已知模型目录 > 名称启发式;force=True 可重检已有标记。
    """
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    if not hasattr(provider_manager, "detect_and_persist_capabilities"):
        raise HTTPException(status_code=501, detail="Provider manager does not support capability detection")

    # 显式 provider_id 必须存在(防误传静默成功)
    if body.provider_id and hasattr(provider_manager, "get_provider"):
        if provider_manager.get_provider(body.provider_id) is None:
            raise HTTPException(status_code=404, detail=f"Provider '{body.provider_id}' not found")

    try:
        result = provider_manager.detect_and_persist_capabilities(
            provider_id=body.provider_id,
            model_id=body.model_id,
            force=body.force,
        )
        return {"code": 0, "message": f"Detected capabilities for {result['detected']} models", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Detect capabilities error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to detect capabilities: {str(e)}")


@router.get("/by-capability", response_model=List[ModelInfo])
async def list_models_by_capability(
    request: Request,
    cap: str = Query(..., description="所需能力(text/reasoning/vision/video/image_generation/video_generation...)"),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """按能力过滤模型列表(AIGC 页面下拉数据源)。"""
    _get_request_id(request)

    cap_value = (cap or "").strip().lower()
    if cap_value not in _VALID_CAPABILITIES:
        raise HTTPException(status_code=400, detail=f"Unknown capability: '{cap}'")

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    matched: List[ModelInfo] = []
    try:
        for model in provider_manager.get_all_models():
            caps = [str(c) for c in (getattr(model, "capabilities", None) or [])]
            if cap_value in caps:
                matched.append(
                    ModelInfo(
                        model_id=getattr(model, "id", "unknown"),
                        name=getattr(model, "name", "Unknown"),
                        provider=getattr(model, "owned_by", ""),
                        capabilities=caps,
                        is_active=getattr(model, "is_active", False),
                        status=getattr(model, "status", "available"),
                    )
                )
    except Exception as e:
        logger.warning("List models by capability error: %s", e)

    return matched


@router.delete("/{model_id}")
async def delete_model(
    request: Request,
    model_id: str = Path(...),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """删除模型（从所属服务商的模型列表中移除）"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        # 找到包含该 model 的 provider
        target_provider = None
        if hasattr(provider_manager, "list_providers"):
            for provider in provider_manager.list_providers():
                if model_id in getattr(provider, "models", []):
                    target_provider = provider
                    break

        if not target_provider:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in any provider")

        # 从 models 列表中移除
        models = list(target_provider.models)
        models.remove(model_id)

        # 持久化
        if hasattr(provider_manager, "update_provider"):
            provider_manager.update_provider(target_provider.id, models=models)
            logger.info("Deleted model '%s' from provider '%s'", model_id, target_provider.name)

        return {"code": 0, "message": f"Model '{model_id}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete model error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


class UpdateModelRequest(BaseModel):
    """编辑模型条目请求:name(显示名)、id(新模型 ID)、provider_id(归属服务商)"""

    name: Optional[str] = None
    id: Optional[str] = None
    provider_id: Optional[str] = None


@router.put("/{model_id}")
async def update_model(
    request: Request,
    model_id: str = Path(...),
    body: UpdateModelRequest = Body(...),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """编辑模型条目(模型 ID / 显示名称),内置/发现的条目同样可编辑。

    body.id 为新模型 ID(缺省保持不变),body.name 为新显示名称。
    无任何改动返回 400;模型不在任何服务商列表中返回 404。
    """
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    new_id = (body.id or model_id).strip() or model_id
    if new_id == model_id and not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Nothing to update: provide 'name' or a new 'id'")

    try:
        # 归属服务商:body.provider_id 优先,否则全服务商扫描
        target_provider = None
        if body.provider_id and hasattr(provider_manager, "get_provider"):
            target_provider = provider_manager.get_provider(body.provider_id)
        if target_provider is None and hasattr(provider_manager, "list_providers"):
            for provider in provider_manager.list_providers():
                if model_id in getattr(provider, "models", []):
                    target_provider = provider
                    break
        if target_provider is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found in any provider")

        updated = False
        if hasattr(provider_manager, "rename_model_entry"):
            updated = provider_manager.rename_model_entry(
                getattr(target_provider, "id", "unknown"),
                model_id,
                new_id=new_id,
                name=(body.name or "").strip() or None,
            )
        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{model_id}' not found in provider '{getattr(target_provider, 'id', 'unknown')}'",
            )
        return {"code": 0, "message": f"Model '{model_id}' updated to '{new_id}'"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update model error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update model: {str(e)}")

@router.get("/active", response_model=ModelInfo)
async def get_active_model(request: Request, agent_id: str = Query(default="default")):
    """获取当前活跃模型"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if agent:
        try:
            model_name = "unknown"
            if hasattr(agent, "config") and hasattr(agent.config, "llm_config"):
                model_name = getattr(agent.config.llm_config, "model", "unknown")

            return ModelInfo(
                model_id=model_name,
                name=model_name,
                provider="agent",
                is_active=True,
                status="active",
            )
        except Exception as e:
            logger.warning("Get active model error: %s", e)

    return ModelInfo(
        model_id="unknown",
        name="Unknown",
        is_active=False,
        status="no_agent",
    )


@router.post("/switch")
async def switch_model(request: Request, body: SwitchModelRequest):
    """切换模型"""
    _get_request_id(request)

    agent = _get_agent(body.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{body.agent_id}' not found")

    loop_rebuilt = False
    try:
        if hasattr(agent, "rebuild_loop"):
            loop_rebuilt = agent.rebuild_loop(model_name=body.model_id)
    except Exception as e:
        logger.error(f"Switch model error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to switch model: {str(e)}")

    return {
        "code": 0,
        "message": "Model switched" if loop_rebuilt else "Model switch attempted",
        "data": {
            "model_id": body.model_id,
            "agent_id": body.agent_id,
            "loop_rebuilt": loop_rebuilt,
        },
    }


@router.post("/probe-multimodal")
async def probe_multimodal(
    request: Request,
    body: ProbeRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """模型多模态探测"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        result = {}
        if hasattr(provider_manager, "probe_model_multimodal"):
            result = await provider_manager.probe_model_multimodal(body.model_id)

        return {
            "code": 0,
            "data": {
                "model_id": body.model_id,
                "probe_type": body.probe_type,
                "result": result,
            },
        }
    except Exception as e:
        logger.error(f"Probe multimodal error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Probe failed: {str(e)}")


@router.post("/check-connection")
async def check_connection(
    request: Request,
    model_id: str = Query(...),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """检查模型连接"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        connected = False
        message = ""

        if hasattr(provider_manager, "check_model_connection"):
            result = await provider_manager.check_model_connection(model_id)
            # manager 层返回 ConnectionResult(异步链路),兼容旧 dict 形状
            connected = getattr(result, "success", False)
            message = getattr(result, "error", "") or getattr(result, "message", "")

        return {
            "code": 0,
            "data": {
                "model_id": model_id,
                "connected": connected,
                "message": message,
            },
        }
    except Exception as e:
        logger.error(f"Check connection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Connection check failed: {str(e)}")


# ==================== 模型下载（双源选择 + 后台触发 + 进度轮询） ====================

class DownloadSourceRequest(BaseModel):
    """下载源选择"""
    model: str
    choice: str  # auto | always_modelscope | always_huggingface | skip


class DownloadTriggerRequest(BaseModel):
    """下载触发"""
    model: str
    source: Optional[str] = None  # 缺省读用户已存选择


@router.get("/pending-downloads")
async def pending_downloads(current_user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """待下载清单（模型缺失项 + 每模型已存选择），供前端渲染下载提示框。"""
    from neurova.tts.download_source import get as get_choice

    try:
        dl = _get_downloader()
        items = []
        for item in dl.pending_downloads():
            item["choice"] = get_choice(item["model"])
            items.append(item)
        return items
    except Exception as e:
        logger.error(f"Pending downloads error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list pending downloads: {str(e)}")


@router.get("/download-source")
async def get_download_source(current_user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """用户下载源选择映射 {model: choice}。"""
    from neurova.tts.download_source import get as get_choice, VALID_CHOICES
    from neurova.tts.model_downloader import MODEL_REGISTRY

    try:
        return {name: get_choice(name) for name in MODEL_REGISTRY}
    except Exception as e:
        logger.error(f"Get download source error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download-source")
async def set_download_source(
    body: DownloadSourceRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """写某模型的下载源选择（非法值/未知模型 400）。"""
    from neurova.tts.download_source import DownloadSourceChoice, set as set_choice

    try:
        set_choice(DownloadSourceChoice(model=body.model, choice=body.choice))
        return {"ok": True, "model": body.model, "choice": body.choice}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Set download source error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download")
async def trigger_download(
    body: DownloadTriggerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """触发模型下载（幂等；重复触发返回同一状态）。"""
    try:
        return _get_service().start(body.model, source=body.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Trigger download error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-progress")
async def download_progress(current_user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """已触发模型的下载状态快照（前端进度条轮询数据源）。"""
    try:
        return _get_service().progress()
    except Exception as e:
        logger.error(f"Download progress error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
