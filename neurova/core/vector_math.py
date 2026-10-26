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

当年按**定义域**划界排除在外的一份（不是按名字，教义第 7 条要求先比再合）：
`memory_layer/vector_search.py::_cosine_similarity` 吃 `Dict[str, float]` 稀疏向量、
按键集并集算，与稠密实现不是同一件事，并过来会把它的稀疏语义洗掉。
该模块连同那份实现已于 §6-376 随 `memory_index` 退净；这条界线本身仍是判据
（见 `tests/unit/core/test_denseCosineSingleSource.py`——将来若再引入稀疏余弦，
必须仍是稀疏定义域，不得改指本模块的稠密口）。
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

__all__ = ["ZERO_NORM_EPSILON", "cosineScore", "cosineSimilarity", "isZeroVector",
           "tryCosineSimilarity", "vectorDot", "vectorNorm", "vectorNormalize"]

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

def isZeroVector(vec: Optional[Sequence[float]]) -> bool:
    """这条向量是不是"算不出来"（空／无分量／范数低于 `ZERO_NORM_EPSILON`）。

    嵌入引擎在模型档缺席时会**兜底返回全零向量**而不是 None。零向量不是"两句不相似"的
    证据，是"这一路没算出来"——按"有向量"处置，缺陷在读数里就完全不可见（余弦恒 0，
    看上去只是"不相似"）。生产侧写库前要拿它拦下占位向量，判据侧要拿它区分
    「环境缺件」与「代码不对」，两处必须同一个口径，故定义在这里。
    """
    if not vec:
        return True
    return vectorNorm(vec) <= ZERO_NORM_EPSILON


def vectorNorm(vec: Sequence[float]) -> float:
    """范数。`_rawCosine` 不复用它——检索热路要一次遍历同时算点积与两条范数。"""
    return math.sqrt(sum(x * x for x in vec))


def vectorDot(vecA: Sequence[float], vecB: Sequence[float]) -> float:
    """点积：长度不等按 `zip` 截断（这是点积的定义，不是缺陷）。
    维度守卫归余弦那一处——那边"不可比"要折成 0.0／None，这里没有可折的语义。"""
    return sum(x * y for x, y in zip(vecA, vecB))


def vectorNormalize(vec: Sequence[float]) -> Sequence[float]:
    """归一化。零范数时**原样返回传入的那个对象**（改前的行为，不是副本）。"""
    norm = vectorNorm(vec)
    if norm == 0:
        return vec
    return [x / norm for x in vec]
