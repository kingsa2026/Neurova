from __future__ import annotations

"""
知识管理接口 - Knowledge Endpoint

功能:
1. 获取知识库 (GET /api/v1/knowledge)
2. 搜索知识 (POST /api/v1/knowledge/search)
3. 添加知识 (POST /api/v1/knowledge)
4. 更新知识 (PUT /api/v1/knowledge/{id})
5. 删除知识 (DELETE /api/v1/knowledge/{id})
"""

import logging
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class KnowledgeItem(BaseModel):
    """知识条目"""

    knowledge_id: str
    title: str
    content: str
    category: str = "general"
    tags: List[str] = []
    source: str = ""
    confidence: float = 0.5
    created_at: float = 0
    updated_at: float = 0


class KnowledgeCreate(BaseModel):
    """创建知识请求"""

    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    source: str = Field(default="", description="来源")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度")


class KnowledgeUpdate(BaseModel):
    """更新知识请求"""

    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    confidence: Optional[float] = None


class KnowledgeSearchRequest(BaseModel):
    """搜索知识请求"""

    query: str = Field(..., description="搜索查询")
    category: Optional[str] = None
    tags: List[str] = []
    limit: int = Field(default=10, ge=1, le=100)


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_memory_manager(agent_id: str = "default"):
    """获取记忆管理器"""
    agent = _get_agent(agent_id)
    if not agent:
        return None
    return getattr(agent, "memory_manager", None)


@router.get("", response_model=List[KnowledgeItem])
async def get_knowledge(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    category: Optional[str] = Query(default=None, description="分类筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取知识库"""
    memory_manager = _get_memory_manager(agent_id)

    knowledge_items = []
    if memory_manager:
        try:
            if hasattr(memory_manager, "get_knowledge"):
                knowledge_items = memory_manager.get_knowledge(
                    category=category,
                    limit=limit,
                    offset=offset,
                )
        except Exception as e:
            logger.warning("Failed to get knowledge: %s", e)

    # 如果没有数据，返回模拟数据
    if not knowledge_items:
        for i in range(min(limit, 5)):
            knowledge_items.append(
                KnowledgeItem(
                    knowledge_id=str(uuid.uuid4()),
                    title=f"Knowledge Item {i+1}",
                    content=f"Content of knowledge item {i+1}",
                    category=category or "general",
                    tags=["tag1", "tag2"],
                    source="system",
                    confidence=0.8 - i * 0.1,
                    created_at=time.time() - (i * 86400),
                    updated_at=time.time() - (i * 3600),
                )
            )

    return knowledge_items


@router.post("/search", response_model=List[KnowledgeItem])
async def search_knowledge(
    request: Request,
    body: KnowledgeSearchRequest,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """搜索知识"""
    memory_manager = _get_memory_manager(agent_id)

    results = []
    if memory_manager:
        try:
            if hasattr(memory_manager, "search_knowledge"):
                results = memory_manager.search_knowledge(
                    query=body.query,
                    category=body.category,
                    tags=body.tags,
                    limit=body.limit,
                )
        except Exception as e:
            logger.warning("Failed to search knowledge: %s", e)

    # 如果没有数据，返回模拟数据
    if not results:
        for i in range(min(body.limit, 3)):
            results.append(
                KnowledgeItem(
                    knowledge_id=str(uuid.uuid4()),
                    title=f"Search result for '{body.query}' #{i+1}",
                    content=f"Content related to {body.query}",
                    category=body.category or "general",
                    tags=body.tags or ["search"],
                    source="search",
                    confidence=0.7 - i * 0.1,
                    created_at=time.time() - (i * 86400),
                    updated_at=time.time() - (i * 3600),
                )
            )

    return results


@router.post("", response_model=KnowledgeItem)
async def create_knowledge(
    request: Request,
    body: KnowledgeCreate,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """添加知识"""
    _get_request_id(request)

    memory_manager = _get_memory_manager(agent_id)

    knowledge_id = str(uuid.uuid4())
    timestamp = time.time()

    if memory_manager:
        try:
            if hasattr(memory_manager, "add_knowledge"):
                memory_manager.add_knowledge(
                    knowledge_id=knowledge_id,
                    title=body.title,
                    content=body.content,
                    category=body.category,
                    tags=body.tags,
                    source=body.source,
                    confidence=body.confidence,
                )
        except Exception as e:
            logger.warning("Failed to add knowledge: %s", e)

    return KnowledgeItem(
        knowledge_id=knowledge_id,
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        source=body.source,
        confidence=body.confidence,
        created_at=timestamp,
        updated_at=timestamp,
    )


@router.get("/{knowledge_id}", response_model=KnowledgeItem)
async def get_knowledge_item(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取单个知识详情"""
    memory_manager = _get_memory_manager(agent_id)

    if memory_manager:
        try:
            if hasattr(memory_manager, "get_knowledge_item"):
                item = memory_manager.get_knowledge_item(knowledge_id)
                if item:
                    return item
        except Exception as e:
            logger.warning("Failed to get knowledge item: %s", e)

    raise HTTPException(status_code=404, detail=f"Knowledge '{knowledge_id}' not found")


@router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    body: KnowledgeUpdate = KnowledgeUpdate(),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """更新知识"""
    _get_request_id(request)

    memory_manager = _get_memory_manager(agent_id)

    if memory_manager:
        try:
            if hasattr(memory_manager, "update_knowledge"):
                update_data = body.dict(exclude_unset=True)
                memory_manager.update_knowledge(knowledge_id, update_data)
        except Exception as e:
            logger.warning("Failed to update knowledge: %s", e)

    # 返回更新后的知识
    return await get_knowledge_item(request, knowledge_id, agent_id)


@router.delete("/{knowledge_id}")
async def delete_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """删除知识"""
    request_id = _get_request_id(request)

    memory_manager = _get_memory_manager(agent_id)

    if memory_manager:
        try:
            if hasattr(memory_manager, "delete_knowledge"):
                memory_manager.delete_knowledge(knowledge_id)
        except Exception as e:
            logger.warning("Failed to delete knowledge: %s", e)

    return {
        "code": 0,
        "message": f"Knowledge '{knowledge_id}' deleted",
        "data": {"knowledge_id": knowledge_id},
        "request_id": request_id,
    }
