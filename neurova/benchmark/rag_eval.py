# -*- coding: utf-8 -*-
"""RAG 评估执行器。

检索指标 Precision/Recall/F1@K（集合交并）+ 数据集
（items: {query, gold_chunk_ids, gold_answer}）+ 可选 LLM Judge 二值。

反向设计（§2.5 前车之鉴）：
- gold_chunk_ids 采用分片索引既有块 id `knowledge_id#chunk_index`——条目 id
 为 UUID 稳定
- 数据集 JSON 原子落盘（temp+os.replace，providers 丢配置教训）；
- LLM Judge 注入式，无注入=该维度缺席（judge_score None），不伪造分数
  （simulated 诚实标记纪律）。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.RLock()
K_DEFAULT = (1, 3, 5, 10)


def _datasets_path() -> Path:
    return Path(os.environ.get("NEUROVA_RAG_EVAL_DATASETS") or "data/rag_eval_datasets.json")


def rag_metrics(gold_ids: set, retrieved_ids: Sequence[str], k_list: Sequence[int] = K_DEFAULT) -> Dict[str, float]:
    """P/R/F1@K：retrieved 有序列表前 K 条与 gold 集合交并。gold 为空返回 {}。"""
    gold = set(gold_ids or ())
    if not gold:
        return {}
    out: Dict[str, float] = {}
    for k in k_list:
        top = set(retrieved_ids[: max(1, int(k))])
        inter = len(top & gold)
        p = inter / max(1, len(top))
        r = inter / len(gold)
        f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        out[f"precision@{k}"] = round(p, 6)
        out[f"recall@{k}"] = round(r, 6)
        out[f"f1@{k}"] = round(f1, 6)
    return out


# ── 数据集持久层 ───────────────────────────────────────────────────

def load_datasets() -> List[Dict[str, Any]]:
    with _LOCK:
        p = _datasets_path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            backup = p.with_name(f"{p.name}.corrupt-{int(datetime.now(timezone.utc).timestamp())}")
            try:
                p.replace(backup)
                logger.error("RAG 数据集损坏，已备份 %s 后空载: %s", backup, e)
            except OSError:
                logger.error("RAG 数据集损坏且备份失败: %s", e)
            return []


def _save_all(datasets: List[Dict[str, Any]]) -> None:
    p = _datasets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(datasets, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def save_dataset(payload: Dict[str, Any], dataset_id: Optional[str] = None) -> Dict[str, Any]:
    """新建/更新数据集（items 结构校验在调用方/端点；此处规范化 id/时间戳）。"""
    items = [
        {
            "item_id": it.get("item_id") or f"qi_{uuid.uuid4().hex[:10]}",
            "query": str(it.get("query") or ""),
            "gold_chunk_ids": [str(c) for c in (it.get("gold_chunk_ids") or [])],
            "gold_answer": it.get("gold_answer"),
        }
        for it in (payload.get("items") or [])
        if it.get("query")
    ]
    with _LOCK:
        datasets = load_datasets()
        now = datetime.now(timezone.utc).isoformat()
        if dataset_id:
            for d in datasets:
                if d["id"] == dataset_id:
                    d.update({"name": payload.get("name", d["name"]), "description": payload.get("description", d.get("description", "")),
                              "items": items, "updated_at": now})
                    _save_all(datasets)
                    return d
            raise KeyError(dataset_id)
        ds = {
            "id": f"rds_{uuid.uuid4().hex[:12]}",
            "name": payload.get("name") or "未命名数据集",
            "description": payload.get("description") or "",
            "items": items,
            "created_at": now,
        }
        datasets.append(ds)
        _save_all(datasets)
        return ds


def delete_dataset(dataset_id: str) -> bool:
    with _LOCK:
        datasets = load_datasets()
        kept = [d for d in datasets if d["id"] != dataset_id]
        if len(kept) == len(datasets):
            return False
        _save_all(kept)
        return True


# ── 评测执行 ───────────────────────────────────────────────────────

def evaluate_dataset(
    dataset: Dict[str, Any],
    retrieve_fn: Callable[[str, int], Sequence[str]],
    top_k: int = 5,
    k_list: Sequence[int] = K_DEFAULT,
    judge_fn: Optional[Callable[[str, str, str], Any]] = None,
) -> Dict[str, Any]:
    """逐题评测：retrieve_fn(query, top_k) 返回有序 chunk id 列表。

    judge_fn 提供且条目有 gold_answer 时记 judge_score∈{0,1}；缺任一不评
 （字段为 None
    recall@10"的口径，本实现两者都给，不静默二选一）。
    """
    per_item: List[Dict[str, Any]] = []
    judge_scores: List[float] = []
    for it in dataset.get("items") or []:
        query = str(it.get("query") or "")
        retrieved = [str(c) for c in retrieve_fn(query, int(top_k))]
        m = rag_metrics(set(it.get("gold_chunk_ids") or []), retrieved, k_list)
        row: Dict[str, Any] = {
            "item_id": it.get("item_id"),
            "query": query,
            "retrieved_chunk_ids": retrieved,
            "metrics": m,
            "judge_score": None,
        }
        gold_answer = it.get("gold_answer")
        if judge_fn is not None and gold_answer:
            context = "\n".join(retrieved)
            score = judge_fn(query, str(gold_answer), context)
            score = 1.0 if score in (1, True, "1", "true") else 0.0
            row["judge_score"] = score
            judge_scores.append(score)
        per_item.append(row)

    means: Dict[str, float] = {}
    if per_item:
        keys = set()
        for r in per_item:
            keys.update(r["metrics"].keys())
        for key in sorted(keys):
            vals = [r["metrics"][key] for r in per_item if key in r["metrics"]]
            if vals:
                means[key] = round(sum(vals) / len(vals), 6)
    if judge_scores:
        means["judge"] = round(sum(judge_scores) / len(judge_scores), 6)
    return {
        "dataset_id": dataset.get("id"),
        "dataset_name": dataset.get("name"),
        "top_k": int(top_k),
        "n_items": len(per_item),
        "mean": means,
        "per_item": per_item,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
