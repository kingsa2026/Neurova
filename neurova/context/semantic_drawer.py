from __future__ import annotations

"""
向量语义匹配取水器 - Semantic Match Drawer

按需取水，支持向量语义匹配和关键词降级匹配。
"""

import hashlib
from dataclasses import replace

from neurova.core.logger import get_logger
import math
import re
from datetime import datetime
from typing import List, Optional

from neurova.context.pool_models import ContextInput, ContextSource

logger = get_logger(__name__)


class SemanticMatchDrawer:
    """向量语义匹配取水器 - 按需取水，不需要预定义需求类型"""

    SOURCE_MULTIPLIERS = {
        ContextSource.USER_INPUT: 1.0,
        ContextSource.SUMMARY: 0.9,  # P1-1③：折叠摘要高价值
        ContextSource.CONVERSATION: 0.8,
        ContextSource.MEMORY: 0.3,
        ContextSource.EMOTION: 0.5,
        ContextSource.TOOL_CALL: 0.6,
        ContextSource.SYSTEM_INSTRUCTION: 0.1,
        ContextSource.EXPERIENCE: 0.4,
        ContextSource.REFLECTION: 0.4,
        ContextSource.MULTIMODAL: 0.7,
        ContextSource.DEVELOPER_INSTRUCTION: 0.1,
    }

    WEIGHTS = {
        "match_score": 0.5,
        "freshness": 0.2,
        "priority": 0.2,
        "source_match": 0.1,
    }

    # [按需调取] 相关性门槛：match_score 低于此值的归档不调入视图。
    # 全路径统一刻度（见 _calculate_match_score）：0.5 = 不相关基线，
    # 实测相关内容 ≥0.64 → 门槛 0.55 取空隙中点，双向留余量。
    # 仅在 need 非空时生效。
    # 残留处理 2026-09-13 校准：`(cos+1)/2` 刻度下"语种相同但语义无关"
    # 短文本基线约 0.60-0.61（raw cos≈0.2），0.55 门槛无区分力
    # （实测"爬虫记忆 vs 今天天气"= 0.6127 泄漏进视图）。相关对有
    # 实测 ≥0.64 锚点，门槛抬至 0.65 落在两带之间。
    # ⚠️ 刻度系减基线重标定（更根本方案）仍属待产品决策项（台账十二）。
    RELEVANCE_FLOOR = 0.65

    def __init__(self, max_tokens: int = 16000, max_candidates: int = None):
        #: 构造期默认额度。它**不随轮次变化**：每轮额度经 `draw(budget_tokens=...)`
        #: 传入（B6-9 前是编排器就地改写本字段——同一个字段在不同时刻含义不同，
        #: 调用方无从分辨手里这个值是"池预算"还是"本轮窗口剩余"）。
        self.max_tokens = max_tokens
        #: 本实例最近一次生效的每轮额度（None=尚无，生效额度回落构造期默认）。
        #: 只读口径，供读数与诊断；选取逻辑一律走 `_budgetFor(budget_tokens)`。
        self._turnBudget: Optional[int] = None
        # 语义打分候选集上限：池规模超过它时先用**零编码**的词法粗筛收敛候选。
        # 单源约束：默认值直接取台账读侧的 `CANDIDATE_LIMIT`（规格 U2 定案），
        # 不在这里另写一个数——两处上限若各写一份，口径必然漂移。
        if max_candidates is None:
            from neurova.context.eviction_ledger_db import CANDIDATE_LIMIT

            max_candidates = CANDIDATE_LIMIT
        self.max_candidates = max(1, int(max_candidates))
        self._vector_store = None

    @property
    def vector_store(self):
        if self._vector_store is None:
            try:
                from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
                self._vector_store = UnifiedVectorStore(backend="auto")
            except ImportError:
                logger.warning("UnifiedVectorStore 不可用，使用简单匹配")
                self._vector_store = False
        return self._vector_store

    def effective_view_budget(self) -> int:
        """本实例**生效**的视图额度（单一解释：本轮入参优先，缺省回落构造期默认）。"""
        return self._turnBudget if self._turnBudget is not None else self.max_tokens

    def _budgetFor(self, budget_tokens: Optional[int]) -> int:
        """本轮额度解析（唯一判据）并记忆为生效额度——入参不改构造期字段。"""
        self._turnBudget = int(budget_tokens) if budget_tokens is not None else None
        return self.effective_view_budget()

    def draw(
        self,
        drops: List[ContextInput],
        need: str = None,
        budget_tokens: Optional[int] = None,
    ) -> List[ContextInput]:
        if not drops:
            return []
        viewBudget = self._budgetFor(budget_tokens)

        # ── 阶段 1：零编码词法粗筛（P1-4 根因修复） ────────────────────────
        # 池规模超过候选上限时，先把候选集收敛到上限以内再进语义打分；池内规模
        # 与单轮成本因此解耦。粗筛只收敛**候选**，不改变归档：未入选条目留在池中，
        # 后续轮次仍可被调取（无损归档语义不变）。
        candidates = self._prefilter_candidates(drops, need)

        # ── 阶段 2：单趟打分（每个文本至多一次语义编码） ───────────────────
        # 改前：need 与每条归档各自在 `_relevant()` 与 `_calculate_score()` 里
        # 重复编码（实测 40 条池内 need 编码 55 次、单条文本最高 55 次）。
        # 现在语义上下文由 `_buildScoringContext` 一次算好：need 编码一次，
        # 候选文本各编码一次，余弦一次性批算——打分与门槛读同一份分数，
        # 不存在"两处各算一遍"的口径分裂。
        scoring = self._buildScoringContext(candidates, need)
        threshold_active = bool(need)

        def _relevant(d: ContextInput) -> bool:
            return (not threshold_active) or scoring.matchScore(d) >= self.RELEVANCE_FLOOR

        conv_items = [
            (i, d)
            for i, d in enumerate(candidates)
            if d.source == ContextSource.CONVERSATION and _relevant(d)
        ]
        non_conv_items = [d for d in candidates if d.source != ContextSource.CONVERSATION and _relevant(d)]

        scored_non_conv = []
        for drop in non_conv_items:
            score = self._calculate_score(drop, need, scoring)
            scored_non_conv.append((score, drop))


        result_by_pos = {}
        for idx, (orig_pos, item) in enumerate(conv_items):
            result_by_pos[orig_pos] = item

        non_conv_idx = 0
        for pos in range(len(candidates)):
            if pos in result_by_pos:
                continue
            if non_conv_idx < len(scored_non_conv):
                _, item = scored_non_conv[non_conv_idx]
                result_by_pos[pos] = item
                non_conv_idx += 1

        # [按需调取] 整条选取：分数只决定"取不取"，绝不切片截断内容
        #（归档无损，视图层超预算的条目整条跳过，留在池中等待后续调取）
        #
        # P1-1④ 分层预算回投：不再按位置序遍历，改按分层优先级——
        #   第 1 层：未读 TOOL_CALL（模型尚未读过，必须在视野内，绝不折叠）
        #   第 2 层：其余条目（conversation/memory/experience/已读 TOOL_CALL）
        # 各层内保持原相对顺序；选中后仍按 created_at 稳定排序（前缀缓存契约）
        selected = []
        total_tokens = 0
        layered_positions = [
            pos
            for pos in sorted(result_by_pos)
            if not (
                result_by_pos[pos].source == ContextSource.TOOL_CALL
                and result_by_pos[pos].seen_confirmed
            )
        ] + [
            pos
            for pos in sorted(result_by_pos)
            if (
                result_by_pos[pos].source == ContextSource.TOOL_CALL
                and result_by_pos[pos].seen_confirmed
            )
        ]
        for pos in layered_positions:
            drop = result_by_pos[pos]
            drop_tokens = drop.tokens if drop.tokens > 0 else self._estimate_tokens(drop.content)

            if total_tokens + drop_tokens <= viewBudget:
                selected.append(drop)
                total_tokens += drop_tokens
            elif drop_tokens > viewBudget and viewBudget > 200:
                # 审验闭环（2026-09-10）：单条超预算的大归档截断召回（尾部省略注记），
                # 不再整条跳过——否则长消息被窗口折叠后永远无法召回（对话连续性断裂）。
                #
                # P0-3：截断**只能产出视图副本**。collect() 返回的是归档列表里的同一批
                # 对象引用，旧实现在这里直接 `drop.content = truncated` 就地改写归档
                # 实体——被截掉的部分没有任何其他副本（违反"永不丢失"），且 hash（来源域
                # + 原文指纹）不重算 → 索引与内容失配 → 后续归档原文会被去重当作
                # "已存在"跳过，丢失不可挽回。改用 dataclasses.replace 产副本，
                # 副本显式标注 truncated_from=原文 hash（可追溯、可重调取）。
                content = str(drop.content or "")
                keep_chars = self._chars_for_token_budget(content, viewBudget)
                truncated = content[:keep_chars] + "…[召回截断，全文见会话记录]"
                view_copy = replace(
                    drop,
                    content=truncated,
                    tokens=self._estimate_tokens(truncated),
                    metadata={**(drop.metadata or {}), "truncated_from": drop.hash},
                )
                selected.append(view_copy)
                total_tokens += view_copy.tokens
            # 其余超预算：整条跳过并继续尝试更小的条目（不截断内容、不中断选取）

        # [缓存稳定] 最终顺序按 created_at 稳定排序：
        # 同一批被调取的条目在不同请求中保持相同相对位置，保住 LLM 前缀缓存
        selected.sort(key=lambda d: d.created_at or datetime.min)
        return selected

    def _calculate_score(self, drop: ContextInput, need: str = None, scoring=None) -> float:
        if scoring is not None:
            match_score = scoring.matchScore(drop) if need else 0.5
        else:
            match_score = self._calculate_match_score(drop, need) if need else 0.5
        freshness_score = self._calculate_freshness_score(drop)
        priority_score = drop.priority / 100.0
        source_score = self._calculate_source_score(drop, need) if need else 0.5

        total = (
            self.WEIGHTS["match_score"] * match_score
            + self.WEIGHTS["freshness"] * freshness_score
            + self.WEIGHTS["priority"] * priority_score
            + self.WEIGHTS["source_match"] * source_score
        )

        return total

    def _calculate_match_score(self, drop: ContextInput, need: str) -> float:
        """匹配得分，全路径统一刻度：0.5 = 不相关基线，1.0 = 强相关。

        本方法保留为**逐条**入口（单条诊断与既有调用方使用）；批量调取路径
        一律走 `_buildScoringContext`，那里每个文本只编码一次。两条路径共用
        `ScoringContext.matchScore` 的实现细节（向量做点积、关键词路径回退），
        所以刻度不存在第二份定义。
        """
        if not need:
            return 0.5
        return self._buildScoringContext([drop], need).matchScore(drop)

    def _prefilter_candidates(self, drops: List[ContextInput], need: str) -> List[ContextInput]:
        """零编码词法粗筛：池规模超过候选上限时收敛候选集。

        为什么必须用"零编码"的判据：P1-4 的成本本体就是语义编码；用向量做粗筛
        等于把成本提前付一遍。这里读的是**已缓存的词法信息**（`tokens` 由写入期
        落定、`tags` 由写入方给出）与查询词的字面命中，不触碰 embedding。

        排序取向：先按"查询词命中数"降序、再按 `priority` 降序、最后按原插入序
        （稳定排序保证跨轮同输入同输出，前缀缓存契约不破）。
        未入选条目**留在池中**（调用方持有原列表），不是丢弃。
        """
        if len(drops) <= self.max_candidates:
            return list(drops)

        need_terms = self._lexical_terms(need)

        def _rank_key(indexed):
            index, drop = indexed
            hits = self._lexical_hits(drop, need_terms)
            return (-hits, -(drop.priority or 0), index)

        ranked = sorted(enumerate(drops), key=_rank_key)
        keep = [drop for _, drop in ranked[: self.max_candidates]]
        keep_ids = {id(drop) for drop in keep}
        dropped = [drop for drop in drops if id(drop) not in keep_ids]
        logger.debug(
            "抽屉候选粗筛：池内 %s 条 → 候选 %s 条（上限 %s），未入选 %s 条留在池中",
            len(drops),
            len(keep),
            self.max_candidates,
            len(dropped),
        )
        return keep

    @staticmethod
    def _lexical_terms(text: str) -> List[str]:
        """查询词（去标点、去单字噪声）——粗筛与关键词刻度共用同一份切分。"""
        return [kw.strip() for kw in re.sub(r"[^\w\s]", " ", text or "").split() if len(kw.strip()) > 1]

    @staticmethod
    def _lexical_hits(drop: ContextInput, need_terms: List[str]) -> int:
        """条目对查询词的字面命中数（零编码）。"""
        if not need_terms:
            return 0
        content = str(drop.content or "")
        tags = drop.tags or []
        hits = 0
        for term in need_terms:
            if term in content or any(term in str(tag) for tag in tags):
                hits += 1
        return hits

    @staticmethod
    def _drop_text(drop: ContextInput) -> str:
        """条目参与语义编码的文本（正文 + 标签）——编码口径的唯一出处。"""
        text = str(drop.content or "")
        tags = drop.tags or []
        if tags:
            text += " " + " ".join(str(tag) for tag in tags)
        return text

    def _buildScoringContext(self, drops: List[ContextInput], need: str):
        """单趟构建打分上下文：need 编码 1 次，候选文本各编码 1 次，余弦批量算。

        `ScoringContext` 是"每个文本至多编码一次"的承载点——`draw` 的相关性门槛
        与 `_calculate_score` 都从它取分，不再各自重算（改前实测单条文本最高重复
        编码 55 次、need 60 次）。
        """
        return ScoringContext.build(self, drops, need)

    def _keyword_match_score(self, drop: ContextInput, need: str) -> float:
        need_keywords = [kw.strip() for kw in re.sub(r"[^\w\s]", " ", need).split() if len(kw.strip()) > 1]
        if not need_keywords:
            return 0.5

        tag_matches = sum(1 for kw in need_keywords if any(kw in tag for tag in drop.tags))
        content_matches = sum(1 for kw in need_keywords if kw in drop.content)

        total_keywords = len(need_keywords)
        tag_ratio = tag_matches / total_keywords
        content_ratio = min(content_matches / total_keywords, 1.0)

        return 0.5 * tag_ratio + 0.5 * content_ratio

    def _calculate_freshness_score(self, drop: ContextInput) -> float:
        """退火因子按**归档时刻**（`created_at`）算——读侧时间判据只有这一份。

        B6-7：改前读 `updated_at`，而该字段是"本次构造对象的时刻"（零写入方），
        于是召回一条 45 天前的归档时 age=0 → 退火系数 1.0：越老的归档越"新鲜"，
        相关性打分被系统性地抬向旧内容。排序（`draw` 末尾的 `created_at` 稳定排序）
        与打分现在共用同一个字段，不再是一处一个时刻。
        """
        if not drop.created_at:
            return 0.5

        age_hours = (datetime.now() - drop.created_at).total_seconds() / 3600
        freshness = math.exp(-0.1 * age_hours)
        multiplier = self.SOURCE_MULTIPLIERS.get(drop.source, 0.5)

        return freshness * multiplier

    def _calculate_source_score(self, drop: ContextInput, need: str) -> float:
        if not need:
            return 0.5

        source_text = drop.source.value.replace("_", " ")
        need_lower = need.lower()

        if source_text in need_lower:
            return 1.0

        return 0.3

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        from neurova.context.token_estimator import estimate_tokens

        return estimate_tokens(text)

    @classmethod
    def _chars_for_token_budget(cls, text: str, budget_tokens: int) -> int:
        """按同一把尺子反解"budget_tokens 能装多少字符"（不许用固定 char/token 常数）。

        固定逆推常数（曾为 2 char/token）对中文等于放进约 3 倍名义额度的内容：
        同一仓库对中文的口径是 ~1 token/字。改为按估算器实测密度反解，
        中文/英文/代码三种形态各自得到自己的字符上限。
        """
        total_tokens = cls._estimate_tokens(text)
        if total_tokens <= 0:
            return len(text)
        return max(200, int(len(text) * budget_tokens / total_tokens))


class ScoringContext:
    """单趟语义打分上下文（`SemanticMatchDrawer` 的成本承载点）。

    改前形态：`draw` 的 `_relevant()` 与 `_calculate_score()` 各自调一次
    `_calculate_match_score`，后者又对 need 与条目文本各编码一次——实测单轮
    40 条池内 need 编码 60 次、单条归档文本最高 60 次。成本随池规模线性放大，
    这是审计 P1-4 点名的形态。

    本类把"编码"与"算分"拆开：构建期一次性完成编码（need 一次、候选各一次），
    并对余弦做一次批量结算；打分期只查表。门槛判定与排序打分读**同一份**分数，
    不存在两处各算一遍的口径分裂。

    降级纪律：批量编码整体失败时，全部候选退回关键词刻度（与逐条路径同刻度），
    并点名告警——不静默把分数当 0 处理（那会把相关性门槛变成"全挡"）。
    """

    _EPSILON = 1e-12

    def __init__(self, drawer, need: str, needVector=None, vectors=None, degraded: bool = False):
        self._drawer = drawer
        self._need = need
        self._needVector = needVector
        self._vectors = vectors or {}
        self._degraded = degraded

    @classmethod
    def build(cls, drawer, drops: List[ContextInput], need: str) -> "ScoringContext":
        if not need:
            return cls(drawer, "")

        store = drawer.vector_store
        if not store:
            return cls(drawer, need)

        candidate_drops = list(drops or [])
        try:
            need_vector = store.encode(need)
            texts = [drawer._drop_text(drop) for drop in candidate_drops]
            if not texts:
                return cls(drawer, need, needVector=need_vector, vectors={})
            encoded = store.encode_batch(texts) if hasattr(store, "encode_batch") else None
            raw = encoded if encoded is not None else [store.encode(text) for text in texts]
            vectors = {id(drop): vector for drop, vector in zip(candidate_drops, raw)}
        except Exception as e:  # noqa: BLE001 - 向量不可用时退回关键词刻度
            logger.warning("批量语义编码失败，全部候选降级为关键词刻度: %s", e)
            return cls(drawer, need, degraded=True)

        return cls(drawer, need, needVector=need_vector, vectors=vectors)

    def matchScore(self, drop: ContextInput) -> float:
        """匹配得分，全路径统一刻度：0.5 = 不相关基线，1.0 = 强相关。"""
        if not self._need:
            return 0.5

        if not self._degraded and self._needVector is not None:
            vector = self._vectors.get(id(drop))
            if vector is not None:
                return self._cosineScore(self._needVector, vector)

        return 0.5 + self._drawer._keyword_match_score(drop, self._need) / 2

    @classmethod
    def _cosineScore(cls, left, right) -> float:
        """余弦 → (cos+1)/2。左向量可与右向量归一化口径不同，故两侧各自求范数。"""
        dot = cls._dot(left, right)
        norm_left = cls._norm(left)
        norm_right = cls._norm(right)
        if norm_left <= cls._EPSILON or norm_right <= cls._EPSILON:
            return 0.0
        return (dot / (norm_left * norm_right) + 1) / 2

    @staticmethod
    def _dot(left, right) -> float:
        try:
            import numpy as np

            return float(np.dot(np.asarray(left, dtype="float32"), np.asarray(right, dtype="float32")))
        except ImportError:
            return float(sum(a * b for a, b in zip(left, right)))

    @staticmethod
    def _norm(vector) -> float:
        try:
            import numpy as np

            return float(np.linalg.norm(np.asarray(vector, dtype="float32")))
        except ImportError:
            return math.sqrt(sum(x * x for x in vector))
