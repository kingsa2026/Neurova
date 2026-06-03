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

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_provider_manager():
    """获取 Provider 管理器"""
    from neurova.api.endpoints import get_provider_manager
    return get_provider_manager()


@router.get("", response_model=List[ProviderInfo])
async def list_providers(request: Request):
    """列出所有服务商"""
    request_id = _get_request_id(request)

    providers = []
    provider_manager = _get_provider_manager()

    if provider_manager:
        try:
            if hasattr(provider_manager, "get_all_providers"):
                all_providers = provider_manager.get_all_providers()
                for provider in all_providers:
                    providers.append(ProviderInfo(
                        provider_id=getattr(provider, "provider_id", "unknown"),
                        name=getattr(provider, "name", "Unknown"),
                        provider_type=getattr(provider, "provider_type", ""),
                        base_url=getattr(provider, "base_url", ""),
                        is_active=getattr(provider, "is_active", False),
                        status=getattr(provider, "status", "unknown"),
                        models_count=getattr(provider, "models_count", 0),
                    ))
        except Exception as e:
            logger.warning(f"List providers error: {e}")

    return providers


@router.get("/{provider_id}", response_model=ProviderInfo)
async def get_provider(request: Request, provider_id: str = Path(...)):
    """获取服务商详情"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "get_provider"):
            provider = provider_manager.get_provider(provider_id)
            if provider:
                return ProviderInfo(
                    provider_id=getattr(provider, "provider_id", provider_id),
                    name=getattr(provider, "name", "Unknown"),
                    provider_type=getattr(provider, "provider_type", ""),
                    base_url=getattr(provider, "base_url", ""),
                    is_active=getattr(provider, "is_active", False),
                    status=getattr(provider, "status", "unknown"),
                    models_count=getattr(provider, "models_count", 0),
                )
    except Exception as e:
        logger.warning(f"Get provider error: {e}")

    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


@router.post("", response_model=ProviderInfo)
async def create_provider(request: Request, body: CreateProviderRequest):
    """添加服务商"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        provider_id = str(uuid.uuid4())[:8]

        if hasattr(provider_manager, "add_provider"):
            provider = provider_manager.add_provider(
                provider_id=provider_id,
                name=body.name,
                provider_type=body.provider_type,
                base_url=body.base_url,
                api_key=body.api_key,
                config=body.config,
            )

            return ProviderInfo(
                provider_id=provider_id,
                name=body.name,
                provider_type=body.provider_type,
                base_url=body.base_url or "",
                is_active=True,
                status="created",
            )
    except Exception as e:
        logger.error(f"Create provider error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create provider: {str(e)}")

    raise HTTPException(status_code=500, detail="Failed to create provider")


@router.put("/{provider_id}", response_model=ProviderInfo)
async def update_provider(
    request: Request,
    provider_id: str = Path(...),
    body: UpdateProviderRequest = Body(...),
):
    """更新服务商"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "update_provider"):
            provider = provider_manager.update_provider(
                provider_id=provider_id,
                name=body.name,
                base_url=body.base_url,
                api_key=body.api_key,
                config=body.config,
            )

            if provider:
                return ProviderInfo(
                    provider_id=getattr(provider, "provider_id", provider_id),
                    name=getattr(provider, "name", "Unknown"),
                    provider_type=getattr(provider, "provider_type", ""),
                    base_url=getattr(provider, "base_url", ""),
                    is_active=getattr(provider, "is_active", False),
                    status="updated",
                )
    except Exception as e:
        logger.error(f"Update provider error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update provider: {str(e)}")

    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


@router.delete("/{provider_id}")
async def delete_provider(request: Request, provider_id: str = Path(...)):
    """删除服务商"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
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


@router.post("/activate-model")
async def activate_model(request: Request, body: ActivateModelRequest):
    """激活模型"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
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
async def get_active_model(request: Request):
    """获取当前活跃模型"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        return {"code": 0, "data": {"model": None, "provider": None}}

    try:
        if hasattr(provider_manager, "get_active_model"):
            active = provider_manager.get_active_model()
            return {"code": 0, "data": active}
    except Exception as e:
        logger.warning(f"Get active model error: {e}")

    return {"code": 0, "data": {"model": None, "provider": None}}


@router.get("/{provider_id}/models/discover")
async def discover_models(request: Request, provider_id: str = Path(...)):
    """发现模型"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "fetch_provider_models"):
            models = provider_manager.fetch_provider_models(provider_id)
            return {
                "code": 0,
                "data": {
                    "provider_id": provider_id,
                    "models": models,
                },
            }
    except Exception as e:
        logger.error(f"Discover models error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to discover models: {str(e)}")

    return {"code": 0, "data": {"provider_id": provider_id, "models": []}}


@router.post("/{provider_id}/check-connection")
async def check_provider_connection(request: Request, provider_id: str = Path(...)):
    """检查服务商连接"""
    request_id = _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        if hasattr(provider_manager, "check_provider_connection"):
            result = provider_manager.check_provider_connection(provider_id)
            return {"code": 0, "data": result}
    except Exception as e:
        logger.error(f"Check connection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Connection check failed: {str(e)}")

    return {"code": 0, "data": {"connected": False, "message": "Check not available"}}
