"""T4 语义置信 — docs/Neurova_工具调用链升级计划_2026-09-13.md。

钉五件事：record_usage 存语义向量；高余弦给向量分；低余弦回落 MD5 等值分支；
余弦低且 MD5 不符不加分（防误自动执行）；开关关时逐位等旧行为。
"""
import math

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import (
    MuscleMemory,
    MuscleMemoryItem,
    MemoryLevel,
)


class FakeEngine:
    """字符散列归一化假引擎（8 维，确定性）。"""

    dimension = 8

    def encode(self, text: str):
        v = [0.0] * 8
        for ch in set(text):
            v[ord(ch) % 8] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


@pytest.fixture(autouse=True)
def _engine_on(monkeypatch):
    monkeypatch.setenv("NEUROVA_MUSCLE_SEMANTIC", "1")
    import neurova.cognitive_layers.memory_layer.muscle_memory as mm

    monkeypatch.setattr(mm, "_get_engine", lambda: FakeEngine())


def _item(**kw) -> MuscleMemoryItem:
    base = dict(id="x1", tool_name="weather", query_fingerprint="北京,天气",
                vector_fingerprint="md5fp", level=MemoryLevel.L3)
    base.update(kw)
    return MuscleMemoryItem(**base)


def test_record_stores_semantic_vector():
    mem = MuscleMemory()
    item = mem.record_usage("weather", "查询北京的天气", {"city": "北京"}, True)
    assert item.metadata.get("query_embedding")


def test_high_cosine_gets_vector_credit():
    mem = MuscleMemory()
    item = _item(metadata={"query_embedding": [1.0] + [0.0] * 7})
    conf = mem._compute_confidence(item, "北京,天气", "other-md5",
                                   query_emb=[0.99, 0.14] + [0.0] * 6)
    # cos≈0.999 → (0.999-0.75)/0.2 封顶 → 向量满档 0.3；关键词全等 +0.6
    assert conf == pytest.approx(0.9)


def test_low_cosine_falls_back_to_md5_equality():
    mem = MuscleMemory()
    item = _item(metadata={"query_embedding": [1.0] + [0.0] * 7})
    conf = mem._compute_confidence(item, "北京,天气", "md5fp",
                                   query_emb=[0.0, 1.0] + [0.0] * 6)
    # cos=0 ≤0.75 → 走 MD5 等值分支（vector_fp 相等 +0.3）
    assert conf == pytest.approx(0.9)


def test_low_cosine_wrong_md5_gets_nothing():
    mem = MuscleMemory()
    item = _item(metadata={"query_embedding": [1.0] + [0.0] * 7})
    conf = mem._compute_confidence(item, "北京,天气", "wrong-fp",
                                   query_emb=[0.0, 1.0] + [0.0] * 6)
    assert conf == pytest.approx(0.6)  # 语义两分支皆不加分


def test_switch_off_is_bitwise_identical(monkeypatch):
    monkeypatch.setenv("NEUROVA_MUSCLE_SEMANTIC", "0")
    mem = MuscleMemory()
    item = _item(metadata={"query_embedding": [1.0] + [0.0] * 7})
    emb = [0.99, 0.14] + [0.0] * 6
    assert mem._compute_confidence(item, "北京,天气", "md5fp", query_emb=emb) == \
        mem._compute_confidence(item, "北京,天气", "md5fp")


def test_record_then_match_full_confidence():
    mem = MuscleMemory()
    mem.record_usage("weather", "北京天气", {"city": "北京"}, True)
    hits = mem.match("weather", "北京天气", top_k=1)
    assert hits and hits[0][1] >= 0.9  # 全等 fp + 语义满档 + 成功率 0.1
