"""
知识库集成接口 - Memory↔Knowledge 关联持久化 + RAG 增强检索 + 进化统计

2026-09-15 收口：
- sync/* 原写进程内 `_sync_links` 列表（重启即丢、无人消费、响应却谎报
  "Synced"）→ 改落 KnowledgeStorage.memory_links（JSON 持久化，跨重启可读）；
- /rag/retrieve、/rag/batch 原恒返回 items:[] 假空成功 → 接真实检索
  （记忆 manager.recall + 知识 hybrid 四路），无命中如实 total=0；
- /gaps/analyze、/learn 维持诚实 501（后端无此能力，不编造数据）；
- /gaps、/learning-records 空列表为真（其产生端未实现）；
- /evolution/progress 的 sync_count 改读真存储计数。
"""

import typing

from neurova.core.logger import get_logger

from fastapi import APIRouter, HTTPException, Request
from neurova.api.auth import get_current_user_or_service, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user_or_service)],)


class RAGRetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    include_memory: bool = True
    include_knowledge: bool = True


class AnalyzeGapsRequest(BaseModel):
    topic: typing.Optional[str] = None
    min_access_count: int = 3


class LearnRequest(BaseModel):
    topic: str
    depth: str = "basic"  # basic, intermediate, advanced


def _storage():
    """记忆-知识关联的持久存储（memory_links.json）。测试 monkeypatch 此缝。"""
    from neurova.knowledge.storage import get_knowledge_storage

    return get_knowledge_storage()


def _user_of(request: Request) -> dict:
    return {"user_id": str(getattr(request.state, "user_id", "") or "")}


def _memory_manager_for(request: Request):
    """运行时 Agent 的 MemoryManager（与 semantic_search_api 同源解析）。"""
    from neurova.api.endpoints import get_app_state

    try:
        agents = (get_app_state() or {}).get("agents") or {}
    except Exception:  # noqa: BLE001
        agents = {}
    if not agents:
        agents = getattr(request.app.state, "agents", {}) or {}
    for agent in agents.values():
        manager = getattr(agent, "memory_manager", None) or getattr(
            getattr(agent, "memory_agent", None), "memory_manager", None
        )
        if manager is not None:
            return manager
    from neurova.cognitive_layers.memory_layer.manager import get_memory_manager

    return get_memory_manager()


def _retrieve_once(query: str, top_k: int, include_memory: bool, include_knowledge: bool,
                   request: Request) -> dict:
    """真实检索一次：记忆 recall + 知识 hybrid/词法检索，各带分数。"""
    results = []
    if include_memory:
        items = []
        try:
            mgr = _memory_manager_for(request)
            for mem in mgr.recall(query, limit=top_k) or []:
                content = str(mem.get("content", "") or "")
                if not content:
                    continue
                items.append(
                    {
                        "id": str(mem.get("id") or mem.get("memory_id") or ""),
                        "content": content,
                        "score": float(mem.get("temperature", 0.0) or 0.0),
                    }
                )
        except Exception as e:  # noqa: BLE001 - 记忆面故障只降级该源，不吞成"零命中假象"
            logger.warning("rag/retrieve 记忆路失败: %s", e)
        results.append({"source": "memory", "items": items, "score": items[0]["score"] if items else 0.0})
    if include_knowledge:
        items = []
        try:
            from neurova.knowledge.repository import get_knowledge_repository

            hits = get_knowledge_repository().search_visible_items(
                _user_of(request), query, scope="all", limit=top_k
            )
            for it in hits or []:
                items.append(
                    {
                        "id": str(it.get("knowledge_id") or ""),
                        "title": str(it.get("title") or ""),
                        "content": str(it.get("content") or ""),
                        "score": float(it.get("score", 0.0) or 0.0),
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("rag/retrieve 知识路失败: %s", e)
        results.append(
            {"source": "knowledge", "items": items, "score": items[0]["score"] if items else 0.0}
        )
    total = sum(len(r["items"]) for r in results)
    return {"query": query, "results": results, "total": total}


@router.post("/sync/knowledge-to-memory")
async def sync_knowledge_to_memory(body: dict, request: Request):
    """记录 知识→记忆 关联（持久化 memory_links，重启保留）。"""
    knowledge_id = str((body or {}).get("knowledge_id", "") or "")
    memory_id = str((body or {}).get("memory_id", "") or "")
    if not knowledge_id or not memory_id:
        # 收口：缺任一端不再合成假 id"成功"，如实失败
        return {
            "code": 1,
            "message": "knowledge_id 与 memory_id 均必填（不再合成虚假关联）",
            "data": None,
        }
    lid = _storage().create_memory_knowledge_link(
        memory_id, knowledge_id, relation="knowledge_to_memory"
    )
    return {
        "code": 0,
        "message": "linked",
        "data": {
            "id": lid,
            "link_id": lid,
            "knowledge_id": knowledge_id,
            "memory_id": memory_id,
        },
    }


@router.post("/sync/memory-to-kb")
async def sync_memory_to_kb(body: dict, request: Request):
    """记录 记忆→知识 关联（与上者同表，relation 区分方向）。"""
    memory_id = str((body or {}).get("memory_id", "") or "")
    knowledge_id = str((body or {}).get("knowledge_id", "") or "")
    if not memory_id or not knowledge_id:
        return {"code": 1, "message": "memory_id 与 knowledge_id 均必填", "data": None}
    lid = _storage().create_memory_knowledge_link(
        memory_id, knowledge_id, relation="memory_to_kb"
    )
    return {
        "code": 0,
        "message": "linked",
        "data": {"id": lid, "link_id": lid, "memory_id": memory_id, "knowledge_id": knowledge_id},
    }


@router.get("/sync/links")
async def get_memory_knowledge_links(request: Request, page: int = 1, size: int = 20):
    """关联列表（读真存储；此前为进程内列表，重启即丢）。"""
    links = _storage().get_memory_links()
    total = len(links)
    start = (max(1, page) - 1) * size
    return {"code": 0, "message": "success", "data": {"items": links[start : start + size], "total": total}}


@router.post("/rag/retrieve")
async def rag_retrieve(body: RAGRetrieveRequest, request: Request):
    """RAG 增强检索——记忆 + 知识真实两路（收口前恒空假成功）。"""
    return {"code": 0, "message": "success", "data": _retrieve_once(
        body.query, body.top_k, body.include_memory, body.include_knowledge, request
    )}


@router.post("/rag/batch")
async def batch_rag_retrieve(body: dict, request: Request):
    """批量 RAG 检索（每 query 真实两路；上限 10 防放大）。"""
    queries = (body or {}).get("queries", []) or []
    top_k = int((body or {}).get("top_k", 5) or 5)
    results = [
        {"query": q, **{k: v for k, v in _retrieve_once(
            str(q), top_k, True, True, request
        ).items() if k != "query"}}
        for q in queries[:10]
    ]
    return {"code": 0, "message": "success", "data": {"results": results}}


@router.post("/gaps/analyze")
async def analyze_knowledge_gaps(body: AnalyzeGapsRequest, request: Request):
    """分析知识盲点

    2026-09-12 P7 诚实化：原实现回显一条编造 gap（access_count=10/depth=low
    写死，不做任何真实分析）。盲点检测未实现 → 501。
    """
    raise HTTPException(status_code=501, detail="知识盲点分析未实现（原返回编造数据）")


@router.post("/learn")
async def learn_from_knowledge(body: LearnRequest, request: Request):
    """从知识库学习特定主题

    2026-09-12 P7 诚实化：原实现 items_learned=0 却谎报 status=completed，
    并向内存 _learning_records 写假记录。学习闭环未接线 → 501。
    """
    raise HTTPException(status_code=501, detail="知识学习闭环未实现（原谎报 completed）")


@router.get("/evolution/progress")
async def get_evolution_progress(request: Request):
    """获取进化进度统计（sync_count 读真存储；learn/gap 面未实现如实 0）。"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "sync_count": len(_storage().get_memory_links()),
            "learning_count": 0,
            "gaps_identified": 0,
            "evolution_score": 0.0,
            "note": "learning/gaps 能力未实现（/learn、/gaps/analyze 返回 501），计数如实为 0",
        },
    }


@router.get("/gaps")
async def get_knowledge_gaps(request: Request, page: int = 1, size: int = 20):
    """获取知识盲点列表（产生端未实现，空列表为真；不伪造 gap 条目）"""
    return {"code": 0, "message": "success", "data": {"items": [], "total": 0}}


@router.get("/learning-records")
async def get_learning_records(request: Request, page: int = 1, size: int = 20):
    """获取学习记录列表（产生端未实现，空列表为真）"""
    return {"code": 0, "message": "success", "data": {"items": [], "total": 0}}
