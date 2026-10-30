"""KnowledgeRetrieverAdapter - 知识库检索器适配器

P0#4：chat 路从裸 TF-IDF 分片切到 knowledge.hybrid
四路 RRF（tfidf 分片 + bm25 + fts + ONNX 向量持久化索引）——双索引器合一，
语义路首次进入对话管线；向量引擎不可用时各辅助路自动降级，主路（tfidf）
异常仍上抛由责任链决定 fallback。用户隔离与质量评分契约不变。
RRF 之后应用轻量采纳先验（success 升、failure 降、unevidenced 中性），
在最终 top-k 截断前重排；候选窗扩到 3 倍以给降权项腾出的位置留替补。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.knowledge.ambiguity_clarification import ambiguityMode, buildAmbiguityBlock
from neurova.knowledge.feedback_prior import rerankByAdoption
from neurova.knowledge.query_normalization import normalizeMode, normalizeQueryForRetrieval

logger = get_logger(__name__)

#: 采纳重排需要比最终 top-k 更宽的候选窗，否则被降权项腾出的位置没有替补。
ADOPTION_CANDIDATE_FACTOR = 3
ADOPTION_CANDIDATE_MAX = 100

#: W2 检索脱靶登记（specs/2026-10-30）：0 命中查询落候选别名，只进人工审批面。
MISS_CAPTURE_ENV = "NEUROVA_KB_MISS_CAPTURE"


def _missCaptureEnabled() -> bool:
    return str(os.environ.get(MISS_CAPTURE_ENV) or "").strip().lower() in (
        "on", "1", "true", "yes",
    )


def _isCapturableMissQuery(query: str) -> bool:
    """平凡查询（空/纯符号/单字符）不登记，防审批面被噪声灌满。"""
    text = str(query or "").strip()
    if len(text) < 2:
        return False
    return any(ch.isalnum() for ch in text)


def _captureRetrievalMiss(agentId: str, tenantId: str, query: str) -> None:
    try:
        from neurova.knowledge.foundation.knowledge_facts import (
            get_knowledge_fact_store,
        )

        get_knowledge_fact_store().captureAliasCandidate(
            agentId, query, tenantId=tenantId
        )
    except Exception as exc:  # noqa: BLE001 - 脱靶登记失败绝不影响检索返回
        logger.debug("检索脱靶登记跳过: %s", exc)


class KnowledgeRetrieverAdapter:
    """适配知识库 Repository，作为检索链的一级检索器。

    优先级 25：在 UnifiedRetriever(10)/MoE(20) 之后、Cache(30) 之前，
    即优先保证记忆与 MoE 路由，知识库作为补充知识源。
    """

    def __init__(self, repo, user: Optional[Dict[str, Any]] = None, factSurface=None,
                 graphWalker=None):
        """
        参数:
            repo: 知识库 Repository 实例（需有 search_visible_items 方法）
            user: 当前用户字典（可后续透传覆盖）
            factSurface: 底座读面；不传则按环境开关惰性取得——装配段因此无需改动
        """
        self._repo = repo
        self._user = user
        self._factSurface = factSurface
        self._graphWalker = graphWalker
        self._name = "KnowledgeRetriever"
        self._priority = 25  # 中等偏下优先级（记忆 >> 知识）

    def _graphRoute(self, context, agentId: Optional[str], limit: int):
        """图谱条目影子路由：fact→entry 映射；默认权重 0，不改变排序。"""
        mode = str(os.environ.get("NEUROVA_KB_GRAPH_ROUTE") or "shadow").lower()
        if mode in ("off", "0", "false", "no"):
            return [], {}, 0.0
        try:
            walker = self._graphWalker
            if walker is None:
                from neurova.knowledge.foundation.graph_walk import GraphFactWalker
                from neurova.knowledge.foundation.knowledge_facts import (
                    get_knowledge_fact_store,
                )

                walker = GraphFactWalker(
                    get_knowledge_fact_store(), agentId=agentId
                )
            tenantId = str(
                (getattr(context, "metadata", None) or {}).get("tenant_id")
                or "default"
            )
            hops = walker.walkFromQuery(
                context.query, limit=max(limit * 2, 10), tenantId=tenantId
            )
            ranks = []
            support = {}
            for hop in hops or []:
                entryId = str(hop.get("entry_id") or "")
                if not entryId:
                    continue
                if entryId not in ranks:
                    ranks.append(entryId)
                support.setdefault(entryId, []).append({
                    "fact_id": hop.get("id"),
                    "hops": hop.get("hop"),
                    "path": hop.get("path"),
                })
            graphWeight = 0.0
            if mode in ("on", "1", "true", "yes"):
                try:
                    graphWeight = float(
                        os.environ.get("NEUROVA_KB_GRAPH_ROUTE_WEIGHT", "0.10")
                    )
                except ValueError:
                    graphWeight = 0.10
            return [
                (entryId, 1.0 / (index + 1))
                for index, entryId in enumerate(ranks)
            ], support, graphWeight
        except Exception as exc:  # noqa: BLE001 - 图谱影子失败不阻断知识主路
            logger.debug("知识图谱影子路由跳过: %s", exc)
            return [], {}, 0.0

    def _surface(self):
        """返回已启用的读面，关闸即 None（判一次，之后所有分支不再各自猜开关状态）。"""
        from neurova.knowledge.foundation.read_surface import FactSurface, FactSurfaceConfig

        surface = self._factSurface
        if surface is None:
            if not FactSurfaceConfig.fromEnv().enabled:
                return None
            from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

            surface = FactSurface(get_knowledge_fact_store())
            self._factSurface = surface
        return surface if surface.enabled else None

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def _enrich(self, knowledge_items):
        """把治理字段挂到已排好序的命中上；注入计数交给最终选中的命中。

        011 试过"两池按秩交织"并被真数据否证（同一份内容在两池各算一票，
        短事实凭 BM25 优势顶掉强叙述命中）。所以接入底座的方式改成富化：
        排序仍由 RRF 打底，底座只补充置信/证据态/采纳三态/血缘内键。
        返回 `(hits, lineageIds, store, recordInjection)`：是否回写注入计数
        由 FactSurface 闸决定，但计数只能对最终注入的命中做，不能算候选窗。
        """
        if not knowledge_items:
            return knowledge_items, [], None, False
        surface = self._surface()
        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store
        from neurova.knowledge.foundation.read_surface import attachGovernance

        # 血缘映射与 FactSurface 的置信富化是两件事：即使富化关着，也要把
        # 条目映射到事实行，否则 /chat/feedback 无法把采纳结果写回正确事实。
        # 事实库不可用（测试夹具/围栏/临时故障）只丢血缘，不打死检索。
        hits = knowledge_items
        lineageIds: List[str] = []
        store = None
        try:
            store = get_knowledge_fact_store()
            hits, lineageIds = attachGovernance(
                store, knowledge_items, enrich=surface is not None
            )
        except Exception as exc:  # noqa: BLE001 - 增强面失败不得影响主检索
            logger.debug("知识血缘富化失败（检索继续，无采纳回写）: %s", exc)
        # 无 fact lineage 的文档条目走 entry 级反馈；有 fact 的以 fact 三态为准。
        entryIds = [
            str(hit["knowledge_id"])
            for hit in hits
            if hit.get("knowledge_id") and not hit.get("lineage_id")
        ]
        lookup = getattr(self._repo, "entryFeedbackMap", None)
        if entryIds and callable(lookup):
            try:
                feedback = lookup(entryIds) or {}
                for hit in hits:
                    if hit.get("lineage_id"):
                        continue
                    row = feedback.get(str(hit.get("knowledge_id") or "")) or {}
                    hit["adoption_outcome"] = row.get("adoption_outcome")
                    hit["injected_count"] = row.get("injected_count", 0)
            except Exception as exc:  # noqa: BLE001 - 反馈读失败只丢先验
                logger.debug("知识条目反馈读取失败（保持中性）: %s", exc)
        return hits, lineageIds, store, surface is not None

    async def retrieve(self, context) -> Any:
        """执行知识库检索（走用户可见性过滤）"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult, RetrievalQuality

        start_time = time.monotonic()

        try:
            # 用户隔离：检索上下文注入 user_id + role（admin 需全可见；metadata 可携带 agent_id）
            user: Optional[Dict[str, Any]] = None
            if getattr(context, "user_id", None):
                user = {"user_id": str(context.user_id)}
                metadataRole = (getattr(context, "metadata", None) or {}).get("role")
                if metadataRole:
                    user["role"] = str(metadataRole)
                user["tenant_id"] = str(
                    (getattr(context, "metadata", None) or {}).get("tenant_id") or "default"
                )

            metadata = getattr(context, "metadata", None) or {}
            agent_id = metadata.get("agent_id")

            # W1 查询侧别名归一（specs/2026-10-30）：off 零开销；shadow 只带读数
            # 不改查询；on 把命中主体的规范名追加进检索词。归一失败让路，主路照跑。
            normMode = normalizeMode()
            normMetadata: Optional[Dict[str, Any]] = None
            searchQuery = str(context.query or "")
            if normMode in ("shadow", "on") and agent_id:
                try:
                    from neurova.knowledge.foundation.knowledge_facts import (
                        get_knowledge_fact_store,
                    )
                    from neurova.knowledge.retrieval_metrics import get_retrieval_metrics

                    tenantId = str(metadata.get("tenant_id") or "default")
                    norm = normalizeQueryForRetrieval(
                        get_knowledge_fact_store(), searchQuery, str(agent_id), tenantId
                    )
                    normMetadata = norm.toMetadata()
                    normMetadata["mode"] = normMode
                    get_retrieval_metrics().recordQueryNormalization(
                        matchedSubjects=len(norm.matchedSubjects)
                    )
                    if normMode == "on":
                        searchQuery = norm.expanded
                except Exception as exc:  # noqa: BLE001 - 归一失败不阻断检索主路
                    logger.debug("查询侧别名归一跳过: %s", exc)

            # 元数据过滤只在调用方显式给出时生效；filter 必须进候选集，
            # 不能检索完再在结果上筛（否则 top-k 已被标签外内容占满）。
            filters: Dict[str, Any] = {}
            category = metadata.get("category")
            if isinstance(category, str) and category:
                filters["category"] = category
            tags = metadata.get("tags")
            if isinstance(tags, (list, tuple)) and tags:
                filters["tags"] = [str(t) for t in tags]
            source = metadata.get("source")
            if isinstance(source, str) and source:
                filters["source"] = source
            updated_after = metadata.get("updated_after")
            if isinstance(updated_after, (int, float)):
                filters["updated_after"] = float(updated_after)

            # P0#4：双索引器合一——chat 路走 hybrid 四路（tfidf/bm25/fts/vector）。
            # 向量引擎不可用时辅助路各自降级，主路 tfidf 异常上抛给责任链决定
            # fallback（错误方向是"整级检索失败可被感知"，不是"静默返回空"）。
            from neurova.knowledge import hybrid as _kb_hybrid

            requested = max(1, int(getattr(context, "limit", 10) or 10))
            candidateLimit = min(requested * ADOPTION_CANDIDATE_FACTOR, ADOPTION_CANDIDATE_MAX)
            if candidateLimit < requested:
                candidateLimit = requested
            graphRanks, graphSupport, graphWeight = self._graphRoute(
                context, agent_id, requested
            )
            knowledge_items = _kb_hybrid.hybrid_search_knowledge(
                self._repo,
                user=user,
                query=searchQuery,
                limit=candidateLimit,
                scope="all",
                agent_id=agent_id,
                graphRanks=graphRanks or None,
                graphSupport=graphSupport or None,
                graphWeight=graphWeight,
                **filters,
            )

            (
                knowledge_items,
                _candidateLineage,
                factStore,
                recordInjection,
            ) = self._enrich(knowledge_items)
            # 采纳先验在最终截断前生效；候选窗由上面的 oversample 提供替补位。
            knowledge_items = rerankByAdoption(knowledge_items)[:requested]
            selectedLineage = list(dict.fromkeys(
                str(item["lineage_id"])
                for item in knowledge_items
                if item.get("lineage_id")
            ))
            selectedEntries = list(dict.fromkeys(
                str(item["knowledge_id"])
                for item in knowledge_items
                if item.get("knowledge_id") and not item.get("lineage_id")
            ))
            if recordInjection and factStore is not None and knowledge_items:
                try:
                    from neurova.knowledge.foundation.read_surface import (
                        recordHitsAsInjection,
                    )

                    recordHitsAsInjection(factStore, knowledge_items)
                except Exception as exc:  # noqa: BLE001 - 注入计数失败不阻断检索
                    logger.debug("知识注入计数跳过: %s", exc)
            if selectedEntries:
                recordEntryInjections = getattr(self._repo, "recordEntryInjections", None)
                if callable(recordEntryInjections):
                    try:
                        recordEntryInjections(agent_id or "default", selectedEntries)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("知识条目注入计数跳过: %s", exc)

            # W4 同名多口径（specs/2026-10-30 §5）：只消费既有主体别名表与冲突账，
            # 只产读侧载荷不改排序；任何异常让路，检索主路不受影响。
            ambiguityMeta: Optional[Dict[str, Any]] = None
            if ambiguityMode() != "off":
                try:
                    from neurova.knowledge.foundation.knowledge_facts import (
                        get_knowledge_fact_store,
                    )

                    ambiguityBlock = buildAmbiguityBlock(
                        get_knowledge_fact_store(),
                        str(context.query or ""),
                        knowledge_items,
                        str(agent_id) if agent_id else None,
                        str(metadata.get("tenant_id") or "default"),
                    )
                    if ambiguityBlock is not None:
                        ambiguityMeta = ambiguityBlock.toMetadata()
                except Exception as exc:  # noqa: BLE001 - 歧义计算绝不影响检索返回
                    logger.debug("歧义载荷计算跳过: %s", exc)

            elapsed = time.monotonic() - start_time

            if not knowledge_items:
                if (
                    agent_id and _missCaptureEnabled()
                    and _isCapturableMissQuery(searchQuery)
                    and not (normMetadata and normMetadata.get("matched_subjects"))
                ):
                    # 归一已命中主体的查询不算脱靶（别名已知，缺的是内容本身）
                    _captureRetrievalMiss(
                        str(agent_id),
                        str(metadata.get("tenant_id") or "default"),
                        searchQuery,
                    )
                emptyMetadata: Dict[str, Any] = {
                    "retriever_type": "knowledge", "hits": 0,
                }
                if normMetadata is not None:
                    emptyMetadata["query_normalization"] = normMetadata
                return RetrievalResult(
                    memories=[],
                    source=self._name,
                    quality=0.0,
                    quality_level=RetrievalQuality.FAILED,
                    retrieval_time=elapsed,
                    metadata=emptyMetadata,
                )

            # 归一化为 memories 载荷（与记忆条目字段一致：content/title 等）
            memories = [self._normalize_item(item) for item in knowledge_items]

            # 质量重合按**实跑查询**计：W1 展开追加的规范词才是真正命中正文
            # 的词——按原始查询计，别名驱动的命中重合恒为 0（双重折损）。
            quality = self.get_quality_score(knowledge_items, searchQuery)
            quality_level = self._quality_from_score(quality)

            resultMetadata: Dict[str, Any] = {
                "retriever_type": "knowledge",
                "hits": len(memories),
                "lineage_ids": selectedLineage,
                "knowledge_entry_ids": selectedEntries,
                "knowledge_entry_scores": {
                    str(item["knowledge_id"]): float(item.get("score", 0.0) or 0.0)
                    for item in knowledge_items
                    if item.get("knowledge_id") and not item.get("lineage_id")
                },
                "adoption_rerank": {
                    "requested": requested,
                    "candidate_limit": candidateLimit,
                },
            }
            if normMetadata is not None:
                resultMetadata["query_normalization"] = normMetadata
            if ambiguityMeta is not None:
                resultMetadata["ambiguity"] = ambiguityMeta

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata=resultMetadata,
            )

        except Exception as e:
            logger.error("KnowledgeRetriever failed: %s", e)
            raise

    def get_quality_score(self, results: List[Dict[str, Any]], query: str) -> float:
        """评估知识检索质量：命中数量 + 查询词面重合，两通道取大。

        重合按"查询词在标题/正文中出现"计（分词与 bm25 同源走 tokenize，
        CJK 可分词）；旧实现按空格切词做集合相等，中文查询的重合恒为 0，
        relevance 通道对中文从来是死重。

        通道取大而非加权和一票否决：命中数项（0.6×命中数/10）是语义/向量
        命中的唯一载体，词面重合项（0.75×重合，≥0.4 即独立过门）是精确小
        语料的唯一载体——specs/2026-10-30 §11.4 的缺陷形态是加权和把 1 条
        半重合的别名命中稀释到 0.26 < min_quality(0.3)，整包被链丢弃，
        MoE 的 no_memory 占位（score=1.0）反而当选。
        """
        if not results:
            return 0.0

        count_score = min(len(results) / 10, 1.0)

        from neurova.knowledge.search import tokenize as _tokenize

        query_tokens = set(_tokenize(query or ""))
        relevance_score = 0.0
        if query_tokens:
            total_overlap = 0.0
            n = 0
            for item in results:
                text = (
                    str(item.get("title") or "") + " " + str(item.get("content") or "")
                ).lower()
                overlap = sum(1 for token in query_tokens if token in text)
                total_overlap += overlap / len(query_tokens)
                n += 1
            relevance_score = total_overlap / n if n else 0.0

        quality = max(
            0.6 * count_score + 0.4 * relevance_score,
            0.75 * relevance_score,
        )
        return min(max(quality, 0.0), 1.0)

    def _quality_from_score(self, score: float) -> Any:
        """质量分数 → 等级（与 UnifiedRetrieverAdapter 阈值一致）"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

        if score >= 0.9:
            return RetrievalQuality.EXCELLENT
        if score >= 0.7:
            return RetrievalQuality.GOOD
        if score >= 0.4:
            return RetrievalQuality.FAIR
        if score > 0.0:
            return RetrievalQuality.POOR
        return RetrievalQuality.FAILED

    # P1-9 来源信任分级: 知识条目 source → origin 闭集映射。
    # fail-safe：未知来源一律 untrusted（外部可写面，绝不静默升权）。
    # kb_builder 是 web_reach 抓取入口 → untrusted；agent 自产/结晶 → agent。
    _ORIGIN_SOURCES_OWNER = {"user_upload", "manual", "local_import"}
    _ORIGIN_SOURCES_AGENT = {"agent_generated", "crystallized"}

    @classmethod
    def _map_origin(cls, source: str) -> str:
        s = (source or "").strip().lower()
        if s in cls._ORIGIN_SOURCES_OWNER:
            return "owner"
        if s in cls._ORIGIN_SOURCES_AGENT:
            return "agent"
        return "untrusted"

    @classmethod
    def _normalize_item(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        """单条知识条目 → 检索链 memories 载荷（含 origin 信任级）。

 P1#6：父子分块命中时用
        context_passages（父块上下文，按命中块定位）作为 content，
        而非整篇正文——细粒度命中 + 完整上下文 + 有界长度。
        """
        passages = item.get("context_passages")
        if passages:
            content = "\n".join(passages)
        else:
            content = item.get("content") or item.get("title") or ""
        return {
            "memory_id": item.get("knowledge_id"),
            "content": content,
            "title": item.get("title", ""),
            "category": item.get("category", "knowledge"),
            "tags": item.get("tags", []),
            "source": item.get("source", "knowledge"),
            "confidence": item.get("confidence", 0.5),
            "visibility": item.get("visibility", "private"),
            "knowledge_id": item.get("knowledge_id"),
            "lineage_id": item.get("lineage_id"),
            "fact_id": item.get("lineage_id"),
            "adoption_outcome": item.get("adoption_outcome"),
            "adoption_prior": float(item.get("adoption_prior", 1.0) or 1.0),
            "base_score": float(
                item.get("base_score", item.get("score", 0.0)) or 0.0
            ),
            "score": float(item.get("score", 0.0) or 0.0),
            "origin": cls._map_origin(item.get("source", "")),
        }
