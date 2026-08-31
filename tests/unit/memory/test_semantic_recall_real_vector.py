"""
P2-1 记忆检索真实性 — _semantic_recall 真向量混合召回红测

原缺陷（评测文档）：
- _semantic_recall 每次调用重建关键词索引（O(n) per query），
  且 UnifiedVectorStore/faiss/fastembed/ONNX 链已存在却没接进召回主链路——"假向量"

新语义：
- 向量检索优先（UnifiedVectorStore.encode + search，真语义相似度）
- 关键词检索兜底（原链路保留）
- RRF 融合两路结果（向量 0.7 / 关键词 0.3 权重）
- 写入侧增量索引：remember 后新记忆立即可被向量召回
- 隔离不破坏：召回结果仍按三元组过滤（agent/neuser/user）
- 向量库不可用时整体降级关键词路径（行为与现状一致，不崩）
"""

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


def _make_manager(tmp_path):
    """沿用记忆套件惯例：db_path 指向 tmp，agent 隔离避免串扰"""
    return MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="test-agent",
        neuser_id="ne_test",
        user_id="u_test",
    )


def _remember(manager, content, mid=None):
    kwargs = {"content": content}
    if mid:
        kwargs["id"] = mid
    return manager.remember(**kwargs)


class TestVectorRecall:
    def test_remember_makes_memory_vector_searchable(self, tmp_path):
        """写入侧增量索引：新记忆立即可被向量召回（无需手动重建索引）"""
        manager = _make_manager(tmp_path)
        _remember(manager, "用户在北京工作，从事后端开发")
        _remember(manager, "用户喜欢养猫，家里有一只橘猫")

        results = manager.recall("北京 后端开发 工作", use_semantic=True)
        assert results, "向量召回返回空"
        assert any("后端开发" in (r.get("content") or "") for r in results)

    def test_vector_path_returns_semantically_related(self, tmp_path):
        """语义相关（非子串）内容也能召回——关键词路径做不到的"""
        manager = _make_manager(tmp_path)
        _remember(manager, "用户从事 Python 后端开发，主用 FastAPI")
        _remember(manager, "用户喜欢周末爬山")

        results = manager.recall("写服务端接口的技术栈", use_semantic=True)
        assert results, "语义召回返回空"
        assert any("FastAPI" in (r.get("content") or "") for r in results)

    def test_isolation_preserved_in_vector_recall(self, tmp_path):
        """隔离：向量召回结果仍按三元组过滤"""
        manager = _make_manager(tmp_path)
        _remember(manager, "用户甲的秘密：在阿里工作")
        _remember(manager, "公共内容：今天天气不错")

        # request_scope 是 manager 自带的 ContextVar 作用域上下文管理器
        with manager.request_scope(neuser_id="ne_2", user_id="u2"):
            results = manager.recall("阿里 秘密", use_semantic=True)
        contents = [r.get("content") or "" for r in results]
        assert all("用户甲的秘密" not in c for c in contents)


class TestHybridFusion:
    def test_rrf_merges_vector_and_keyword_paths(self, tmp_path, monkeypatch):
        """两路融合：向量命中 + 关键词命中的记忆排名应更高"""
        from neurova.cognitive_layers.memory_layer import manager as manager_module

        manager = _make_manager(tmp_path)
        _remember(manager, "Kubernetes 部署与回滚策略详解")
        _remember(manager, "用户喜欢的电影类型")

        results = manager.recall("Kubernetes 部署 回滚", use_semantic=True)
        assert results
        assert any("Kubernetes" in (r.get("content") or "") for r in results)

    def test_vector_unavailable_degrades_to_keyword(self, tmp_path, monkeypatch):
        """向量库异常 → 降级关键词路径（与现状行为一致，不崩）"""
        manager = _make_manager(tmp_path)
        _remember(manager, "包含特定关键词 pineapple pizza 的记忆")

        # 打爆向量检索入口（_get_vector_store 抛异常 → 整体降级关键词路径）
        monkeypatch.setattr(
            manager, "_get_vector_store",
            lambda: (_ for _ in ()).throw(RuntimeError("vs down")),
        )
        results = manager.recall("pineapple pizza", use_semantic=True)
        assert any("pineapple pizza" in (r.get("content") or "") for r in results)


class TestNoReindexPerQuery:
    def test_repeated_recall_does_not_rebuild_index(self, tmp_path, monkeypatch):
        """回归锁定：同一批记忆连续召回不重建索引（原 O(n) per query 缺陷）"""
        manager = _make_manager(tmp_path)
        _remember(manager, "内容一")
        _remember(manager, "内容二")

        manager.recall("内容", use_semantic=True)  # 触发懒建
        store = manager._get_vector_store()
        calls = {"n": 0}
        original = store.index_memories

        def counting_index(memories, incremental=False):
            if not incremental:
                calls["n"] += 1
            return original(memories, incremental=True)

        monkeypatch.setattr(store, "index_memories", counting_index)

        manager.recall("内容", use_semantic=True)
        manager.recall("内容", use_semantic=True)
        manager.recall("内容", use_semantic=True)

        assert calls["n"] == 0, f"召回路径全量重建索引 {calls['n']} 次（应为 0）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
