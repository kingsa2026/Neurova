"""知识核心端点（CRUD / 搜索 / 分块预览 / 块级编辑 / 详情参数路由）。

2026-09-16 自 knowledge.py 拆出；路径与响应契约不变。
本模块导出两个 router（同一域但注册顺序要求相反）：
  - router         字面前缀路由（/search /preview-chunking /{id}/chunks 等）——无遮蔽风险
  - detail_router  单段参数路由（GET/PUT/DELETE /{knowledge_id}）——会遮蔽其后注册的
                   单段字面 GET（/configs /collections 等），必须由聚合器最后 include
                   （路由顺序契约守护见 test_knowledge_route_order.py）

依赖方向（架构约束，2026-09-16 拆分后冻结；全图见 knowledge.py 头部）：
    本模块 ──▶ knowledge_common（模型 / 守卫 / repository 解析）
    禁止：本模块 import 兄弟叶子（sharing/remote/ingestion），也禁止 import
    聚合器 knowledge.py（成环）；共享需求下沉 knowledge_common。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.logger import get_logger
from neurova.api.endpoints.knowledge_common import (
    KnowledgeCreate,
    KnowledgeItem,
    KnowledgeSearchRequest,
    KnowledgeUpdate,
    entry_or_403,
    entry_or_404,
    get_repository,
    item_response,
)

logger = get_logger(__name__)

# 字面前缀路由（含块级编辑）——无单段参数 GET，无遮蔽风险
router = APIRouter()

# 详情参数路由（GET/PUT/DELETE /{knowledge_id}）：单段参数 GET 会遮蔽其后注册的
# 单段字面 GET（/configs /collections 等）——必须由聚合器保证在全部字面 GET
# 之后 include（knowledge API 层路由顺序契约，守护见 test_knowledge_route_order.py）。
detail_router = APIRouter()

# 切分 live-preview——只读、不入库、不算 embedding
# 与摄取路径共享 split_with_meta 单源。
# 字面路由注册在 /{knowledge_id} 之前（knowledge API 层路由顺序契约）。
_PREVIEW_MAX_CHARS = 64 * 1024


class ChunkUpdate(BaseModel):
    """块编辑请求：content 必填；expected_revision 乐观锁（不传=不校验）。"""

    content: str
    expected_revision: Optional[int] = None


# 注意：根路由 GET ""/POST "" 由聚合器 add_api_route 注册（FastAPI 禁止嵌套
# include 时 prefix 与 path 双空），本模块只导出处理函数。
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
    repo = get_repository()
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
            "items": [item_response(i) for i in window],
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
    repo = get_repository()
    results = repo.search_visible_items(
        current_user,
        body.query,
        scope=scope,
        category=body.category,
        agent_id=agent_id,
        limit=body.limit,
    )
    return [item_response(i) for i in results]


@router.post("/preview-chunking")
async def preview_chunking(
    body: dict,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """分块预览：{content, max_chars?, overlap?} → chunks + 统计。

    与 POST /knowledge（导入）同一分块实现（split_with_meta），供导入前
    "这份文本会被切成什么样"的所见即所得核对；正文只在响应内回显，
    不持久化、不索引。
    """
    from neurova.knowledge.splitter import (
        DEFAULT_MAX_CHARS,
        DEFAULT_OVERLAP,
        split_with_meta,
    )

    content = str((body or {}).get("content") or "")
    if not content.strip():
        return {"code": 1, "message": "content 不能为空", "data": None}
    if len(content) > _PREVIEW_MAX_CHARS:
        return {
            "code": 1,
            "message": "预览文本超过 %d 字符上限（请分段预览）" % _PREVIEW_MAX_CHARS,
            "data": None,
        }
    try:
        max_chars = int((body or {}).get("max_chars") or DEFAULT_MAX_CHARS)
        overlap = int((body or {}).get("overlap") or DEFAULT_OVERLAP)
    except (TypeError, ValueError):
        return {"code": 1, "message": "max_chars/overlap 必须是整数", "data": None}
    # 钳制与摄取端可接受域对齐
    max_chars = max(100, min(4000, max_chars))
    overlap = max(0, min(overlap, max_chars // 2))
    chunks = split_with_meta(content, max_chars=max_chars, overlap=overlap)
    # P1#6：同时预览生产形态——子块进索引、父块作 LLM 上下文
    from neurova.knowledge.splitter import build_entry_chunks

    children, parents = build_entry_chunks(content, parent_max=max_chars, parent_overlap=overlap)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "chunks": chunks,
            "total": len(chunks),
            "children": children,
            "parents": parents,
            "char_total": len(content),
            "max_chars": max_chars,
            "overlap": overlap,
        },
    }


async def create_knowledge(
    request: Request,
    body: KnowledgeCreate,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """添加知识（visibility=public 仅管理员）"""
    visibility = (body.visibility or "private").lower()
    if visibility not in ("private", "public"):
        raise HTTPException(status_code=400, detail="visibility 仅支持 private/public")
    if visibility == "public" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可直接创建公开知识")

    repo = get_repository()
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
    return item_response(item)


@router.get("/{knowledge_id}/revisions")
async def list_knowledge_revisions(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """条目 revision 账本（最新在前；仅可见条目）"""
    repo = get_repository()
    entry_or_404(repo, knowledge_id, current_user)
    return repo.list_revisions(knowledge_id)


@router.get("/{knowledge_id}/chunks")
async def list_knowledge_chunks(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """块清单（含 revision/index_status；仅可见条目）"""
    repo = get_repository()
    entry_or_404(repo, knowledge_id, current_user)
    return repo.list_chunks(knowledge_id) or []


@router.get("/{knowledge_id}/chunks/{index}/revisions")
async def list_chunk_revisions(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    index: int = Path(..., description="块序号"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """单块追加式修订账本（最新在前；仅可见条目）"""
    repo = get_repository()
    entry_or_404(repo, knowledge_id, current_user)
    revs = repo.chunk_revisions(knowledge_id, index)
    if revs is None:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    return revs


@router.put("/{knowledge_id}/chunks/{index}")
async def update_knowledge_chunk(
    request: Request,
    body: ChunkUpdate,
    knowledge_id: str = Path(..., description="知识ID"),
    index: int = Path(..., description="块序号"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """编辑单个块（属主/管理员；乐观锁 + 自动重索引）。

    409=修订冲突（携带 expected_revision 且与当前不符）——客户端须重读后重试；
    成功返回新 revision 与块序号。
    """
    from neurova.knowledge.repository import ChunkRevisionConflict

    repo = get_repository()
    entry_or_404(repo, knowledge_id, current_user)
    try:
        revision = repo.update_chunk(
            knowledge_id, index, body.content, user=current_user,
            expected_revision=body.expected_revision,
        )
    except ChunkRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "success", "data": {"knowledge_id": knowledge_id, "index": index, "revision": revision}}


@detail_router.get("/{knowledge_id}", response_model=KnowledgeItem)
async def get_knowledge_item(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """获取单个知识详情（仅可见条目；不可见 404 不泄露存在性）"""
    repo = get_repository()
    _agent_id, item = entry_or_404(repo, knowledge_id, current_user)
    return item_response(item)


@detail_router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(
    request: Request,
    knowledge_id: str = Path(..., description="知识ID"),
    body: KnowledgeUpdate = KnowledgeUpdate(),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """更新知识（属主/管理员；被共享者只读）"""
    repo = get_repository()
    agent_id, _item = entry_or_403(repo, knowledge_id, current_user)
    if not repo.update_knowledge(agent_id, knowledge_id, body.dict(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="Knowledge '%s' not found" % knowledge_id)

    return item_response(repo.get_item(agent_id, knowledge_id))


@detail_router.delete("/{knowledge_id}")
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
    from neurova.api.endpoints.knowledge_common import get_request_id

    request_id = get_request_id(request)

    repo = get_repository()
    _agent_id, item = entry_or_403(repo, knowledge_id, current_user)
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
