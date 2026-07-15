"""
增强用户管理 API

提供以下端点:
- GET    /v1/enhanced-users                   列出用户
- POST   /v1/enhanced-users                   创建用户
- GET    /v1/enhanced-users/{user_id}         获取用户详情
- PUT    /v1/enhanced-users/{user_id}         更新用户
- DELETE /v1/enhanced-users/{user_id}         删除用户
- POST   /v1/enhanced-users/{user_id}/backup  备份用户
- GET    /v1/enhanced-users/{user_id}/quota    获取配额状态
- PUT    /v1/enhanced-users/{user_id}/password 修改密码
"""

from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class UserInfo(BaseModel):
    user_id: str
    username: str
    display_name: str = ""
    email: str = ""
    role: str = "user"
    group: str = "default"
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0


class UserCreate(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    display_name: str = Field(default="", description="显示名")
    email: str = Field(default="", description="邮箱")
    role: str = Field(default="user", description="角色")
    group: str = Field(default="default", description="用户组")


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    group: Optional[str] = None
    enabled: Optional[bool] = None


class PasswordChange(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., description="新密码")


class UserQuotaStatus(BaseModel):
    user_id: str
    storage_used: int = 0
    storage_limit: int = 0
    api_calls_today: int = 0
    api_calls_limit: int = 0


_users_store: Dict[str, Dict[str, Any]] = {}
_backups_store: Dict[str, Dict[str, Any]] = {}


@router.get("", response_model=List[UserInfo])
async def list_users(
    group: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
):
    """列出用户"""
    users = list(_users_store.values())
    if group:
        users = [u for u in users if u.get("group") == group]
    if role:
        users = [u for u in users if u.get("role") == role]
    return [UserInfo(**{k: v for k, v in u.items() if k != "password"}) for u in users]


@router.post("", response_model=UserInfo)
async def create_user(body: UserCreate):
    """创建用户"""
    uid = str(uuid.uuid4())
    now = time.time()
    user = {
        "user_id": uid,
        "username": body.username,
        "password": body.password,
        "display_name": body.display_name,
        "email": body.email,
        "role": body.role,
        "group": body.group,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    _users_store[uid] = user
    return UserInfo(**{k: v for k, v in user.items() if k != "password"})


@router.get("/{user_id}", response_model=UserInfo)
async def get_user(user_id: str):
    """获取用户详情"""
    user = _users_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserInfo(**{k: v for k, v in user.items() if k != "password"})


@router.put("/{user_id}", response_model=UserInfo)
async def update_user(user_id: str, body: UserUpdate):
    """更新用户"""
    user = _users_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for k, v in safe_model_dump(body, exclude_none=True).items():  # s9: pydantic v1 兼容
        user[k] = v
    user["updated_at"] = time.time()
    return UserInfo(**{k: v for k, v in user.items() if k != "password"})


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    """删除用户"""
    if user_id not in _users_store:
        raise HTTPException(status_code=404, detail="User not found")
    del _users_store[user_id]
    return {"code": 0, "message": "User deleted"}


@router.post("/{user_id}/backup")
async def backup_user(user_id: str):
    """备份用户资料"""
    user = _users_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    backup_id = str(uuid.uuid4())
    _backups_store[backup_id] = {
        "backup_id": backup_id,
        "user_id": user_id,
        "data": dict(user),
        "created_at": time.time(),
    }
    return {"code": 0, "message": "Backup created", "data": {"backup_id": backup_id}}


@router.get("/{user_id}/quota", response_model=UserQuotaStatus)
async def get_quota_status(user_id: str):
    """获取用户配额状态"""
    if user_id not in _users_store:
        raise HTTPException(status_code=404, detail="User not found")
    return UserQuotaStatus(
        user_id=user_id, storage_used=0, storage_limit=1073741824, api_calls_today=0, api_calls_limit=1000
    )


@router.put("/{user_id}/password")
async def change_password(user_id: str, body: PasswordChange):
    """修改密码"""
    user = _users_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["password"] = body.new_password
    user["updated_at"] = time.time()
    return {"code": 0, "message": "Password changed"}
