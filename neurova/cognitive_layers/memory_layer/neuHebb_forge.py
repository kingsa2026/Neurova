"""
NeuHebbForge — Neurova Hebb 生成器

深度模块设计：小接口（generate_pre_queries / split_content / generate_neurova_hebb），
深实现（预查询生成、稠密检索、问答生成、两步验证、多样性过滤）。

依赖注入 llm_fn / embed_fn 以实现可测试性和可替换性。
"""

from __future__ import annotations

import logging
import re
import math
from typing import Callable, List, Optional, Dict, Any

from .neurova_hebb import NeurovaHebb, NeuHebbConfig

logger = logging.getLogger(__name__)

# 无效答案特征词（小写匹配）
_INVALID_INDICATORS = [
    "i don't know", "idk", "insufficient information",
    "i do not know", "not sure", "cannot determine",
    "no information", "unable to answer", "not enough context",
]


class NeuHebbForge:
    """
    Neurova Hebb 生成器。

    接口极简:
      - generate_pre_queries(content) → List[str]
      - split_content(content) → List[str]
      - generate_neurova_hebb(document_id, content) → List[NeurovaHebb]

    内部实现: 预查询生成 → 文档分块 → 稠密检索 → 问答 → 两步验证 → 多样性过滤。
    """

    def __init__(
        self,
        config: Optional[NeuHebbConfig] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
    ):
        """
        Args:
            config: Neurova Hebb 配置
            llm_fn: 文本生成函数 (prompt → response)
            embed_fn: 文本嵌入函数 (text → vector)
        """
        self.config = config or NeuHebbConfig()
        self._llm = llm_fn or self._default_llm
        self._embed = embed_fn or self._default_embed

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def generate_pre_queries(self, content: str) -> List[str]:
        """
        为文档内容生成预查询（What / How / Why 类型）。

        Args:
            content: 文档内容

        Returns:
            预查询列表，数量受 config.pre_query_count 限制
        """
        prompt = (
            f"Based on the following content, generate up to {self.config.pre_query_count} "
            f"diverse questions (What, How, Why types). One question per line, no numbering:\n\n"
            f"{content[:2000]}"
        )
        raw = self._llm(prompt)
        queries = self._parse_queries(raw)
        return queries[: self.config.pre_query_count]

    def split_content(self, content: str) -> List[str]:
        """
        将文档内容分割为块。

        使用双换行分段，过长段落再按句子切分。
        """
        if not content or not content.strip():
            return []

        # 先按双换行分段
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

        # 如果段落太少，按句号切分
        if len(paragraphs) < 2:
            sentences = re.split(r'(?<=[.!?。！？])\s+', content.strip())
            chunks = []
            current = ""
            for s in sentences:
                if len(current) + len(s) > 1000:
                    if current:
                        chunks.append(current.strip())
                    current = s
                else:
                    current = current + " " + s if current else s
            if current.strip():
                chunks.append(current.strip())
            return chunks if chunks else [content.strip()]

        return paragraphs

    def generate_neurova_hebb(
        self,
        document_id: str,
        content: str,
    ) -> List[NeurovaHebb]:
        """
        核心生成管道：内容 → 预查询 → 检索 → 问答 → 验证 → NeurovaHebb 列表。

        Args:
            document_id: 文档标识
            content: 文档内容

        Returns:
            有效的 NeurovaHebb 列表
        """
        # 1. 文档分块
        chunks = self.split_content(content)

        # 2. 预查询生成
        pre_queries = self.generate_pre_queries(content)

        # 3. 编码 chunks 用于检索
        chunk_embeddings = [self._embed(c) for c in chunks]

        # 4. 处理每个预查询
        new_hebbs: List[NeurovaHebb] = []
        new_hebb_embeddings: List[List[float]] = []

        for query in pre_queries:
            if len(new_hebbs) >= self.config.neurova_hebbs_limit:
                break

            # 4.1 稠密检索相关块
            retrieved_chunks = self._dense_search(
                query, chunks, chunk_embeddings,
                num=min(self.config.chunk_num, len(chunks)),
            )

            # 4.2 生成答案
            answer = self._generate_answer(query, retrieved_chunks)

            # 4.3 验证答案有效性
            if self._is_invalid_answer(answer):
                logger.debug("Skipping invalid answer for query: %s", query[:60])
                continue

            # 4.4 总结为 NeurovaHebb 内容
            if self.config.verification_enabled:
                content_text = self._summarize_to_neurova_hebb(query, answer, verify=True)
                if self._is_invalid_answer(content_text):
                    logger.debug("Verification failed for query: %s", query[:60])
                    continue
            else:
                content_text = self._summarize_to_neurova_hebb(query, answer, verify=False)

            # 4.5 构建 NeurovaHebb
            hebb = NeurovaHebb(
                content=content_text,
                question=query,
                answer=answer,
                source="pre_query",
                document_id=document_id,
                verification_score=1.0 if not self._is_invalid_answer(content_text) else 0.0,
            )

            # 4.6 多样性过滤
            hebb_embedding = self._embed(content_text)
            if self._is_diverse_enough(hebb_embedding, new_hebb_embeddings):
                hebb.embedding = hebb_embedding
                new_hebbs.append(hebb)
                new_hebb_embeddings.append(hebb_embedding)

        logger.info(
            "Generated %d NeurovaHebbs for document %s (from %d queries)",
            len(new_hebbs), document_id, len(pre_queries),
        )
        return new_hebbs

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _parse_queries(self, raw: str) -> List[str]:
        """从 LLM 原始输出中解析问题列表。"""
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        # 去除编号前缀
        cleaned = []
        for line in lines:
            line = re.sub(r"^[\d\.\-\)\]]+\s*", "", line).strip()
            if line and len(line) > 5:
                cleaned.append(line)
        return cleaned

    def _dense_search(
        self,
        query: str,
        chunks: List[str],
        chunk_embeddings: List[List[float]],
        num: int = 8,
    ) -> List[str]:
        """使用余弦相似度检索最相关的块。"""
        if not chunks:
            return []

        query_vec = self._embed(query)
        scores = []
        for i, emb in enumerate(chunk_embeddings):
            sim = self._cosine_similarity(query_vec, emb)
            scores.append((i, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [chunks[i] for i, _ in scores[:num]]

    def _generate_answer(self, question: str, context_chunks: List[str]) -> str:
        """基于检索到的上下文生成答案。"""
        context = "\n\n".join(context_chunks)
        prompt = (
            f"Based on the following context, answer the question concisely.\n\n"
            f"Context:\n{context[:3000]}\n\n"
            f"Question: {question}\n\n"
            f"Answer:"
        )
        return self._llm(prompt).strip()

    def _summarize_to_neurova_hebb(
        self, question: str, answer: str, verify: bool = False
    ) -> str:
        """将问答对总结为结构化的知识单元。"""
        if verify:
            prompt = (
                f"Summarize the following Q&A into a single concise knowledge statement. "
                f"If the answer is invalid or says 'I don't know', respond with 'INVALID'.\n\n"
                f"Q: {question}\nA: {answer}\n\n"
                f"Knowledge statement:"
            )
        else:
            prompt = (
                f"Summarize the following Q&A into a single concise knowledge statement:\n\n"
                f"Q: {question}\nA: {answer}\n\n"
                f"Knowledge statement:"
            )
        return self._llm(prompt).strip()

    def _is_invalid_answer(self, text: str) -> bool:
        """检查文本是否为无效答案。"""
        text_lower = text.lower().strip()
        if not text_lower or len(text_lower) < 3:
            return True
        return any(indicator in text_lower for indicator in _INVALID_INDICATORS)

    def _is_diverse_enough(
        self,
        candidate_embedding: List[float],
        existing_embeddings: List[List[float]],
    ) -> bool:
        """检查候选嵌入与已有嵌入的多样性（余弦相似度 < 阈值）。"""
        if not existing_embeddings:
            return True
        for existing in existing_embeddings:
            sim = self._cosine_similarity(candidate_embedding, existing)
            if sim >= self.config.diversity_threshold:
                return False
        return True

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── 默认实现 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _default_llm(prompt: str) -> str:
        logger.warning("NeuHebbForge: no llm_fn provided, returning stub response")
        return "I don't know"

    @staticmethod
    def _default_embed(text: str) -> List[float]:
        logger.warning("NeuHebbForge: no embed_fn provided, returning zero vector")
        return [0.0] * 64
