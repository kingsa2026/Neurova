"""
Tier 3C.1 RED 测试 — SemanticSearch embedding 注入验证

验证 Bug 12：semantic_search.py:239-243 get_semantic_search() 全局单例
首次创建后忽略 embedding_model 参数，且无 _reset_semantic_search() 测试辅助。
"""
from __future__ import annotations


class TestSemanticSearchInjection:
    """SemanticSearch 应接受 embedding 注入且支持测试重置"""

    def test_get_semantic_search_accepts_embedding(self):
        """RED: get_semantic_search(embedding_model=...) 必须真实注入"""
        from neurova.cognitive_layers.memory_layer import semantic_search as ss_module

        ss_module._semantic_search = None  # 重置单例

        class DummyEmbedding:
            def embed(self, text):
                return [0.1] * 512

        search = ss_module.get_semantic_search(embedding_model=DummyEmbedding())
        assert search._embedding_model is not None, "RED: embedding 未注入（Bug 12）"
        assert search._use_embedding is True, "RED: use_embedding 应为 True"

    def test_singleton_preserves_first_embedding(self):
        """RED: 单例模式下，首次注入的 embedding 应保留（不被后续 None 覆盖）"""
        from neurova.cognitive_layers.memory_layer import semantic_search as ss_module

        ss_module._semantic_search = None

        class DummyEmbedding:
            def embed(self, text):
                return [0.1] * 512

        # 第一次：注入真实 embedding
        search1 = ss_module.get_semantic_search(embedding_model=DummyEmbedding())
        assert search1._use_embedding is True

        # 第二次：不传 embedding（应保留第一次的）
        search2 = ss_module.get_semantic_search()
        assert search2 is search1, "应返回同一单例"
        assert search2._use_embedding is True, "RED: 不应被 None 覆盖（Bug 12）"

    def test_reset_semantic_search_clears_singleton(self):
        """RED: _reset_semantic_search() 应清空单例"""
        from neurova.cognitive_layers.memory_layer import semantic_search as ss_module

        ss_module._semantic_search = None
        search1 = ss_module.get_semantic_search()
        assert ss_module._semantic_search is search1

        ss_module._reset_semantic_search()
        assert ss_module._semantic_search is None, "RED: 缺 _reset_semantic_search()（Bug 12）"
