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
from typing import List

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


class ModelInfo(BaseModel):
    """模型信息"""

    model_id: str
    name: str
    provider: str = ""
    capabilities: List[str] = []
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


def _get_provider_manager():
    """获取 Provider 管理器"""
    from neurova.api.endpoints import get_provider_manager

    return get_provider_manager()


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


@router.get("", response_model=List[ModelInfo])
async def list_models(request: Request):
    """列出可用模型"""
    _get_request_id(request)

    models = []
    provider_manager = _get_provider_manager()

    if provider_manager:
        try:
            if hasattr(provider_manager, "get_all_models"):
                all_models = provider_manager.get_all_models()
                for model in all_models:
                    # PydanticModelInfo uses 'owned_by' for provider_id
                    models.append(
                        ModelInfo(
                            model_id=getattr(model, "id", "unknown"),
                            name=getattr(model, "name", "Unknown"),
                            provider=getattr(model, "owned_by", ""),
                            capabilities=getattr(model, "capabilities", []),
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


@router.delete("/{model_id}")
async def delete_model(request: Request, model_id: str = Path(...)):
    """删除模型（从所属服务商的模型列表中移除）"""
    _get_request_id(request)

    provider_manager = _get_provider_manager()
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
async def probe_multimodal(request: Request, body: ProbeRequest):
    """模型多模态探测"""
    _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        result = {}
        if hasattr(provider_manager, "probe_model_multimodal"):
            result = provider_manager.probe_model_multimodal(body.model_id)

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
async def check_connection(request: Request, model_id: str = Query(...)):
    """检查模型连接"""
    _get_request_id(request)

    provider_manager = _get_provider_manager()
    if not provider_manager:
        raise HTTPException(status_code=503, detail="Provider manager not available")

    try:
        connected = False
        message = ""

        if hasattr(provider_manager, "check_model_connection"):
            result = provider_manager.check_model_connection(model_id)
            connected = result.get("connected", False)
            message = result.get("message", "")

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
