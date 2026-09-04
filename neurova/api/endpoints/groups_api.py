from __future__ import annotations

"""
群组接口 - Groups Endpoint

功能:
1. 获取群组列表 (GET /api/v1/groups)
2. 创建群组 (POST /api/v1/groups)
3. 获取群组详情 (GET /api/v1/groups/{id})
4. 更新群组 (PUT /api/v1/groups/{id}) — 含 allowed_modules 功能模块白名单
5. 删除群组 (DELETE /api/v1/groups/{id})
6. 获取成员 (GET /api/v1/groups/{id}/members)
7. 添加成员 (POST /api/v1/groups/{id}/members) — body {username}
8. 移除成员 (DELETE /api/v1/groups/{id}/members/{username})
"""

from neurova.core.logger import get_logger
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)

router = APIRouter()

# 导入用户组服务
try:
    from neurova.auth.user_group_model import UserGroup, UserGroupManager, get_user_group_manager
except ImportError:
    logger.warning("User group service not available")
    get_user_group_manager = None
    UserGroupManager = None
    UserGroup = None


class GroupInfo(BaseModel):
    """群组信息"""

    group_id: str
    name: str
    description: str = ""
    owner_id: str = ""
    members: List[str] = []
    members_count: int = 0
    allowed_modules: List[str] = []
    is_system: bool = False
    created_at: float = 0
    updated_at: float = 0


class GroupCreate(BaseModel):
    """创建群组请求"""

    name: str = Field(..., description="群组名称")
    description: str = Field(default="", description="群组描述")
    members: List[str] = Field(default_factory=list, description="初始成员（用户名）")
    allowed_modules: Optional[List[str]] = Field(default=None, description="可用功能模块（菜单路由 key）")


class GroupUpdate(BaseModel):
    """更新群组请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    allowed_modules: Optional[List[str]] = None


class GroupMemberAdd(BaseModel):
    """添加成员请求"""

    username: str = Field(default="", description="用户名")


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _group_to_info(group: UserGroup) -> GroupInfo:
    """UserGroup → API 响应模型"""
    members = list(group.members or [])
    return GroupInfo(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        owner_id="",
        members=members,
        members_count=len(members),
        allowed_modules=list(group.allowed_modules or []),
        is_system=bool(group.is_system),
        created_at=group.created_at or 0,
        updated_at=group.updated_at or 0,
    )


def _require_manager():
    """获取用户组管理器，服务不可用时抛 503"""
    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")
    return get_user_group_manager()


@router.get("", response_model=List[GroupInfo])
async def get_groups(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取群组列表 — 登录用户可读"""
    try:
        manager = _require_manager()
        groups = manager.list_groups()
        return [_group_to_info(group) for group in groups]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting groups: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get groups: {str(e)}")


@router.post("", response_model=GroupInfo)
async def create_group(
    request: Request,
    body: GroupCreate,
    admin: dict = Depends(require_admin()),
):
    """创建群组 — 仅管理员"""
    _get_request_id(request)

    try:
        manager = _require_manager()

        # 创建用户组
        group = manager.create_group(
            name=body.name, description=body.description, group_type="custom"  # 默认为自定义类型
        )

        if group is None:
            raise HTTPException(status_code=500, detail="Failed to create group")

        # 功能模块白名单
        if body.allowed_modules is not None:
            manager.set_allowed_modules(group.group_id, body.allowed_modules)

        # 添加初始成员（用户名）
        for member_name in body.members:
            manager.add_user_to_group(member_name, group.group_id)

        return _group_to_info(manager.get_group(group.group_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating group: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create group: {str(e)}")


@router.get("/{group_id}", response_model=GroupInfo)
async def get_group(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    current_user: dict = Depends(get_current_user),
):
    """获取群组详情 — 登录用户可读"""
    try:
        manager = _require_manager()
        group = manager.get_group(group_id)

        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        return _group_to_info(group)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to get group: {str(e)}")


@router.put("/{group_id}", response_model=GroupInfo)
async def update_group(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    body: GroupUpdate = GroupUpdate(),
    admin: dict = Depends(require_admin()),
):
    """更新群组 — 仅管理员。

    name/description 仅自定义组可改（系统组由 manager 保护）；
    allowed_modules 属运营配置，系统组/自定义组均可设置。
    """
    _get_request_id(request)

    try:
        manager = _require_manager()
        group = manager.get_group(group_id)

        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 更新组信息（仅自定义组；系统组 update_group 内部拒绝并返回 None）
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        if updates:
            updated = manager.update_group(group_id, **updates)
            if updated is not None:
                group = updated

        # 功能模块白名单（系统组也可设置）
        if body.allowed_modules is not None:
            updated = manager.set_allowed_modules(group_id, body.allowed_modules)
            if updated is not None:
                group = updated

        return _group_to_info(group)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update group: {str(e)}")


@router.delete("/{group_id}")
async def delete_group(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    admin: dict = Depends(require_admin()),
):
    """删除群组 — 仅管理员"""
    request_id = _get_request_id(request)

    try:
        manager = _require_manager()
        success = manager.delete_group(group_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        return {
            "code": 0,
            "message": f"Group '{group_id}' deleted",
            "data": {"group_id": group_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete group: {str(e)}")


@router.get("/{group_id}/members")
async def get_group_members(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    current_user: dict = Depends(get_current_user),
):
    """获取群组成员 — 登录用户可读"""
    try:
        manager = _require_manager()
        group = manager.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        members = manager.get_group_members(group_id)
        return [{"id": name, "username": name} for name in members]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting members of group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to get members: {str(e)}")


@router.post("/{group_id}/members")
async def add_group_member(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    body: GroupMemberAdd = GroupMemberAdd(),
    admin: dict = Depends(require_admin()),
):
    """添加群组成员 — 仅管理员（按用户名，即 users.username 唯一标识）"""
    request_id = _get_request_id(request)

    try:
        if not body.username:
            raise HTTPException(status_code=422, detail="username is required")
        manager = _require_manager()

        # 检查组是否存在
        group = manager.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 添加成员
        success = manager.add_user_to_group(body.username, group_id)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to add user '{body.username}' to group '{group_id}'")

        return {
            "code": 0,
            "message": f"User '{body.username}' added to group '{group_id}'",
            "data": {"group_id": group_id, "username": body.username},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error adding member to group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)}")


@router.delete("/{group_id}/members/{username}")
async def remove_group_member(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    username: str = Path(..., description="用户名"),
    admin: dict = Depends(require_admin()),
):
    """移除群组成员 — 仅管理员"""
    request_id = _get_request_id(request)

    try:
        manager = _require_manager()

        # 检查组是否存在
        group = manager.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 移除成员
        success = manager.remove_user_from_group(username, group_id)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to remove user '{username}' from group '{group_id}'")

        return {
            "code": 0,
            "message": f"User '{username}' removed from group '{group_id}'",
            "data": {"group_id": group_id, "username": username},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error removing member from group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to remove member: {str(e)}")
