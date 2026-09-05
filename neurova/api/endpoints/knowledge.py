from __future__ import annotations

"""
知识管理接口 - Knowledge Endpoint

功能:
1. 获取知识库 (GET /api/v1/knowledge)
2. 搜索知识 (POST /api/v1/knowledge/search)
3. 添加知识 (POST /api/v1/knowledge)
4. 更新知识 (PUT /api/v1/knowledge/{id})
5. 删除知识 (DELETE /api/v1/knowledge/{id})
6. 导入文件 (POST /api/v1/knowledge/import) R-4: word/excel/ppt/pdf/html/txt/md
7. 导入远程网页 (POST /api/v1/knowledge/import-url) R-4（含 SSRF 防护）

R-4 修复: CRUD 接入 KnowledgeRepository（JSON 持久化），删除 memory_manager
探测与模拟数据兜底；无数据返回空列表。
"""

from neurova.core.logger import get_logger
import time
import urllib.parse
from typing import Dict, Any, Tuple

from neurova.api.auth import get_current_user_or_service
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, UploadFile
from pydantic import BaseModel, Field

logger = get_logger(__name__)

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


def _get_repository(agent_id: str = "default"):
    """获取知识条目仓库（R-4: JSON 持久化）。测试可 monkeypatch 为独立实例。"""
    from neurova.knowledge.repository import get_knowledge_repository

    return get_knowledge_repository()


def _item_response(item: Dict[str, Any]) -> KnowledgeItem:
    """条目 dict → 响应模型（统一投影，避免四处重复构造）。"""
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


def _resolve_usernames(usernames: List[str]) -> Dict[str, str]:
    """用户名 → user_id 映射；任一用户名不存在抛 ValueError（API 层转 400）。"""
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


def _entry_or_404(repo, knowledge_id: str, current_user: Dict[str, Any]):
    """取条目并做可见性校验；不可见一律 404（不泄露存在性）。"""
    found = repo.find_item(knowledge_id)
    if found is None or not repo.can_view(current_user, found[1]):
        raise HTTPException(status_code=404, detail="Knowledge '%s' not found" % knowledge_id)
    return found


def _entry_or_403(repo, knowledge_id: str, current_user: Dict[str, Any]):
    """取条目并做归属校验（owner/admin），不可见 404、无权 403。"""
    agent_id, item = _entry_or_404(repo, knowledge_id, current_user)
    if not repo.can_modify(current_user, item):
        raise HTTPException(status_code=403, detail="仅条目属主或管理员可执行此操作")
    return agent_id, item


def _guard(exc: Exception) -> HTTPException:
    """仓库层领域异常 → HTTP 语义。"""
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def get_knowledge(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None, description="来源 agent 过滤（不再构成安全边界）"),
    category: Optional[str] = Query(default=None, description="分类筛选"),
    scope: str = Query(default="all", description="范围：all/public/private/shared"),
    # 双兼容分页：page/page_size（前端知识库页）与 limit/offset（其余调用方）。
    # 2026-09-06 修复：此前只认 limit/offset，page/page_size 被静默忽略 →
    # 列表恒只有前 20 条，第 21 条起"导入成功但列表没有"。
    page: Optional[int] = Query(default=None, ge=1, description="页码（与 page_size 搭配）"),
    page_size: Optional[int] = Query(default=None, ge=1, le=100, description="每页数量"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制（limit/offset 语义）"),
    offset: int = Query(default=0, ge=0, description="偏移量（limit/offset 语义）"),
):
    """获取当前用户可见的知识条目（public + 我的私有 + 共享给我；admin 全量）。

    page/page_size 优先；未传时回退 limit/offset。响应为
    {items, total, page, page_size} 信封（total 供前端分页器）。
    """
    repo = _get_repository()
    items = repo.visible_items(current_user, scope=scope, category=category, agent_id=agent_id)
    total = len(items)
    if page is not None or page_size is not None:
        size = page_size or limit
        start = ((page or 1) - 1) * size
    else:
        size = limit
        start = offset
    page_out = (start // size + 1) if size else 1
    window = items[start : start + size]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [_item_response(i) for i in window],
            "total": total,
            "page": page_out,
            "page_size": size,
        },
    }


@router.post("/search", response_model=List[KnowledgeItem])
async def search_knowledge(
    request: Request,
    body: KnowledgeSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None, description="来源 agent 过滤"),
    scope: str = Query(default="all", description="范围：all/public/private/shared"),
):
    """在当前用户可见范围内搜索知识（标题+内容包含匹配）"""
    repo = _get_repository()
    results = repo.search_visible_items(
        current_user,
        body.query,
        scope=scope,
        category=body.category,
        agent_id=agent_id,
        limit=body.limit,
    )
    return [_item_response(i) for i in results]


@router.post("", response_model=KnowledgeItem)
async def create_knowledge(
    request: Request,
    body: KnowledgeCreate,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """添加知识（visibility=public 仅管理员）"""
    _get_request_id(request)

    visibility = (body.visibility or "private").lower()
    if visibility not in ("private", "public"):
        raise HTTPException(status_code=400, detail="visibility 仅支持 private/public")
    if visibility == "public" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可直接创建公开知识")

    repo = _get_repository()
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        source=body.source,
        confidence=body.confidence,
        visibility=visibility,
        owner_user_id=str(current_user.get("user_id", "")),
    )
    return _item_response(item)


# ══════════════════════════════════════════════════════════════
# 共享 / 公共库审批（字面路由，必须注册在 /{knowledge_id} 之前防遮蔽）
# ══════════════════════════════════════════════════════════════

@router.get("/public-submissions")
async def list_public_submissions(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """待审批的公共库提交清单（仅管理员）"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看公共库审批队列")
    repo = _get_repository()
    return [_item_response(i) for i in repo.pending_submissions()]


class ConflictResolutionRequest(BaseModel):
    """同值冲突裁决请求（仅管理员）"""

    resolution: str = Field(..., description="keep_both=保留双条目 / supersede_old=新说法接管（旧条目入墓碑）")


@router.get("/conflicts")
async def list_conflicts(
    request: Request,
    status: str = Query(default="pending", description="pending 待审 / resolved 裁决历史"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """同值冲突清单（仅管理员）：新条目与旧条目疑似「同一事实的新说法」"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看冲突队列")
    repo = _get_repository()
    return repo.list_conflicts(status=status)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    request: Request,
    conflict_id: str = Path(..., description="冲突记录ID"),
    body: ConflictResolutionRequest = ...,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """裁决同值冲突（仅管理员）。supersede_old 会把旧条目移入墓碑（可复活）。"""
    _get_request_id(request)
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可裁决冲突")
    repo = _get_repository()
    try:
        ok = repo.resolve_conflict(
            conflict_id, body.resolution, resolved_by=str(current_user.get("user_id", ""))
        )
    except ValueError as e:
        raise _guard(e)
    except LookupError as e:
        raise _guard(e)
    if not ok:
        raise HTTPException(status_code=404, detail="Conflict '%s' not found or already resolved" % conflict_id)
    return {
        "code": 0,
        "message": "Conflict resolved (%s)" % body.resolution,
        "data": {"conflict_id": conflict_id, "resolution": body.resolution},
    }


@router.get("/deleted")
async def list_deleted_knowledge(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """墓碑清单（仅管理员）：软删条目审计视图，Utopia 0022 删除是事件。"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看墓碑清单")
    repo = _get_repository()
    out = []
    for rec in repo.list_deleted():
        item = rec.get("item") or {}
        out.append(
            {
                "knowledge_id": rec.get("knowledge_id"),
                "title": item.get("title", ""),
                "owner_user_id": item.get("owner_user_id", ""),
                "deleted_at": rec.get("deleted_at"),
                "deleted_by": rec.get("deleted_by"),
                "superseded_by": rec.get("superseded_by"),
            }
        )
    return out


@router.post("/{knowledge_id}/restore")
async def restore_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """从墓碑复活条目（属主或管理员）"""
    _get_request_id(request)
    repo = _get_repository()
    rec = next((r for r in repo.list_deleted() if r.get("knowledge_id") == knowledge_id), None)
    if rec is None:
        raise HTTPException(status_code=404, detail="Knowledge '%s' is not deleted" % knowledge_id)
    owner_id = str((rec.get("item") or {}).get("owner_user_id", "") or "")
    if current_user.get("role") != "admin" and str(current_user.get("user_id", "")) != owner_id:
        raise HTTPException(status_code=403, detail="仅条目属主或管理员可恢复")
    if not repo.restore_knowledge(knowledge_id):
        raise HTTPException(status_code=404, detail="Knowledge '%s' is not deleted" % knowledge_id)
    return {
        "code": 0,
        "message": "Knowledge '%s' restored" % knowledge_id,
        "data": {"knowledge_id": knowledge_id, "action": "restored"},
        "request_id": _get_request_id(request),
    }


@router.get("/{knowledge_id}/revisions")
async def list_knowledge_revisions(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """条目 revision 账本（最新在前；仅可见条目）"""
    repo = _get_repository()
    _entry_or_404(repo, knowledge_id, current_user)
    return repo.list_revisions(knowledge_id)


@router.post("/{knowledge_id}/share", response_model=KnowledgeItem)
async def share_knowledge(
    request: Request,
    body: KnowledgeShareRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """把私有条目共享给指定用户（只读；属主/管理员）"""
    repo = _get_repository()
    _entry_or_403(repo, knowledge_id, current_user)
    try:
        mapping = _resolve_usernames(body.usernames)
        item = repo.share_entry(current_user, knowledge_id, list(mapping.values()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (PermissionError, LookupError) as exc:
        raise _guard(exc)
    return _item_response(item)


@router.post("/{knowledge_id}/unshare", response_model=KnowledgeItem)
async def unshare_knowledge(
    request: Request,
    body: KnowledgeShareRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """取消对指定用户的共享（属主/管理员）"""
    repo = _get_repository()
    _entry_or_403(repo, knowledge_id, current_user)
    try:
        mapping = _resolve_usernames(body.usernames)
        item = repo.unshare_entry(current_user, knowledge_id, list(mapping.values()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (PermissionError, LookupError) as exc:
        raise _guard(exc)
    return _item_response(item)


@router.post("/{knowledge_id}/submit-public", response_model=KnowledgeItem)
async def submit_knowledge_to_public(
    request: Request,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """把私有条目提交公共库（进入待审批；属主）并通知管理员审核"""
    repo = _get_repository()
    _entry_or_403(repo, knowledge_id, current_user)
    try:
        item = repo.submit_to_public(current_user, knowledge_id)
    except (PermissionError, LookupError, ValueError) as exc:
        raise _guard(exc)

    # 通知管理员审核（异常只记日志，不阻断提交）
    try:
        from neurova.api.endpoints.notifications import notify_admins

        submission = item.get("submission") or {}
        submitter_id = str(submission.get("submitted_by") or current_user.get("user_id") or "")
        submitter_name = str(current_user.get("username") or submitter_id)
        notify_admins(
            title="知识库提交待审核",
            message=f"用户 {submitter_name} 提交「{item.get('title', '')}」到公共库，等待审核",
            notification_type="kb_review",
            data={
                "knowledge_id": knowledge_id,
                "title": item.get("title", ""),
                "submitter": submitter_id,
                "submitter_name": submitter_name,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("submit-public 通知管理员失败")
    return _item_response(item)


@router.post("/{knowledge_id}/review-public", response_model=KnowledgeItem)
async def review_knowledge_public(
    request: Request,
    body: KnowledgeReviewRequest,
    knowledge_id: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """审批公共库提交（仅管理员）：通过→public，拒绝→维持 private；结果回执提交者"""
    repo = _get_repository()
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可审批公共库提交")
    _entry_or_404(repo, knowledge_id, current_user)
    try:
        item = repo.review_public_submission(
            current_user,
            knowledge_id,
            approve=bool(body.approve),
            reviewed_by=str(current_user.get("user_id", "")),
            note=body.note,
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise _guard(exc)

    # 回执提交者（异常只记日志，不阻断审批）
    try:
        from neurova.api.endpoints.notifications import notify_user

        submission = item.get("submission") or {}
        submitter = str(submission.get("submitted_by") or "")
        if submitter:
            title = item.get("title", "")
            if body.approve:
                msg = f"你提交的「{title}」已通过审核，进入公共库"
            else:
                msg = f"你提交的「{title}」未通过审核" + (f"：{body.note}" if body.note else "")
            notify_user(
                submitter,
                title="知识库审核结果",
                message=msg,
                notification_type="kb_review_result",
                data={"knowledge_id": knowledge_id, "approve": bool(body.approve)},
            )
    except Exception:  # noqa: BLE001
        logger.exception("review-public 通知提交者失败")
    return _item_response(item)


# ══════════════════════════════════════════════════════════════
# R-7(A): 远程知识库配置托管（configs / collections）
# ══════════════════════════════════════════════════════════════

def _get_kb_storage():
    """用户级远程知识库配置存储（configs/collections）。"""
    from neurova.knowledge.storage import get_knowledge_storage

    return get_knowledge_storage()


@router.get("/configs")
async def list_kb_configs(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """列出当前用户全部远程知识库配置（不回显密钥）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    return {
        "code": 0,
        "data": {
            "configs": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "source_type": c.get("source_type"),
                    "is_default": c.get("is_default"),
                    "is_active": c.get("is_active"),
                    "settings": c.get("settings", {}),
                    "has_api_key": bool(c.get("api_key_hash")),
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                }
                for c in storage.get_configs_by_user(user_id)
            ]
        },
    }


@router.post("/configs")
async def create_kb_config(request: Request, body: dict, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """创建远程知识库配置（API Key 加密存储，不回显）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cid = storage.create_config(
        user_id=user_id,
        name=str(body.get("name", "") or ""),
        source_type=str(body.get("source_type", "") or "custom"),
        is_default=bool(body.get("is_default", False)),
        is_active=bool(body.get("is_active", False)),
        api_key=str(body.get("api_key", "") or "") or None,
        settings=body.get("settings"),
    )
    return {"code": 0, "data": {"id": cid}}


@router.get("/configs/{config_id}")
async def get_kb_config(request: Request, config_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """获取单个配置（属主；回显元数据不含密钥）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    return {
        "code": 0,
        "data": {
            "id": cfg.get("id"),
            "name": cfg.get("name"),
            "source_type": cfg.get("source_type"),
            "settings": cfg.get("settings", {}),
            "has_api_key": bool(cfg.get("api_key_hash")),
            "is_default": cfg.get("is_default"),
            "is_active": cfg.get("is_active"),
        },
    }


@router.put("/configs/{config_id}")
async def update_kb_config(request: Request, config_id: str = Path(...), body: dict = None, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """更新配置（api_key 传新值则重加密）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    fields: Dict[str, Any] = {}
    for k in ("name", "source_type", "settings"):
        if body and k in body:
            fields[k] = body[k]
    if body is not None and body.get("api_key") is not None:
        fields["api_key"] = body["api_key"]
    storage.update_config(config_id, **fields)
    return {"code": 0, "message": "updated"}


@router.delete("/configs/{config_id}")
async def delete_kb_config(request: Request, config_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """删除配置（属主）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    cfg = storage.get_config_by_id(config_id)
    if not cfg or cfg.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    storage.delete_config(config_id)
    return {"code": 0, "message": "deleted"}


@router.get("/collections")
async def list_kb_collections(request: Request, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """列出当前用户的集合映射。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    return {"code": 0, "data": {"collections": storage.get_user_collections(user_id)}}


@router.post("/collections")
async def create_kb_collection(request: Request, body: dict, current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """创建集合映射（config_id + collection_name + vector_store）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    mid = storage.create_collection_mapping(
        user_id,
        str(body.get("config_id", "") or ""),
        str(body.get("collection_name", "") or ""),
        vector_store=str(body.get("vector_store", "qdrant") or "qdrant"),
    )
    return {"code": 0, "data": {"id": mid}}


@router.delete("/collections/{mapping_id}")
async def delete_kb_collection(request: Request, mapping_id: str = Path(...), current_user: Dict[str, Any] = Depends(get_current_user_or_service)):
    """删除集合映射（属主）。"""
    user_id = str(current_user.get("user_id", ""))
    storage = _get_kb_storage()
    items = storage.get_user_collections(user_id)
    if not any(i.get("id") == mapping_id for i in items):
        raise HTTPException(status_code=404, detail=f"Collection '{mapping_id}' not found")
    storage.delete_collection_mapping(mapping_id)
    return {"code": 0, "message": "deleted"}


@router.get("/{knowledge_id}", response_model=KnowledgeItem)
async def get_knowledge_item(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """获取单个知识详情（仅可见条目；不可见 404 不泄露存在性）"""
    repo = _get_repository()
    _agent_id, item = _entry_or_404(repo, knowledge_id, current_user)
    return _item_response(item)


@router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    body: KnowledgeUpdate = KnowledgeUpdate(),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """更新知识（属主/管理员；被共享者只读）"""
    _get_request_id(request)

    repo = _get_repository()
    agent_id, _item = _entry_or_403(repo, knowledge_id, current_user)
    if not repo.update_knowledge(agent_id, knowledge_id, body.dict(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="Knowledge '%s' not found" % knowledge_id)

    return _item_response(repo.get_item(agent_id, knowledge_id))


@router.delete("/{knowledge_id}")
async def delete_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    purge: bool = Query(default=False, description="物理删除。管理员删除他人提交的公共条目时默认为下架（保留属主私人数据），purge=true 才整条删除"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """删除知识（属主/管理员）

    语义分流（2026-09-01 修复连坐删除 bug）：
    - 公共库与私人库是同一份物理数据（submit-public 仅改可见性）。
    - 管理员删除「他人提交的公共条目」→ 默认下架：条目保留、回私有、
      submission 置 rejected——公共库消失，属主私人库保住。
    - ?purge=true → 物理删除整条（清除违规内容的显式通道）。
    - 删除自己的条目（属主或管理员自建）→ 物理删除，语义不变。
    """
    request_id = _get_request_id(request)

    repo = _get_repository()
    _agent_id, item = _entry_or_403(repo, knowledge_id, current_user)
    is_owner = str(item.get("owner_user_id") or "") == str(current_user.get("user_id") or "")

    if (
        not purge
        and current_user.get("role") == "admin"
        and not is_owner
        and item.get("visibility") == "public"
    ):
        unpublished = repo.unpublish(
            knowledge_id,
            reviewed_by=str(current_user.get("user_id", "")),
            note="管理员下架",
        )
        if unpublished is not None:
            return {
                "code": 0,
                "message": "Knowledge '%s' unpublished (owner data kept)" % knowledge_id,
                "data": {"knowledge_id": knowledge_id, "action": "unpublished"},
                "request_id": request_id,
            }

    if purge:
        repo.purge_knowledge(_agent_id, knowledge_id)
    else:
        repo.delete_knowledge(
            _agent_id,
            knowledge_id,
            deleted_by=str(current_user.get("user_id", "")),
        )

    return {
        "code": 0,
        "message": "Knowledge '%s' deleted" % knowledge_id,
        "data": {"knowledge_id": knowledge_id, "action": "deleted"},
        "request_id": request_id,
    }


# ══════════════════════════════════════════════════════════════
# R-4: 多格式导入（文件 + 远程网页）
# ══════════════════════════════════════════════════════════════

def _build_item_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """导入响应投影：剔 chunks 正文冗余（块已含于 content），附 chunk_count。"""
    item = dict(item)
    chunks = item.pop("chunks", None) or []
    item["chunk_count"] = len(chunks) or 1
    return item


def _resolve_runtime_agents(request: Optional[Request]) -> Dict[str, Any]:
    """运行时 Agent 注册表解析（生产唯一事实源 + 测试回退）。

    生产链路：app.py 经 set_app_state 注入的 neurova.api.endpoints 模块级
    注册表（home.py _get_app_state 注释已明示：request.app.state 是
    Starlette State 对象，生产从不写入 agents）。回退读 request.app.state
    仅兼容测试自建 app 直接挂载的写法。
    """
    try:
        from neurova.api.endpoints import get_app_state

        agents = (get_app_state() or {}).get("agents")
        if agents:
            return agents
    except Exception:  # noqa: BLE001
        pass
    try:
        return getattr(getattr(getattr(request, "app", None), "state", None), "agents", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _default_llm_call(request: Optional[Request], prefer_agent_id: Optional[str] = None):
    """从运行时 Agent 解析 LLM 调用器（prompt→文本）；不可用返回 None（跳过抽取）。

    根因修复（2026-09-05 知识图谱空图）：agent 从注册表解析（此前读
    request.app.state.agents——生产恒空，抽取恒被跳过）；AgentLLMClient.chat
    是 async，经 mem_core.run_async_safely 同步桥接（BE-CORE-001 同款，
    此前同步调用拿到 coroutine 后 content 恒空）。

    prefer_agent_id：优先用知识所属 Agent 的 llm_client（per-agent 模型配置）；
    其模型不可用（AgentLLMClient 错误契约返回 "[LLM Error]" 文本或抛异常）时
    逐个回退其他活跃 Agent——抽取是后台增强任务，不应因单个 Agent 配置坏而死亡。
    """
    try:
        agents = _resolve_runtime_agents(request)
        candidates: List[Any] = []
        if prefer_agent_id and prefer_agent_id in agents:
            candidates.append(agents[prefer_agent_id])
        for aid, agent in agents.items():
            if prefer_agent_id and aid == prefer_agent_id:
                continue
            candidates.append(agent)
        clients = [c for c in (getattr(a, "llm_client", None) for a in candidates) if c is not None]
        if not clients:
            return None

        def _call(prompt: str):
            from neurova.mem_core import run_async_safely

            last = ""
            for client in clients:
                try:
                    resp = run_async_safely(
                        client.chat([{"role": "user", "content": prompt}])
                    )
                except Exception as exc:  # noqa: BLE001 - 换下一个候选
                    logger.warning("graph_bridge: LLM 调用异常，尝试下一个候选: %s", exc)
                    continue
                content = getattr(resp, "content", "") or ""
                if content.startswith("[LLM Error]"):
                    last = content
                    logger.warning("graph_bridge: 候选 LLM 返回错误，尝试下一个: %s", content[:120])
                    continue
                return content
            return last

        return _call
    except Exception as e:  # noqa: BLE001
        logger.debug("graph_bridge LLM 解析失败: %s", e)
    return None


def _try_extract_to_graph(
    items: List[Dict[str, Any]], request: Request, agent_id: Optional[str] = None
) -> None:
    """导入后触发"知识条目→图谱节点"抽取（批次 3）。失败逐条吞掉，不阻断导入。"""
    from neurova.cognitive_layers.knowledge_graph.manager import (
        get_agent_knowledge_graph_manager,
        get_knowledge_graph_manager,
    )
    from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
    from neurova.knowledge.repository import get_knowledge_repository

    llm_call = _default_llm_call(request, prefer_agent_id=agent_id)
    if llm_call is None:
        logger.info("[知识导入] 未解析到可用 LLM，跳过 %s 条的图谱抽取", len(items))
        return
    repo = get_knowledge_repository()
    # per-agent 隔离：写入所属 agent 的图谱（agent_id 缺失时退全局，仅测试路径）
    if agent_id:
        try:
            graph = get_agent_knowledge_graph_manager(agent_id)
        except ValueError:
            graph = get_knowledge_graph_manager()
    else:
        graph = get_knowledge_graph_manager()
    for entry in items:
        try:
            extract_knowledge_to_graph(entry, repo=repo, llm_call=llm_call, graph_manager=graph)
        except Exception as e:  # noqa: BLE001
            logger.warning("[知识导入] 图谱抽取失败（已跳过）: %s", e)


@router.post("/import")
async def import_knowledge_file(
    file: UploadFile,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """导入知识文件（txt/md/docx/xlsx/pptx/pdf/html/csv）。

    R-4: 复用 attachment_parser 抽取文本，抽取成功则创建知识条目
    （归属当前用户、默认私有）。批次 3：导入后触发图谱抽取。
    """
    filename = file.filename or "imported"
    data = await file.read()
    items, extract_status = _import_file_data(data, filename, agent_id, current_user)
    if not items:
        # 2026-09-06 修复：抽取失败显式化——此前以成功语义静默返回空列表，
        # 前端一律提示"导入成功"，用户无从知晓 .ppt 旧格式/超 2MB/纯图片页
        # 实际未入库（"提示成功但列表没有"的根因）。
        return {
            "code": 1,
            "message": f"extract_failed:{extract_status}",
            "data": {"items": [], "status": extract_status},
        }
    _try_extract_to_graph(items, request, agent_id=agent_id)
    return {"code": 0, "message": "Import completed", "data": {"items": items}}


def _import_file_data(
    data: bytes, filename: str, agent_id: str, user: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], str]:
    from neurova.attachment_parser import extract_attachment_text
    from neurova.knowledge.splitter import split_with_meta

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_type = _guess_type(ext)
    text, status = extract_attachment_text(data, filename, file_type)
    if not text:
        logger.info("[知识导入] %s 未抽取文本 (%s)", filename, status)
        return [], status

    repo = _get_repository()
    title = _title_from_filename(filename)
    # P0-2 分块：摄取即分块（段落→句→硬切降级），检索命中可溯源到块
    item = repo.create_knowledge(
        agent_id=agent_id,
        title=title,
        content=text,
        category="import",
        tags=[],
        source="import:" + filename,
        confidence=0.7,
        visibility="private",
        owner_user_id=str((user or {}).get("user_id", "") or "default"),
        chunks=split_with_meta(text),
        # P0-3 闭环审查修 D：批量导入不进同值冲突队列——同名文件批量导入
        # （课件/周报）会瞬间产生 N-1 条 pending 刷屏待审；导入条目已有
        # source 字段独立溯源，冲突检测留给交互式单条创建路径
        detect_conflict=False,
    )
    return [_build_item_dict(item)], status


def _guess_type(ext: str) -> str:
    if ext in ("txt", "md", "rst", "json", "yaml", "yml", "toml", "log"):
        return "text"
    if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "html", "htm",
               "rtf", "odt", "ods", "odp", "xml"):
        return "document"
    return "file"


def _title_from_filename(filename: str) -> str:
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return base.strip() or "Imported Knowledge"


# ── 远程网页导入（SSRF 防护） ─────────────────────────────────

def _validate_import_url(url: str) -> bool:
    """校验导入 URL 安全（R-4 SSRF 防护）：
    - 仅 http/https
    - 拒绝 localhost/环回/私有/保留地址（解析后 IP 判断）
    Allowlist 语义：不合规 → False。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False

    # 主机名快速拒绝：localhost / 内部域名后缀
    lowered = host.lower()
    if lowered in ("localhost",) or lowered.endswith(".localhost"):
        return False

    import ipaddress

    # 直接 IP 字面量
    try:
        ip = ipaddress.ip_address(lowered)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except ValueError:
        pass

    # 域名：解析后逐个 IP 检查（DNS rebinding 场景下至少列出全部分析结果）
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _fetch_url(url: str) -> bytes:
    """抓取远程网页（测试可 monkeypatch）。校验通过后由 urllib 拉取。"""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Neurova-KB/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(1024 * 1024)  # 最多 1MB


@router.post("/import-url")
async def import_knowledge_url(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
    url: str = Query(..., description="远程网页 URL"),
):
    """导入远程网页（抽取正文存为知识条目，归属当前用户、默认私有）"""
    if not _validate_import_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL: only public http(s) allowed")

    try:
        data = _fetch_url(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail="Fetch failed: %s" % e)

    items = _import_file_data(data, _title_from_url(url), agent_id, current_user)
    _try_extract_to_graph(items, request, agent_id=agent_id)
    return {"code": 0, "message": "URL import completed", "data": {"items": items}}


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/") or "root"
    name = path.rsplit("/", 1)[-1]
    return name[:64] or parsed.netloc or "Web Page"
