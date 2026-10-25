"""T3 语义混合检索 —。

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

    def encodeOrNone(self, text: str):
        """引擎那一处的判据口（`ONNXEmbeddingEngine.encodeOrNone` 的契约）：算得出才给向量。"""
        return self.encode(text)


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


# ── 词表口径（§6-419）：中文不能整段当一个 token ──


class TestCjkLexicalFallback:
    """引擎缺席/回零向量时回落 BM25——回落得有一条能命中的词表。

    改前 `_TOKEN_SPLIT` 对中文是无操作：「查询天气」是一条词、「天气」是另一条，
    两者永不相等。目录里明明有天气工具，查「天气」零命中；而零命中在生产侧会被
    `handle_control_tool` 投递成「能力缺口」并驱动自主造工具——词表口径的缺陷被
    翻译成了一个假缺口（实测：`test_hitSearch_doesNotRecordGap` 的前提当场塌掉）。
    """

    def testChineseIsSplitIntoRunsTheQueryCanMatch(self):
        tokens = ts._tokenize("查询天气")
        assert "天气" in tokens, f"「查询天气」切不出「天气」：{tokens}"
        assert ts._tokenize("天气") == ["天气"]

    def testLatinAndDigitsStayWholeTokens(self):
        assert ts._tokenize("mcp weather lookup x1") == ["mcp", "weather", "lookup", "x1"]

    def testSingleCharacterCjkRunIsNotAWord(self):
        """单字段只剩噪声，不进词表（与 `knowledge.search.tokenize` 的下限同口径）。"""
        assert ts._tokenize("a 天 b") == ["a", "b"]

    def testSearchFallsBackToBm25WhenTheEngineGivesNoVector(self, isolated_index, monkeypatch):
        """引擎算不出向量时，检索必须整体回落 BM25。

        `ONNXEmbeddingEngine.encodeOrNone()` 是"这一轮算没算出向量"的唯一判定处：引擎缺档
        （`requirements-ci.txt` 刻意不含 onnxruntime/tokenizers）时它给 None。`_hybrid_scores`
        若照旧拿"一列 0"进语义加权，余弦那一支恒 0 却仍参与，检索读数就随"装没装 tokenizer"变。
        """

        catalog = ts.build_catalog([
            {"type": "function", "function": {"name": "mcp.weather.lookup",
              "description": "查询天气", "parameters": {"type": "object", "properties": {}}}},
        ])

        class UnreadyEngine:
            """查询算不出；条目照常编码（引擎半可用是常态，不是二值）。"""

            def encode(self, text):
                return [1.0] + [0.0] * 7

            def encodeOrNone(self, text):
                return None if text == "天气" else self.encode(text)

        monkeypatch.setattr(ts, "_get_engine", lambda: UnreadyEngine())
        assert ts._hybrid_scores("天气", catalog) is None, (
            "引擎没给向量却仍进了语义加权：余弦那一支恒 0，检索读数随装没装 tokenizer 变"
        )
        assert ts.search_catalog("天气", catalog, limit=1)[0]["name"] == "mcp.weather.lookup", (
            "回落之后检索仍是空手——零命中在生产侧会被投递成能力缺口"
        )

        class ReadyEngine(UnreadyEngine):
            def encodeOrNone(self, text):
                return self.encode(text)

        # 反向控制：同一坐标下引擎算得出时，语义那一路必须真的进场
        monkeypatch.setattr(ts, "_get_engine", lambda: ReadyEngine())
        assert ts._hybrid_scores("天气", catalog) is not None
