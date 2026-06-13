"""
记忆共享组管理 API

提供共享组的 CRUD 操作，用于控制哪些 Agent 可以共享记忆。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neurova.cognitive_layers.memory_layer.share_group import (
    get_share_group_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory-share-groups", tags=["memory-share-groups"])


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────


class ShareGroupCreate(BaseModel):
    """创建共享组请求"""

    name: str = Field(..., description="共享组名称", min_length=1, max_length=100)
    description: str = Field("", description="共享组描述", max_length=500)
    agent_ids: List[str] = Field(default_factory=list, description="初始 Agent ID 列表")
    metadata: dict = Field(default_factory=dict, description="额外元数据")


class ShareGroupUpdate(BaseModel):
    """更新共享组请求"""

    name: Optional[str] = Field(None, description="共享组名称", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="共享组描述", max_length=500)
    metadata: Optional[dict] = Field(None, description="额外元数据")


class ShareGroupResponse(BaseModel):
    """共享组响应"""

    group_id: str
    name: str
    description: str
    agent_ids: List[str]
    created_at: str
    updated_at: str
    metadata: dict


class AddAgentRequest(BaseModel):
    """添加 Agent 到共享组请求"""

    agent_id: str = Field(..., description="Agent ID", min_length=1)


class RemoveAgentRequest(BaseModel):
    """从共享组移除 Agent 请求"""

    agent_id: str = Field(..., description="Agent ID", min_length=1)


# ── API 端点 ──────────────────────────────────────────────────────────────────


@router.get("", response_model=List[ShareGroupResponse])
async def list_share_groups():
    """获取所有共享组"""
    manager = get_share_group_manager()
    groups = manager.list_groups()
    return [group.to_dict() for group in groups]


@router.post("", response_model=ShareGroupResponse)
async def create_share_group(request: ShareGroupCreate):
    """创建共享组"""
    manager = get_share_group_manager()

    # 验证 agent_ids 不为空
    if not request.agent_ids:
        raise HTTPException(status_code=400, detail="agent_ids 不能为空")

    # 去重
    unique_agent_ids = list(set(request.agent_ids))

    group = manager.create_group(
        name=request.name,
        agent_ids=unique_agent_ids,
        description=request.description,
        metadata=request.metadata,
    )

    logger.info("Created share group: %s (%s)", group.group_id, request.name)
    return group.to_dict()


@router.get("/{group_id}", response_model=ShareGroupResponse)
async def get_share_group(group_id: str):
    """获取共享组详情"""
    manager = get_share_group_manager()
    group = manager.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return group.to_dict()


@router.put("/{group_id}", response_model=ShareGroupResponse)
async def update_share_group(group_id: str, request: ShareGroupUpdate):
    """更新共享组信息"""
    manager = get_share_group_manager()
    group = manager.update_group(
        group_id=group_id,
        name=request.name,
        description=request.description,
        metadata=request.metadata,
    )
    if not group:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return group.to_dict()


@router.delete("/{group_id}")
async def delete_share_group(group_id: str):
    """删除共享组"""
    manager = get_share_group_manager()
    success = manager.delete_group(group_id)
    if not success:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return {"success": True, "message": "共享组已删除"}


@router.post("/{group_id}/agents")
async def add_agent_to_group(group_id: str, request: AddAgentRequest):
    """将 Agent 添加到共享组"""
    manager = get_share_group_manager()
    success = manager.add_agent_to_group(group_id, request.agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return {"success": True, "message": f"Agent {request.agent_id} 已添加到共享组"}


@router.delete("/{group_id}/agents/{agent_id}")
async def remove_agent_from_group(group_id: str, agent_id: str):
    """从共享组移除 Agent"""
    manager = get_share_group_manager()
    success = manager.remove_agent_from_group(group_id, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return {"success": True, "message": f"Agent {agent_id} 已从共享组移除"}


@router.get("/{group_id}/agents")
async def get_agents_in_group(group_id: str):
    """获取共享组中的所有 Agent"""
    manager = get_share_group_manager()
    agents = manager.get_agents_in_group(group_id)
    if agents is None:
        raise HTTPException(status_code=404, detail="共享组不存在")
    return {"group_id": group_id, "agent_ids": agents}


@router.get("/agent/{agent_id}")
async def get_groups_for_agent(agent_id: str):
    """获取 Agent 所属的所有共享组"""
    manager = get_share_group_manager()
    groups = manager.get_groups_for_agent(agent_id)
    return {
        "agent_id": agent_id,
        "groups": [group.to_dict() for group in groups],
    }


@router.get("/agent/{agent_id}/shared-agents")
async def get_shared_agents(agent_id: str):
    """获取与指定 Agent 共享记忆的所有 Agent"""
    manager = get_share_group_manager()
    shared_agents = manager.get_shared_agent_ids(agent_id)
    return {
        "agent_id": agent_id,
        "shared_agents": list(shared_agents),
    }


@router.get("/check/{agent_id_1}/{agent_id_2}")
async def check_agents_shared(agent_id_1: str, agent_id_2: str):
    """检查两个 Agent 是否在同一共享组中"""
    manager = get_share_group_manager()
    is_shared = manager.are_agents_shared(agent_id_1, agent_id_2)
    return {
        "agent_id_1": agent_id_1,
        "agent_id_2": agent_id_2,
        "is_shared": is_shared,
    }
