"""演化评测集核选——难度加权多样性贪心（HN6/HC6，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）断点 HN6——评测集三级回退
（golden→挖掘→合成）解决「有没有」，不做「选哪几个最划算」的核选；
评测成本随评测集线性走。HarnessPro 用 DPP（行列式点过程）做难度×多样性
核选；本仓按同一思想**独立实现**一个零依赖的确定性贪心：

- **难度权重**：任务面信息量代理 = len(task_input)+len(expected_behavior)
  归一化（无 LLM、零成本；它是"更长的任务通常更复杂"的保守代理，不是
  真难度判定——诚实边界）；
- **多样性**：任务面字符 bigram 集合的 Jaccard 距离（近重复任务互相排斥）；
- **贪心**：每轮选 `score = (0.5 + 0.5·weight) · minDistToSelected` 最大者
  ——多样性主导、难度做同距加成；全程无随机（同输入同输出）。

与 DPP 的关系：DPP 的核行列式同时惩罚冗余并奖励高权重；本贪心是它的
廉价近似（farthest-point 采样的加权变体），不宣称等价，只承诺可复现与
「近重复不挤占、难题优先」两条可测性质。
"""

from __future__ import annotations

from typing import List, Sequence, Set


def _bigrams(text: str) -> Set[str]:
    """字符 bigram 集合（任务面指纹；跨语言可用，零依赖）。"""
    cleaned = "".join(str(text or "").split())
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _complexity(case) -> int:
    """任务面信息量代理：输入面 + 期望面的体量。"""
    return len(str(getattr(case, "task_input", "") or "")) + len(
        str(getattr(case, "expected_behavior", "") or ""))


def selectCoreset(cases: Sequence, k: int) -> List:
    """从评测用例里选 k 个「难度加权、彼此最不相似」的核选集。

    - k <= 0 ⇒ 空表；k >= n ⇒ 全量（原顺序拷贝）；
    - 确定性：同输入同输出（无随机；平分时先到者胜）；
    - 返回元素是**原用例对象**（不复制、不改写）。
    """
    items = list(cases or [])
    if k is None or int(k) <= 0 or not items:
        return []
    if len(items) <= int(k):
        return items

    weights = [_complexity(c) for c in items]
    max_weight = max(weights) or 1
    fingerprints = [_bigrams(str(getattr(c, "task_input", "") or "")) for c in items]

    selected: List[int] = []
    remaining = set(range(len(items)))

    def pick(first: bool) -> int:
        best_idx: int | None = None
        best_score = -1.0
        for idx in sorted(remaining):
            weight = 0.5 + 0.5 * (weights[idx] / max_weight)
            if first:
                score = weight
            else:
                min_dist = 1.0 - max(
                    _jaccard(fingerprints[idx], fingerprints[s]) for s in selected)
                score = weight * min_dist
            if score > best_score + 1e-12:
                best_score = score
                best_idx = idx
        return int(best_idx) if best_idx is not None else sorted(remaining)[0]

    for _ in range(int(k)):
        idx = pick(not selected)
        selected.append(idx)
        remaining.discard(idx)

    return [items[i] for i in selected]
