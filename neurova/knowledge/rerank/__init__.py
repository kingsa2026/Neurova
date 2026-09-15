"""rerank 双模模块。

双模式：
- WeightRerankRunner：多路分数加权融合（无外部依赖，默认）
- ModelRerankRunner：rerank 模型重排（provider 注入式——bge-reranker/
  cohere 等由调用方装配；provider 失败/契约不符时退化加权，不阻断检索）

P0#3：refine 子模块提供重排精修四连
（clean_passage_for_rerank / threshold_fallback / composite_score /
mmr_select / finalize_reranked），出口默认全关、按配置开启。
"""

from .model_rerank_runner import ModelRerankRunner
from .rerank_factory import rerank
from .weight_rerank_runner import WeightRerankRunner
from . import refine

__all__ = ["WeightRerankRunner", "ModelRerankRunner", "rerank", "refine"]
