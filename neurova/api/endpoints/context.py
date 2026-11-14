from __future__ import annotations

"""
上下文系统接口 - Context Endpoint

提供以下API:
1. 构建上下文 (POST /api/v1/context/build)
2. 获取上下文统计 (GET /api/v1/context/stats)
3. 获取上下文预览 (GET /api/v1/context/{context_id}/preview)
4. 注入反思日志 (GET /api/v1/context/inject/reflection)
5. 注入记忆 (GET /api/v1/context/inject/memories)
6. 注入高温记忆 (GET /api/v1/context/inject/hot)
7. 压缩上下文 (POST /api/v1/context/{context_id}/compress)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.context_pool import ContextInput, ContextSource

logger = get_logger(__name__)

router = APIRouter()


class BuildContextRequest(BaseModel):
    """构建上下文请求"""

    agent_id: str = Field(default="default", description="Agent ID")
    user_input: str = Field(default="", description="用户输入")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    max_tokens: int = Field(default=16000, description="最大 token 数")
    include_reflection: bool = Field(default=True, description="包含反思日志")
    include_memories: bool = Field(default=True, description="包含记忆")
    include_constitution: bool = Field(default=True, description="包含宪法规则")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class BuildContextResponse(BaseModel):
    """构建上下文响应"""

    context_id: str
    content: str
    token_count: int
    sources: List[str]
    build_time: float


class ContextStats(BaseModel):
    """上下文池统计（P2-7 收口：字段全部来自池的真实读数，不再有恒零假位）"""

    pools: int = 0
    total_contexts: int = 0
    average_resident: float = 0
    archived_total: int = 0
    ledger_rows: int = 0
    indexed_entries: int = 0
    # B13（对照改进项）：取水质量读数（各池抽屉累计计数求和）
    drawer: Optional[Dict[str, Any]] = None
    # B12（对照改进项）：语义判重读数（各池累计计数求和；台账规模求和）
    dedup: Optional[Dict[str, Any]] = None


class ContextCompositionResponse(BaseModel):
    """上下文组成实测（聊天页悬停面板数据源）"""

    agent_id: str
    measured_at: float
    elapsed_ms: float
    context_window: Optional[int] = None
    total_tokens: int = 0
    messages: Dict[str, Any] = Field(default_factory=dict)
    tools: Dict[str, Any] = Field(default_factory=dict)
    cache_hit_rate: Optional[float] = None
    cache_source: str = "none"


class ContextPreview(BaseModel):
    """上下文预览"""

    context_id: str
    content: str
    token_count: int
    sources: List[str]


# P2-1（全库断点审计 2026-11-12）：已构建上下文的进程内登记（有界，淘汰最旧）。
# /{context_id}/preview 与 /{context_id}/compress 此前是 TODO 桩——根因是构建
# 产物从未按 id 落册，两个端点无物可查。
_BUILT_CONTEXTS_MAX = 50
_built_contexts: Dict[str, Dict[str, Any]] = {}


def _store_built_context(
    context_id: str,
    content: str,
    token_count: int,
    sources: List[str],
    agent_id: str = "",
    session_id: Optional[str] = None,
) -> None:
    _built_contexts[context_id] = {
        "content": content,
        "token_count": int(token_count),
        "sources": list(sources or []),
        "agent_id": agent_id,
        "session_id": session_id,
        "created_at": time.time(),
    }
    while len(_built_contexts) > _BUILT_CONTEXTS_MAX:
        oldest = min(_built_contexts, key=lambda k: _built_contexts[k]["created_at"])
        _built_contexts.pop(oldest, None)


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = ""):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_context_builder(user_id: str = None, agent_id: str = None, session_id: str = None):
    """取该身份下的上下文池（隔离版本）。

    改前每次请求都 `ContextPool(...)` 新建：与 Agent 的池完全隔离，写入即丢
    （审计 P2-3）。现在按身份**取同一个池**：

    1. Agent 已有编排器池 → 直接返回它（这才是对话主链真正在用的池）；
    2. 否则按 (user, agent, session) 在注册表里取；取不到才创建**并登记**——
       登记这一步是根因所在：不登记，同一身份的下一次请求又会拿到新池。

    池身份是隔离契约的一部分，故参数缺省仍落显式默认值（不静默丢弃隔离维度）。
    """
    try:
        from neurova.context_pool import ContextPool, get_context_pool
        from neurova.context_pool_registry import get_registry

        if user_id is None or agent_id is None:
            logger.warning("ContextPool requires user_id and agent_id for isolation. Using default values.")
            user_id = user_id or "default_user"
            agent_id = agent_id or "default_agent"

        agent = _get_agent(agent_id)
        orchestrator = getattr(agent, "context_orchestrator", None) if agent is not None else None
        agent_pool = getattr(orchestrator, "context_pool", None) if orchestrator is not None else None
        if agent_pool is not None:
            get_registry().adopt(agent_pool)
            return agent_pool

        existing = get_context_pool(user_id=user_id, agent_id=agent_id, session_id=session_id)
        if existing is not None:
            return existing

        pool = ContextPool(user_id=user_id, agent_id=agent_id, session_id=session_id)
        get_registry().adopt(pool)
        return pool
    except Exception as e:
        logger.warning("ContextPool not available: %s", e)
        return None



def _count_tokens(text: str) -> int:
    """全仓唯一的 token 计数入口（判据与展示同源，T-01）。

    端点不另写一份计数：`context/token_estimator` 是尺子的唯一事实源，
    `composition` 面板与全部预算判据都走它。就地近似（`len//4`、`len*1.5`、
    `len(split())`）一律不允许——那是第二把尺子，会让"该压缩时不压缩"。
    """
    from neurova.context.token_estimator import estimate_tokens

    return estimate_tokens(text)


@router.post("/build", response_model=BuildContextResponse)
async def build_context(
    request: Request,
    body: BuildContextRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """构建上下文（带用户隔离）"""
    _get_request_id(request)
    start_time = time.time()
    context_id = str(uuid.uuid4())

    try:
        # 从JWT获取用户ID，确保隔离
        user_id = current_user.get("user_id", "unknown")
        agent_id = body.agent_id
        session_id = body.session_id

        # 使用隔离的上下文构建器
        context_builder = _get_context_builder(user_id=user_id, agent_id=agent_id, session_id=session_id)

        if context_builder:
            # 使用 ContextPool 构建上下文
            try:
                # 添加用户输入到上下文池
                # 优先级由来源经池内阶梯派生（`context.pool_models.priorityForSource`）。
                # 改前此处写死 10 并注释「高优先级」——池内 60–100 才是高档，
                # 10 属最低档：注释与真值相反，且与编排器同一来源的 90 是两份口径。
                user_context = ContextInput(
                    content=body.user_input,
                    source=ContextSource.USER_INPUT,
                )
                context_builder.add_context(user_context)

                # 构建上下文（使用默认模型名称）
                context_messages = context_builder.build_context_for_model("default")

                # 转换为字符串格式
                context_content = "\n".join(
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in context_messages
                )
                sources = [msg.get("source", "context_pool") for msg in context_messages]

            except Exception as e:
                logger.warning("ContextPool failed, falling back: %s", e)
                # 降级到原有逻辑
                context_builder = None

        if not context_builder:
            # 降级：使用原有的 Agent 构建器
            agent = _get_agent(agent_id)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            context_content = ""
            sources = []

            if hasattr(agent, "build_context"):
                # 审计⑮：按 ContextOrchestrator.build_context 真实签名调用——
                # 旧代码传 session_id/include_memories 等不存在的 kwargs →
                # TypeError 500
                result = await agent.build_context(user_input=body.user_input)
                if isinstance(result, list):
                    context_content = "\n".join(
                        f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in result
                    )
                    sources = ["agent_build_context"]
                elif isinstance(result, dict):
                    context_content = result.get("content", "")
                    sources = result.get("sources", [])
                else:
                    context_content = str(result)
            else:
                # 降级：构建基础上下文
                context_content = f"User: {body.user_input}\n\nSystem: Processing request..."
                sources = ["user_input"]

        token_count = _count_tokens(context_content)
        # P2-1：构建产物按 id 落册——preview/compress 由此有物可查
        _store_built_context(context_id, context_content, token_count, sources, agent_id, session_id)

        return BuildContextResponse(
            context_id=context_id,
            content=context_content,
            # 全仓唯一 token 尺子（T-01 契约）。改前这里是 `len(context_content.split())`
            # ——第二把尺子，且中文整句在空白分词下只算一个词（实测同一句 4 vs 15）。
            # 响应契约字段报假数不是"粗略"，而是与 composition 面板 / 判据不同源。
            token_count=token_count,
            sources=sources,
            build_time=time.time() - start_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build context: {str(e)}")


@router.post("/build/v2", response_model=BuildContextResponse)
async def build_context_v2(
    request: Request,
    body: BuildContextRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """构建上下文 V2（增强版，带用户隔离）"""
    _get_request_id(request)
    start_time = time.time()
    context_id = str(uuid.uuid4())

    try:
        # 从JWT获取用户ID，确保隔离
        user_id = current_user.get("user_id", "unknown")
        agent_id = body.agent_id
        session_id = body.session_id

        # 使用隔离的上下文构建器
        context_builder = _get_context_builder(user_id=user_id, agent_id=agent_id, session_id=session_id)

        if context_builder:
            # 使用 ContextPool 构建上下文
            try:
                # 添加用户输入到上下文池
                # 优先级由来源经池内阶梯派生（同 `/build`，单源见
                # `context.pool_models.priorityForSource`）。
                user_context = ContextInput(
                    content=body.user_input,
                    source=ContextSource.USER_INPUT,
                )
                context_builder.add_context(user_context)

                # 构建上下文（使用默认模型名称）
                context_messages = context_builder.build_context_for_model("default")

                # 转换为字符串格式
                context_content = "\n".join(
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in context_messages
                )
                sources = [msg.get("source", "context_pool") for msg in context_messages]

            except Exception as e:
                logger.warning("ContextPool failed, falling back: %s", e)
                # 降级到原有逻辑
                context_builder = None

        if not context_builder:
            # 降级：使用原有的 Agent 构建器
            agent = _get_agent(agent_id)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            # 使用 UnifiedContextInjector
            context_content = ""
            sources = []

            if hasattr(agent, "unified_injector") and agent.unified_injector:
                # 审计⑮：按 UnifiedContextInjector.build_context 真实签名调用
                result = agent.unified_injector.build_context(
                    system_prompt=getattr(agent, "soul", "") or "",
                    memories=[],
                    conversation_history=[],
                    user_input=body.user_input,
                    max_tokens=body.max_tokens,
                    include_reflection_log=body.include_reflection,
                )
                if isinstance(result, list):
                    context_content = "\n".join(
                        f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in result
                    )
                    sources = ["unified_injector"]
                else:
                    context = getattr(result, "context", None) or result.get("context", [])
                    context_content = "\n".join(
                        f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in context
                    )
                    sources = ["unified_injector"]
            elif hasattr(agent, "build_context"):
                result = await agent.build_context(user_input=body.user_input)
                if isinstance(result, list):
                    context_content = "\n".join(
                        f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in result
                    )
                    sources = ["agent_build_context"]
                elif isinstance(result, dict):
                    context_content = result.get("content", "")
                    sources = result.get("sources", [])
                else:
                    context_content = str(result)
            else:
                context_content = f"User: {body.user_input}"
                sources = ["user_input"]

        token_count = _count_tokens(context_content)
        # P2-1：同 /build，构建产物按 id 落册
        _store_built_context(context_id, context_content, token_count, sources, agent_id, session_id)

        return BuildContextResponse(
            context_id=context_id,
            content=context_content,
            # 同 `/build`：唯一尺子（单源见 `_count_tokens`）。
            token_count=token_count,
            sources=sources,
            build_time=time.time() - start_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build context v2 error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build context: {str(e)}")


@router.get("/stats", response_model=ContextStats)
async def get_context_stats(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取上下文池真实统计（P2-7 收口：此前恒回全零 stub）。

    聚合 context pool 注册表中全部已登记池的保留读数
    （`ContextPool.get_retention_stats`，Issue #65 可观测面）。无池时
    `pools=0`、各计数 0——那是"当前确实没有池"的真值，不是伪造的零。
    """
    from neurova.context_pool_registry import get_registry

    pools = get_registry().allPools()
    stats = []
    for pool in pools:
        try:
            stats.append(pool.get_retention_stats())
        except Exception:  # noqa: BLE001 - 单池读数失败不拖垮聚合
            logger.warning("context stats: 单池读数失败", exc_info=True)
    total_contexts = sum(int(s.get("resident_count") or 0) for s in stats)
    archived_total = sum(int(s.get("archived_total") or 0) for s in stats)
    ledger_rows = sum(int((s.get("ledger") or {}).get("rows") or 0) for s in stats)
    indexed_entries = sum(int((s.get("read_index") or {}).get("indexed_entries") or 0) for s in stats)
    # B13（对照改进项）：各池抽屉累计计数求和——键集固定（_READOUT_KEYS），
    # 单池缺键按 0 计，不因单池读数形状漂移而 500。
    drawer_keys = (
        "draws_total", "offered_total", "candidates_total", "threshold_pass_total",
        "threshold_miss_total", "injected_total", "injected_tokens_total", "degraded_total",
    )
    drawer_totals = {
        key: sum(int((s.get("drawer") or {}).get(key) or 0) for s in stats)
        for key in drawer_keys
    }
    # B12（对照改进项）：语义判重读数聚合（计数求和；开关取任一池开启）。
    dedup_keys = ("semantic_checks", "semantic_dedup_total", "restores", "restore_ledger_size")
    dedup_totals: Dict[str, Any] = {
        key: sum(int((s.get("dedup") or {}).get(key) or 0) for s in stats)
        for key in dedup_keys
    }
    dedup_totals["semantic_enabled"] = any(
        bool((s.get("dedup") or {}).get("semantic_enabled")) for s in stats
    )
    similarities = [
        float((s.get("dedup") or {}).get("last_similarity"))
        for s in stats
        if (s.get("dedup") or {}).get("last_similarity") is not None
    ]
    dedup_totals["last_similarity"] = max(similarities) if similarities else None
    return ContextStats(
        pools=len(stats),
        total_contexts=total_contexts,
        average_resident=round(total_contexts / len(stats), 2) if stats else 0,
        archived_total=archived_total,
        ledger_rows=ledger_rows,
        indexed_entries=indexed_entries,
        drawer=drawer_totals,
        dedup=dedup_totals,
    )


@router.get("/composition", response_model=ContextCompositionResponse)
async def get_context_composition(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    session_id: str = Query(default="", description="Session ID（提供时按会话隔离快照）"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取最近一轮 LLM 请求的上下文组成实测（消息分桶 + 工具分类 + 命中率）。

    数据来自 ChatPipeline._step_llm_call 挂点的真实测算（非估算 stub）；
    该 agent 尚未跑过任何一轮时返回 404——前端按"暂无数据"处理，不伪造。
    session_id 提供时优先读该会话自己的快照（聊天页环图按会话隔离，2026-09-08 bug2）。
    """
    from neurova.context.composition import estimate_composition_from_history, get_last_composition

    comp = get_last_composition(agent_id or "default", session_id or None)
    if comp is None and session_id:
        # 该会话尚无实测快照（修复前创建的老会话）→ 用会话历史估算兜底。
        # 不回落 agent 级快照：那是别的会话的上下文，会造成"环图数据相同"。
        comp = estimate_composition_from_history(agent_id or "default", session_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="No composition measured for this session yet")
    return ContextCompositionResponse(**comp)


@router.get("/budget")
async def get_context_budget(
    agent_id: str = Query(default="default", description="Agent ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取最近一次系统提示的常驻分段预算（N6，只读）。

    无实测记录返回 404——不伪造一份空报告；报告只测量、不改写 prompt。
    """
    from neurova.context.budget_report import getContextBudget

    report = getContextBudget(agent_id or "default")
    if report is None:
        raise HTTPException(status_code=404, detail="No always-on budget measured for this agent yet")
    return report


@router.get("/{context_id}/preview", response_model=ContextPreview)
async def get_context_preview(
    request: Request,
    context_id: str = Path(..., description="上下文ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取上下文预览（P2-1 实装：读取 /build 登记的构建产物；未知 id 404）"""
    entry = _built_contexts.get(context_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Context '{context_id}' not found（构建产物有界过期，请重新 /build 后再取）",
        )
    return ContextPreview(
        context_id=context_id,
        content=entry["content"],
        token_count=entry["token_count"],
        sources=entry["sources"],
    )


@router.post("/{context_id}/compress")
async def compress_context(
    request: Request,
    context_id: str = Path(..., description="上下文ID"),
    target_tokens: int = Query(default=4000, description="目标 token 数"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """压缩上下文（P2-1 实装：保留最近段落在目标 token 预算内，淘汰最旧段；
    压缩结果写回登记，后续 preview 读到的是压缩后版本）"""
    request_id = _get_request_id(request)
    entry = _built_contexts.get(context_id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Context '{context_id}' not found（构建产物有界过期，请重新 /build 后再压缩）",
        )
    if target_tokens <= 0:
        raise HTTPException(status_code=400, detail="target_tokens 必须为正数")

    try:
        content = entry["content"]
        original_tokens = entry["token_count"]
        segments = content.split("\n")

        # 保留最近的连续段落：从最新段向前累计，首个放不下的段起淘汰
        kept: List[str] = []
        used = 0
        for seg in reversed(segments):
            cost = _count_tokens(seg) + 1  # 换行符开销
            if used + cost > target_tokens:
                break
            kept.append(seg)
            used += cost
        kept.reverse()
        dropped = len(segments) - len(kept)

        compressed_content = "\n".join(kept)
        compressed_tokens = _count_tokens(compressed_content)

        entry["content"] = compressed_content
        entry["token_count"] = compressed_tokens

        return {
            "code": 0,
            "message": "Context compressed",
            "data": {
                "context_id": context_id,
                "target_tokens": target_tokens,
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "dropped_segments": dropped,
                "content": compressed_content,
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compress context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compress context: {str(e)}")


@router.get("/inject/reflection")
async def inject_reflection_log(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """注入反思日志到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 获取反思日志
        reflection_logs = []
        if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
            # 根因修复: get_recent_logs 不存在（hasattr 守卫使其静默为空）
            # → read_logs 真实读取并序列化
            entries = agent.growth_log_manager.read_logs(limit=limit)
            reflection_logs = [e.to_dict() for e in entries]

        return {
            "code": 0,
            "message": "success",
            "data": {
                "reflection_logs": reflection_logs,
                "count": len(reflection_logs),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject reflection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject reflection: {str(e)}")


@router.get("/inject/memories")
async def inject_memories(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    query: str = Query(default="", description="搜索查询"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """注入相关记忆到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 搜索记忆（MemoryManager 真实接口：search_memories / get_hot_memories）
        memories = []
        if hasattr(agent, "memory_manager") and agent.memory_manager:
            if query:
                memories = agent.memory_manager.search_memories(query=query, limit=limit)
            else:
                memories = agent.memory_manager.get_hot_memories(limit=limit)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "memories": memories,
                "count": len(memories),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject memories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject memories: {str(e)}")


@router.get("/inject/hot")
async def inject_hot_memories(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=5, ge=1, le=50, description="数量限制"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """注入高温记忆到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 获取高温记忆
        hot_memories = []
        if hasattr(agent, "memory_manager") and agent.memory_manager:
            hot_memories = agent.memory_manager.get_hot_memories(limit=limit)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "hot_memories": hot_memories,
                "count": len(hot_memories),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject hot memories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject hot memories: {str(e)}")
