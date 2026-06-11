"""
Neurova 统一记忆检索引擎 — 多维融合 + 意图钻取

架构：
  Phase 1: 多维融合召回 — 5通道并行，多信号加权排序
  Phase 2: 意图驱动钻取 — 从种子记忆沿关系路径定向深入

核心理念：
  不是"搜索"，而是"浮现"——热的、情感的、相关的记忆自然浮现
  不是"遍历"，而是"钻探"——有意图、有方向、可解释地深入
"""

from dataclasses import dataclass, field
import datetime
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ────── Enums ──────

class RecallChannel(Enum):
    """检索通道"""
    TEMPERATURE = "temperature"   # 温度通道（热记忆优先）
    TEXT = "text"                 # 文本通道（语义相似度）
    CATEGORY = "category"        # 分类通道（同类别记忆）
    GRAPH = "graph"              # 图通道（关系图谱）
    EMOTION = "emotion"          # 情感通道（情感相似度）
    VOICE = "voice"              # 语音通道（语音转写记忆）


class DrillIntent(Enum):
    """钻取意图"""
    EXPLORE = "explore"           # 探索（发现新知识）
    DEEPEN = "deepen"            # 深化（深入理解）
    CONNECT = "connect"          # 连接（建立关联）
    CONTRAST = "contrast"        # 对比（寻找差异）
    VALIDATE = "validate"        # 验证（确认事实）


class QueryIntent(Enum):
    """查询意图 — 决定检索策略选择"""
    FACTUAL = "factual"           # 事实查询（精确匹配）
    TEMPORAL = "temporal"         # 时间查询（时间敏感）
    CAUSAL = "causal"             # 因果查询（因果推理）
    COMPARATIVE = "comparative"   # 比较查询（多维对比）
    EXPLORATORY = "exploratory"   # 探索查询（广泛发现）
    UNKNOWN = "unknown"           # 未知意图


class QueryIntentDetector:
    """查询意图检测器

    基于关键词匹配检测查询意图，支持中英文。
    每个意图维护一组关键词，通过计分选择最佳匹配。
    """

    INTENT_KEYWORDS = {
        QueryIntent.TEMPORAL: [
            # 英文
            "when", "time", "date", "before", "after", "during", "recently",
            "lately", "ago", "last", "next", "today", "yesterday", "tomorrow",
            "latest", "recent", "history", "timeline", "schedule",
            # 中文
            "什么时候", "时间", "日期", "之前", "之后", "期间", "最近",
            "以来", "昨天", "今天", "明天", "上次", "下次", "历史", "时间线",
        ],
        QueryIntent.CAUSAL: [
            # 英文
            "why", "because", "cause", "reason", "result", "lead to", "due to",
            "effect", "consequence", "impact", "how did", "what caused",
            "therefore", "hence", "consequently",
            # 中文
            "为什么", "原因", "导致", "因为", "结果", "影响", "因素",
            "故而", "因此", "之所以", "造成", "引发", "致使",
        ],
        QueryIntent.COMPARATIVE: [
            # 英文
            "compare", "difference", "vs", "versus", "better", "worse",
            "similar", "different", "alternative", "which", "prefer",
            "advantage", "disadvantage", "pros", "cons", "trade-off",
            # 中文
            "比较", "对比", "区别", "差异", "哪个", "更好", "更差",
            "类似", "不同", "替代", "优势", "劣势", "优缺点", "权衡",
        ],
        QueryIntent.EXPLORATORY: [
            # 英文
            "explore", "discover", "find", "search", "look for", "what",
            "how", "tell me about", "describe", "explain", "overview",
            "introduction", "learn", "understand", "know about",
            # 中文
            "什么是", "介绍", "描述", "解释", "概述", "了解", "探索",
            "发现", "查找", "搜索", "学习", "理解", "知道", "知识",
        ],
        QueryIntent.FACTUAL: [
            # 英文
            "who", "where", "how many", "how much", "exact", "specific",
            "define", "definition", "name", "list", "count",
            # 中文
            "谁", "哪里", "多少", "具体", "定义", "名称", "列表",
            "数量", "确切", "精确", "几个", "哪些",
        ],
    }

    def detect_intent(self, query: str) -> QueryIntent:
        """检测查询意图

        Args:
            query: 查询文本

        Returns:
            QueryIntent: 检测到的意图
        """
        if not query or not query.strip():
            return QueryIntent.UNKNOWN

        scores = {}
        for intent, keywords in self.INTENT_KEYWORDS.items():
            score = self._score_keywords(query, keywords)
            scores[intent] = score

        best_intent = max(scores, key=scores.get)
        if scores[best_intent] > 0:
            return best_intent

        return QueryIntent.EXPLORATORY  # 默认探索意图

    def get_intent_confidence(self, query: str, intent: QueryIntent) -> float:
        """获取指定意图的置信度

        Args:
            query: 查询文本
            intent: 意图类型

        Returns:
            float: 置信度 (0.0 - 1.0)
        """
        if not query or not query.strip():
            return 0.0

        keywords = self.INTENT_KEYWORDS.get(intent, [])
        if not keywords:
            return 0.0

        score = self._score_keywords(query, keywords)

        # 计算所有意图的总分用于归一化
        total_score = sum(
            self._score_keywords(query, kw)
            for kw in self.INTENT_KEYWORDS.values()
        )

        if total_score == 0:
            return 0.0

        # 置信度 = 该意图得分 / 总分（归一化）
        raw_confidence = score / total_score

        # 多关键词匹配提升置信度
        matched_count = sum(
            1 for kw in keywords
            if kw.lower() in query.lower()
        )
        boost = min(0.3, matched_count * 0.1)

        return min(1.0, raw_confidence + boost)

    @staticmethod
    def _score_keywords(query: str, keywords: List[str]) -> int:
        """计算查询与关键词列表的匹配分数

        Args:
            query: 查询文本
            keywords: 关键词列表

        Returns:
            int: 匹配分数
        """
        query_lower = query.lower()
        score = 0
        for keyword in keywords:
            if keyword.lower() in query_lower:
                # 长关键词权重更高
                score += len(keyword)
        return score


class IntentAwareRecallStrategy:
    """意图感知检索策略

    为每种查询意图维护独立的通道权重和检索参数，
    使检索引擎能根据意图自适应调整检索行为。
    """

    # 意图 → 通道权重（总和 = 1.0）
    INTENT_CHANNEL_WEIGHTS: Dict[QueryIntent, Dict[RecallChannel, float]] = {
        QueryIntent.FACTUAL: {
            RecallChannel.TEMPERATURE: 0.20,
            RecallChannel.TEXT: 0.40,
            RecallChannel.CATEGORY: 0.20,
            RecallChannel.GRAPH: 0.10,
            RecallChannel.EMOTION: 0.05,
            RecallChannel.VOICE: 0.05,
        },
        QueryIntent.TEMPORAL: {
            RecallChannel.TEMPERATURE: 0.50,
            RecallChannel.TEXT: 0.15,
            RecallChannel.CATEGORY: 0.10,
            RecallChannel.GRAPH: 0.10,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.05,
        },
        QueryIntent.CAUSAL: {
            RecallChannel.TEMPERATURE: 0.10,
            RecallChannel.TEXT: 0.15,
            RecallChannel.CATEGORY: 0.10,
            RecallChannel.GRAPH: 0.50,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.05,
        },
        QueryIntent.COMPARATIVE: {
            RecallChannel.TEMPERATURE: 0.10,
            RecallChannel.TEXT: 0.25,
            RecallChannel.CATEGORY: 0.35,
            RecallChannel.GRAPH: 0.15,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.05,
        },
        QueryIntent.EXPLORATORY: {
            RecallChannel.TEMPERATURE: 0.20,
            RecallChannel.TEXT: 0.25,
            RecallChannel.CATEGORY: 0.15,
            RecallChannel.GRAPH: 0.20,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.10,
        },
        QueryIntent.UNKNOWN: {
            RecallChannel.TEMPERATURE: 0.25,
            RecallChannel.TEXT: 0.30,
            RecallChannel.CATEGORY: 0.15,
            RecallChannel.GRAPH: 0.10,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.10,
        },
    }

    # 意图 → 检索参数
    INTENT_PARAMS: Dict[QueryIntent, Dict[str, Any]] = {
        QueryIntent.FACTUAL: {
            "limit": 5,
            "min_score": 0.3,
        },
        QueryIntent.TEMPORAL: {
            "limit": 10,
            "min_score": 0.2,
            "time_decay": 0.8,
        },
        QueryIntent.CAUSAL: {
            "limit": 8,
            "min_score": 0.2,
            "max_depth": 4,
        },
        QueryIntent.COMPARATIVE: {
            "limit": 10,
            "min_score": 0.2,
            "diversity": 0.7,
        },
        QueryIntent.EXPLORATORY: {
            "limit": 15,
            "min_score": 0.1,
            "serendipity": 0.3,
        },
        QueryIntent.UNKNOWN: {
            "limit": 10,
            "min_score": 0.2,
        },
    }

    def __init__(self):
        # 运行时可覆盖的权重（深拷贝默认值）
        self._overrides: Dict[QueryIntent, Dict[RecallChannel, float]] = {}

    def get_channel_weights(self, intent: QueryIntent) -> Dict[RecallChannel, float]:
        """获取意图对应的通道权重

        Args:
            intent: 查询意图

        Returns:
            Dict[RecallChannel, float]: 通道权重映射
        """
        if intent in self._overrides:
            return self._overrides[intent]
        return dict(self.INTENT_CHANNEL_WEIGHTS.get(intent, self.INTENT_CHANNEL_WEIGHTS[QueryIntent.UNKNOWN]))

    def get_retrieval_params(self, intent: QueryIntent) -> Dict[str, Any]:
        """获取意图对应的检索参数

        Args:
            intent: 查询意图

        Returns:
            Dict[str, Any]: 检索参数
        """
        return dict(self.INTENT_PARAMS.get(intent, self.INTENT_PARAMS[QueryIntent.UNKNOWN]))

    def update_channel_weights(self, intent: QueryIntent, weights: Dict[RecallChannel, float]) -> None:
        """动态更新指定意图的通道权重

        Args:
            intent: 查询意图
            weights: 新的通道权重映射
        """
        self._overrides[intent] = dict(weights)
        logger.debug(f"更新意图 {intent.value} 的通道权重: {weights}")


# ────── Data Models ──────

@dataclass
class RecalledMemory:
    """召回的记忆"""
    memory_id: str = ""
    content: str = ""
    score: float = 0.0
    channel: RecallChannel = RecallChannel.TEXT
    metadata: Dict[str, Any] = field(default_factory=dict)
    recalled_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        包含 channel_scores（如果有）用于前端 NeRF 可视化。
        """
        result = {
            "memory_id": self.memory_id,
            "content": self.content,
            "score": self.score,
            "channel": self.channel.value,
            "metadata": self.metadata,
            "recalled_at": self.recalled_at.isoformat(),
        }
        # 从 metadata 中提取 channel_scores（NeRF 体渲染数据）
        if self.metadata and "channel_scores" in self.metadata:
            result["channel_scores"] = self.metadata["channel_scores"]
            result["nerf_rendered"] = self.metadata.get("nerf_rendered", False)
        return result


@dataclass
class RecallResult:
    """检索结果"""
    query: str = ""
    intent: QueryIntent = QueryIntent.UNKNOWN
    recalled_memories: List[RecalledMemory] = field(default_factory=list)
    total_score: float = 0.0
    phase1_duration_ms: float = 0.0
    phase2_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent.value,
            "recalled_memories": [m.to_dict() for m in self.recalled_memories],
            "total_score": self.total_score,
            "phase1_duration_ms": self.phase1_duration_ms,
            "phase2_duration_ms": self.phase2_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "metadata": self.metadata,
        }


# ────── Main Engine ──────

class NeurovaRecallEngine:
    """
    Neurova 统一记忆检索引擎
    
    多维融合召回 + 意图驱动钻取
    
    fusion_mode:
        "legacy" — 传统加权求和: score × weight × time_decay
        "nerf"   — NeRF 体渲染: Σ T_i · σ_i · c_i · w_i（透射率加权积分）
    """
    
    def __init__(
        self,
        memory_manager: Any = None,
        max_workers: int = 4,
        timeout_seconds: float = 10.0,
        intent_detector: Optional[QueryIntentDetector] = None,
        intent_strategy: Optional[IntentAwareRecallStrategy] = None,
        use_plugins: bool = False,
        registry: Any = None,
        fusion_mode: str = "legacy",
        density_scale: float = 1.0,
    ):
        """
        初始化检索引擎

        Args:
            memory_manager: 记忆管理器
            max_workers: 最大并行工作线程数
            timeout_seconds: 超时时间（秒）
            intent_detector: 查询意图检测器（可选，默认自动创建）
            intent_strategy: 意图检索策略（可选，默认自动创建）
            use_plugins: 是否使用插件化通道（Phase 1）
            registry: ChannelRegistry 实例（use_plugins=True 时使用）
            fusion_mode: 融合模式 "legacy" 或 "nerf"
            density_scale: 体渲染密度缩放因子（nerf 模式专用）
        """
        self.memory_manager = memory_manager
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        self.use_plugins = use_plugins
        self.fusion_mode = fusion_mode

        # 意图感知组件
        self.intent_detector = intent_detector or QueryIntentDetector()
        self.intent_strategy = intent_strategy or IntentAwareRecallStrategy()

        # 插件化通道注册表
        self._registry = registry
        if use_plugins and self._registry is None:
            from .channels.registry import get_channel_registry
            self._registry = get_channel_registry()

        # 体渲染器（nerf 模式）
        self._volume_renderer = None
        if fusion_mode == "nerf":
            from .volume_renderer import VolumeRenderer
            self._volume_renderer = VolumeRenderer(density_scale=density_scale)

        # 默认通道权重（无意图时的 fallback）
        self._channel_weights = {
            RecallChannel.TEMPERATURE: 0.25,
            RecallChannel.TEXT: 0.30,
            RecallChannel.CATEGORY: 0.15,
            RecallChannel.GRAPH: 0.10,
            RecallChannel.EMOTION: 0.10,
            RecallChannel.VOICE: 0.10,
        }

        mode = "插件模式" if use_plugins else "传统模式"
        fusion_desc = "体渲染" if fusion_mode == "nerf" else "加权求和"
        logger.info(f"NeurovaRecallEngine 初始化完成（{mode}，{fusion_desc}融合，含意图感知）")

    def update_fusion_settings(
        self,
        fusion_mode: Optional[str] = None,
        density_scale: Optional[float] = None,
        channel_densities: Optional[Dict[str, float]] = None,
    ) -> None:
        """运行时更新体渲染融合设置

        Args:
            fusion_mode: "legacy" 或 "nerf"
            density_scale: 密度缩放因子 (0.1 ~ 5.0)
            channel_densities: 各通道密度 {"text": 0.9, ...}
        """
        if fusion_mode is not None and fusion_mode in ("legacy", "nerf"):
            self.fusion_mode = fusion_mode
            if fusion_mode == "nerf" and self._volume_renderer is None:
                from .volume_renderer import VolumeRenderer
                self._volume_renderer = VolumeRenderer(
                    density_scale=density_scale or 1.0
                )

        if density_scale is not None and self._volume_renderer is not None:
            self._volume_renderer.density_scale = max(0.1, min(5.0, density_scale))

        if channel_densities and self._volume_renderer is not None:
            for ch, val in channel_densities.items():
                if ch in self._volume_renderer.channel_densities:
                    self._volume_renderer.channel_densities[ch] = max(0.0, min(1.0, float(val)))

        logger.info(f"NeRF 融合设置已更新: mode={self.fusion_mode}")

    def get_fusion_settings(self) -> Dict[str, Any]:
        """获取当前融合设置"""
        settings: Dict[str, Any] = {
            "fusion_mode": self.fusion_mode,
            "density_scale": 1.0,
            "channel_densities": {},
        }
        if self._volume_renderer is not None:
            settings["density_scale"] = self._volume_renderer.density_scale
            settings["channel_densities"] = dict(self._volume_renderer.channel_densities)
        else:
            from .volume_renderer import VolumeRenderer
            settings["channel_densities"] = dict(VolumeRenderer.DEFAULT_CHANNEL_DENSITY)
        return settings

    def recall(
        self,
        query: str,
        intent: DrillIntent = DrillIntent.EXPLORE,
        limit: int = 20,
        channels: Optional[List[RecallChannel]] = None,
        query_intent: Optional[QueryIntent] = None,
    ) -> RecallResult:
        """
        检索记忆（两阶段 + 意图感知）

        Args:
            query: 查询文本
            intent: 钻取意图（Phase 2）
            limit: 返回数量限制
            channels: 启用的通道
            query_intent: 查询意图（Phase 1 策略选择），None 时自动检测

        Returns:
            检索结果（metadata 包含 query_intent 和 intent_confidence）
        """
        start_time = time.time()

        # ── 意图检测 ──
        if query_intent is None:
            query_intent = self.intent_detector.detect_intent(query)

        intent_confidence = self.intent_detector.get_intent_confidence(query, query_intent)

        # 获取意图特定的通道权重和检索参数
        channel_weights = self.intent_strategy.get_channel_weights(query_intent)
        retrieval_params = self.intent_strategy.get_retrieval_params(query_intent)

        # 意图覆盖的 limit
        effective_limit = retrieval_params.get("limit", limit)

        # 确定启用的通道
        if channels is None:
            channels = list(RecallChannel)

        # Phase 1: 多维融合召回（使用意图感知的权重）
        phase1_start = time.time()
        phase1_results = self._phase1_multichannel_recall(
            query, channels, effective_limit * 2, channel_weights=channel_weights
        )
        phase1_duration = (time.time() - phase1_start) * 1000

        # Phase 2: 意图驱动钻取
        phase2_start = time.time()
        phase2_results = self._phase2_drill(query, intent, phase1_results, effective_limit)
        phase2_duration = (time.time() - phase2_start) * 1000

        total_duration = (time.time() - start_time) * 1000

        # 计算总分
        total_score = sum(m.score for m in phase2_results)

        return RecallResult(
            query=query,
            intent=query_intent,
            recalled_memories=phase2_results,
            total_score=total_score,
            phase1_duration_ms=phase1_duration,
            phase2_duration_ms=phase2_duration,
            total_duration_ms=total_duration,
            metadata={
                "channels_used": [c.value for c in channels],
                "limit": effective_limit,
                "query_intent": query_intent.value,
                "intent_confidence": intent_confidence,
                "retrieval_params": retrieval_params,
            },
        )
    
    def recall_flat(
        self,
        query: str,
        limit: int = 20,
        channels: Optional[List[RecallChannel]] = None,
        query_intent: Optional[QueryIntent] = None,
    ) -> List[RecalledMemory]:
        """
        平坦检索（不进行意图钻取）

        Args:
            query: 查询文本
            limit: 返回数量限制
            channels: 启用的通道
            query_intent: 查询意图，None 时自动检测

        Returns:
            召回的记忆列表
        """
        if channels is None:
            channels = list(RecallChannel)

        # 意图检测
        if query_intent is None:
            query_intent = self.intent_detector.detect_intent(query)

        channel_weights = self.intent_strategy.get_channel_weights(query_intent)
        retrieval_params = self.intent_strategy.get_retrieval_params(query_intent)
        effective_limit = retrieval_params.get("limit", limit)

        results = self._phase1_multichannel_recall(
            query, channels, effective_limit, channel_weights=channel_weights
        )

        # 按分数排序
        results.sort(key=lambda m: m.score, reverse=True)

        return results[:effective_limit]
    
    def _run_with_timeout(self, func, *args, **kwargs) -> Any:
        """带超时执行"""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=self.timeout_seconds)
            except TimeoutError:
                logger.warning(f"执行超时: {func.__name__}")
                return []
    
    def _phase1_multichannel_recall(
        self,
        query: str,
        channels: List[RecallChannel],
        limit: int,
        channel_weights: Optional[Dict[RecallChannel, float]] = None,
    ) -> List[RecalledMemory]:
        """
        Phase 1: 多维融合召回

        Args:
            query: 查询文本
            channels: 启用的通道
            limit: 返回数量限制
            channel_weights: 意图感知的通道权重（可选，None 时使用默认权重）

        Returns:
            召回的记忆列表
        """
        # 插件模式：通过 ChannelRegistry 调用通道
        if self.use_plugins and self._registry is not None:
            return self._phase1_plugin_recall(query, channels, limit, channel_weights)

        # 传统模式：直接调用硬编码通道
        all_results: List[RecalledMemory] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}

            for channel in channels:
                if channel == RecallChannel.TEMPERATURE:
                    futures[executor.submit(self._channel_temperature, query, limit)] = channel
                elif channel == RecallChannel.TEXT:
                    futures[executor.submit(self._channel_text, query, limit)] = channel
                elif channel == RecallChannel.CATEGORY:
                    futures[executor.submit(self._channel_category, query, limit)] = channel
                elif channel == RecallChannel.GRAPH:
                    futures[executor.submit(self._channel_graph, query, limit)] = channel
                elif channel == RecallChannel.EMOTION:
                    futures[executor.submit(self._channel_emotion, query, limit)] = channel
                elif channel == RecallChannel.VOICE:
                    futures[executor.submit(self._channel_voice, query, limit)] = channel

            for future in as_completed(futures):
                channel = futures[future]
                try:
                    results = future.result(timeout=self.timeout_seconds)
                    all_results.extend(results)
                except Exception as e:
                    logger.error(f"通道 {channel.value} 检索失败: {e}")

        deduplicated = self._deduplicate_results(all_results)

        if self.fusion_mode == "nerf" and self._volume_renderer is not None:
            deduplicated = self._nerf_fusion(deduplicated, channel_weights, limit)
        else:
            weights = channel_weights if channel_weights else self._channel_weights
            for memory in deduplicated:
                memory.score = self._fusion_score(memory, query, channel_weights=weights)
            deduplicated.sort(key=lambda m: m.score, reverse=True)
            deduplicated = deduplicated[:limit]

        return deduplicated

    def _phase1_plugin_recall(
        self,
        query: str,
        channels: List[RecallChannel],
        limit: int,
        channel_weights: Optional[Dict[RecallChannel, float]] = None,
    ) -> List[RecalledMemory]:
        """插件模式：通过 ChannelRegistry 执行通道检索"""
        import asyncio
        from .channels.base import ChannelResult

        # 映射 RecallChannel → 通道名称
        channel_name_map = {rc.value: rc.value for rc in RecallChannel}

        all_results: List[RecalledMemory] = []
        weights = channel_weights if self._channel_weights else {}

        # 获取启用的插件通道
        enabled_names = {rc.value for rc in channels}
        plugin_channels = [
            ch for ch in self._registry.get_active()
            if ch.metadata.name in enabled_names
        ]

        if not plugin_channels:
            return []

        # 异步并行执行
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def _run_all():
            tasks = []
            for ch in plugin_channels:
                ch_weight = weights.get(RecallChannel(ch.metadata.name), 1.0)
                tasks.append(ch.retrieve(
                    query=query, limit=limit, weight=ch_weight,
                    memory_manager=self.memory_manager,
                ))
            return await asyncio.gather(*tasks, return_exceptions=True)

        results_list = loop.run_until_complete(_run_all())

        for channel_results in results_list:
            if isinstance(channel_results, Exception):
                logger.warning(f"插件通道执行异常: {channel_results}")
                continue
            if not isinstance(channel_results, list):
                continue
            for cr in channel_results:
                if not isinstance(cr, ChannelResult):
                    continue
                all_results.append(RecalledMemory(
                    memory_id=cr.memory_id,
                    content=cr.content,
                    score=cr.score,
                    channel=RecallChannel(cr.channel) if cr.channel in channel_name_map else RecallChannel.TEXT,
                    metadata=cr.metadata,
                ))

        deduplicated = self._deduplicate_results(all_results)
        for memory in deduplicated:
            memory.score = self._fusion_score(memory, query, channel_weights=weights)

        deduplicated.sort(key=lambda m: m.score, reverse=True)
        return deduplicated[:limit]
    
    def _channel_temperature(self, query: str, limit: int) -> List[RecalledMemory]:
        """温度通道（热记忆优先）"""
        # 简化实现
        logger.debug(f"温度通道检索: {query}")
        return []
    
    def _channel_text(self, query: str, limit: int) -> List[RecalledMemory]:
        """文本通道（语义相似度）"""
        # 简化实现
        logger.debug(f"文本通道检索: {query}")
        return []
    
    def _channel_category(self, query: str, limit: int) -> List[RecalledMemory]:
        """分类通道（同类别记忆）"""
        # 简化实现
        logger.debug(f"分类通道检索: {query}")
        return []
    
    def _channel_graph(self, query: str, limit: int) -> List[RecalledMemory]:
        """图通道（关系图谱）"""
        # 简化实现
        logger.debug(f"图通道检索: {query}")
        return []
    
    def _channel_emotion(self, query: str, limit: int) -> List[RecalledMemory]:
        """情感通道（情感相似度）
        
        检索与查询文本情感相似的记忆：
        1. 分析查询文本的情感
        2. 搜索相同情感类型的记忆
        3. 按情感强度排序
        """
        logger.debug(f"情感通道检索: {query}")
        
        if not self.memory_manager:
            return []
        
        try:
            # 分析查询情感
            from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
            emotion_module = getattr(self.memory_manager, 'emotion_module', None)
            if not emotion_module:
                return []
            
            # 分析查询情感
            emotion_state = emotion_module.analyze_text_emotion(query)
            if not emotion_state or emotion_state.primary_emotion.value == "neutral":
                return []
            
            # 搜索相同情感的记忆
            memory_ids = emotion_module.get_emotional_memories(
                emotion_type=emotion_state.primary_emotion,
                min_intensity=0.3,
                limit=limit,
            )
            
            results = []
            for mid in memory_ids:
                mem_dict = self.memory_manager.recall(query="", limit=1)
                # 找到对应记忆
                mem_obj = self.memory_manager._memories.get(mid)
                if mem_obj:
                    mem_emotion = emotion_module.get_emotion(mid)
                    score = mem_emotion.intensity if mem_emotion else 0.5
                    
                    results.append(RecalledMemory(
                        memory_id=mid,
                        content=mem_obj.content,
                        score=score,
                        channel=RecallChannel.EMOTION,
                        metadata={
                            "emotion": emotion_state.primary_emotion.value,
                            "intensity": emotion_state.intensity,
                        },
                    ))
            
            return results
            
        except Exception as e:
            logger.debug(f"情感通道检索失败: {e}")
            return []
    
    def _channel_voice(self, query: str, limit: int) -> List[RecalledMemory]:
        """语音通道（语音转写记忆检索）
        
        检索语音转写记忆（用户通过语音说过的内容）：
        1. 搜索 memory_type="asr_transcription" 的记忆
        2. 按置信度和时间衰减排序
        3. 返回 RecalledMemory 对象列表
        """
        logger.debug(f"语音通道检索: {query}")
        
        if not self.memory_manager:
            return []
        
        try:
            # 搜索语音转写记忆
            all_memories = self.memory_manager.get_all_memories()
            voice_memories = []
            
            for mem_dict in all_memories:
                mem_type = mem_dict.get("memory_type", "")
                meta = mem_dict.get("metadata", {})
                
                # 筛选语音转写记忆
                if mem_type == "asr_transcription" or meta.get("record"):
                    content = mem_dict.get("content", "")
                    # 简单关键词匹配
                    if query.lower() in content.lower() or not query.strip():
                        # 提取置信度和时间
                        record_data = meta.get("record", {})
                        confidence = record_data.get("confidence", 0.5)
                        timestamp = mem_dict.get("timestamp", "")
                        
                        # 计算分数（置信度 + 时间衰减）
                        recency_score = 1.0  # 简化：假设都是近期记忆
                        score = confidence * 0.7 + recency_score * 0.3
                        
                        voice_memories.append(RecalledMemory(
                            memory_id=mem_dict.get("id", ""),
                            content=content,
                            score=score,
                            channel=RecallChannel.VOICE,
                            metadata={
                                "confidence": confidence,
                                "engine": record_data.get("engine", "unknown"),
                                "language": record_data.get("language", "unknown"),
                                "emotion": record_data.get("emotion_label"),
                            },
                        ))
            
            # 按分数排序
            voice_memories.sort(key=lambda m: m.score, reverse=True)
            
            return voice_memories[:limit]
            
        except Exception as e:
            logger.debug(f"语音通道检索失败: {e}")
            return []
    
    def _fusion_score(
        self,
        memory: RecalledMemory,
        query: str,
        channel_weights: Optional[Dict[RecallChannel, float]] = None,
    ) -> float:
        """计算融合分数（legacy 模式）

        Args:
            memory: 召回的记忆
            query: 查询文本
            channel_weights: 通道权重（可选，None 时使用默认权重）

        Returns:
            float: 融合分数
        """
        # 基础分数
        base_score = memory.score

        # 通道权重（意图感知或默认）
        weights = channel_weights if channel_weights else self._channel_weights
        channel_weight = weights.get(memory.channel, 0.1)

        # 时间衰减（越新越好）
        time_decay = self._recency_score(memory.recalled_at)

        # 融合分数
        fusion_score = base_score * channel_weight * time_decay

        return fusion_score

    def _nerf_fusion(
        self,
        memories: List[RecalledMemory],
        channel_weights: Optional[Dict[RecallChannel, float]] = None,
        limit: int = 10,
    ) -> List[RecalledMemory]:
        """NeRF 体渲染融合

        将多通道 RecalledMemory 列表按通道分组，通过 VolumeRenderer
        执行透射率加权积分，再转换回 RecalledMemory 格式。

        Args:
            memories: 去重后的记忆列表
            channel_weights: 意图感知的通道权重
            limit: 返回数量

        Returns:
            体渲染后的 RecalledMemory 列表
        """
        # 按 memory_id 分组（同一条记忆可能出现在多个通道）
        memory_groups: Dict[str, List[RecalledMemory]] = {}
        for mem in memories:
            if mem.memory_id not in memory_groups:
                memory_groups[mem.memory_id] = []
            memory_groups[mem.memory_id].append(mem)

        # 转换为 VolumeRenderer 需要的格式
        channel_results: Dict[str, List[Dict]] = {}
        for mem in memories:
            ch_name = mem.channel.value if hasattr(mem.channel, 'value') else str(mem.channel)
            if ch_name not in channel_results:
                channel_results[ch_name] = []
            channel_results[ch_name].append({
                "memory_id": mem.memory_id,
                "content": mem.content,
                "score": mem.score,
                "metadata": mem.metadata,
            })

        # 获取意图字符串
        intent_str = "exploratory"
        if channel_weights:
            # 从权重反推意图（取第一个匹配的）
            for intent in QueryIntent:
                if self.intent_strategy.get_channel_weights(intent) == channel_weights:
                    intent_str = intent.value
                    break

        # 体渲染
        rendered = self._volume_renderer.render(
            channel_results, intent=intent_str, limit=limit
        )

        # 转换回 RecalledMemory
        result = []
        for rm in rendered:
            # 找到原始记忆的元数据
            original = memory_groups.get(rm.memory_id, [None])[0]
            # 从 channel_scores 找最高贡献通道
            best_ch = "text"
            if rm.channel_scores:
                best_ch = max(rm.channel_scores, key=rm.channel_scores.get)
            try:
                channel_enum = RecallChannel(best_ch)
            except ValueError:
                channel_enum = RecallChannel.TEXT

            # 构建 metadata，包含 channel_scores 供前端展示
            meta = rm.metadata.copy() if rm.metadata else (original.metadata.copy() if original and original.metadata else {})
            # 将 channel_scores 注入 metadata，前端用作 NeRF 标识和可视化
            if rm.channel_scores:
                meta["channel_scores"] = rm.channel_scores
                meta["nerf_rendered"] = True

            result.append(RecalledMemory(
                memory_id=rm.memory_id,
                content=rm.content,
                score=rm.score,
                channel=channel_enum,
                metadata=meta,
            ))

        return result
    
    def _recency_score(self, recalled_at: datetime.datetime) -> float:
        """计算时间衰减分数"""
        now = datetime.datetime.now(datetime.timezone.utc)
        age_hours = (now - recalled_at).total_seconds() / 3600
        
        # 指数衰减
        decay_rate = 0.1  # 每小时衰减10%
        score = math.exp(-decay_rate * age_hours)
        
        return max(0.1, score)  # 最低0.1分
    
    def _deduplicate_results(self, results: List[RecalledMemory]) -> List[RecalledMemory]:
        """去重结果"""
        seen: Dict[str, RecalledMemory] = {}
        
        for memory in results:
            if memory.memory_id in seen:
                # 保留分数更高的
                if memory.score > seen[memory.memory_id].score:
                    seen[memory.memory_id] = memory
            else:
                seen[memory.memory_id] = memory
        
        return list(seen.values())
    
    def _phase2_drill(
        self,
        query: str,
        intent: DrillIntent,
        seed_memories: List[RecalledMemory],
        limit: int,
    ) -> List[RecalledMemory]:
        """
        Phase 2: 意图驱动钻取
        
        Args:
            query: 查询文本
            intent: 钻取意图
            seed_memories: 种子记忆
            limit: 返回数量限制
            
        Returns:
            钻取后的记忆列表
        """
        if not seed_memories:
            return []
        
        # 推断钻取意图
        inferred_intent = self._infer_intent(query, intent)
        
        # 根据意图选择钻取策略
        if inferred_intent == DrillIntent.EXPLORE:
            return self._drill_explore(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.DEEPEN:
            return self._drill_deepen(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.CONNECT:
            return self._drill_connect(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.CONTRAST:
            return self._drill_contrast(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.VALIDATE:
            return self._drill_validate(query, seed_memories, limit)
        
        # 默认返回种子记忆
        return seed_memories[:limit]
    
    def _infer_intent(self, query: str, default_intent: DrillIntent) -> DrillIntent:
        """推断钻取意图"""
        query_lower = query.lower()
        
        # 关键词匹配
        if any(word in query_lower for word in ["什么是", "是什么", "定义", "概念"]):
            return DrillIntent.EXPLORE
        elif any(word in query_lower for word in ["为什么", "原因", "解释", "详细"]):
            return DrillIntent.DEEPEN
        elif any(word in query_lower for word in ["关联", "关系", "连接", "相关"]):
            return DrillIntent.CONNECT
        elif any(word in query_lower for word in ["区别", "不同", "对比", "比较"]):
            return DrillIntent.CONTRAST
        elif any(word in query_lower for word in ["确认", "验证", "正确", "真实"]):
            return DrillIntent.VALIDATE
        
        return default_intent
    
    def _infer_category(self, query: str) -> Optional[str]:
        """推断查询类别"""
        # 简化实现
        return None
    
    def _active_channels(self, intent: DrillIntent) -> List[RecallChannel]:
        """根据意图确定活跃通道"""
        channel_mapping = {
            DrillIntent.EXPLORE: [RecallChannel.TEMPERATURE, RecallChannel.TEXT],
            DrillIntent.DEEPEN: [RecallChannel.TEXT, RecallChannel.GRAPH],
            DrillIntent.CONNECT: [RecallChannel.GRAPH, RecallChannel.CATEGORY],
            DrillIntent.CONTRAST: [RecallChannel.TEXT, RecallChannel.CATEGORY],
            DrillIntent.VALIDATE: [RecallChannel.TEXT, RecallChannel.EMOTION],
        }
        
        return channel_mapping.get(intent, list(RecallChannel))
    
    def _drill_explore(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """探索钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_deepen(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """深化钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_connect(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """连接钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_contrast(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """对比钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_validate(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """验证钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]