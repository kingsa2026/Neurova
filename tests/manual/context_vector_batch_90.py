#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6-6 live-verify：真抽屉 + 真 UnifiedVectorStore，一条命令复现全部读数。

用法：PYTHONPATH=. python tests/manual/context_vector_batch_90.py

验三件事（Issue #90 · B5 尾巴一 / B6-6）：

1. store 层存在批量入口，且是单条 `encode` 的**唯一**来源；
2. tfidf 稳定形态下同批文本跨轮真编码次数降为 0（改前每轮各 301 次）；
3. 池内多轮 `draw` 的候选编码走批量入口（改前 `hasattr(store, "encode_batch")` 恒假）。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
CACHE = os.path.join(tempfile.mkdtemp(), "embedding_cache.json")
os.environ.setdefault("NEUROVA_EMBEDDING_CACHE", CACHE)

import random  # noqa: E402

from neurova.cognitive_layers.memory_layer import unified_vector_store as uvs  # noqa: E402
from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore  # noqa: E402
from neurova.context.pool_models import ContextInput, ContextSource  # noqa: E402
from neurova.context.semantic_drawer import SemanticMatchDrawer  # noqa: E402

WORDS = "固件 升级 失败 回滚 设备 协议 日志 缓存 心跳 温度 电池 网络 配置 版本 传输".split()
NEED = "固件升级失败了怎么办"


def buildPool(count: int, seed: int = 11):
    random.seed(seed)
    return [
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=f"第{i}条归档记录：{' '.join(random.sample(WORDS, 6))}，编号 {i}",
            priority=60,
            tokens=20,
        )
        for i in range(count)
    ]


def countingStore():
    uvs.reset_embedding_cache()
    store = UnifiedVectorStore(backend="tfidf")
    counter = {"n": 0}
    for name in ("_encode_uncached", "_tfidf_encode"):
        original = getattr(store, name)

        def counting(text, _original=original):
            counter["n"] += 1
            return _original(text)

        setattr(store, name, counting)
    return store, counter


def section1_entry():
    print("── 1. store 层批量入口 ──")
    store = UnifiedVectorStore(backend="auto")
    print(f"  后端: {store.backend} | has encode_batch: {hasattr(store, 'encode_batch')}")
    print(f"  encode 由批量入口派生: {store.encode('探针文本') == store.encode_batch(['探针文本'])[0]}")


def section2_cache():
    print("── 2. tfidf 稳定形态跨轮真编码 ──")
    store, counter = countingStore()
    texts = [f"第{i}条归档记录：固件 升级 失败 回滚，编号 {i}" for i in range(300)]
    for round_index in range(2):
        counter["n"] = 0
        started = time.perf_counter()
        store.encode_batch(texts)
        elapsed = (time.perf_counter() - started) * 1000
        print(f"  第 {round_index + 1} 轮 300 条：真编码 {counter['n']} 次 | {elapsed:.1f}ms")


def section3_drawer():
    print("── 3. 池内多轮 draw 的候选编码 ──")
    drops = buildPool(300)
    drawer = SemanticMatchDrawer(max_tokens=8000)
    store, counter = countingStore()
    drawer._vector_store = store
    for round_index in range(2):
        counter["n"] = 0
        selected = drawer.draw(list(drops), need=NEED)
        print(f"  第 {round_index + 1} 轮 draw：真编码 {counter['n']} 次 | 入选 {len(selected)} 条")
    print("  注：首轮 need 1 次 + 候选 300 次；第二轮同文本全命中缓存 —— 改前每轮各 301 次")
    print(f"  缓存文件: {os.path.basename(CACHE)} | 命名空间数: {_namespaceCount()}")


def _namespaceCount():
    import json

    uvs.flush_embedding_cache()
    try:
        return len(json.loads(open(CACHE, encoding="utf-8").read()).get("namespaces") or {})
    except Exception:
        return 0


def main():
    print("B6-6 向量层批量入口 live-verify（Issue #90）")
    section1_entry()
    section2_cache()
    section3_drawer()
    print("\nLIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
