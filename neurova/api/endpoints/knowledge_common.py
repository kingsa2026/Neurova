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

import os
import uuid
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from neurova.core.logger import get_logger

logger = get_logger(__name__)  # 抽取共享件要出声；治理校验路径仍不写日志


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
    source_created_at: str = ""
    source_modified_at: str = ""
    visibility: str = "private"
    owner_user_id: str = ""
    shared_with: List[str] = []
    submission: Optional[Dict[str, Any]] = None
    graph_node_ids: List[str] = []
    valid_until: Optional[str] = None
    lifecycle_status: str = "active"
    sources: List[Dict[str, Any]] = []
    geo: Optional[Dict[str, float]] = None
    duplicate: Optional[bool] = None
    lifecycle_reason: str = ""
    lifecycle_changed_at: Optional[str] = None
    # P0-2 分块契约：块数 + 检索命中的块级溯源（[{chunk_index, content, score}]）
    chunk_count: int = 1
    chunk_hits: List[Dict[str, Any]] = []
    # B11 双时态事实视图：confidence/qualifier/valid/transaction 随条目带出；
    # 条目检索旧行为不填（空字典），不改变既有响应形状。
    metadata: Dict[str, Any] = {}


class KnowledgeCreate(BaseModel):
    """创建知识请求"""

    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    source: str = Field(default="", description="来源")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度")
    visibility: str = Field(default="private", description="可见性：private（默认）/ public（仅管理员）")
    valid_until: Optional[str] = Field(default=None, description="有效期截止（ISO8601，空=不过期）")
    lifecycle_status: Literal["active", "archived"] = Field(default="active", description="生命周期状态")
    author: str = Field(default="", description="作者（文档元数据过滤维度）")
    geo: Optional[Dict[str, float]] = Field(default=None, description="坐标 {lat, lon}，坏形状入库归 None")


class KnowledgeUpdate(BaseModel):
    """更新知识请求"""

    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    confidence: Optional[float] = None
    valid_until: Optional[str] = None
    lifecycle_status: Optional[Literal["active", "archived"]] = None


class KnowledgeSearchRequest(BaseModel):
    """搜索知识请求"""

    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(..., description="搜索查询")
    category: Optional[str] = None
    tags: List[str] = []
    source: Optional[str] = None
    author: Optional[str] = None
    source_type: Optional[str] = None
    ocr_used: Optional[bool] = None
    page_min: Optional[int] = Field(default=None, ge=0)
    updated_after: Optional[float] = None
    source_modified_after: Optional[str] = None
    source_modified_before: Optional[str] = None
    # B11 L3 双时态：asOf 裁 valid time，knownAt 裁 transaction time。
    # 任一轴给出时 query 走事实层（factsBitemporal）；两轴都空保持条目检索旧行为。
    as_of: Optional[str] = Field(default=None, alias="asOf")
    known_at: Optional[str] = Field(default=None, alias="knownAt")

    @field_validator("source_modified_after", "source_modified_before")
    @classmethod
    def _rejectUnparseableSourceDate(cls, value):
        """非法过滤值在请求边界 422，不许静默跳过。

        `_parseSourceDate` 对不可考值返回 None；若在 repository 里静默跳过，
        请求会得到 200＋被收窄（或未收窄）的结果集，排障时看不出参数写错了。
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        from neurova.knowledge.repository import _parseSourceDate

        if _parseSourceDate(text) is None:
            raise ValueError(
                "源时间过滤值不可解析（支持 ISO 8601、epoch 秒、PDF D: 形）"
            )
        return text
    geo_radius: Optional[Dict[str, float]] = Field(
        default=None, description="半径过滤 {lat, lon, radius_km}")
    geo_bbox: Optional[Dict[str, float]] = Field(
        default=None, description="矩形过滤 {min_lat, min_lon, max_lat, max_lon}")
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


def get_agent(agent_id: str = ""):
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
        source_created_at=str(item.get("source_created_at", "") or ""),
        source_modified_at=str(item.get("source_modified_at", "") or ""),
        visibility=item.get("visibility", "private"),
        owner_user_id=item.get("owner_user_id", ""),
        shared_with=item.get("shared_with") or [],
        submission=item.get("submission"),
        graph_node_ids=item.get("graph_node_ids") or [],
        valid_until=item.get("valid_until"),
        lifecycle_status=item.get("lifecycle_status", "active"),
        lifecycle_reason=item.get("lifecycle_reason", ""),
        lifecycle_changed_at=item.get("lifecycle_changed_at"),
        chunk_count=len(item.get("chunks") or []) or 1,
        chunk_hits=item.get("chunk_hits") or [],
        sources=item.get("sources") or [],
        geo=item.get("geo"),
        duplicate=item.get("duplicate"),
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


def entry_for_update(repo, knowledge_id: str, current_user: Dict[str, Any], fields: Dict[str, Any]):
    """按本次要写的字段选门（用户裁定 2026-11-09）：只写分类 → 私有条目
    （含被共享）可见即可写、公共条目仍归属主/管理员；其余字段一律属主/管理员。
    可见性与归属谓词都取自仓库单源（can_view/can_categorize/can_modify），
    本函数只决定用哪一扇门，不另立权限口径。"""
    from neurova.knowledge.repository import VISIBILITY_PUBLIC

    agent_id, item = entry_or_404(repo, knowledge_id, current_user)
    if set(fields) == {"category"}:
        if not repo.can_categorize(current_user, item):
            raise HTTPException(status_code=403, detail="公共条目分类仅属主或管理员可修改")
        return agent_id, item
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



# ── 抽取共享件（2026-11-05 自 knowledge_ingestion 下沉）──────────────────
# 分层守卫不变量 2 的原话是"共享需求一律下沉共享层"：knowledge_core 的 PUT 更新
# 路径与 knowledge_ingestion 的 /import 路由要的是同一条抽取管线，此前是叶子互调
# （同层交叉，常驻红）。搬进来后两侧都指向下层；ingestion 用 `from ... import` 取
# 本地绑定，测试按属性 patch 依然咬得到它自己那条调用。
ENV_EXTRACT_ON_UPDATE = "NEUROVA_KB_EXTRACT_ON_UPDATE"

#: 事件摘要索引增强的门控（SAG 对比候选 C5）：LLM 成本 per 条目，默认 off＝
#: 旧行为（索引输入不含摘要）；开闸后摘要写回条目并登记 reindex。
ENV_EVENT_SUMMARY = "NEUROVA_KB_EVENT_SUMMARY"

#: 事件摘要生成提示词（本仓自研措辞）：一句话、只输出摘要本身。
_EVENT_SUMMARY_PROMPT = (
    "把下面的知识条目压缩成一句事件摘要（谁/什么/结果或状态），"
    "不超过 60 个字，直接输出摘要本身，不要解释：\n标题：{title}\n正文：{content}"
)


def eventSummaryMode() -> str:
    """D-16 的现值形读数：注册表与本文件的门控共用这一个解点。

    env 在这里解一次；`extract_event_summary` 过去自己读，读的就是这条串。
    """
    raw = str(os.environ.get(ENV_EVENT_SUMMARY) or "").strip().lower()
    return "on" if raw in ("1", "true", "on", "yes") else "off"


def extract_event_summary(
    item: Dict[str, Any], request: Optional[Request], agent_id: str,
    tenant_id: str = "default",
    llm_call: Optional[Callable[[str], str]] = None,
) -> str:
    """条目事件摘要生成并写回（SAG 对比候选 C5，2026-11-05）。

    摘要写回 `event_summary` 字段（update 白名单）并登记索引重排——摘要随后
    进入全部索引输入单点（build_index_content 词法三路 + embeddingText 向量），
    召回从字面重叠升到语义事件。NEUROVA_KB_EVENT_SUMMARY 门控（默认 off）；
    无 LLM/空输出/写回失败均如实返回状态串，绝不打断导入主流程。
    """
    if eventSummaryMode() != "on":
        return "skipped_disabled"
    try:
        if llm_call is None:
            llm_call = _default_llm_call(request, prefer_agent_id=agent_id)
        if llm_call is None:
            return "skipped_no_llm"
        prompt = _EVENT_SUMMARY_PROMPT.format(
            title=str(item.get("title") or ""),
            content=str(item.get("content") or "")[:2000],
        )
        text = str(llm_call(prompt) or "").strip()
        summary = text.splitlines()[0].strip()[:120] if text else ""
        if not summary:
            return "skipped_empty_summary"
        from neurova.knowledge.repository import get_knowledge_repository

        ok = get_knowledge_repository().update_knowledge(
            str(agent_id or "default"), str(item.get("knowledge_id") or ""),
            {"event_summary": summary},
        )
        return "extracted" if ok else "skipped_update_failed"
    except Exception as exc:  # noqa: BLE001 - 摘要失败不影响导入/更新主流程
        logger.warning("事件摘要生成失败（不影响主流程）: %s", exc)
        return "extract_error"


def extract_after_update(
    item: Dict[str, Any], request: Optional[Request], agent_id: str,
    tenant_id: str = "default",
) -> str:
    """条目内容更新后的 facts 重抽（SAG 对比候选 C2，2026-11-05）。

    更新路径此前不重抽实体关系——旧 facts 与新正文漂移只能靠 drift 读数
    被动发现（SAG 对比 §4 实测的增量更新缺口）。本函数复用导入抽取同一条
    管线（_try_extract_to_graph → extract_knowledge_to_graph →
    admitExtractedFacts），增量 admit；漂移治理仍走既有 supersede/conflict
    机制，不在本函数职责内。

    NEUROVA_KB_EXTRACT_ON_UPDATE 门控（默认 off＝旧行为）；抽取失败
    fail-soft 返回状态串，绝不打断更新主流程。
    """
    raw = str(os.environ.get(ENV_EXTRACT_ON_UPDATE) or "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return "skipped_disabled"
    if raw not in ("1", "true", "on", "yes"):
        # 无 env 显式值 → 跟随设置面（Ontology 设置卡，app_settings 持久化）
        from neurova.core.app_settings import get_advanced_settings

        if not bool(get_advanced_settings().get("ontology_extract_on_update")):
            return "skipped_disabled"
    try:
        _try_extract_to_graph(
            [dict(item)], request, agent_id=agent_id, tenant_id=tenant_id
        )
        return "extracted"
    except Exception as exc:  # noqa: BLE001 - 重抽失败不影响更新返回
        logger.warning("更新后 facts 重抽失败（更新已生效）: %s", exc)
        return "extract_error"

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
    items: List[Dict[str, Any]], request: Request, agent_id: Optional[str] = None,
    tenant_id: str = "default",
) -> None:
    """导入后触发"知识条目→图谱节点"抽取（批次 3）。失败逐条吞掉，不阻断导入。"""
    from neurova.cognitive_layers.knowledge_graph.manager import (
        get_agent_knowledge_graph_manager,
    )
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store
    from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
    from neurova.knowledge.repository import get_knowledge_repository

    llm_call = _default_llm_call(request, prefer_agent_id=agent_id)
    if llm_call is None:
        logger.info("[知识导入] 未解析到可用 LLM，跳过 %s 条的图谱抽取", len(items))
        return
    repo = get_knowledge_repository()
    # 权威落点必须显式接入：不传底座时抽取只落 JSON 投影，而答题读的是底座三元组，
    # 那就是 Issue #72 的"两张图"（审计 §5.3 / B-09）。
    authority = get_knowledge_fact_store()
    # per-agent + per-tenant 隔离：写入所属 agent/租户的图谱；agent_id 缺失时
    # 落 default 域（测试路径），不退回跨租户共享的全局图。
    graph = get_agent_knowledge_graph_manager(
        agent_id or "default", tenant_id=str(tenant_id or "default")
    )
    for entry in items:
        try:
            # C3（SAG 对比候选）：待抽条目先过认知安全门——复用既有三态配置
            # （observe 默认只记读数；enforce 且不安全才跳过该条目，其余照常）。
            # 门故障 fail-open：读不到读数就按安全处理，不阻断导入。
            try:
                from neurova.security.cognitive_security_gate import runInputSafetyGate

                guardReading = runInputSafetyGate("%s\n%s" % (
                    str(entry.get("title") or ""), str(entry.get("content") or ""),
                ))
                if (guardReading and not guardReading.get("is_safe", True)
                        and guardReading.get("mode") == "enforce"):
                    logger.warning(
                        "[知识导入] 条目 %s 命中注入嫌疑且为 enforce 态，跳过抽取",
                        entry.get("knowledge_id"),
                    )
                    continue
            except Exception as guardExc:  # noqa: BLE001 - 安全门故障不阻断导入
                logger.debug("[知识导入] 安全门读数失败（fail-open）: %s", guardExc)
            # agentId 必须传：抽取产物要落进被检索的那张图，落错域等于把条目的事实
            # 写进别人的库；factStore 同理——不传底座就只剩 JSON 投影。
            extract_knowledge_to_graph(
                entry, repo=repo, llm_call=llm_call, graph_manager=graph,
                factStore=authority, agentId=agent_id or "",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[知识导入] 图谱抽取失败（已跳过）: %s", e)
