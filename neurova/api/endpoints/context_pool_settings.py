"""
上下文池设置API - Context Pool Settings Endpoint

提供以下API:
1. 获取上下文池设置 (GET /api/v1/context-pool/pool-settings)
2. 更新上下文池设置 (PUT /api/v1/context-pool/pool-settings)
3. 获取特定模型的Token预算 (GET /api/v1/context-pool/pool-settings/token-budget/{model_name})
4. 测试Token预算计算 (POST /api/v1/context-pool/pool-settings/test-budget)
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.context_pool import ContextPool

logger = get_logger(__name__)

router = APIRouter()

# 默认上下文池设置
# Issue #65：``max_size`` 在 ContextPool「无损归档」改造后**已失效**（池不按容量
# 驱逐，常驻占用严格线性 0.76 KB/条）。此键仍在响应里（前端/历史调用方在读），
# 但必须与 ``max_size_effective=False`` 一起返回，否则等于继续谎报"设了有效"。
# 需要常驻上限请改用 ContextPool(resident_limit=..., ledger_db=...)。
_default_pool_settings = {
    "max_size": 100,
    "max_size_effective": False,
    "resident_limit": None,
    "ttl_seconds": 3600,
    "default_token_budget": 16000,
    "model_budgets": {
        "gpt-4": 32000,
        "gpt-4-turbo": 32000,
        "gpt-4o": 32000,
        "gpt-3.5-turbo": 16000,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "claude-2": 100000,
        "deepseek-chat": 32000,
        "deepseek-coder": 32000,
        "qwen-max": 32000,
        "qwen-turbo": 16000,
    },
}


class PoolSettingsResponse(BaseModel):
    """上下文池设置响应"""

    code: int = 0
    data: Dict[str, Any]
    message: Optional[str] = None


class UpdatePoolSettingsRequest(BaseModel):
    """更新上下文池设置请求"""

    max_size: Optional[int] = Field(None, ge=10, le=1000, description="最大池大小")
    ttl_seconds: Optional[int] = Field(None, ge=60, le=86400, description="TTL过期时间（秒）")
    default_token_budget: Optional[int] = Field(None, ge=1000, le=200000, description="默认Token预算")


class TestBudgetRequest(BaseModel):
    """测试Token预算计算请求"""

    model_name: str = Field(..., description="模型名称")
    capabilities: Optional[List[str]] = Field(None, description="模型能力列表")


class TestBudgetResponse(BaseModel):
    """测试Token预算计算响应"""

    code: int = 0
    data: Dict[str, Any]


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("/pool-settings", response_model=PoolSettingsResponse)
async def get_pool_settings(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取上下文池设置

    Issue #65：``max_size``/``ttl_seconds`` 为此前的"名义配置"（PUT 已于
    2026-09-12 改 501 如实上报"未接线"）。其中 ``max_size`` 更是**失效参数**
    ——ContextPool 不再按容量驱逐，故连同 ``max_size_effective=False`` 返回，
    避免调用方把"设了 max_size"误读成"内存有上限"。
    """
    _get_request_id(request)

    try:
        # 返回当前设置
        return PoolSettingsResponse(code=0, data=dict(_default_pool_settings))
    except Exception as e:
        logger.error(f"Get pool settings error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get pool settings: {str(e)}")


@router.put("/pool-settings", response_model=PoolSettingsResponse)
async def update_pool_settings(
    request: Request,
    body: UpdatePoolSettingsRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新上下文池设置

    2026-09-12 P7 诚实化：本设置与真实 ContextPool 运行时零接线（全仓无
    消费者，池创建不读这些键）——保存"成功"但运行时行为不变属假持久化，
    改 501 如实上报，待接线后恢复。GET 预览仍可读。
    """
    _get_request_id(request)

    raise HTTPException(
        status_code=501,
        detail="上下文池设置未与运行时接线（ContextPool 不消费这些键），暂不支持保存；防止假持久化",
    )


@router.get("/pool-settings/token-budget/{model_name}")
async def get_token_budget_for_model(
    request: Request,
    model_name: str = Path(..., description="模型名称"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取特定模型的Token预算"""
    _get_request_id(request)

    try:
        # 使用静态方法获取预算
        token_budget = ContextPool.get_token_budget_for_model(
            model_name, default_budget=_default_pool_settings["default_token_budget"]
        )

        return {"code": 0, "data": {"model_name": model_name, "token_budget": token_budget}}
    except Exception as e:
        logger.error(f"Get token budget error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get token budget: {str(e)}")


@router.post("/pool-settings/test-budget", response_model=TestBudgetResponse)
async def test_budget_calculation(
    request: Request,
    body: TestBudgetRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """测试Token预算计算"""
    _get_request_id(request)

    try:
        # 计算预算
        token_budget = ContextPool.get_token_budget_for_model(
            body.model_name, default_budget=_default_pool_settings["default_token_budget"]
        )

        # 生成解释
        explanation = f"基于模型名称匹配"
        if body.model_name.lower() in [k.lower() for k in _default_pool_settings["model_budgets"].keys()]:
            explanation = f"匹配到预设模型 '{body.model_name}'"
        else:
            explanation = f"使用默认预算 {_default_pool_settings['default_token_budget']}"

        return TestBudgetResponse(
            code=0,
            data={
                "model_name": body.model_name,
                "capabilities": body.capabilities or [],
                "calculated_budget": token_budget,
                "explanation": explanation,
            },
        )
    except Exception as e:
        logger.error(f"Test budget calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to test budget calculation: {str(e)}")
