"""
用户组管理 API

提供以下端点:
- GET    /v1/user-groups                列出用户组
- POST   /v1/user-groups                创建用户组
- GET    /v1/user-groups/{group_id}     获取用户组详情
- PUT    /v1/user-groups/{group_id}     更新用户组
- DELETE /v1/user-groups/{group_id}     删除用户组
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class UserGroupInfo(BaseModel):
    group_id: str
    name: str
    description: str = ""
    is_system: bool = False
    permissions: List[str] = []
    users_count: int = 0
    created_at: float = 0
    updated_at: float = 0


class UserGroupCreate(BaseModel):
    name: str = Field(..., description="用户组名称")
    description: str = Field(default="", description="描述")
    permissions: List[str] = Field(default_factory=list, description="权限列表")


class UserGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


_groups_store: Dict[str, Dict[str, Any]] = {}

# 预置系统内置组
for _gid, _gname, _perms in [
    ("admin", "管理员", ["*"]),
    ("default", "默认用户", ["chat", "memory", "skill"]),
    ("readonly", "只读用户", ["chat:read"]),
]:
    _groups_store[_gid] = {
        "group_id": _gid,
        "name": _gname,
        "description": f"系统内置{_gname}组",
        "is_system": True,
        "permissions": _perms,
        "users_count": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
    }


@router.get("", response_model=List[UserGroupInfo])
async def list_user_groups():
    """列出所有用户组"""
    return [UserGroupInfo(**g) for g in _groups_store.values()]


@router.get("/{group_id}", response_model=UserGroupInfo)
async def get_user_group(group_id: str):
    """获取用户组详情"""
    group = _groups_store.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    return UserGroupInfo(**group)


@router.post("", response_model=UserGroupInfo)
async def create_user_group(body: UserGroupCreate):
    """创建用户组"""
    gid = str(uuid.uuid4())
    now = time.time()
    group = {
        "group_id": gid,
        "name": body.name,
        "description": body.description,
        "is_system": False,
        "permissions": body.permissions,
        "users_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    _groups_store[gid] = group
    return UserGroupInfo(**group)


@router.put("/{group_id}", response_model=UserGroupInfo)
async def update_user_group(group_id: str, body: UserGroupUpdate):
    """更新用户组"""
    group = _groups_store.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    if group.get("is_system"):
        raise HTTPException(status_code=403, detail="Cannot modify system group")
    for k, v in body.model_dump(exclude_none=True).items():
        group[k] = v
    group["updated_at"] = time.time()
    return UserGroupInfo(**group)


@router.delete("/{group_id}")
async def delete_user_group(group_id: str):
    """删除用户组"""
    group = _groups_store.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="User group not found")
    if group.get("is_system"):
        raise HTTPException(status_code=403, detail="Cannot delete system group")
    del _groups_store[group_id]
    return {"code": 0, "message": "User group deleted"}
