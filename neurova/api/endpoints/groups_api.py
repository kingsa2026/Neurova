from __future__ import annotations

"""
群组接口 - Groups Endpoint

功能:
1. 获取群组列表 (GET /api/v1/groups)
2. 创建群组 (POST /api/v1/groups)
3. 获取群组详情 (GET /api/v1/groups/{id})
4. 更新群组 (PUT /api/v1/groups/{id})
5. 删除群组 (DELETE /api/v1/groups/{id})
6. 添加成员 (POST /api/v1/groups/{id}/members)
7. 移除成员 (DELETE /api/v1/groups/{id}/members/{user_id})
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

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
    created_at: float = 0
    updated_at: float = 0


class GroupCreate(BaseModel):
    """创建群组请求"""

    name: str = Field(..., description="群组名称")
    description: str = Field(default="", description="群组描述")
    members: List[str] = Field(default_factory=list, description="初始成员")


class GroupUpdate(BaseModel):
    """更新群组请求"""

    name: Optional[str] = None
    description: Optional[str] = None


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("", response_model=List[GroupInfo])
async def get_groups(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取群组列表"""
    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()
        groups = manager.list_groups(limit=limit, offset=offset)

        # 转换为API响应格式
        result = []
        for group in groups:
            result.append(
                GroupInfo(
                    group_id=group.group_id,
                    name=group.name,
                    description=group.description,
                    owner_id="",  # UserGroup没有owner_id，使用空字符串
                    members=[],  # UserGroup没有members列表，使用空列表
                    created_at=group.created_at or 0,
                    updated_at=group.updated_at or 0,
                )
            )

        return result
    except Exception as e:
        logger.exception("Error getting groups: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get groups: {str(e)}")


@router.post("", response_model=GroupInfo)
async def create_group(
    request: Request,
    body: GroupCreate,
):
    """创建群组"""
    _get_request_id(request)

    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()

        # 创建用户组
        group = manager.create_group(
            name=body.name, description=body.description, group_type="custom"  # 默认为自定义类型
        )

        if group is None:
            raise HTTPException(status_code=500, detail="Failed to create group")

        # 添加成员
        for member_id in body.members:
            manager.add_user_to_group(member_id, group.group_id)

        timestamp = time.time()

        return GroupInfo(
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            owner_id="",
            members=body.members,
            created_at=group.created_at or timestamp,
            updated_at=group.updated_at or timestamp,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating group: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create group: {str(e)}")


@router.get("/{group_id}", response_model=GroupInfo)
async def get_group(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
):
    """获取群组详情"""
    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()
        group = manager.get_group(group_id)

        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 获取组成员
        members = manager.get_group_members(group_id)

        return GroupInfo(
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            owner_id="",
            members=members,
            created_at=group.created_at or 0,
            updated_at=group.updated_at or 0,
        )
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
):
    """更新群组"""
    _get_request_id(request)

    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()
        group = manager.get_group(group_id)

        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 更新组信息
        if body.name is not None:
            group.name = body.name
        if body.description is not None:
            group.description = body.description

        # 保存更新
        manager.update_group(group)

        # 获取组成员
        members = manager.get_group_members(group_id)

        return GroupInfo(
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            owner_id="",
            members=members,
            created_at=group.created_at or 0,
            updated_at=group.updated_at or 0,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update group: {str(e)}")


@router.delete("/{group_id}")
async def delete_group(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
):
    """删除群组"""
    request_id = _get_request_id(request)

    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()
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


@router.post("/{group_id}/members")
async def add_group_member(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    user_id: str = Query(..., description="用户ID"),
):
    """添加群组成员"""
    request_id = _get_request_id(request)

    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()

        # 检查组是否存在
        group = manager.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 添加成员
        success = manager.add_user_to_group(user_id, group_id)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to add user '{user_id}' to group '{group_id}'")

        return {
            "code": 0,
            "message": f"User '{user_id}' added to group '{group_id}'",
            "data": {"group_id": group_id, "user_id": user_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error adding member to group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to add member: {str(e)}")


@router.delete("/{group_id}/members/{user_id}")
async def remove_group_member(
    request: Request,
    group_id: str = Path(..., description="群组ID"),
    user_id: str = Path(..., description="用户ID"),
):
    """移除群组成员"""
    request_id = _get_request_id(request)

    if get_user_group_manager is None:
        raise HTTPException(status_code=503, detail="User group service not available")

    try:
        manager = get_user_group_manager()

        # 检查组是否存在
        group = manager.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found")

        # 移除成员
        success = manager.remove_user_from_group(user_id, group_id)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to remove user '{user_id}' from group '{group_id}'")

        return {
            "code": 0,
            "message": f"User '{user_id}' removed from group '{group_id}'",
            "data": {"group_id": group_id, "user_id": user_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error removing member from group %s: %s", group_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to remove member: {str(e)}")
