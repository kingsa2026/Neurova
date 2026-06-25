"""
NeuHebbManager — Neurova Hebb 系统协调器

深度模块设计：小接口（generate_neurova_hebb / retrieve_neurova_hebb），
深实现（协调 Forge、Curator、Mem 三个子模块）。

Agent 只与 NeuHebbManager 交互，不直接接触内部子模块。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any, Callable, Dict, List, Optional

from .neuHebb_curator import NeuHebbCurator
from .neuHebb_forge import NeuHebbForge
from .neurova_hebb import NeuHebbConfig, NeuHebbMem, NeurovaHebb

logger = get_logger(__name__)


class NeuHebbManager:
    """
    Neurova Evocate 系统协调器。

    接口极简:
      - generate_neurova_hebb(document_id, content) → List[NeurovaHebb]
      - retrieve_neurova_hebb(query) → List[NeurovaHebb]

    内部协调:
      - NeuHebbForge: 预查询生成 + Neurova Hebb 生成管道
      - NeuHebbCurator: Neurova Hebb 检索 + 多样性过滤
      - NeuHebbMem: 持久化存储
    """

    def __init__(
        self,
        config: Optional[NeuHebbConfig] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        storage: Optional[NeuHebbMem] = None,
    ):
        """
        Args:
            config: 配置
            llm_fn: LLM 生成函数 (prompt → text)
            embed_fn: 嵌入函数 (text → vector)
            storage: 外部传入的 NeuHebbMem 实例
        """
        self.config = config or NeuHebbConfig()
        self._llm_fn = llm_fn
        self._embed_fn = embed_fn

        # 共享存储实例
        self._storage = storage

        # 子模块
        self._forge: Optional[NeuHebbForge] = None
        self._curator: Optional[NeuHebbCurator] = None

    # ── 属性 ──

    @property
    def storage(self) -> NeuHebbMem:
        if self._storage is None:
            self._storage = NeuHebbMem(self.config)
        return self._storage

    @property
    def forge(self) -> NeuHebbForge:
        if self._forge is None:
            self._forge = NeuHebbForge(
                config=self.config,
                llm_fn=self._llm_fn,
                embed_fn=self._embed_fn,
            )
        return self._forge

    @property
    def curator(self) -> NeuHebbCurator:
        if self._curator is None:
            self._curator = NeuHebbCurator(
                config=self.config,
                embed_fn=self._embed_fn,
                storage=self.storage,
            )
        return self._curator

    # ── 公开接口 ──

    def generate_neurova_hebb(
        self,
        document_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[NeurovaHebb]:
        """
        为文档内容生成 NeurovaHebb 并存储。

        Args:
            document_id: 文档唯一标识
            content: 文档内容
            metadata: 可选的元数据

        Returns:
            生成的 NeurovaHebb 列表
        """
        # 1. 生成 NeurovaHebb
        hebbs = self.forge.generate_neurova_hebb(
            document_id=document_id,
            content=content,
        )

        # 2. 设置元数据
        if metadata:
            for h in hebbs:
                h.metadata.update(metadata)

        # 3. 存储
        if hebbs:
            stored = self.storage.store(document_id, hebbs)
            logger.info(
                "Stored %d/%d NeurovaHebbs for document %s",
                stored,
                len(hebbs),
                document_id,
            )

        return hebbs

    def generate_from_conversation(
        self,
        user_input: str,
        reply: str,
        session_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[NeurovaHebb]:
        """
        从对话内容生成 NeurovaHebb（Evocate 闭环的核心生成方法）。

        将对话视为文档，提取结构化推理记忆。

        Args:
            user_input: 用户输入
            reply: 助手回复
            session_id: 会话 ID
            metadata: 可选的元数据

        Returns:
            生成的 NeurovaHebb 列表
        """
        # 1. 构建文档内容
        content = f"用户: {user_input}\n助手: {reply}"

        # 2. 生成唯一的 document_id（使用会话 ID + 时间戳）
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        document_id = f"conversation_{session_id}_{timestamp}"

        # 3. 构建对话特定的元数据
        conversation_metadata = {
            "source": "conversation",
            "session_id": session_id,
            "user_input_length": len(user_input),
            "reply_length": len(reply),
        }
        if metadata:
            conversation_metadata.update(metadata)

        # 4. 委托给 generate_neurova_hebb
        hebbs = self.generate_neurova_hebb(
            document_id=document_id,
            content=content,
            metadata=conversation_metadata,
        )

        if hebbs:
            logger.info(
                "Generated %d NeurovaHebbs from conversation (session: %s)",
                len(hebbs),
                session_id,
            )

        return hebbs

    def retrieve_neurova_hebb(self, query: str) -> List[NeurovaHebb]:
        """
        检索与查询相关的 NeurovaHebb。

        Args:
            query: 用户查询文本

        Returns:
            按相关度降序排列的 NeurovaHebb 列表（经多样性过滤）
        """
        # 1. 获取查询向量
        query_embedding = self.curator.get_query_embedding(query)

        # 2. 检索 + 多样性过滤
        results = self.curator.retrieve(
            query_embedding=query_embedding,
            top_k=self.config.top_k,
        )

        if results:
            logger.info(
                "Retrieved %d NeurovaHebbs for query: %.60s",
                len(results),
                query,
            )

        return results

    def count(self, document_id: Optional[str] = None) -> int:
        """返回存储的 NeurovaHebb 总数。"""
        return self.storage.count(document_id)

    def get_statistics(self) -> Dict[str, Any]:
        """返回系统统计信息。"""
        all_data = self.storage.get_all()
        total_hebbs = sum(len(v) for v in all_data.values())
        total_docs = len(all_data)

        # 计算平均验证分数
        all_scores = []
        for doc_hebbs in all_data.values():
            for h in doc_hebbs:
                if h.verification_score > 0:
                    all_scores.append(h.verification_score)

        return {
            "total_documents": total_docs,
            "total_neurova_hebbs": total_hebbs,
            "avg_verification_score": (sum(all_scores) / len(all_scores) if all_scores else 0.0),
            "config": {
                "enabled": self.config.enabled,
                "top_k": self.config.top_k,
                "diversity_threshold": self.config.diversity_threshold,
                "neurova_hebbs_limit": self.config.neurova_hebbs_limit,
            },
        }
