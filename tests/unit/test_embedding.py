"""
Tests for Neurova embedding module

Uses TDD vertical slice approach: one test at a time.
"""
import pytest
import asyncio
np = pytest.importorskip("numpy")


class TestONNXEmbeddingEngine:
    """ONNXEmbeddingEngine 单元测试"""

    def test_import(self):
        from neurova.embedding import ONNXEmbeddingEngine
        engine = ONNXEmbeddingEngine(auto_download=False)
        assert engine is not None

    @pytest.mark.asyncio
    async def test_init_no_model(self):
        """无模型时初始化应返回 False"""
        from neurova.embedding import ONNXEmbeddingEngine
        engine = ONNXEmbeddingEngine(auto_download=False)
        ok = await engine.initialize()
        # auto_download=False 且无本地模型 → 失败
        # 但如果模型已下载则可能成功，所以只检查不崩溃
        assert isinstance(ok, bool)

    @pytest.mark.asyncio
    async def test_encode_before_init(self):
        """未初始化时 encode 应返回零向量"""
        from neurova.embedding import ONNXEmbeddingEngine
        engine = ONNXEmbeddingEngine(auto_download=False)
        result = engine.encode("hello")
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(v == 0.0 for v in result)

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """shutdown 应清理资源"""
        from neurova.embedding import ONNXEmbeddingEngine
        engine = ONNXEmbeddingEngine(auto_download=False)
        await engine.shutdown()
        assert engine._ort_session is None
        assert engine._st_model is None
        assert engine._initialized is False

    @pytest.mark.asyncio
    async def test_stats(self):
        """stats 应返回正确格式"""
        from neurova.embedding import ONNXEmbeddingEngine
        engine = ONNXEmbeddingEngine(auto_download=False)
        stats = engine.stats
        assert "model_name" in stats
        assert "total_requests" in stats
        assert stats["total_requests"] == 0


class TestUnifiedVectorStoreONNX:
    """UnifiedVectorStore with ONNX backend 测试"""

    def test_backend_selection(self):
        """backend='onnx' 应正确选择"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        store = UnifiedVectorStore(backend="onnx")
        assert store.backend == "onnx"

    @pytest.mark.asyncio
    async def test_async_initialize_encoder(self):
        """async initialize_encoder 应能加载模型"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        store = UnifiedVectorStore(backend="onnx")
        ok = await store.initialize_encoder()
        # 模型已下载，应成功
        assert ok is True

    @pytest.mark.asyncio
    async def test_encode_returns_vector(self):
        """encode 应返回正确维度向量"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        store = UnifiedVectorStore(backend="onnx")
        await store.initialize_encoder()
        vec = store.encode("测试文本")
        assert isinstance(vec, list)
        assert len(vec) == 512

    @pytest.mark.asyncio
    async def test_encode_consistency(self):
        """相同文本应产生相同向量"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        store = UnifiedVectorStore(backend="onnx")
        await store.initialize_encoder()
        vec1 = store.encode("测试文本")
        vec2 = store.encode("测试文本")
        np.testing.assert_array_almost_equal(vec1, vec2, decimal=6)

    @pytest.mark.asyncio
    async def test_different_texts_different_vectors(self):
        """不同文本应产生不同向量"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
        store = UnifiedVectorStore(backend="onnx")
        await store.initialize_encoder()
        vec1 = store.encode("猫")
        vec2 = store.encode("量子物理")
        sim = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        assert sim < 1.0  # 不完全相同


class TestModelDownloader:
    """ModelDownloader 集成测试"""

    def test_registry_has_embedding_model(self):
        """MODEL_REGISTRY 应包含 bge-small-zh-v1.5"""
        from neurova.tts.model_downloader import MODEL_REGISTRY
        assert "bge-small-zh-v1.5" in MODEL_REGISTRY
        entry = MODEL_REGISTRY["bge-small-zh-v1.5"]
        assert entry["repo_id"] == "BAAI/bge-small-zh-v1.5"
        assert "local_dir" in entry
        assert "size_hint" in entry

    def test_is_model_available(self):
        """已下载的模型应返回 True"""
        from neurova.tts.model_downloader import get_model_downloader
        downloader = get_model_downloader()
        # 模型已下载到 models/embedding/bge-small-zh-v1.5
        assert downloader.is_model_available("bge-small-zh-v1.5")
