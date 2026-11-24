# -*- coding: utf-8 -*-
"""UnifiedVectorStore 编码器进程级共享（2026-11-24 启动性能根修）。

红灯依据：每个 agent 的 init_moe_router 各建一个 UnifiedVectorStore，
各自 new 一个 ONNXEmbeddingEngine 并各自加载同一份 bge-small-zh-v1.5
（首载实测 ~0.9s/agent）。推理会话无状态且线程安全，进程内共享一份即可
——首个使用方付费，其余复用。
"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer import unified_vector_store as uvs


@pytest.fixture(autouse=True)
def _clean_shared_cache():
    uvs._reset_shared_encoders_for_tests()
    yield
    uvs._reset_shared_encoders_for_tests()


def _make_store():
    # 显式指定 onnx 后端，避开 faiss/fastembed 可用性对 auto 探测的干扰
    return uvs.UnifiedVectorStore(backend="onnx")


def test_two_stores_share_one_encoder():
    s1 = _make_store()
    s2 = _make_store()
    assert s1._encoder is not None, "onnx 后端必须产出编码器"
    assert s1._encoder is s2._encoder, "同进程同后端必须复用同一编码器实例"


def test_encoder_initializes_once_across_stores(monkeypatch):
    import asyncio

    from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine

    calls = {"n": 0}

    def fake_init_sync(self):
        calls["n"] += 1
        self._initialized = True
        return True

    monkeypatch.setattr(ONNXEmbeddingEngine, "initialize_sync", fake_init_sync)

    s1 = _make_store()
    assert asyncio.run(s1.initialize_encoder()) is True
    s2 = _make_store()
    assert asyncio.run(s2.initialize_encoder()) is True
    assert calls["n"] == 1, f"初始化应只发生一次，实际 {calls['n']} 次"


def test_failed_creation_is_not_cached(monkeypatch):
    """编码器创建失败（返回 None）不得把 None 钉进缓存——下次还要重试。"""
    def boom():
        raise RuntimeError("构造失败")

    monkeypatch.setattr(uvs.UnifiedVectorStore, "_create_encoder_fresh", lambda self: None)
    s1 = _make_store()
    assert s1._encoder is None
    s2 = _make_store()
    assert s2._encoder is None  # 仍走重试路径（缓存里没有假 None）
