"""rerank 双模模块（P0-3 — Dify RerankRunnerFactory 对标）。

双模式（docs/Neurova_Dify代码级对比_2026-09-03.md §2.6）：
- WeightRerankRunner：多路分数加权融合（无外部依赖，默认）
- ModelRerankRunner：rerank 模型重排（provider 注入式——bge-reranker/
  cohere 等由调用方装配；provider 失败/契约不符时退化加权，不阻断检索）
"""

from .model_rerank_runner import ModelRerankRunner
from .rerank_factory import rerank
from .weight_rerank_runner import WeightRerankRunner

__all__ = ["WeightRerankRunner", "ModelRerankRunner", "rerank"]
