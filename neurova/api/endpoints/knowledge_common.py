"""knowledge 域共享依赖（2026-09-16 knowledge.py 模块化拆分产物）。

子路由模块共用：Pydantic 模型、repository/storage 解析、可见性/归属校验、
领域异常 → HTTP 语义守卫。原私有名经 knowledge 聚合器 re-export 保持兼容
（knowledge_graph_api / ingest_worker 等外部消费方不动）。

依赖方向（架构约束，2026-09-16 拆分后冻结；全图见 knowledge.py 头部）：
    本模块是依赖图最底层节点，只允许对下层域做函数内懒导入：
        本模块 ──▶ neurova.knowledge.repository / storage
    禁止：本模块 import 任何兄弟叶子（core/sharing/remote/ingestion），
    也禁止 import 聚合器 knowledge.py。
    兄弟间的共享需求一律下沉到本模块，不得在叶子之间直接互调。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

logger = None  # 本模块不自持 logger（避免与聚合器的 logger 语义混淆）


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
    visibility: str = "private"
    owner_user_id: str = ""
    shared_with: List[str] = []
    submission: Optional[Dict[str, Any]] = None
    graph_node_ids: List[str] = []
    # P0-2 分块契约：块数 + 检索命中的块级溯源（[{chunk_index, content, score}]）
    chunk_count: int = 1
    chunk_hits: List[Dict[str, Any]] = []


class KnowledgeCreate(BaseModel):
    """创建知识请求"""

    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    source: str = Field(default="", description="来源")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度")
    visibility: str = Field(default="private", description="可见性：private（默认）/ public（仅管理员）")


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


class KnowledgeShareRequest(BaseModel):
    """共享请求（按用户名）"""

    usernames: List[str] = Field(..., description="目标用户名列表")


class KnowledgeReviewRequest(BaseModel):
    """公共库审批请求（仅管理员）"""

    approve: bool = Field(..., description="true=通过（转公开），false=拒绝（维持私有）")
    note: str = Field(default="", description="审批备注")


def get_request_id(request: Request) -> str:
    """获取请求ID（原 knowledge._get_request_id，经聚合器 re-export）"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def get_memory_manager(agent_id: str = "default"):
    """获取记忆管理器（原 knowledge._get_memory_manager）"""
    from neurova.api.endpoints.knowledge_common import get_agent

    agent = get_agent(agent_id)
    if not agent:
        return None
    return getattr(agent, "memory_manager", None)


def get_agent(agent_id: str = "default"):
    """获取 Agent 实例（原 knowledge._get_agent）"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def get_repository(agent_id: str = "default"):
    """获取知识条目仓库（R-4: JSON 持久化）。测试可 monkeypatch 为独立实例。
    （原 knowledge._get_repository）"""
    from neurova.knowledge.repository import get_knowledge_repository

    return get_knowledge_repository()


def item_response(item: Dict[str, Any]) -> KnowledgeItem:
    """条目 dict → 响应模型（统一投影，避免四处重复构造）。（原 _item_response）"""
    return KnowledgeItem(
        knowledge_id=item["knowledge_id"],
        title=item["title"],
        content=item["content"],
        category=item.get("category", "general"),
        tags=item.get("tags") or [],
        source=item.get("source", ""),
        confidence=item.get("confidence", 0.5),
        created_at=item.get("created_at", 0),
        updated_at=item.get("updated_at", 0),
        visibility=item.get("visibility", "private"),
        owner_user_id=item.get("owner_user_id", ""),
        shared_with=item.get("shared_with") or [],
        submission=item.get("submission"),
        graph_node_ids=item.get("graph_node_ids") or [],
        chunk_count=len(item.get("chunks") or []) or 1,
        chunk_hits=item.get("chunk_hits") or [],
    )


def resolve_usernames(usernames: List[str]) -> Dict[str, str]:
    """用户名 → user_id 映射；任一用户名不存在抛 ValueError（API 层转 400）。（原 _resolve_usernames）"""
    from neurova.auth.user_model import UserModel

    mapping: Dict[str, str] = {}
    for name in usernames:
        name = (name or "").strip()
        if not name:
            continue
        u = UserModel().get_user_by_username(name)
        if u is None:
            raise ValueError("unknown user: %s" % name)
        mapping[name] = str(getattr(u, "id", "") or "")
    return mapping


def entry_or_404(repo, knowledge_id: str, current_user: Dict[str, Any]):
    """取条目并做可见性校验；不可见一律 404（不泄露存在性）。（原 _entry_or_404）"""
    found = repo.find_item(knowledge_id)
    if found is None or not repo.can_view(current_user, found[1]):
        raise HTTPException(status_code=404, detail="Knowledge '%s' not found" % knowledge_id)
    return found


def entry_or_403(repo, knowledge_id: str, current_user: Dict[str, Any]):
    """取条目并做归属校验（owner/admin），不可见 404、无权 403。（原 _entry_or_403）"""
    agent_id, item = entry_or_404(repo, knowledge_id, current_user)
    if not repo.can_modify(current_user, item):
        raise HTTPException(status_code=403, detail="仅条目属主或管理员可执行此操作")
    return agent_id, item


def guard(exc: Exception) -> HTTPException:
    """仓库层领域异常 → HTTP 语义。（原 _guard）"""
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))
