"""T3 语义混合检索 — docs/Neurova_工具调用链升级计划_2026-09-13.md。

钉四件事：无引擎=纯BM25零回归；有引擎=语义近但词面不交的条目上位；
模型指纹一致复用持久索引不重嵌目录；条目内容变更只重嵌该条。
"""
import json
import math

import pytest

from neurova.context import tool_search as ts


class FakeEngine:
    """字符 one-hot 的确定性假引擎（归一化输出，同 ONNX 引擎语义）。"""

    dimension = 512

    def __init__(self):
        self.encode_calls: list[str] = []

    def encode(self, text: str):
        self.encode_calls.append(text)
        vec = [0.0] * 512
        for ch in set(text):
            vec[ord(ch) % 512] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


@pytest.fixture
def entries():
    return ts.build_catalog([
        {"type": "function", "function": {"name": "weather_lookup",
          "description": "查询指定城市的实时天气与温度",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "file_write",
          "description": "写入文件内容到指定路径",
          "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}}}},
    ])


@pytest.fixture
def isolated_index(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "_INDEX_PATH", str(tmp_path / "idx.json"))


def test_no_engine_falls_back_to_bm25_unchanged(entries, isolated_index, monkeypatch):
    # 查询用 "weather"（词法 token 命中 name）；整句中文描述在本 BM25 分词下
    # 是单 token，不能用"天气"二字测词法回落——那正是 T3 语义要解决的层
    monkeypatch.setattr(ts, "_get_engine", lambda: None)
    hits = ts.search_catalog("weather", entries, limit=2)
    assert hits and hits[0]["name"] == "weather_lookup"


def test_semantic_lifts_keyword_disjoint_match(entries, isolated_index, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(ts, "_get_engine", lambda: eng)
    # "气温如何" 与两目录条目的词法 token 均无交集，仅字符嵌入对 weather 条目有重叠
    hits = ts.search_catalog("气温如何", entries, limit=1)
    assert hits and hits[0]["name"] == "weather_lookup"


def test_fingerprint_reuse_skips_reembed(entries, isolated_index, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(ts, "_get_engine", lambda: eng)
    ts.search_catalog("气温如何", entries, limit=1)
    assert len(eng.encode_calls) == 3, "首跑应嵌 1 查询 + 2 目录条目"
    first = len(eng.encode_calls)
    ts.search_catalog("气温如何", entries, limit=1)
    assert len(eng.encode_calls) - first == 1, "二跑仅重嵌查询，目录向量命中持久索引"


def test_schema_change_reembeds_only_changed(entries, isolated_index, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(ts, "_get_engine", lambda: eng)
    ts.search_catalog("weather", entries, limit=1)
    base = len(eng.encode_calls)
    entries2 = json.loads(json.dumps(entries))
    entries2[0]["description"] = "查询天气预报（含空气质量）"  # 仅改 weather 条目
    ts.search_catalog("weather", entries2, limit=1)
    delta = len(eng.encode_calls) - base
    assert delta <= 2, f"只应重嵌变化条目+查询，实际 {delta} 次"


def test_env_off_forces_pure_bm25(entries, isolated_index, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setattr(ts, "_get_engine", lambda: eng)
    monkeypatch.setenv("NEUROVA_TOOL_SEARCH_EMBEDDING", "0")
    ts.search_catalog("气温如何", entries, limit=1)
    assert eng.encode_calls == [], "开关关闭时不得调用任何嵌入"
