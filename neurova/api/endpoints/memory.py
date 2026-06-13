from __future__ import annotations

"""
记忆管理接口 - Memory Endpoint

功能:
1. 查询记忆 (GET /api/v1/memory)
2. 获取记忆详情 (GET /api/v1/memory/{memory_id})
3. 创建记忆 (POST /api/v1/memory)
4. 更新记忆 (PUT /api/v1/memory/{memory_id})
5. 删除记忆 (DELETE /api/v1/memory/{memory_id})
6. 搜索记忆 (POST /api/v1/memory/search)
7. 获取记忆统计 (GET /api/v1/memory/stats)
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.endpoints import get_agent_instance

logger = logging.getLogger(__name__)

router = APIRouter()


class MemoryItem(BaseModel):
    """记忆项"""

    memory_id: str
    content: str
    memory_type: str = "conversation"
    importance: float = 0.5
    tags: List[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = {}


class CreateMemoryRequest(BaseModel):
    """创建记忆请求"""

    content: str = Field(..., description="记忆内容")
    memory_type: str = Field(default="conversation", description="记忆类型")
    importance: float = Field(default=0.5, description="重要性", ge=0, le=1)
    tags: List[str] = Field(default=[], description="标签")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""

    query: str = Field(..., description="搜索查询")
    memory_type: Optional[str] = Field(default=None, description="记忆类型过滤")
    tags: List[str] = Field(default=[], description="标签过滤")
    limit: int = Field(default=20, description="返回数量限制")
    min_importance: float = Field(default=0, description="最小重要性")


class MemoryStats(BaseModel):
    """记忆统计"""

    total_count: int = 0
    by_type: Dict[str, int] = {}
    avg_importance: float = 0
    oldest_memory: Optional[str] = None
    newest_memory: Optional[str] = None


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    return get_agent_instance(agent_id)


@router.get("")
async def list_memories(
    request: Request,
    agent_id: str = Query(default="default"),
    memory_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """查询记忆列表"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        return {"code": 0, "data": {"count": 0, "memories": []}}

    memories = []
    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            # 优先使用 get_memories 方法获取列表
            if hasattr(mem_core, "get_memories"):
                results = mem_core.get_memories(limit=limit, offset=offset)
            elif hasattr(mem_core, "memory_manager") and mem_core.memory_manager:
                # 降级到 memory_manager.get_memories()
                results = mem_core.memory_manager.get_memories(limit=limit, offset=offset)
            elif hasattr(mem_core, "search_memories"):
                # 最后降级到 search_memories（但空查询会返回空）
                results = mem_core.search_memories(
                    query="",
                    limit=limit,
                )
            else:
                results = []

            for mem in results:
                # get_memories() 返回 dict 列表，用 dict.get() 而非 getattr()
                mem_dict = mem if isinstance(mem, dict) else getattr(mem, "__dict__", mem)

                # 处理 memory_type 过滤
                mem_type = (
                    mem_dict.get("memory_type", "semantic")
                    if isinstance(mem_dict, dict)
                    else getattr(mem, "memory_type", "semantic")
                )
                if hasattr(mem_type, "value"):
                    mem_type = mem_type.value
                elif not isinstance(mem_type, str):
                    mem_type = str(mem_type)

                if memory_type and mem_type != memory_type:
                    continue

                # 处理 category 字段
                mem_category = (
                    mem_dict.get("category", "general")
                    if isinstance(mem_dict, dict)
                    else getattr(mem, "category", "general")
                )
                if hasattr(mem_category, "value"):
                    mem_category = mem_category.value
                elif not isinstance(mem_category, str):
                    mem_category = str(mem_category)

                # 处理时间戳
                created_at = (
                    mem_dict.get("created_at", "") if isinstance(mem_dict, dict) else getattr(mem, "created_at", "")
                )
                if hasattr(created_at, "isoformat"):
                    created_at = created_at.isoformat()
                else:
                    created_at = str(created_at)

                updated_at = (
                    mem_dict.get("updated_at", "") if isinstance(mem_dict, dict) else getattr(mem, "updated_at", "")
                )
                if hasattr(updated_at, "isoformat"):
                    updated_at = updated_at.isoformat()
                else:
                    updated_at = str(updated_at)

                content = mem_dict.get("content", "") if isinstance(mem_dict, dict) else getattr(mem, "content", "")

                memories.append(
                    {
                        "id": (
                            mem_dict.get("id", str(uuid.uuid4()))
                            if isinstance(mem_dict, dict)
                            else getattr(mem, "id", str(uuid.uuid4()))
                        ),
                        "content": content,
                        "type": mem_type,
                        "category": mem_category,
                        "importance": (
                            mem_dict.get("importance", 0.5)
                            if isinstance(mem_dict, dict)
                            else getattr(mem, "importance", 0.5)
                        ),
                        "tags": mem_dict.get("tags", []) if isinstance(mem_dict, dict) else getattr(mem, "tags", []),
                        "shared": (
                            mem_dict.get("shared", False)
                            if isinstance(mem_dict, dict)
                            else getattr(mem, "shared", False)
                        ),
                        "agent_id": (
                            mem_dict.get("agent_id", "") if isinstance(mem_dict, dict) else getattr(mem, "agent_id", "")
                        ),
                        "share_group_ids": (
                            mem_dict.get("share_group_ids", [])
                            if isinstance(mem_dict, dict)
                            else getattr(mem, "share_group_ids", [])
                        ),
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "summary": content[:100] if content else "",
                        "timestamp": (
                            mem_dict.get("timestamp", time.time() * 1000)
                            if isinstance(mem_dict, dict)
                            else getattr(mem, "timestamp", time.time() * 1000)
                        ),
                        "metadata": (
                            mem_dict.get("metadata", {}) if isinstance(mem_dict, dict) else getattr(mem, "metadata", {})
                        ),
                    }
                )
    except Exception as e:
        logger.warning("List memories error: %s", e)

    return {"data": {"total": len(memories), "memories": memories}}


@router.get("/{memory_id}", response_model=MemoryItem)
async def get_memory(request: Request, memory_id: str = Path(...), agent_id: str = Query(default="default")):
    """获取记忆详情"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "get_memory"):
                mem = mem_core.get_memory(memory_id)
                if mem:
                    return MemoryItem(
                        memory_id=getattr(mem, "id", memory_id),
                        content=getattr(mem, "content", ""),
                        memory_type=getattr(mem, "memory_type", "conversation"),
                        importance=getattr(mem, "importance", 0.5),
                        tags=getattr(mem, "tags", []),
                        created_at=str(getattr(mem, "created_at", "")),
                        metadata=getattr(mem, "metadata", {}),
                    )
    except Exception as e:
        logger.warning("Get memory error: %s", e)

    raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")


@router.post("", response_model=MemoryItem)
async def create_memory(request: Request, body: CreateMemoryRequest, agent_id: str = Query(default="default")):
    """创建记忆"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    memory_id = str(uuid.uuid4())

    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "remember"):
                mem_core.remember(
                    content=body.content,
                    memory_type=body.memory_type,
                    importance=body.importance,
                    tags=body.tags,
                    metadata=body.metadata,
                )
    except Exception as e:
        logger.warning("Create memory error: %s", e)

    return MemoryItem(
        memory_id=memory_id,
        content=body.content,
        memory_type=body.memory_type,
        importance=body.importance,
        tags=body.tags,
        created_at=str(time.time()),
        metadata=body.metadata,
    )


@router.post("/search", response_model=List[MemoryItem])
async def search_memories(request: Request, body: SearchMemoryRequest, agent_id: str = Query(default="default")):
    """搜索记忆"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        return []

    memories = []
    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "search_memories"):
                results = mem_core.search_memories(
                    query=body.query,
                    memory_type=body.memory_type,
                    limit=body.limit,
                )
                for mem in results:
                    importance = getattr(mem, "importance", 0)
                    if importance >= body.min_importance:
                        memories.append(
                            MemoryItem(
                                memory_id=getattr(mem, "id", str(uuid.uuid4())),
                                content=getattr(mem, "content", ""),
                                memory_type=getattr(mem, "memory_type", "conversation"),
                                importance=importance,
                                tags=getattr(mem, "tags", []),
                                created_at=str(getattr(mem, "created_at", "")),
                                metadata=getattr(mem, "metadata", {}),
                            )
                        )
    except Exception as e:
        logger.warning("Search memories error: %s", e)

    return memories


@router.delete("/{memory_id}")
async def delete_memory(request: Request, memory_id: str = Path(...), agent_id: str = Query(default="default")):
    """删除记忆"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "forget"):
                mem_core.forget(memory_id)
    except Exception as e:
        logger.warning("Delete memory error: %s", e)

    return {"code": 0, "message": f"Memory '{memory_id}' deleted"}


@router.get("/stats/overview", response_model=MemoryStats)
async def get_memory_stats(request: Request, agent_id: str = Query(default="default")):
    """获取记忆统计"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        return MemoryStats()

    stats = MemoryStats()
    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "get_stats"):
                raw_stats = mem_core.get_stats()
                stats.total_count = raw_stats.get("total_count", 0)
                stats.by_type = raw_stats.get("by_type", {})
                stats.avg_importance = raw_stats.get("avg_importance", 0)
    except Exception as e:
        logger.warning("Get memory stats error: %s", e)

    return stats
