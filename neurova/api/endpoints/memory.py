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

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
    from neurova.api.endpoints import get_agent_instance
    return get_agent_instance(agent_id)


@router.get("", response_model=List[MemoryItem])
async def list_memories(
    request: Request,
    agent_id: str = Query(default="default"),
    memory_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """查询记忆列表"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        return []

    memories = []
    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "search_memories"):
                results = mem_core.search_memories(
                    query="",
                    memory_type=memory_type,
                    limit=limit,
                    offset=offset,
                )
                for mem in results:
                    memories.append(MemoryItem(
                        memory_id=getattr(mem, "id", str(uuid.uuid4())),
                        content=getattr(mem, "content", ""),
                        memory_type=getattr(mem, "memory_type", "conversation"),
                        importance=getattr(mem, "importance", 0.5),
                        tags=getattr(mem, "tags", []),
                        created_at=str(getattr(mem, "created_at", "")),
                        metadata=getattr(mem, "metadata", {}),
                    ))
    except Exception as e:
        logger.warning(f"List memories error: {e}")

    return memories


@router.get("/{memory_id}", response_model=MemoryItem)
async def get_memory(request: Request, memory_id: str = Path(...), agent_id: str = Query(default="default")):
    """获取记忆详情"""
    request_id = _get_request_id(request)

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
        logger.warning(f"Get memory error: {e}")

    raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")


@router.post("", response_model=MemoryItem)
async def create_memory(request: Request, body: CreateMemoryRequest, agent_id: str = Query(default="default")):
    """创建记忆"""
    request_id = _get_request_id(request)

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
        logger.warning(f"Create memory error: {e}")

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
    request_id = _get_request_id(request)

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
                        memories.append(MemoryItem(
                            memory_id=getattr(mem, "id", str(uuid.uuid4())),
                            content=getattr(mem, "content", ""),
                            memory_type=getattr(mem, "memory_type", "conversation"),
                            importance=importance,
                            tags=getattr(mem, "tags", []),
                            created_at=str(getattr(mem, "created_at", "")),
                            metadata=getattr(mem, "metadata", {}),
                        ))
    except Exception as e:
        logger.warning(f"Search memories error: {e}")

    return memories


@router.delete("/{memory_id}")
async def delete_memory(request: Request, memory_id: str = Path(...), agent_id: str = Query(default="default")):
    """删除记忆"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        if hasattr(agent, "memory_agent") and agent.memory_agent:
            mem_core = agent.memory_agent
            if hasattr(mem_core, "forget"):
                mem_core.forget(memory_id)
    except Exception as e:
        logger.warning(f"Delete memory error: {e}")

    return {"code": 0, "message": f"Memory '{memory_id}' deleted"}


@router.get("/stats/overview", response_model=MemoryStats)
async def get_memory_stats(request: Request, agent_id: str = Query(default="default")):
    """获取记忆统计"""
    request_id = _get_request_id(request)

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
        logger.warning(f"Get memory stats error: {e}")

    return stats
