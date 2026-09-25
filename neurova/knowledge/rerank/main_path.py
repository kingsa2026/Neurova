"""主路末端精排（工单 014，灭 B05）：让 RRF 之后还有一道可关闸的排序段。

B05 的形状：精修能力（`knowledge/rerank/`）只有旁路 API 用得到，`hybrid.py` 与
知识检索适配器对它零引用 ⇒ 对话主链的排序永远停在 RRF 秩融合。本模块把它接进
`hybrid_search_knowledge` 的末端，并且**装配口只留一个**（`rerank_factory.buildRunner`），
旁路 API 也改成走同一个口——两份装配迟早各差一段。

三条纪律：

- **先精排再截断**。RRF 序里排 11–30 名的候选要能被顶进前 10，否则精排只是在
  已经选定的池子里重新洗牌。候选池上限 `limit * poolFactor`，成本随 limit 而不是语料。
- **通道分取自 `confidence_breakdown`**，不在这一步重算分数——重算就是第二把尺子。
- **模型通道不在事件循环里跑**。`hybrid_search_knowledge` 是同步函数，而它被
  `KnowledgeRetrieverAdapter.retrieve`（async）直接调用；模型 provider 是同步 HTTP，
  在循环里跑会卡住整个服务。因此主路请求 model 而当前在循环内时，退化为加权并把
  原因写进 note——退化必须可见，标成 model 就是冒充已生效。

`rerank_method` / `rerank_score` 只在实际精排发生时才盖到结果上：关闸态与开闸前的
行为必须逐字一致，不留新字段当"我来过"的记号。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .rerank_factory import buildRunner

MAIN_RERANK_ENV = "NEUROVA_KB_MAIN_RERANK"
_OFF_VALUES = ("0", "false", "off", "no")


@dataclass
class MainPathRerankConfig:
    """主路精排段配置。默认**开**：B05 是断点不是新能力，关掉它等于把断点留在原地。

    默认态是在冻结锚点上量出来的，不是拍的：同一把尺子（30 例 / admin / top-5）
    关闸 0.855489 / 0.83 / 0.1 与基线逐位一致，开闸 0.855489 / 0.831667 / 0.1
    ——召回与未命中率一字未动、倒数排名略升，且真检索 top-5 确实换了序（不是空接）。
    成本上限是 `limit * poolFactor`，加权融合零外部依赖。
    """

    enabled: bool = True
    method: str = "weight"
    weights: Optional[Dict[str, float]] = None
    rerankProvider: str = ""
    poolFactor: int = 3

    @classmethod
    def fromEnv(cls) -> "MainPathRerankConfig":
        raw = (os.environ.get(MAIN_RERANK_ENV) or "").strip().lower()
        enabled = raw not in _OFF_VALUES
        method = (os.environ.get("NEUROVA_KB_MAIN_RERANK_METHOD") or "weight").strip().lower()
        try:
            poolFactor = max(int(os.environ.get("NEUROVA_KB_MAIN_RERANK_POOL") or 3), 1)
        except ValueError:
            poolFactor = 3
        return cls(enabled=enabled, method=method or "weight", poolFactor=poolFactor)


def _insideEventLoop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def refineMainPathResults(query: str, pool: List[Dict[str, Any]], *, limit: int,
                          config: Optional[MainPathRerankConfig] = None,
                          runner: Any = None,
                          providerResolver: Any = None
                          ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """精排候选池并截断到 limit。返回 `(结果, 降级说明)`；关闸即原样透传。"""
    cfg = config or MainPathRerankConfig.fromEnv()
    if not cfg.enabled or not pool:
        return pool, None

    note: Optional[Dict[str, Any]] = None
    method = cfg.method
    if method == "model" and runner is None and _insideEventLoop():
        method = "weight"
        note = {"requested": cfg.method, "reason": "model_channel_blocked_in_event_loop"}

    candidates = pool[: max(int(limit), 1) * max(cfg.poolFactor, 1)]
    docs: List[Dict[str, Any]] = []
    for index, row in enumerate(candidates):
        breakdown = row.get("confidence_breakdown") or {}
        docs.append({
            "index": index,
            "id": str(row.get("knowledge_id", "") or ""),
            "content": str(row.get("content", "") or ""),
            "tfidf": float(breakdown.get("tfidf", 0.0) or 0.0),
            "bm25": float(breakdown.get("bm25", 0.0) or 0.0),
            "fts": float(breakdown.get("fts", 0.0) or 0.0),
            "vector": float(breakdown.get("vector", 0.0) or 0.0),
        })

    if runner is None:
        runner, label, built = buildRunner(
            {"method": method, "weights": cfg.weights, "rerank_provider": cfg.rerankProvider},
            providerResolver=providerResolver)
        note = note or built
        method = label

    scored = runner.rerank(query, docs)
    out: List[Dict[str, Any]] = []
    for row in scored:
        position = int(row.get("index", 0))
        if not 0 <= position < len(candidates):
            continue
        stamped = dict(candidates[position])
        stamped["rerank_score"] = round(float(row.get("score", 0.0)), 6)
        stamped["rerank_method"] = method
        out.append(stamped)
    out.sort(key=lambda r: r["rerank_score"], reverse=True)
    if len(out) != len(candidates):
        # runner 交回的 index 覆盖不全 ⇒ 有候选被静默丢弃；这比排序变化严重，必须留痕
        note = note or {"requested": method, "reason": "runner_returned_%d_of_%d"
                        % (len(out), len(candidates))}
    return out[: max(int(limit), 1)], note
