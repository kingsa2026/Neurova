from __future__ import annotations

"""
LLM 服务商管理接口 - Provider Endpoint

功能:
1. 列出所有服务商 (GET /api/v1/providers)
2. 获取服务商详情 (GET /api/v1/providers/{provider_id})
3. 添加服务商 (POST /api/v1/providers)
4. 更新服务商 (PUT /api/v1/providers/{provider_id})
5. 删除服务商 (DELETE /api/v1/providers/{provider_id})
6. 激活模型 (POST /api/v1/providers/activate-model)
7. 获取当前活跃模型 (GET /api/v1/providers/active-model)
8. 发现模型 (GET /api/v1/providers/{provider_id}/models/discover)
9. 多模态探测 (POST /api/v1/providers/{provider_id}/models/{model}/probe-multimodal)
10. 检查连接 (POST /api/v1/providers/{provider_id}/check-connection)
11. 模型连接检查 (POST /api/v1/providers/{provider_id}/models/{model}/check-connection)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.llm.provider_manager import KEYLESS_PROVIDER_IDS

logger = get_logger(__name__)

router = APIRouter()


class ProviderInfo(BaseModel):
    """服务商信息"""

    provider_id: str
    name: str
    provider_type: str = ""
    base_url: str = ""
    is_active: bool = False
    status: str = "unknown"
    models_count: int = 0
    health: str = "unknown"


class CreateProviderRequest(BaseModel):
    """创建服务商请求"""

    name: str = Field(..., description="服务商名称")
    provider_type: str = Field(..., description="服务商类型 (openai, anthropic, gemini, ollama, openrouter)")
    base_url: Optional[str] = Field(default=None, description="API 基础 URL")
    api_key: Optional[str] = Field(default=None, description="API Key")
    config: Dict[str, Any] = Field(default_factory=dict, description="额外配置")


class UpdateProviderRequest(BaseModel):
    """更新服务商请求"""

    name: Optional[str] = Field(default=None, description="服务商名称")
    base_url: Optional[str] = Field(default=None, description="API 基础 URL")
    api_key: Optional[str] = Field(default=None, description="API Key")
    config: Dict[str, Any] = Field(default_factory=dict, description="额外配置")


class ActivateModelRequest(BaseModel):
    """激活模型请求"""

    provider_id: str = Field(..., description="服务商 ID")
    model_id: str = Field(..., description="模型 ID")


class FilterModelsRequest(BaseModel):
    """筛选模型请求(对齐 QwenPaw filter_models 四维)"""

    providers: List[str] = Field(default_factory=list, description="系列前缀,如 ['openai']")
    input_modalities: List[str] = Field(default_factory=list, description="必需输入模态,如 ['image']")
    output_modalities: List[str] = Field(default_factory=list, description="必需输出模态")
    max_prompt_price: Optional[float] = Field(
        default=None,
        description="prompt 价格上限(每 1M tokens)",
    )
    is_free: Optional[bool] = Field(default=None, description="仅免费模型")


class MergeDiscoveredRequest(BaseModel):
    """并入发现候选请求"""

    model_ids: Optional[List[str]] = Field(
        default=None,
        description="要并入的候选模型 id;None 表示并入全部候选",
    )


def _model_to_json(model) -> Dict[str, Any]:
    """ModelInfo → JSON 安全 dict(capabilities/provider_type 转字符串)。"""
    data = model.to_dict()
    data["capabilities"] = [
        c.value if hasattr(c, "value") else str(c)
        for c in (data.get("capabilities") or [])
    ]
    provider_type = data.get("provider_type")
    if hasattr(provider_type, "value"):
        data["provider_type"] = provider_type.value
    return data


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_provider_manager(current_user: Optional[Dict[str, Any]] = None):
    """获取(按用户隔离的)Provider 管理器。

    隔离模型:
    - admin 角色 → 全局 admin scope(最高权限)
    - 普通用户 → user:<user_id> scope(仅自己的配置)
    - 未认证/无用户上下文 → app_state 注入的全局实例(存量行为,兼容测试与启动链路)
    """
    if isinstance(current_user, dict):
        from neurova.llm.provider_manager import get_provider_manager_for_user

        return get_provider_manager_for_user(current_user)
    return _get_app_state_manager()


def _get_app_state_manager():
    """获取 app_state 注入的全局实例(启动链路/测试环境)。"""
    from neurova.api.endpoints import get_provider_manager

    return get_provider_manager()


@router.get("/scopes")
async def list_provider_scopes(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """管理员查看所有用户 LLM 配置的 scope 清单(普通用户 403)。"""
    _get_request_id(request)

    role = (current_user or {}).get("role", "user")
    if role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required",
        )

    try:
        from neurova.llm.provider_manager import list_available_scopes

        scopes = list_available_scopes()
        return {
            "code": 0,
            "data": {
                "scopes": scopes,
            },
        }
    except Exception as e:
        logger.error(f"List provider scopes error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list scopes: {str(e)}")


@router.get("", response_model=List[ProviderInfo])
async def list_providers(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """列出所有服务商"""
    _get_request_id(request)

    providers = []
    provider_manager = _get_provider_manager(current_user)

    if provider_manager:
        try:
            # 使用 list_providers() 方法（ProviderManager 的真实 API）
            list_method = getattr(provider_manager, "list_providers", None) or \
                          getattr(provider_manager, "get_all_providers", None)
            if list_method:
                all_providers = list_method()
                for provider in all_providers:
                    providers.append(
                        ProviderInfo(
                            provider_id=getattr(provider, "id", "unknown"),
                            name=getattr(provider, "name", "Unknown"),
                            provider_type=getattr(provider, "provider", ""),
                            base_url=getattr(provider, "base_url", ""),
                            is_active=getattr(provider, "enabled", False),
                            status=getattr(provider, "health_status", "unknown"),
                            models_count=len(getattr(provider, "models", [])),
                        )
                    )
        except Exception as e:
            logger.warning("List providers error: %s", e)

    return providers


@router.post("/activate-model")
async def activate_model(
    request: Request,
    body: ActivateModelRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """激活模型"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "activate_model"):
            success = provider_manager.activate_model(body.provider_id, body.model_id)
            if success:
                return {
                    "code": 0,
                    "message": "Model activated",
                    "data": {
                        "provider_id": body.provider_id,
                        "model_id": body.model_id,
                    },
                }
    except Exception as e:
        logger.error(f"Activate model error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to activate model: {str(e)}")

    raise HTTPException(status_code=500, detail="Failed to activate model")


@router.get("/active-model")
async def get_active_model(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取当前活跃模型"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        return {"code": 0, "data": {"model": None, "provider": None}}

    try:
        if hasattr(provider_manager, "get_active_model"):
            active = provider_manager.get_active_model()
            return {"code": 0, "data": active}
    except Exception as e:
        logger.warning("Get active model error: %s", e)

    return {"code": 0, "data": {"model": None, "provider": None}}


@router.get("/{provider_id}", response_model=ProviderInfo)
async def get_provider(
    request: Request,
    provider_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取服务商详情"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "get_provider"):
            provider = provider_manager.get_provider(provider_id)
            if provider:
                return ProviderInfo(
                    provider_id=getattr(provider, "id", provider_id),
                    name=getattr(provider, "name", "Unknown"),
                    provider_type=getattr(provider, "provider", ""),
                    base_url=getattr(provider, "base_url", ""),
                    is_active=getattr(provider, "enabled", False),
                    status=getattr(provider, "health_status", "unknown"),
                    models_count=len(getattr(provider, "models", [])),
                )
    except Exception as e:
        logger.warning("Get provider error: %s", e)

    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


@router.post("", response_model=ProviderInfo)
async def create_provider(
    request: Request,
    body: CreateProviderRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """添加服务商"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "add_provider"):
            logger.info(f"Creating provider: name={body.name}, provider_type={body.provider_type}, base_url={body.base_url}")
            provider = provider_manager.add_provider(
                name=body.name,
                provider=body.provider_type,
                base_url=body.base_url or "",
                api_key=body.api_key,
            )
            logger.info(f"Provider created successfully: {provider.id}")

            return ProviderInfo(
                provider_id=getattr(provider, "id", ""),
                name=getattr(provider, "name", body.name),
                provider_type=getattr(provider, "provider", body.provider_type),
                base_url=getattr(provider, "base_url", ""),
                is_active=getattr(provider, "enabled", True),
                status="created",
            )
        else:
            logger.error("Provider manager does not have add_provider method")
            raise HTTPException(status_code=500, detail="Provider manager not properly initialized")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create provider error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create provider: {str(e)}")

    raise HTTPException(status_code=500, detail="Failed to create provider")


@router.put("/{provider_id}", response_model=ProviderInfo)
async def update_provider(
    request: Request,
    provider_id: str = Path(...),
    body: UpdateProviderRequest = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新服务商"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        # 处理 config 中的特殊指令
        config = body.config or {}
        add_model_id = config.get("add_model")

        if hasattr(provider_manager, "update_provider"):
            # 构建更新参数
            update_kwargs: dict = {"provider_id": provider_id}
            if body.base_url is not None:
                update_kwargs["base_url"] = body.base_url
            if body.api_key is not None:
                update_kwargs["api_key"] = body.api_key

            # 如果有 add_model 指令，先获取当前 models 再合并
            if add_model_id:
                provider = provider_manager.get_provider(provider_id) if hasattr(provider_manager, "get_provider") else None
                if provider:
                    models = list(getattr(provider, "models", []))
                    if add_model_id not in models:
                        models.append(add_model_id)
                        update_kwargs["models"] = models
                        logger.info(f"Added model '{add_model_id}' to provider '{provider_id}'")

            success = provider_manager.update_provider(**update_kwargs)

            if success:
                # 读取更新后的配置（使用公共 API 而非私有属性）
                provider = None
                if hasattr(provider_manager, "get_provider"):
                    provider = provider_manager.get_provider(provider_id)
                if provider:
                    return ProviderInfo(
                        provider_id=getattr(provider, "id", provider_id),
                        name=getattr(provider, "name", "Unknown"),
                        provider_type=getattr(provider, "provider", ""),
                        base_url=getattr(provider, "base_url", ""),
                        is_active=getattr(provider, "enabled", False),
                        status="updated",
                    )
                return ProviderInfo(
                    provider_id=provider_id,
                    name="Unknown",
                    status="updated",
                )
    except Exception as e:
        logger.error(f"Update provider error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update provider: {str(e)}")

    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


@router.delete("/{provider_id}")
async def delete_provider(
    request: Request,
    provider_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除服务商"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "remove_provider"):
            success = provider_manager.remove_provider(provider_id)
            if success:
                return {"code": 0, "message": f"Provider '{provider_id}' deleted"}
    except Exception as e:
        logger.error(f"Delete provider error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete provider: {str(e)}")

    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


@router.get("/{provider_id}/models/discover")
async def discover_models(
    request: Request,
    provider_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """发现模型"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "fetch_provider_models"):
            provider = (
                provider_manager.get_provider(provider_id)
                if hasattr(provider_manager, "get_provider")
                else None
            )
            models = await provider_manager.fetch_provider_models(provider_id)
            message = ""
            if (
                not models
                and provider is not None
                and not provider.api_key
                and provider.id not in KEYLESS_PROVIDER_IDS
            ):
                message = "该服务商尚未配置 API Key,请先配置后再发现"
            return {
                "code": 0,
                "data": {
                    "provider_id": provider_id,
                    "models": models,
                    "message": message,
                },
            }
    except Exception as e:
        logger.error(f"Discover models error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to discover models: {str(e)}")

    return {"code": 0, "data": {"provider_id": provider_id, "models": []}}


@router.get("/{provider_id}/models/series")
async def get_provider_series(
    request: Request,
    provider_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取 provider 可用的系列/服务商列表(如 OpenRouter 的 ['openai', ...])。"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        instance = getattr(provider_manager, "_get_provider_instance", lambda _: None)(
            provider_id,
        )
        if instance is not None and hasattr(instance, "get_available_providers"):
            series = await instance.get_available_providers()
            return {"code": 0, "data": {"provider_id": provider_id, "series": series}}
    except Exception as e:
        logger.error(f"Get series error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get series: {str(e)}")

    return {"code": 0, "data": {"provider_id": provider_id, "series": []}}


@router.post("/{provider_id}/models/filter")
async def filter_provider_models(
    request: Request,
    provider_id: str = Path(...),
    body: FilterModelsRequest = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """按系列/模态/价格/免费四维筛选 provider 发现的模型。"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        provider = (
            provider_manager.get_provider(provider_id)
            if hasattr(provider_manager, "get_provider")
            else None
        )
        if provider is None:
            return {"code": 0, "data": {"provider_id": provider_id, "models": [], "total_count": 0}}
        if not provider.api_key and provider.id not in KEYLESS_PROVIDER_IDS:
            # 与 discover 一致:未配置 key 时给可行动提示,而非静默空结果
            # (opencode/kilo-code 等免 key 网关不受此限)
            return {
                "code": 0,
                "data": {
                    "provider_id": provider_id,
                    "models": [],
                    "total_count": 0,
                    "message": "该服务商尚未配置 API Key,请先配置后再筛选",
                },
            }

        if hasattr(provider_manager, "filter_provider_models"):
            models = await provider_manager.filter_provider_models(
                provider_id,
                providers=body.providers or None,
                input_modalities=body.input_modalities or None,
                output_modalities=body.output_modalities or None,
                max_prompt_price=body.max_prompt_price,
                is_free=body.is_free,
            )
            payload = [_model_to_json(m) for m in models]
            return {
                "code": 0,
                "data": {
                    "provider_id": provider_id,
                    "models": payload,
                    "total_count": len(payload),
                },
            }
    except Exception as e:
        logger.error(f"Filter models error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to filter models: {str(e)}")

    return {"code": 0, "data": {"provider_id": provider_id, "models": [], "total_count": 0}}


@router.post("/{provider_id}/models/discover/merge")
async def merge_discovered_models_endpoint(
    request: Request,
    provider_id: str = Path(...),
    body: MergeDiscoveredRequest = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """把发现候选并入配置列表(选择式合并;None = 并入全部候选)。"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "merge_discovered_models"):
            merged_count = provider_manager.merge_discovered_models(
                provider_id,
                model_ids=body.model_ids,
            )
            return {
                "code": 0,
                "data": {
                    "provider_id": provider_id,
                    "merged_count": merged_count,
                },
            }
    except Exception as e:
        logger.error(f"Merge discovered models error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to merge: {str(e)}")

    return {"code": 0, "data": {"provider_id": provider_id, "merged_count": 0}}


@router.post("/{provider_id}/check-connection")
async def check_provider_connection(
    request: Request,
    provider_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """检查服务商连接"""
    _get_request_id(request)

    provider_manager = _get_provider_manager(current_user)
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "check_provider_connection"):
            result = await provider_manager.check_provider_connection(provider_id)
            return {"code": 0, "data": result}
    except Exception as e:
        logger.error(f"Check connection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Connection check failed: {str(e)}")

    return {"code": 0, "data": {"connected": False, "message": "Check not available"}}
