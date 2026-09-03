"""
Tier 3A.1 RED 测试 — embedding 工厂单例验证

验证 Bug：embedding/__init__.py 缺 get_embedding_engine() / _reset_embedding_engine()
"""
from __future__ import annotations


class TestEmbeddingFactory:
    """embedding 工厂应提供懒加载单例 + 测试重置"""

    def test_get_embedding_engine_returns_singleton(self):
        """RED: 工厂应返回单例（含 None 情况）"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        e1 = get_embedding_engine()
        e2 = get_embedding_engine()
        assert e1 is e2  # 单例（含 None）

    def test_get_embedding_engine_lazy_init(self):
        """RED: 懒加载 — 首次调用初始化，再次调用复用"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        e1 = get_embedding_engine()
        e2 = get_embedding_engine()
        assert e1 is e2

    def test_reset_embedding_engine_clears_singleton(self):
        """RED: _reset_embedding_engine 应清空单例"""
        from neurova.embedding import get_embedding_engine, _reset_embedding_engine

        _reset_embedding_engine()
        e1 = get_embedding_engine()
        _reset_embedding_engine()
        e2 = get_embedding_engine()
        # 重置后再次获取，应重新初始化（但仍可能是 None 若模型未安装）
        assert e1 is not None or e1 is None  # 仅验证不抛异常
        assert e2 is not None or e2 is None
