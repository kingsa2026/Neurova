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

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import PlainTextResponse
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


class FactAdoptionRequest(BaseModel):
    """事实采纳结果显式写回；不接受“猜测的”默认值。"""

    outcome: Literal["success", "failure", "unevidenced"]


class KnowledgeExpiryRequest(BaseModel):
    """到期条目归档开关；默认 dry-run，不让审计动作顺手改数据。"""

    apply: bool = False


class KnowledgeReindexRequest(BaseModel):
    """索引维护开关；force=true 才做向量全量重算。"""

    force: bool = False


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
        tags=body.tags,
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
        valid_until=body.valid_until,
        lifecycle_status=body.lifecycle_status,
    )
    return item_response(item)


@router.get("/evaluation/baseline")
async def get_evaluation_baseline(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """检索评测基线读数（只读）。未冻结基线时回 unevidenced，不回 0。"""
    import json as _json

    from neurova.knowledge.evaluation import get_retrieval_benchmark

    bench = get_retrieval_benchmark()
    baseline = bench.baseline()
    if baseline is None:
        return {
            "measure_state": "unevidenced",
            "missing_reason": "尚未冻结基线：先跑 RetrievalBenchmark.seedFromRepository + run + freezeBaseline",
            "case_count": bench.caseCount(),
            "readings": None,
        }
    return {
        "measure_state": baseline.get("measure_state"),
        "run_id": baseline.get("run_id"),
        "frozen_at": baseline.get("frozen_at"),
        "case_count": baseline.get("case_count"),
        "top_k": baseline.get("top_k"),
        "context": _json.loads(baseline.get("context_json") or "{}"),
        "readings": {
            "recall_at_k": baseline.get("recall_at_k"),
            "mrr": baseline.get("mrr"),
            "unhit_rate": baseline.get("unhit_rate"),
        },
    }


@router.get("/foundation/usage")
async def get_foundation_usage(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """底座使用与采纳回流度量（只读）。空库回 unevidenced，不回 0% 无视。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store

    return get_knowledge_fact_store().usageMetrics()


@router.get("/audit/redundancy")
async def get_redundancy_audit(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """重复内容审计（只读，管理员）。

    只报重复组与冗余行，不删除、不改条目。删除仍走 tombstone／purge 的显式通道；
    报告命中条目的 title/knowledge_id，足够人工复核，不在响应里回显正文。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="冗余审计是整库只读报告，仅管理员可查看")

    from neurova.knowledge.foundation.redundancy import RedundancyAudit

    report = RedundancyAudit.auditRepository(get_repository())
    return {"code": 0, "message": "ok", "data": report}


@router.post("/facts/{fact_id}/adoption")
async def record_fact_adoption(
    request: Request,
    fact_id: str = Path(..., description="事实 ID"),
    body: FactAdoptionRequest = ...,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """显式写回某条事实的采纳结果（管理员／服务身份）。

    只接受 fact_id + outcome，不从聊天 like/dislike 或引用关系猜测归因；
    自动归因需要产品语义拍板（见审计报告 P0-1 三态票）。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="采纳结果写回是治理动作，仅管理员可执行")

    from neurova.knowledge.foundation import get_knowledge_fact_store

    try:
        get_knowledge_fact_store().recordAdoption(fact_id, body.outcome)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "code": 0,
        "message": "ok",
        "data": {"fact_id": fact_id, "outcome": body.outcome},
    }


@router.get("/audit/retrieval-metrics")
async def get_retrieval_metrics_snapshot(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """检索在线快照（管理员）：只报已接的读数，未接指标不伪造。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="检索指标是整库读数，仅管理员可查看")

    from neurova.knowledge.retrieval_metrics import get_retrieval_metrics

    repo = get_repository()
    data: Dict[str, Any] = {
        "retrieval": get_retrieval_metrics().snapshot(),
        "lifecycle": repo.lifecycleReport()["counts"],
        "pending_conflicts": None,
        "token_usage": None,
    }
    try:
        from neurova.core.usage_accounting import get_usage_accounting

        data["token_usage"] = get_usage_accounting().snapshot()
    except Exception as exc:  # noqa: BLE001 — 指标读取失败不阻断端点，但必须点名
        data["token_usage_missing_reason"] = str(exc)
    try:
        from neurova.knowledge.foundation import get_knowledge_fact_store

        store = get_knowledge_fact_store()
        data["pending_conflicts"] = (
            len(repo.list_conflicts("pending")) + len(store.conflicts("pending"))
        )
        data["knowledge_token_usage"] = store.tokenUsageMetrics()
    except Exception as exc:  # noqa: BLE001 — 指标读取失败不阻断端点，但必须点名缺哪项
        data["missing_reason"] = "pending_conflicts unavailable: %s" % exc
    return {"code": 0, "message": "ok", "data": data}


@router.post("/audit/reindex")
async def run_knowledge_reindex(
    request: Request,
    body: KnowledgeReindexRequest = KnowledgeReindexRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """索引维护（管理员）：默认增量自愈；force=true 做向量全量重算。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="索引维护是整库动作，仅管理员可执行")

    import asyncio

    from neurova.knowledge.maintenance import maintainKnowledgeIndexes

    result = await asyncio.to_thread(maintainKnowledgeIndexes, body.force)
    return {"code": 0, "message": "ok", "data": result}


@router.get("/audit/index-health")
async def get_knowledge_index_health(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """知识向量索引健康度（管理员只读）：文件/向量/引擎分布/坏分片。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="索引健康度是整库读数，仅管理员可查看")
    from neurova.knowledge.vector_index import get_knowledge_vector_index

    data = {
        "vector": get_knowledge_vector_index().health(),
        "lifecycle": get_repository().lifecycleReport()["counts"],
    }
    try:
        data["fts"] = get_repository().ftsHealth()
    except Exception as exc:  # noqa: BLE001 — FTS 不可用不顶住健康读数，但要点名
        data["fts_missing_reason"] = str(exc)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/audit/expiry")
async def run_knowledge_expiry(
    request: Request,
    body: KnowledgeExpiryRequest = KnowledgeExpiryRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """到期条目自动归档（管理员）。默认 dry-run；apply=True 才把 active→archived。

    不删除正文；归档后仍可 PUT 恢复 active。启动路径也调用同一方法（apply=True）。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="到期归档是整库动作，仅管理员可执行")
    return {"code": 0, "message": "ok",
            "data": get_repository().expireDueEntries(apply=body.apply)}


@router.get("/audit/lifecycle")
async def get_lifecycle_audit(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """生命周期只读报告（管理员）：active/archived/expired 计数与不可检索清单。

    只读；变更走条目的 PUT（lifecycle_status/valid_until），物理删除仍走 purge。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="生命周期审计是整库只读报告，仅管理员可查看")
    return {"code": 0, "message": "ok", "data": get_repository().lifecycleReport()}


@router.get("/audit/entry-feedback")
async def get_entry_feedback_audit(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """文档条目采纳/注入覆盖率；三态缺失按 never_written 报，不伪造 0。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="条目反馈审计是整库读数，仅管理员可查看")
    return {"code": 0, "message": "ok", "data": get_repository().entryFeedbackMetrics()}


@router.get("/foundation/integrity")
async def get_foundation_integrity(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """溯源链完整性巡检（只读，工单 023 / G02）。

    只报实况不动数据：改写任何一条断言都会在这里露出来，并指到具体活动与第几跳；
    `unlinked` 是"上链之前写的行"这一维没依据，不等于被篡改。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.foundation.digest_chain import ActivityDigestChain

    return ActivityDigestChain(get_knowledge_fact_store()).verify()


@router.post("/foundation/expiry")
async def run_foundation_expiry(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """把已到期的事实推进为 `expired`，并撤销以它们为前提的推导结论（批次 K1 / 断点 N1）。

    为什么要有这个端点而不是让 `expireDueFacts()` 继续等着：底座的生命周期注释写着
    "状态是唯一权威……到期靠显式调用推进，不起后台线程"，而那句"显式调用"在全仓
    没有落点——于是它下面那段"前提到期⇒撤销其推导"的级联运行期不可达。读侧另有
    `searchableFacts` 的时钟兜底，直接检索看不出问题，漏的是派生面：由带窗口前提推出的
    结论行不带窗口（推导器不填 `validUntil`），永远进不了到期候选。

    与 `/foundation/integrity` 同族，但那条只读、这一条**会写**：整库状态迁移不是租户级
    动作，所以只有管理员能按。这里给 403 而不是 404 同构——不存在"别人的资源"，
    只存在"普通人不该有这个开关"，装作没有反而让人以为试错姿势不对。

    幂等：只推进 `status='active'` 且已过 `valid_until` 的行，第二次跑回 0；
    重复跑不重复写活动账，这是它敢被启动路径调一次的前提。
    """
    from neurova.api.endpoints.knowledge_common import get_request_id

    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="到期收敛是整库动作，仅管理员可触发")

    from neurova.knowledge.foundation import get_knowledge_fact_store

    expired = int(get_knowledge_fact_store().expireDueFacts())
    return {
        "code": 0,
        "message": "Expired facts advanced: %d" % expired,
        "data": {"expired": expired},
        "request_id": get_request_id(request),
    }


@router.get("/facts/{fact_id}/lineage")
async def get_fact_lineage(
    request: Request,
    fact_id: str = Path(..., description="事实底座 fact_id"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """一条事实的逐跳血缘（只读，工单 024 / G01）。

    `missing` 是显式的缺维清单：没有断言、断言没挂活动、活动没记介质各占一条。
    回一条空链会被读成"溯过源、没来源"，那是假的确定性。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.foundation.lineage_view import FactLineageView

    view = FactLineageView(get_knowledge_fact_store()).trace(fact_id)
    if view is None:
        raise HTTPException(status_code=404, detail="事实不存在: %s" % fact_id)
    return view


@router.get("/facts/{fact_id}/turtle", response_class=PlainTextResponse)
async def get_fact_turtle(
    request: Request,
    fact_id: str = Path(..., description="事实底座 fact_id"),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """血缘的 RDF/Turtle 导出（自拼文本，零新增依赖）。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.turtle import serializeFact

    try:
        return PlainTextResponse(
            serializeFact(get_knowledge_fact_store(), fact_id), media_type="text/turtle")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
    - ?purge=true → 条目擦除喉：逐面清除该条目留在各存储的正文副本（权威事实行、
      断言正文、活动信封、向量分片、投影节点、条目行与墓碑），并逐面回执。
      断言**行**留在审计链上（`seq`/`digest`/`statement_hash` 不动，正文置空并打
      `erased_at` 标记）——合规删除不以毁掉 `/foundation/integrity` 为代价。
      任一面失败即回 500 并点名是哪一面，不再无条件报"已删除"。
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
        receipt = repo.purge_knowledge(
            _agent_id, knowledge_id,
            reason="purge by %s" % str(current_user.get("user_id", "")))
        failed = {name: face for name, face in receipt["faces"].items()
                  if face.get("state") == "failed"}
        if failed:
            # 半删不叫删：把失败面点名交回调用方，别让它读成"已删除"。
            raise HTTPException(
                status_code=500,
                detail={"knowledge_id": knowledge_id, "faces_failed": failed,
                        "message": "条目擦除未完成，正文仍在下列存储面可读"})
        return {
            "code": 0,
            "message": "Knowledge '%s' erased" % knowledge_id,
            "data": {"knowledge_id": knowledge_id, "action": "purged",
                     "erasure": receipt},
            "request_id": request_id,
        }

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
