# -*- coding: utf-8 -*-
"""云端嵌入引擎（R11）：duck-type 本地 ONNXEmbeddingEngine 的消费面。

接口对齐 encodeOrNone / encode / encode_batch / dimension / releaseBackend /
markHandedOutByFactory，get_embedding_engine() 的消费方零改动切换。

**不回落本地**：远程失败时 encodeOrNone 返回 None、encode 抛
EmbeddingChannelError——不同嵌入空间向量不可比，静默换空间会污染索引。
"""
from __future__ import annotations

import time
from typing import List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class RemoteEmbeddingEngine:
    """经 LLM 层 embeddings 通道取向量的远程引擎。"""

    def __init__(self, provider_id: str, model: str):
        self.provider_id = provider_id
        self.model = model
        self._dimension = 0

    @property
    def dimension(self) -> int:
        """已知维度（首次成功嵌入前为 0；仓内无生产消费方，仅对账用）。"""
        return self._dimension

    def encodeOrNone(self, text: str) -> Optional[List[float]]:
        """失败返回 None（诚实口径：本轮无嵌入，不换空间兜底）。"""
        try:
            return self.encode(text)
        except Exception as e:  # noqa: BLE001 — 通道失败按无嵌入处理
            logger.warning("远程嵌入失败（%s/%s，不回落本地防跨空间污染）: %s",
                           self.provider_id, self.model, e)
            return None

    def encode(self, text: str) -> List[float]:
        from neurova.llm.embeddings_channel import embedTexts

        vectors = embedTexts([text], provider_id=self.provider_id, model=self.model)
        vector = vectors[0]
        self._dimension = len(vector)
        return vector

    def encode_batch(self, texts: List[str]):
        from neurova.llm.embeddings_channel import embedTexts

        started = time.time()
        vectors = embedTexts(list(texts), provider_id=self.provider_id,
                             model=self.model)
        if vectors:
            self._dimension = len(vectors[0])
        # EmbeddingResult 所在模块顶层 import numpy（重依赖），按包纪律惰性取
        from neurova.embedding.onnx_embedding import EmbeddingResult

        return EmbeddingResult(
            vectors=vectors,
            model_name=self.model,
            dimension=self._dimension,
            inference_ms=(time.time() - started) * 1000,
        )

    def releaseBackend(self) -> None:
        """与本地引擎同款释放入口（reset 流程安全探测用）；远程无后端可放。"""

    def markHandedOutByFactory(self) -> None:
        """工厂交接标记（本地引擎同款接口，行为对齐）。"""
