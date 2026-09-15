# -*- coding: utf-8 -*-
"""RAG 评估执行器。

前车之鉴反向设计：**gold_chunk_ids 用 `knowledge_id#chunk_index`**——NV 分片
索引既有块 id，重新分块只影响条目内部（条目 id 稳定）
`{file_id}_chunk_{idx}` 那样重分块即废数据集。
LLM 相关能力（出题/Judge）为注入式，无注入如实报错不伪造。
"""
import json
from pathlib import Path

import pytest

from neurova.benchmark import rag_eval as re5
from neurova.benchmark.rag_eval import (
    evaluate_dataset,
    rag_metrics,
    save_dataset,
    load_datasets,
    delete_dataset,
)


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RAG_EVAL_DATASETS", str(tmp_path / "rag_datasets.json"))
    yield


def _hit_ids(query, top_k=10):
    """stub 检索器：按查询词返回有序 chunk ids。"""
    table = {
        "q1": ["kA#0", "kB#2", "kA#1"],       # gold {kA#0} → rank1 命中
        "q2": ["kX#0", "kY#1"],                # gold {kZ#0} → 未命中
    }
    return table.get(query, [])[:top_k]


# ── metrics ────────────────────────────────────────────────────────

def test_metrics_at_k_values():
    m = rag_metrics({"kA#0"}, ["kA#0", "kB#2", "kA#1"], k_list=(1, 3, 5))
    assert m["precision@1"] == 1.0 and m["recall@1"] == 1.0
    assert m["precision@3"] == pytest.approx(1 / 3)
    assert m["recall@3"] == 1.0
    assert m["f1@3"] == pytest.approx(2 * (1 / 3) * 1 / (1 / 3 + 1))


def test_metrics_miss_all_zero():
    m = rag_metrics({"kZ#0"}, ["kX#0"], k_list=(1,))
    assert m["precision@1"] == 0.0 and m["recall@1"] == 0.0 and m["f1@1"] == 0.0


def test_metrics_empty_gold_none():
    assert rag_metrics(set(), ["a"], k_list=(1,)) == {}


# ── dataset CRUD ───────────────────────────────────────────────────

def test_dataset_crud_roundtrip():
    ds = save_dataset({
        "name": "smoke",
        "description": "d",
        "items": [{"query": "q1", "gold_chunk_ids": ["kA#0"], "gold_answer": "A"}],
    })
    assert ds["id"]
    loaded = load_datasets()
    assert [d["id"] for d in loaded] == [ds["id"]]
    assert delete_dataset(ds["id"]) is True
    assert load_datasets() == []
    assert delete_dataset("nope") is False


# ── evaluator ──────────────────────────────────────────────────────

def test_evaluate_dataset_mean_and_items():
    ds = {
        "id": "d1", "name": "two-questions",
        "items": [
            {"item_id": "i1", "query": "q1", "gold_chunk_ids": ["kA#0"], "gold_answer": "A"},
            {"item_id": "i2", "query": "q2", "gold_chunk_ids": ["kZ#0"], "gold_answer": None},
        ],
    }
    report = evaluate_dataset(ds, _hit_ids, top_k=3, k_list=(1, 3))
    assert report["n_items"] == 2
    # q1 全对、q2 全错 → recall@1 均值 0.5
    assert report["mean"]["recall@1"] == pytest.approx(0.5)
    per = {p["item_id"]: p for p in report["per_item"]}
    assert per["i1"]["retrieved_chunk_ids"] == ["kA#0", "kB#2", "kA#1"]
    assert per["i2"]["metrics"]["recall@3"] == 0.0
    # 报告 JSON 可序列化
    json.dumps(report, ensure_ascii=False)


def test_evaluate_dataset_optional_llm_judge():
    ds = {
        "id": "d2", "name": "j",
        "items": [{"item_id": "i1", "query": "q1", "gold_chunk_ids": [], "gold_answer": "标准答案"}],
    }
    calls = []

    def judge(question, expected, actual):
        calls.append((question, expected, actual))
        return 1

    report = evaluate_dataset(ds, _hit_ids, judge_fn=judge)
    assert calls and report["per_item"][0]["judge_score"] == 1
    assert report["mean"]["judge"] == 1.0


def test_evaluate_dataset_no_judge_when_no_gold_answer():
    ds = {"id": "d3", "name": "n", "items": [{"item_id": "i1", "query": "q1", "gold_chunk_ids": ["x"]}]}
    report = evaluate_dataset(ds, _hit_ids, judge_fn=lambda *a: 1)
    assert report["per_item"][0].get("judge_score") is None


# ── 自动出题 ───────────────────────────────────────────────────────

def test_generate_items_requires_llm_honest():
    from neurova.benchmark.rag_dataset_gen import generate_items

    result = generate_items(items=[], sample_n=2, llm_fn=None)
    assert "error" in result  # 无 LLM 如实报错，不伪造题目


def test_generate_items_builds_dataset_from_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RAG_EVAL_DATASETS", str(tmp_path / "rag_datasets.json"))
    from neurova.benchmark.rag_dataset_gen import generate_items

    items = [
        {"knowledge_id": "kA", "title": "T", "content": "甲乙丙", "chunks": [
            {"char_start": 0, "char_end": 1}, {"char_start": 1, "char_end": 2}, {"char_start": 2, "char_end": 3},
        ]},
    ]

    def fake_llm(prompt: str) -> str:
        assert "块内容" in prompt or "chunk" in prompt.lower()
        return json.dumps({"question": "这是问题？", "answer": "这是回答"})

    out = generate_items(items=items, sample_n=2, llm_fn=fake_llm)
    assert out["dataset"]["items"]
    for row in out["dataset"]["items"]:
        assert row["gold_chunk_ids"] and all("#" in c for c in row["gold_chunk_ids"])
        assert row["query"] and row["gold_answer"]
    assert out["generated"] <= out["sampled"]
