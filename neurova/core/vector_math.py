"""稠密向量余弦的唯一出处（§6-179 批 33，教义第 6/7 条：全仓 13 份收成本份）。

背景：`cosine` 这件事在仓内被抄了十三遍，跨 `cognitive_layers/memory_layer`、`context`、
`knowledge`、`skills` 四个包。抄写的代价不是行数，是**分叉**：

- 五份（`muscle_memory`／`neuHebb_curator`／`neuHebb_forge`／`unified_vector_store`／`tool_search`）
  **没有长度检查**，`zip` 会把长的那条截掉，于是两条维度不同的向量（换过嵌入引擎、索引里存的
  旧向量、缓存里没对齐的那一份）算出来的是一个**看着完全正常的相似度**，并按它排序、按它加分——
  比"报错"坏得多的形态：它不喊人。
- 长度不等的处置另有三份返回 0.0、一份抛 `ValueError`；零范数处置有 `== 0`、`or 1.0`、
  `<= 1e-12` 三种写法。
- 值域有两种口径：原始余弦 ∈ [-1,1]，以及映射到 [0,1] 的 `(cos+1)/2`（两处用）。

本模块把这三种事实各定一处：`cosineSimilarity`（原始值域）、`cosineScore`（[0,1] 映射）、
`ZERO_NORM_EPSILON`（零范数阈值）。两者的"不可比/零向量"一律 0.0，而**正交**在 `cosineScore`
里是 0.5、在 `cosineSimilarity` 里是 0.0——这三个数各指各的事，合成一个就是把口径抹平。

不并进来的一份（按**定义域**划界而不是按名字，教义第 7 条要求先比再合）：
`memory_layer/vector_search.py::_cosine_similarity` 吃 `Dict[str, float]` 稀疏向量，
按键集并集算，与稠密实现不是同一件事，并过来会把它的稀疏语义洗掉。
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

__all__ = ["ZERO_NORM_EPSILON", "cosineScore", "cosineSimilarity", "tryCosineSimilarity"]

#: 范数低于此值按"没有信息"处理。取 1e-12 而不是 0：`context/semantic_drawer` 今天就是用
#: 这个阈值防 float32 噪声，沿用它可让那支点保持原读数；对真实嵌入（范数量级 1）无影响。
ZERO_NORM_EPSILON = 1e-12


def _rawCosine(vecA: Sequence[float], vecB: Sequence[float]) -> Optional[float]:
    """可比则返回原始余弦，不可比（长度不等／任一侧空／任一侧零范数）返回 None。

    维度不等**不抛**：这些调用点都在检索与排序的路上（记忆召回、工具目录、技能合并、
    情绪原型匹配），一条坏向量不该打断整轮问答。但它必须拿"没有分"（由两个出口折成 0.0），
    而不是此前五份实现里 `zip` 截断后那个像分的数——假数会顺着排序往上走，永远不喊人。
    """
    if not vecA or not vecB or len(vecA) != len(vecB):
        return None

    dot = 0.0
    sumA = 0.0
    sumB = 0.0
    for a, b in zip(vecA, vecB):
        dot += a * b
        sumA += a * a
        sumB += b * b

    normA = math.sqrt(sumA)
    normB = math.sqrt(sumB)
    if normA <= ZERO_NORM_EPSILON or normB <= ZERO_NORM_EPSILON:
        return None
    return dot / (normA * normB)


def tryCosineSimilarity(vecA: Sequence[float], vecB: Sequence[float]) -> Optional[float]:
    """原始余弦；"不可比／零向量"返回 None 而不是 0.0——给需要区分这两件事的调用方。

    `evolution/eval/constraints` 那条进化闸要拿 None 去回退 Jaccard：把"算不了"折成 0.0，
    它就再也不会回退（0.0 在它眼里是"算出来很低"，不是"没算成"）。
    """
    return _rawCosine(vecA, vecB)


def cosineSimilarity(vecA: Sequence[float], vecB: Sequence[float]) -> float:
    """原始余弦 ∈ [-1, 1]；不可比或零向量 ⇒ 0.0（正交同样是 0.0，两者在这一口径下同值）。"""
    raw = _rawCosine(vecA, vecB)
    return 0.0 if raw is None else raw


def cosineScore(vecA: Sequence[float], vecB: Sequence[float]) -> float:
    """映射到 [0, 1] 的 `(cos + 1) / 2`，只在这里定义一次。

    不可比或零向量 ⇒ 0.0；正交 ⇒ 0.5。这两个数不能混：`0.5` 是"确知无关"，
    `0.0` 是"没法比"。
    """
    raw = _rawCosine(vecA, vecB)
    return 0.0 if raw is None else (raw + 1) / 2
