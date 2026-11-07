"""知识库自定义分类注册表端点（specs/2026-11-07 批 A）。

分类清单的受控管理面（单一事实源：`neurova/knowledge/categories_registry.py`）：
- GET    /v1/knowledge/categories          列表（登录可读；活跃分类。?include_inactive=true 仅 admin）
- POST   /v1/knowledge/categories          注册（仅管理员）
- PUT    /v1/knowledge/categories/{id}     更新/停用/复用（仅管理员）
- DELETE /v1/knowledge/categories/{id}     删除（仅管理员）

不做租户/部门切分——部门级开放由分组白名单（`allowed_categories`）表达。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _registry():
    from neurova.knowledge.categories_registry import CategoryRegistry
    from neurova.knowledge.foundation import get_knowledge_fact_store

    return CategoryRegistry(get_knowledge_fact_store())


def _actor(current_user: dict) -> str:
    return str((current_user or {}).get("username") or "")


def _visibleForUser(current_user: dict, items: list) -> list:
    """按请求身份过滤分类清单（specs/2026-11-07 §3：受限部门只见白名单内分类）。

    admin / 无部门组 / 未配置白名单 → 全量；受限部门 → 白名单内（解析失败
    回落全量，与服务端"不猜部门"的缺省语义一致）。
    """
    if str((current_user or {}).get("role") or "") == "admin":
        return items
    username = str((current_user or {}).get("username") or "")
    if not username:
        return items
    try:
        from neurova.auth.user_group_model import resolveUserDepartment

        dept = resolveUserDepartment(username)
    except Exception:  # noqa: BLE001 - 解析失败回落全量
        return items
    if not dept.get("restricted"):
        return items
    allowed = set(dept.get("allowed_categories") or [])
    return [c for c in items if c.get("category_id") in allowed]


class CategoryCreate(BaseModel):
    """注册分类请求"""

    category_id: str = Field(..., description="分类标识（规范化为小写后落库）")
    name: str = Field(..., description="分类名称")
    description: str = Field(default="", description="描述")


class CategoryUpdate(BaseModel):
    """更新分类请求（字段缺省 = 不动）"""

    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_categories(
    request: Request,
    include_inactive: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """分类列表 — 登录可读（活跃分类，按请求身份过滤：受限部门只见白名单内）；
    停用清单仅 admin 可看"""
    if include_inactive and str((current_user or {}).get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="停用分类清单仅管理员可查看")
    items = _registry().list(activeOnly=not include_inactive)
    items = _visibleForUser(current_user, items)
    return {"code": 0, "data": items, "request_id": getattr(request.state, "request_id", "")}


@router.post("")
async def create_category(
    request: Request,
    body: CategoryCreate,
    admin: dict = Depends(require_admin()),
):
    """注册分类 — 仅管理员"""
    try:
        item = _registry().create(
            categoryId=body.category_id, name=body.name, description=body.description, actor=_actor(admin)
        )
        return {"code": 0, "data": item, "request_id": getattr(request.state, "request_id", "")}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{category_id}")
async def update_category(
    request: Request,
    category_id: str = Path(..., description="分类标识"),
    body: CategoryUpdate = CategoryUpdate(),
    admin: dict = Depends(require_admin()),
):
    """更新/停用/复用分类 — 仅管理员"""
    try:
        item = _registry().update(
            categoryId=category_id,
            name=body.name,
            description=body.description,
            is_active=body.is_active,
            actor=_actor(admin),
        )
        return {"code": 0, "data": item, "request_id": getattr(request.state, "request_id", "")}
    except ValueError as e:
        raise HTTPException(status_code=404 if "未注册" in str(e) else 400, detail=str(e))


@router.delete("/{category_id}")
async def delete_category(
    request: Request,
    category_id: str = Path(..., description="分类标识"),
    admin: dict = Depends(require_admin()),
):
    """删除分类 — 仅管理员（引用该分类的分组白名单解析时如实剔除）"""
    deleted = _registry().delete(category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"分类 '{category_id}' 未注册")
    return {"code": 0, "data": {"category_id": category_id}, "request_id": getattr(request.state, "request_id", "")}
