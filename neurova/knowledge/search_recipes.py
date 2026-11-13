"""检索配方（C3，graphiti 对照批，docs/08-research/graphiti_vs_neurova_* §7-C3）。

把散在各读取点上的检索可调面收敛成**命名配方**：图路权重、主路精排方法、
精排候选池、recency 权重/半衰期。配方是可命名、可测试、可设置项化的资产
（graphiti 的 search recipes 启发），默认档 = 现网行为逐位不变。

优先级纪律：env 显式设置 > 设置文件（active_recipe）> default 配方。
三个 resolve* 收口函数是各读取点（knowledge_retriever_adapter /
rerank.main_path）的唯一取值口——同一参数不许出现第二份读取逻辑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple

RECIPE_NAMES = ("default", "balanced", "precise", "graph_expanded")


@dataclass(frozen=True)
class RetrievalRecipe:
    """一份命名检索配方。default 档各值与改造前 env 缺省逐位一致。"""

    name: str
    #: 图谱第五路融合权重（原 NEUROVA_KB_GRAPH_ROUTE_WEIGHT 缺省 0.10）
    graphRouteWeight: float
    #: 主路精排方法（weight|model；原 NEUROVA_KB_MAIN_RERANK_METHOD 缺省 weight）
    rerankMethod: str
    #: 精排候选池因子（原 NEUROVA_KB_MAIN_RERANK_POOL 缺省 3）
    rerankPoolFactor: int
    #: recency 权重（原 NEUROVA_RECENCY_WEIGHT 缺省 0=关闭）
    recencyWeight: float
    #: recency 半衰期天数（原 NEUROVA_RECENCY_HALF_LIFE_DAYS 缺省 30）
    recencyHalfLifeDays: float


_RECIPES = {
    "default": RetrievalRecipe("default", 0.10, "weight", 3, 0.0, 30.0),
    "balanced": RetrievalRecipe("balanced", 0.15, "weight", 4, 0.15, 30.0),
    "precise": RetrievalRecipe("precise", 0.10, "model", 5, 0.20, 14.0),
    "graph_expanded": RetrievalRecipe("graph_expanded", 0.30, "weight", 3, 0.0, 30.0),
}


def recipeByName(name: str) -> RetrievalRecipe:
    key = str(name or "").strip().lower()
    if key not in _RECIPES:
        raise ValueError("未知检索配方: %r（可选 %s）" % (name, "/".join(RECIPE_NAMES)))
    return _RECIPES[key]


def resolveRecipe(path: Optional[str] = None) -> RetrievalRecipe:
    """当前生效配方（env > 设置文件 > default）。"""
    from neurova.security.retrieval_recipe_settings import load_settings

    return recipeByName(load_settings(path)["active_recipe"])


def saveActiveRecipe(name: str, path: Optional[str] = None) -> None:
    """落盘 active_recipe；非法名 ValueError，IO 失败 IOError。"""
    from neurova.security import retrieval_recipe_settings as rrs

    normalized = recipeByName(name).name
    if not rrs.save_settings({"active_recipe": normalized}, path):
        raise IOError("检索配方设置保存失败")


def resolveGraphRouteWeight() -> float:
    """图谱第五路权重：env 显式 > 配方。env 非法回 0.10（原缺省行为）。"""
    raw = (os.environ.get("NEUROVA_KB_GRAPH_ROUTE_WEIGHT") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            return 0.10
    return resolveRecipe().graphRouteWeight


def resolveRerankParams() -> Tuple[str, int]:
    """主路精排 (method, poolFactor)：env 显式 > 配方。"""
    method = (os.environ.get("NEUROVA_KB_MAIN_RERANK_METHOD") or "").strip().lower()
    poolRaw = (os.environ.get("NEUROVA_KB_MAIN_RERANK_POOL") or "").strip()
    pool: Optional[int] = None
    if poolRaw:
        try:
            pool = max(int(poolRaw), 1)
        except ValueError:
            pool = None
    if not method or pool is None:
        recipe = resolveRecipe()
        method = method or recipe.rerankMethod
        pool = pool if pool is not None else max(recipe.rerankPoolFactor, 1)
    return method, pool


def resolveRecencyParams() -> Tuple[float, float]:
    """recency (weight, halfLifeDays)：env 显式 > 配方。"""
    rawWeight = (os.environ.get("NEUROVA_RECENCY_WEIGHT") or "").strip()
    rawHalfLife = (os.environ.get("NEUROVA_RECENCY_HALF_LIFE_DAYS") or "").strip()
    recipe = None
    if not rawWeight or not rawHalfLife:
        recipe = resolveRecipe()
    weight = float(rawWeight) if rawWeight else recipe.recencyWeight
    halfLife = float(rawHalfLife) if rawHalfLife else recipe.recencyHalfLifeDays
    return weight, halfLife
