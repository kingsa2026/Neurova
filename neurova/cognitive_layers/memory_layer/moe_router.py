"""
MoE Memory Router — 稀疏门控专家混合记忆路由器

核心思想:
  一个向量索引服务三个目的:
  1. 路由: query_vec vs centroids → Top-K Expert
  2. 兜底: query_vec vs memories → Top-K 记忆
  3. 可塑性: centroid drift (LTP/LTD 更新质心位置)
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neurova.cognitive_layers.memory_layer.unified_vector_store import (
    UnifiedVectorStore,
    cosine_similarity,
    vector_norm,
    vector_normalize,
)

logger = get_logger(__name__)


@dataclass
class QueryTags:
    """从查询中提取的结构化标签"""

    categories: List[Tuple[str, float]] = field(default_factory=list)
    emotions: List[Tuple[str, float]] = field(default_factory=list)
    time_range: Optional[Tuple[str, float]] = None
    entities: List[Tuple[str, float]] = field(default_factory=list)
    memory_types: List[Tuple[str, float]] = field(default_factory=list)
    is_tool_query: bool = False


@dataclass
class ProcessedResults:
    """处理后的结果"""

    independent: List[Dict[str, Any]] = field(default_factory=list)
    conflict_groups: List[Any] = field(default_factory=list)
    evolution_chains: List[List[Dict]] = field(default_factory=list)
    injection_text: str = ""
    has_conflicts: bool = False


class VectorGatingNetwork:
    """
    向量门控网络 — 用 cosine 相似度替代 LLM 标签提取

    核心公式:
      activation_i = cosine(query_vec, centroid_i)
      activated = {i | activation_i >= threshold, i in top_k}
    """

    def __init__(self, vector_store: UnifiedVectorStore, top_k: int = 3, activation_threshold: float = 0.3):
        """
        初始化向量门控网络

        Args:
            vector_store: 向量存储
            top_k: 稀疏激活数量
            activation_threshold: 最低激活阈值
        """
        self.vector_store = vector_store
        self.top_k = top_k
        self.activation_threshold = activation_threshold

    async def route(self, query_vec: List[float]) -> Dict[str, float]:
        """
        向量路由: query_vec vs 所有 Expert 质心

        Args:
            query_vec: 查询向量

        Returns:
            {expert_id: activation_score} (只包含激活的)
        """
        centroids = self.vector_store.get_expert_centroids()

        # 归一化查询向量
        norm = vector_norm(query_vec)
        if norm > 0:
            query_vec = vector_normalize(query_vec)

        # 计算 cosine 相似度
        scores = {}
        for expert_id, centroid in centroids.items():
            score = cosine_similarity(query_vec, centroid)
            if score >= self.activation_threshold:
                scores[expert_id] = score

        # Top-K 稀疏选择
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_scores[: self.top_k])


class ExpertDrilldownRetriever:
    """
    专家内部下钻检索器

    检索流程:
      L0: SQL 精确索引 (<1ms)
      L1: 结构化下钻 (1-10ms)
      L2: TF-IDF 重排 (10-50ms)
      L3: 向量兜底 (100-500ms)
    """

    def __init__(
        self,
        expert_def: Dict[str, Any],
        store: Any,
        vector_store: Optional[UnifiedVectorStore] = None,
        cache_max_size: Optional[int] = None,
    ):
        """
        初始化下钻检索器

        Args:
            expert_def: Expert 定义
            store: 存储层
            vector_store: 向量存储（用于 L3 兜底）
            cache_max_size: L0 查询缓存上限（None 时读 vector_search.cache_max_size）
        """
        self.expert_def = expert_def
        self.store = store
        self.vector_store = vector_store
        self._l0_cache: Dict[str, List] = {}
        # L0 查询缓存上限配置化（memory-settings 配置页）:
        # vector_search.cache_max_size，默认 1000
        if cache_max_size is None:
            from neurova.cognitive_layers.memory_layer.settings_config import (
                get_memory_settings,
            )

            cache_max_size = int(
                get_memory_settings().get("vector_search.cache_max_size", 1000)
            )
        self._l0_cache_max_size = max(1, int(cache_max_size))

    def _cache_l0(self, key: str, value: List) -> None:
        """写入 L0 缓存，超过上限时 FIFO 淘汰最旧条目"""
        if len(self._l0_cache) >= self._l0_cache_max_size:
            oldest = next(iter(self._l0_cache))
            self._l0_cache.pop(oldest, None)
        self._l0_cache[key] = value

    async def retrieve(self, query: str, query_vec: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        """
        递进检索

        Args:
            query: 查询文本
            query_vec: 查询向量
            limit: 返回数量限制

        Returns:
            排序后的记忆列表
        """
        candidates = None

        # === Layer 0: 标签精确索引 (<1ms) ===
        cache_key = self._l0_cache_key(query_vec)
        if cache_key in self._l0_cache:
            candidates = self._l0_cache[cache_key]
            if len(candidates) >= limit:
                return candidates[:limit]

        if candidates is None:
            candidates = self._layer0_exact_index()
            self._cache_l0(cache_key, candidates)
            if len(candidates) >= limit * 2:
                return self._rank_and_limit(candidates, query, limit)

        # === Layer 1: 结构化下钻 (1-10ms) ===
        candidates = self._layer1_structured_drilldown(candidates)
        if len(candidates) >= limit:
            return self._rank_and_limit(candidates, query, limit)

        # === Layer 2: TF-IDF 重排 (10-50ms) ===
        candidates = self._layer2_tfidf_rerank(candidates, query)
        if len(candidates) >= limit:
            return candidates[:limit]

        # === Layer 3: 向量兜底 (100-500ms) ===
        return await self._layer3_vector_fallback(query_vec, limit)

    def _l0_cache_key(self, query_vec: List[float]) -> str:
        """生成 L0 缓存键（兼容 list / numpy 数组——onnx encode 返回 list）"""
        # 使用向量前 10 维作为缓存键
        head = query_vec[:10]
        tolist = getattr(head, "tolist", None)
        return str(tolist() if tolist else list(head))

    def _layer0_exact_index(self) -> List[Dict]:
        """Layer 0: 利用 SQL 复合索引做精确标签匹配"""
        conditions = []
        params = {}

        if "category" in self.expert_def:
            conditions.append("category = :category")
            params["category"] = self.expert_def["category"]

        if "lifecycle_stage" in self.expert_def:
            conditions.append("lifecycle_stage = :stage")
            params["stage"] = self.expert_def["lifecycle_stage"]

        if "is_crystallized" in self.expert_def:
            conditions.append("is_crystallized = :crystallized")
            params["crystallized"] = int(self.expert_def["is_crystallized"])

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY temperature DESC LIMIT 200"

        try:
            result = self.store.execute(sql, params)
            return result.fetchall() if hasattr(result, "fetchall") else []
        except Exception as e:
            logger.warning("Layer 0 查询失败: %s", e)
            return []

    def _layer1_structured_drilldown(self, candidates: List[Dict], min_floor: int = 5) -> List[Dict]:
        """Layer 1: 逐层过滤"""
        drill_steps = [
            ("emotion_tags", self._filter_emotion),
            ("temperature", self._filter_temperature),
        ]

        for step_name, filter_fn in drill_steps:
            if len(candidates) <= min_floor:
                break
            candidates = filter_fn(candidates)

        return candidates

    def _filter_emotion(self, candidates: List[Dict]) -> List[Dict]:
        """按情感标签过滤"""
        # 简单实现：保留高情感分数的记忆
        return [c for c in candidates if float(c.get("emotion_score", 0)) > 0.3 or c.get("emotion_tags") != "[]"]

    def _filter_temperature(self, candidates: List[Dict]) -> List[Dict]:
        """按温度过滤"""
        # 按温度排序，保留前 50%
        sorted_candidates = sorted(candidates, key=lambda x: float(x.get("temperature", 50)), reverse=True)
        return sorted_candidates[: max(len(sorted_candidates) // 2, 5)]

    def _layer2_tfidf_rerank(self, candidates: List[Dict], query: str) -> List[Dict]:
        """Layer 2: TF-IDF 关键词重排"""
        if not candidates:
            return []

        # 简单关键词匹配
        query_lower = query.lower()
        scored = []
        for mem in candidates:
            content = mem.get("content", "").lower()
            # 计算关键词重叠
            overlap = sum(1 for word in query_lower.split() if word in content)
            score = overlap / max(len(query_lower.split()), 1)
            scored.append((mem, score))

        # 按分数排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return [mem for mem, _ in scored]

    async def _layer3_vector_fallback(self, query_vec: List[float], limit: int) -> List[Dict]:
        """Layer 3: 向量兜底"""
        if not self.vector_store:
            return []

        return self.vector_store.search_in_expert(query="", expert_def=self.expert_def, limit=limit)

    def _rank_and_limit(self, candidates: List[Dict], query: str, limit: int) -> List[Dict]:
        """排序并限制数量"""
        # 简单实现：按温度排序
        sorted_candidates = sorted(candidates, key=lambda x: float(x.get("temperature", 50)), reverse=True)
        return sorted_candidates[:limit]


class MoEMemoryRouter:
    """
    MoE 记忆路由器 — 神经元节点层的核心组件

    作为稀疏门控专家混合记忆路由器，模拟大脑的功能特化神经元集群。
    通过向量门控网络（突触连接层）选择性激活专家神经元节点，
    每个专家节点内部通过树突输入层（L0-L3）进行渐进式检索。

    神经隐喻:
    - 稀疏激活: 像大脑的稀疏编码原则，只激活最相关的专家
    - 质心漂移: 像突触可塑性（LTP/LTD），根据使用模式调整连接强度
    - 缓冲区刷新: 像记忆巩固过程，将短期记忆转化为长期记忆
    - 冲突检测: 像前额叶的认知控制，监控和解决记忆冲突

    检索流程（信号传导路径）:
      Step 1: 向量编码 (Single Encode) — 将查询转换为神经表示
      Step 2: 向量路由 (Vector Gating) — 通过突触连接选择激活的神经元节点
      Step 3: 专家内部下钻 (Expert Drill-down) — 每个激活的神经元节点内部进行树突级检索
      Step 4: 结果评估 — 轴突输出层的信号整合
      Step 5: 全数据库向量兜底 — 海马体的全局搜索
      Step 6: 无记忆处理 — 默认响应机制
    """

    NO_MEMORY_HINT = {
        "id": "no_memory",
        "content": "系统提示: 未找到与当前查询相关的记忆。请基于通用知识回答，并告知用户这是基于通用知识而非个人记忆的回答。",
        "score": 1.0,
        "is_hint": True,
        "category": "hint",
    }

    def __init__(
        self,
        experts: Dict[str, Dict[str, Any]],
        storage: Any,
        vector_store: Optional[UnifiedVectorStore] = None,
        backend: str = "tfidf",
        top_k: int = 3,
        activation_threshold: float = 0.3,
        min_expert_results: int = 3,
        min_relevance: float = 0.4,
    ):
        """
        初始化 MoE 路由器

        Args:
            experts: Expert 定义字典
            storage: 存储层
            vector_store: 向量存储（可选，自动创建）
            backend: 向量后端
            top_k: 激活专家数量
            activation_threshold: 激活阈值
            min_expert_results: Expert 内部最少结果数
            min_relevance: 最低相关性分数
        """
        self.experts = experts
        self.storage = storage
        self.vector_store = vector_store or UnifiedVectorStore(backend=backend)
        self.top_k = top_k
        self.activation_threshold = activation_threshold
        self.min_expert_results = min_expert_results
        self.min_relevance = min_relevance

        # 初始化门控网络
        self.gating_network = VectorGatingNetwork(
            vector_store=self.vector_store,
            top_k=top_k,
            activation_threshold=activation_threshold,
        )

        # 初始化质心
        if not self.vector_store.get_expert_centroids():
            self.vector_store.initialize_centroids(experts)

        logger.info("MoEMemoryRouter 初始化完成，%s 个专家，top_k=%s", len(experts), top_k)

    async def retrieve(self, query: str, limit: int = 5, progress_cb=None) -> List[Dict[str, Any]]:
        """
        完整检索流程

        Args:
            query: 查询文本
            limit: 返回数量限制
            progress_cb: 可选进度回调 (event: Dict) -> None，
                         用于 UI 实时显示检索过程（不落盘）

        Returns:
            排序后的记忆列表
        """

        def _emit(event: Dict[str, Any]) -> None:
            if progress_cb:
                try:
                    progress_cb(event)
                except Exception:  # noqa: BLE001 - 进度回调失败不阻断检索
                    pass

        # Step 1: 向量编码
        query_vec = self.vector_store.encode(query)

        # Step 2: 向量路由
        activated_experts = await self.gating_network.route(query_vec)
        logger.debug("激活专家: %s", activated_experts)
        _emit({"stage": "moe_gate", "experts": list(activated_experts.keys())})

        # Step 3: 专家内部下钻
        all_results = []
        for expert_id, activation in activated_experts.items():
            expert_def = self.experts.get(expert_id, {})
            retriever = ExpertDrilldownRetriever(
                expert_def=expert_def,
                store=self.storage,
                vector_store=self.vector_store,
            )

            expert_results = await retriever.retrieve(query, query_vec, limit=limit)
            _emit({"stage": "moe_expert", "expert": expert_id, "count": len(expert_results)})

            # 按激活权重加权
            for r in expert_results:
                r["score"] = float(r.get("score", 0.5)) * activation
                r["expert_id"] = expert_id

            all_results.extend(expert_results)

        # Step 4: 结果评估
        if not self._should_fallback_to_full_db(all_results):
            # 按分数排序，返回 top-limit
            all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            _emit({"stage": "moe_done", "count": len(all_results[:limit]), "fallback": False})
            return all_results[:limit]

        # Step 5: 全数据库兜底
        logger.debug("Expert 内部结果不足，启动全数据库兜底")
        full_db_results = self.vector_store.search(query, limit=limit * 2)
        if full_db_results:
            _emit({"stage": "moe_done", "count": len(full_db_results[:limit]), "fallback": True})
            return full_db_results[:limit]

        # Step 6: 无记忆处理
        logger.debug("全数据库兜底无结果，返回无记忆提示")
        _emit({"stage": "moe_done", "count": 0, "fallback": True})
        return [self.NO_MEMORY_HINT]

    def _should_fallback_to_full_db(self, results: List[Dict]) -> bool:
        """判断是否需要全数据库兜底"""
        if not results:
            return True
        if len(results) < self.min_expert_results:
            return True
        max_score = max(r.get("score", 0) for r in results)
        if max_score < self.min_relevance:
            return True
        return False
