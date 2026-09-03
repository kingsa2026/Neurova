"""孤岛引擎接入主链路的集成测试

背景（2026-08-29 梳理）：compression/vector_search/graph 三组引擎文件存在
但主链路从不实例化（孤岛）。本测试锁定三个接入点的行为契约：

1. MemoryCompressor：压缩结果 details 必须包含可安全写回的操作明细（groups）
2. MemoryManager.compress_low_value_memories：压缩运维入口（dry_run 默认安全）
3. MoEMemoryRouter L0 缓存上限：vector_search.cache_max_size 修复无限增长
4. MemoryManager.traverse_relations：GraphTraversal + graph.min_strength 接入
"""

import uuid
from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.settings_config import (
    get_memory_settings,
    MemorySettingsConfig,
)


@pytest.fixture
def settings(tmp_path):
    MemorySettingsConfig.reset_instance()
    cfg = get_memory_settings(str(tmp_path))
    yield cfg
    MemorySettingsConfig.reset_instance()


def _make_manager(agent_id="engine_it"):
    unique = f"{agent_id}_{uuid.uuid4().hex[:8]}"
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(db_path=":memory:", agent_id=unique)


# ============================================================
# 1. MemoryCompressor details 明细
# ============================================================


class TestCompressorDetails:
    def test_semantic_compression_returns_groups(self):
        """compress 的 details 必须给出每组的 keep_id/member_ids/merged_content，
        否则调用方无法安全写回（不知道删谁留谁）"""
        from neurova.cognitive_layers.memory_layer.compression import (
            MemoryCompressor,
            CompressionStrategy,
        )

        compressor = MemoryCompressor(
            storage=None,
            llm_client=None,
            config={"similarity_threshold": 0.3},
        )
        memories = [
            {"id": "m1", "content": "团队周报 项目进度 本周完成登录模块", "importance": 10.0},
            {"id": "m2", "content": "团队周报 项目进度 本周完成登录模块 开发", "importance": 20.0},
            {"id": "m3", "content": "团队周报 项目进度 登录模块 联调", "importance": 30.0},
        ]
        result = compressor.compress(memories, strategy=CompressionStrategy.SEMANTIC)

        assert result.merged_count >= 1, "相似记忆应被合并"
        groups = result.details.get("groups")
        assert groups, "details 缺少 groups 操作明细"
        for g in groups:
            assert "keep_id" in g and "member_ids" in g and "merged_content" in g
            assert g["keep_id"] in g["member_ids"], "keep 必须是组成员"
        # keep 应是组内 importance 最高的成员
        top = max(groups, key=lambda g: 0)  # 至少一组存在
        assert any(g["keep_id"] == "m3" for g in groups), "keep 应为 importance 最高者"


# ============================================================
# 2. manager 压缩运维入口
# ============================================================


class TestManagerCompression:
    def _seed(self, mgr):
        low = []
        for i, imp in enumerate((1.0, 2.0, 3.0)):
            mid = mgr.remember(
                f"团队周报 项目进度 重复内容变体 {i}", temperature=30.0, importance=imp
            )
            low.append(mid)
        high = mgr.remember("核心 重要记忆 不应被压缩", temperature=80.0, importance=90.0)
        return low, high

    def test_dry_run_does_not_mutate(self, settings):
        """dry_run（默认）只返回计划，不改任何数据"""
        settings.update({"compression.importance_threshold": 0.05})
        mgr = _make_manager()
        low, high = self._seed(mgr)
        before = {mid: mgr._memories[mid].lifecycle_stage for mid in low + [high]}

        report = mgr.compress_low_value_memories(dry_run=True)

        after = {mid: mgr._memories[mid].lifecycle_stage for mid in low + [high]}
        assert after == before, "dry_run 不得修改数据"
        assert report["dry_run"] is True

    def test_execute_merges_low_value_group(self, settings):
        """执行模式：低重要性相似组被合并——keep 保留新内容，成员软删"""
        settings.update(
            {
                "compression.importance_threshold": 0.05,
                "compression.similarity_threshold": 0.3,
            }
        )
        mgr = _make_manager()
        low, high = self._seed(mgr)

        report = mgr.compress_low_value_memories(dry_run=False)

        assert report["dry_run"] is False
        # 高重要性记忆不受影响
        assert mgr._memories[high].lifecycle_stage.value != "forgotten"
        # 至少一条低重要性成员被软删或 keep 被更新
        changed = (
            any(
                mgr._memories[mid].lifecycle_stage.value == "forgotten"
                for mid in low
            )
            or report.get("merged_count", 0) >= 1
        )
        assert changed, f"应发生合并: {report}"

    def test_respects_importance_threshold(self, settings):
        """阈值过滤：importance 高于阈值的记忆不进入候选"""
        settings.update({"compression.importance_threshold": 0.01})
        mgr = _make_manager()
        low, high = self._seed(mgr)

        report = mgr.compress_low_value_memories(dry_run=False)

        assert report["candidates"] == 0
        assert all(
            mgr._memories[mid].lifecycle_stage.value != "forgotten" for mid in low
        )


# ============================================================
# 3. MoE L0 缓存上限（vector_search.cache_max_size）
# ============================================================


class TestMoEL0CacheLimit:
    """MoE 专家下钻检索器的 L0 查询缓存上限（vector_search.cache_max_size）。

    ExpertDrilldownRetriever 每次 retrieve 重建（缓存当前为一次性），
    上限作为构造防线接入；settings 默认 1000 与历史无上限兼容
    （单次 retrieve 的缓存条目远小于 1000）。
    """

    def _make_retriever(self, **kwargs):
        from neurova.cognitive_layers.memory_layer.moe_router import (
            ExpertDrilldownRetriever,
        )

        return ExpertDrilldownRetriever(
            expert_def={}, store=MagicMock(), **kwargs
        )

    def test_l0_cache_bounded(self, settings):
        """L0 查询缓存不得超过构造上限（FIFO 淘汰最旧）"""
        settings.update({"vector_search.cache_max_size": 10})
        retriever = self._make_retriever(cache_max_size=3)

        for i in range(6):
            retriever._cache_l0(f"k{i}", [f"v{i}"])

        assert len(retriever._l0_cache) == 3
        assert "k0" not in retriever._l0_cache and "k5" in retriever._l0_cache

    def test_cache_size_from_settings(self, settings):
        """构造未显式传参时从 settings 读取上限"""
        settings.update({"vector_search.cache_max_size": 20})
        retriever = self._make_retriever()
        assert retriever._l0_cache_max_size == 20

    def test_l0_cache_key_accepts_list_vectors(self):
        """真实 onnx encode 返回 List[float]——缓存键不得假设 numpy 数组

        生产事故（2026-08-30）：query_vec[:10].tolist() 对 list 抛
        AttributeError，导致 MoE 检索在每次真实对话中异常、
        永远降级到 FallbackRetriever。
        """
        retriever = self._make_retriever()

        key_list = retriever._l0_cache_key([0.1, 0.2, 0.3])
        assert isinstance(key_list, str) and key_list

        import numpy as np

        key_np = retriever._l0_cache_key(np.array([0.1, 0.2, 0.3]))
        assert key_np == key_list, "list 与 numpy 数组应生成相同缓存键"


# ============================================================
# 4. GraphTraversal 接入（graph.min_strength）
# ============================================================


class TestTraverseRelations:
    def test_traverse_filters_by_min_strength(self, settings):
        """graph.min_strength 过滤弱关系"""
        settings.update({"graph.min_strength": 0.5})
        mgr = _make_manager()
        a = mgr.remember("中心记忆")
        b = mgr.remember("强关联记忆")
        c = mgr.remember("弱关联记忆")
        mgr.add_relation(source_id=a, target_id=b, strength=0.9)
        mgr.add_relation(source_id=a, target_id=c, strength=0.2)

        result = mgr.traverse_relations(a)

        visited_ids = {n.get("id") for n in result.get("nodes", [])}
        assert b in visited_ids, "强关联应被访问"
        assert c not in visited_ids, "弱关联应被 min_strength 过滤"

    def test_default_min_strength_unchanged(self, settings):
        """默认 0.15 与 GraphTraversal 历史默认一致"""
        mgr = _make_manager()
        a = mgr.remember("中心")
        b = mgr.remember("邻居")
        mgr.add_relation(source_id=a, target_id=b, strength=0.2)

        result = mgr.traverse_relations(a)
        visited_ids = {n.get("id") for n in result.get("nodes", [])}
        assert b in visited_ids


# ============================================================
# 5. 全库渐进语义索引（vector_search.moe_index_limit）
# ============================================================


def _make_fetch(rows):
    """构造 fetch_page(offset, size) 闭包（与 init_moe_router 的持久层闭包同形）"""

    def fetch(offset: int, size: int):
        return rows[offset : offset + size]

    return fetch


def _mock_encode_store(dim=4):
    """tfidf backend（不加载 onnx 模型）+ 固定维度 mock encode"""
    from neurova.cognitive_layers.memory_layer.unified_vector_store import (
        UnifiedVectorStore,
    )

    vs = UnifiedVectorStore(backend="tfidf")

    def encode(text: str):
        base = float(len(text) % 7)
        return [base, 1.0, 0.5, 0.2][:dim]

    vs.encode = encode
    return vs


class TestIncrementalIndex:
    def test_incremental_appends_not_resets(self):
        """incremental=True 追加索引且同 id 去重（修复每次调用清空重置）"""
        vs = _mock_encode_store()
        vs.index_memories([{"id": "a", "content": "one"}, {"id": "b", "content": "two"}])
        assert len(vs.memory_ids) == 2

        vs.index_memories(
            [{"id": "b", "content": "two dup"}, {"id": "c", "content": "three"}],
            incremental=True,
        )
        assert sorted(vs.memory_ids) == ["a", "b", "c"], "同 id 去重、新 id 追加"

    def test_non_incremental_resets(self):
        """默认行为保持：清空重建（向后兼容）"""
        vs = _mock_encode_store()
        vs.index_memories([{"id": "a", "content": "one"}])
        vs.index_memories([{"id": "b", "content": "two"}])
        assert vs.memory_ids == ["b"]

    def test_numpy_search_top1(self):
        """numpy 路径的 top-1 与暴力扫描一致"""
        vs = _mock_encode_store()
        rows = [
            {"id": f"m{i}", "content": "内容变体 " + "0" * i}
            for i in range(5)
        ]
        vs.index_memories(rows)
        assert vs._np_matrix is not None, "固定维度下应构建 numpy 矩阵"

        query = "内容变体 " + "0" * 3  # 与 m3 同长 → mock 向量最接近
        hits = vs.search(query, limit=2)
        assert hits, "应返回结果"
        assert hits[0]["id"] == "m3"
        assert vs._np_matrix.shape == (5, 4)

    def test_dim_mismatch_falls_back(self):
        """维度不齐时 numpy 矩阵置空、暴力扫描兜底不崩溃"""
        vs = _mock_encode_store(dim=4)
        vs.index_memories([{"id": "a", "content": "abc"}])

        # 模拟历史维度漂移残留：向量与元数据不同步追加
        vs.memory_vectors.append([1.0, 2.0])
        vs.memory_metadata.append({"id": "legacy"})
        vs._refresh_numpy_matrix()
        assert vs._np_matrix is None

        hits = vs.search("abc", limit=2)
        assert isinstance(hits, list)


class TestBackgroundIndexer:
    def _rows(self, n):
        return [
            {
                "id": f"m{i}",
                "content": f"内容 {i}",
                "category": "general",
                "lifecycle_stage": "active",
            }
            for i in range(n)
        ]

    def test_indexes_up_to_limit(self, settings):
        """后台索引在 index_limit 处停止；分页游标推进正确（直接传参绕开 schema min=500）"""
        from neurova.mem_core import _background_index_memories

        vs = _mock_encode_store()
        added = _background_index_memories(
            vs,
            _make_fetch(self._rows(10)),
            index_limit=5,
            batch_size=2,
            batch_delay=0,
        )

        assert added == 5
        assert len(vs.memory_ids) == 5

    def test_stops_at_data_end(self, settings):
        """数据少于 limit 时扫尽即停"""
        from neurova.mem_core import _background_index_memories

        vs = _mock_encode_store()
        added = _background_index_memories(
            vs,
            _make_fetch(self._rows(3)),
            index_limit=100,
            batch_size=2,
            batch_delay=0,
        )

        assert added == 3
        assert len(vs.memory_ids) == 3

    def test_respects_existing_index(self, settings):
        """已有索引（初始 500 条场景）不重复索引，预算按新增计"""
        from neurova.mem_core import _background_index_memories

        vs = _mock_encode_store()
        rows = self._rows(6)
        vs.index_memories(rows[:3])  # 模拟 init 同步索引

        added = _background_index_memories(
            vs,
            _make_fetch(rows),
            index_limit=5,  # 直接传参：schema min=500 会拒绝对 settings 写 5
            batch_size=2,
            batch_delay=0,
        )

        assert added == 2, "预算 = index_limit - 已索引 = 2"
        assert len(vs.memory_ids) == 5

    def test_moe_index_limit_schema_default(self):
        """schema 默认 20000（内存预算 ~40MB numpy 矩阵）"""
        from neurova.cognitive_layers.memory_layer.settings_config import (
            get_memory_settings,
            MemorySettingsConfig,
        )

        MemorySettingsConfig.reset_instance()
        try:
            import tempfile, os

            tmp = tempfile.mkdtemp()
            cfg = get_memory_settings(tmp)
            assert cfg.get("vector_search.moe_index_limit") == 20000
        finally:
            MemorySettingsConfig.reset_instance()
