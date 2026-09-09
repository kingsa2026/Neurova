"""ONNX 编码器懒初始化死锁回归测试

事故：2026-09-10 01:08，服务重启后聊天请求触发记忆批量编码，ONNX 编码器
因"事件循环在跑→无法同步初始化"永远降级 TF-IDF，一分钟内 1035 次纯 Python
TF-IDF 全量重算把 CPU 打满。

根因链（修复前）：
1. UnifiedVectorStore._encode_uncached 的 onnx 分支在检测到运行中的事件循环
   时直接放弃初始化、降级 TF-IDF；
2. initialize_encoder() 全仓无调用方（死代码）；
3. encode_batch() 未初始化时静默返回零向量（semantic_search / vector_index
   拿到的是质量腐坏的向量）。
"""
import pytest

np = pytest.importorskip("numpy")


@pytest.fixture
def store():
    from neurova.cognitive_layers.memory_layer.unified_vector_store import (
        UnifiedVectorStore,
    )

    s = UnifiedVectorStore(backend="onnx")
    yield s
    # 不 cleanup：store 无需显式关闭


class TestEncodeInsideEventLoop:
    """核心事故场景：事件循环内直接 encode，不得降级 TF-IDF"""

    @pytest.mark.asyncio
    async def test_encode_in_loop_uses_onnx_not_tfidf(self, store):
        """在事件循环内 encode：必须懒初始化 ONNX 并用真实模型编码，
        不得走"循环在跑→降级 TF-IDF"分支（事故根因）"""
        assert store.backend == "onnx"
        # 未预初始化，直接在事件循环内 encode —— 事故触发路径
        vec = store.encode("今晚吃什么好呢")
        assert store._encoder is not None
        assert store._encoder.is_initialized, (
            "事件循环内 encode 后编码器仍未初始化 —— 懒初始化死锁未修复"
        )
        assert len(vec) == 512
        assert any(v != 0.0 for v in vec), "全零向量说明走了未初始化兜底"

    @pytest.mark.asyncio
    async def test_encode_in_loop_not_tfidf_dimension(self, store):
        """TF-IDF 维度取决于词汇表（或 100 兜底），ONNX 固定 512。
        维度即可区分是否降级。"""
        vec = store.encode("另一个测试文本")
        assert len(vec) == 512

    @pytest.mark.asyncio
    async def test_encode_cacheable_after_loop_init(self, store):
        """初始化成功后 encode 结果应可入进程级缓存（事故中缓存被永久禁用
        导致每轮对话全量重算）"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import (
            _cacheable_vector,
        )

        store.encode("缓存判定文本")
        assert _cacheable_vector("onnx", store._encoder), (
            "编码器初始化后 _cacheable_vector 仍为 False，进程级缓存将持续失效"
        )


class TestEngineLazyInit:
    """引擎层契约：encode 遇未初始化应自救，不应静默返回零向量"""

    @pytest.mark.asyncio
    async def test_engine_encode_lazy_initializes(self):
        """engine.encode() 未初始化时必须先初始化，不得返回全零向量"""
        from neurova.embedding import ONNXEmbeddingEngine

        engine = ONNXEmbeddingEngine(auto_download=False)
        vec = engine.encode("回归测试文本")
        assert engine.is_initialized, "engine.encode 未触发懒初始化"
        assert len(vec) == engine.dimension
        assert any(v != 0.0 for v in vec)

    @pytest.mark.asyncio
    async def test_engine_encode_batch_lazy_initializes(self):
        """encode_batch 同样适用懒初始化"""
        from neurova.embedding import ONNXEmbeddingEngine

        engine = ONNXEmbeddingEngine(auto_download=False)
        result = engine.encode_batch(["文本一", "文本二"])
        assert engine.is_initialized
        assert len(result.vectors) == 2

    @pytest.mark.asyncio
    async def test_engine_initialize_sync_equivalent(self):
        """同步初始化入口与异步 initialize() 契约等价（假异步收编）"""
        from neurova.embedding import ONNXEmbeddingEngine

        engine = ONNXEmbeddingEngine(auto_download=False)
        ok = engine.initialize_sync()
        assert ok is True
        assert engine.is_initialized

    @pytest.mark.asyncio
    async def test_unified_store_initialize_encoder_uses_sync(self):
        """UnifiedVectorStore.initialize_encoder（现有唯一显式初始化口）
        在事件循环内也应真正完成初始化，而非依赖死锁路径"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import (
            UnifiedVectorStore,
        )

        store = UnifiedVectorStore(backend="onnx")
        ok = await store.initialize_encoder()
        assert ok is True
        assert store._encoder.is_initialized
