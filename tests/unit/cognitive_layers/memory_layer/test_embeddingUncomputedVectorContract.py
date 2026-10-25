import pytest

pytest.importorskip("numpy")


def _engine():
    from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine
    return ONNXEmbeddingEngine()


class TestEngineOwnsTheNotComputedVerdict:
    def test_未就绪的引擎不把零向量当向量交出去(self, monkeypatch):
        engine = _engine()
        monkeypatch.setattr(engine, "_initialized", False)

        def _never(_text):
            return [0.0] * engine._dimension

        monkeypatch.setattr(engine, "encode", _never)
        assert engine.encodeOrNone("许昌明天天气怎么样") is None

    def test_真向量照原样交出(self, monkeypatch):
        engine = _engine()
        monkeypatch.setattr(engine, "_dimension", 8)
        vec = [0.0] * 8
        vec[0] = 0.25
        monkeypatch.setattr(engine, "encode", lambda _t: list(vec))
        assert engine.encodeOrNone("许昌明天天气怎么样") == vec


class TestMuscleMemoryDoesNotStoreAnUncomputedVector:
    def test_未就绪的引擎不写向量也不冒充成命中(self, monkeypatch):
        from neurova.cognitive_layers.memory_layer import muscle_memory

        zeroed = type("ZeroEngine", (), {
            "encode": lambda self, _t: [0.0] * 8,
            "encodeOrNone": lambda self, _t: None,
        })()
        monkeypatch.setattr(muscle_memory, "_get_engine", lambda: zeroed)
        memory = muscle_memory.MuscleMemory()
        item = memory.record_usage(
            tool_name="weather", query="许昌今天天气怎么样",
            parameters={"location": "许昌"}, success=True,
        )
        assert "query_embedding" not in item.metadata, (
            f"引擎没给向量却被写进条目：{item.metadata.get('query_embedding')}")
        matches = memory.match_by_query("许昌明天天气怎么样")
        assert matches, "零向量冒充向量后，近似问法当场判死"
        assert matches[0][1] >= 0.85, f"近似问法的置信度掉到 {matches[0][1]}"

    def test_存量条目里的零向量不算向量(self, monkeypatch):
        from neurova.cognitive_layers.memory_layer import muscle_memory

        zeroed = type("ZeroEngine", (), {
            "encode": lambda self, _t: [0.0] * 8,
            "encodeOrNone": lambda self, _t: None,
        })()
        monkeypatch.setattr(muscle_memory, "_get_engine", lambda: zeroed)
        memory = muscle_memory.MuscleMemory()
        item = memory.record_usage(
            tool_name="weather", query="许昌今天天气怎么样",
            parameters={"location": "许昌"}, success=True,
        )
        item.metadata["query_embedding"] = [0.0] * 512  # 上一版本留在盘上的形状
        matches = memory.match_by_query("许昌明天天气怎么样")
        assert matches and matches[0][1] >= 0.85, (
            f"存量零向量把近似问法判死了：{matches}")


class TestToolSearchFallsBackToLexicalWhenEngineCannotEncode:
    def test_引擎缺档时词面那一路仍然命中(self, monkeypatch):
        from neurova.context import tool_search

        zeroed = type("ZeroEngine", (), {
            "encode": lambda self, _t: [0.0] * 8,
            "encodeOrNone": lambda self, _t: None,
        })()
        monkeypatch.setattr(tool_search, "_get_engine", lambda: zeroed)
        entries = tool_search.build_catalog([{
            "type": "function",
            "function": {
                "name": "mcp.weather.lookup",
                "description": "查询天气",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }])
        hits = tool_search.search_catalog("查询天气", entries)
        assert hits, "引擎缺档时混合检索把词面命中一并吞了"
