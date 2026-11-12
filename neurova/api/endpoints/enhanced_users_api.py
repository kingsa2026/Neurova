"""增强用户管理 API——真账本单源（`neurova/auth/user_model.UserModel` / users.db）。

接通记录（2026-11-12 断点修复）：本模块此前 8 端点全读进程内 `_users_store` 假
字典——创建的用户无法登录、改密不影响鉴权、删除的账号照常登录，页面
EnhancedUserPage 整条写入→读取→反馈闭环断裂。现全部端点改走登录链路的同一份
账本 UserModel（访问器复用 endpoints.auth 的 `_get_user_model` 单例，不另立实例），
哈希走 `auth.hash_password`（与登录验密同口径）。

消费方契约按 EnhancedUserPage 实际形态对齐：`{items, total}` 分页、行键 `id`
（真账本 int 主键）、`active` 布尔（映射账本 status active/disabled）、
`GET /backup` 真导出（脱敏 JSON，无任何口令材料）。

假面退役：`GET /{id}` 详情（页面零消费）、`GET /{id}/quota`（假常量——系统无
per-user 配额账本）、`POST /{id}/backup`（假单体备份）三端点直接拔除，
缺席由 tests/unit/api/test_enhanced_users_real_store.py 钉死。

安全护栏：自删 409——操作者经 require_admin 恒为 admin，自删禁令同时保住
最后一名 admin（删除他人 admin 后操作者仍是 admin，无需第二道护栏）；
重名/重邮箱 409（账本 ValueError 显式映射）。
"""

from typing import Any, Dict, Optional

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.auth.user_model import User
from neurova.api.auth import hash_password
from neurova.api.deps import require_admin
from neurova.api.endpoints._pydantic_compat import safe_model_dump
from neurova.core.logger import get_logger

logger = get_logger(__name__)
# 用户管理整路由仅管理员（列表/导出同样属管理数据）
router = APIRouter(dependencies=[Depends(require_admin())])


class UserOut(BaseModel):
    id: int
    username: str
    email: str = ""
    role: str = "user"
    active: bool = True
    created_at: str = ""
    last_login: str = ""


class UserCreate(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="初始密码（登录链路同款哈希落库）")
    email: str = Field(default="", description="邮箱")
    role: str = Field(default="user", description="角色")
    active: bool = Field(default=True, description="启用状态")


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


class PasswordReset(BaseModel):
    password: str = Field(..., description="新密码（管理员重置；哈希落库）")


def _get_model():
    # 真账本单源：与登录/注册/首账号引导共用同一访问器（endpoints.auth 的 DCL 单例）
    from neurova.api.endpoints.auth import _get_user_model

    return _get_user_model()


def _userOut(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email or "",
        role=user.role,
        active=(user.status == "active"),
        created_at=user.created_at or "",
        last_login=user.last_login or "",
    )


@router.get("", response_model=Dict[str, Any])
async def list_users(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    role: Optional[str] = None,
):
    """列出用户（真账本分页；search 按 username/email 子串过滤）。"""
    model = _get_model()
    totalAll = model.count_users(role=role)
    users = model.list_users(limit=max(1, totalAll), role=role) if totalAll else []
    needle = (search or "").strip().lower()
    if needle:
        users = [u for u in users if needle in u.username.lower() or needle in (u.email or "").lower()]
    total = len(users)
    start = max(0, (page - 1)) * max(1, page_size)
    pageItems = users[start:start + max(1, page_size)]
    return {"items": [safe_model_dump(_userOut(u)) for u in pageItems], "total": total}


@router.post("", response_model=UserOut)
async def create_user(body: UserCreate):
    """创建用户（哈希落真账本；创建的账号立即可走登录链路）。"""
    username = (body.username or "").strip()
    if not username:
        raise HTTPException(status_code=422, detail="用户名不能为空")
    if not body.password:
        raise HTTPException(status_code=422, detail="初始密码不能为空")
    try:
        user = _get_model().create_user(
            username,
            hash_password(body.password),
            email=(body.email or "").strip() or None,
            role=body.role or "user",
            status="active" if body.active else "disabled",
        )
    except ValueError as e:
        # 账本对重名/重邮箱 fail-fast，显式映射 409 不吞
        raise HTTPException(status_code=409, detail=str(e))
    return _userOut(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate):
    """更新用户（email/role/启用状态 → 账本字段 email/role/status）。"""
    model = _get_model()
    user = model.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    kwargs: Dict[str, Any] = {}
    if body.email is not None:
        email = body.email.strip() or None
        if email and email != (user.email or None):
            existing = model.get_user_by_email(email)
            if existing and existing.id != user_id:
                raise HTTPException(status_code=409, detail=f"Email '{email}' already exists")
        kwargs["email"] = email
    if body.role is not None:
        kwargs["role"] = body.role
    if body.active is not None:
        kwargs["status"] = "active" if body.active else "disabled"
    if kwargs and not model.update_user(user_id, **kwargs):
        raise HTTPException(status_code=500, detail="用户更新失败")
    return _userOut(model.get_user_by_id(user_id))


@router.put("/{user_id}/password")
async def change_password(user_id: int, body: PasswordReset):
    """管理员重置密码（哈希落真账本——改密即影响登录鉴权）。"""
    if not body.password:
        raise HTTPException(status_code=422, detail="新密码不能为空")
    ok = _get_model().update_user(user_id, password_hash=hash_password(body.password))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"code": 0, "message": "Password changed"}


@router.delete("/{user_id}")
async def delete_user(user_id: int, current: Dict[str, Any] = Depends(require_admin())):
    """删除用户（自删 409：操作者恒为 admin，禁令同时保住最后一名 admin）。

    操作者身份以**账本为准**：按 username 回查真账本拿权威 id——存量令牌的
    JWT sub 可能是非数字（用户名形态），整型化比对会旁路护栏（live-verify 实测）。
    """
    model = _get_model()
    operatorName = str(current.get("username") or "")
    operator = model.get_user_by_username(operatorName) if operatorName else None
    if operator is None:
        try:
            subId = int(str(current.get("user_id") or current.get("neuser_id") or "0"))
            operator = model.get_user_by_id(subId) if subId else None
        except ValueError:
            operator = None
    if operator is not None and user_id == operator.id:
        raise HTTPException(status_code=409, detail="不能删除当前登录账号")
    if not model.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"code": 0, "message": "User deleted"}


@router.get("/backup")
async def backup_users():
    """导出全部用户（脱敏 JSON：不含 password_hash 等任何口令材料）。"""
    model = _get_model()
    total = model.count_users()
    users = model.list_users(limit=max(1, total)) if total else []
    return {
        "exported_at": datetime.datetime.now().isoformat(),
        "users": [safe_model_dump(_userOut(u)) for u in users],
    }
