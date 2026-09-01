# -*- coding: utf-8 -*-
"""
P3-e 单例收敛防回归网（切片 2：高危无锁惰性单例补 DCL）

审计基线（2026-09-01，AST 扫描 neurova/ 全部模块级 get_* 工厂）：
- 287 个 get_* 工厂；55 个惰性创建型全局单例（_x=None + global _x）
- 其中 17 个创建段无锁（并发首次访问可双创建）——本切片修 6 个高危
  （构造有副作用 + 并发热路径）；其余多为无状态/幂等构造，渐进另批
- semantic_search/embedding 缺公有 reset（测试隔离受限）

锁定契约：
1. 高危单例 get_ 函数体必须含锁守卫（AST 结构断言）
2. get_multi_model_client 并发首访单次构造（行为断言：barrier + 慢构造）
3. semantic_search / embedding 提供公有 reset
"""
import ast
import threading
from pathlib import Path

import pytest

NEUROVA_ROOT = Path(__file__).resolve().parents[3] / "neurova"

# 高危清单：构造有副作用/持有资源 + 并发热路径
HIGH_RISK_SINGLETONS = [
    ("neurova/llm/multi_model_client.py", "get_multi_model_client"),
    ("neurova/cognitive_layers/memory_layer/semantic_search.py", "get_semantic_search"),
    ("neurova/llm/providers/secret_store_clean.py", "get_secret_store"),
    ("neurova/security/neu_token_manager.py", "get_neu_token_manager"),
    ("neurova/shared_core/execution_engine.py", "get_execution_engine"),
    ("neurova/shared_core/infrastructure.py", "get_infrastructure_manager"),
]

# 良性批（P3-e 收尾）：无状态/幂等构造，但统一收敛到 DCL 模式，
# 防止未来构造获得副作用后竞态复活
BENIGN_SINGLETONS = [
    ("neurova/api/openplatform/events.py", "get_event_system"),
    ("neurova/auth/invitation_code.py", "get_invitation_code_model"),
    ("neurova/auth/password_hasher.py", "get_password_hasher"),
    ("neurova/auth/user_group_model.py", "get_user_group_manager"),
    ("neurova/auth/verification_code.py", "get_verification_code_model"),
    ("neurova/cognitive_layers/memory_layer/memory_field.py", "get_memory_field"),
    ("neurova/collaboration/collaboration_isolation.py", "get_collaboration_manager"),
    ("neurova/core/error_handler.py", "get_error_handler"),
    ("neurova/core/logger.py", "get_log_manager"),
    ("neurova/execution_engine/plan_orchestrator.py", "get_plan_orchestrator"),
    ("neurova/security/constitution.py", "get_constitution_engine"),
]


def _get_function_source(rel_path: str, func_name: str) -> str:
    src = (NEUROVA_ROOT.parent / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{rel_path} 中未找到 {func_name}")


class TestHighRiskSingletonsLockGuarded:
    """结构断言：高危惰性单例创建段必须带锁守卫（DCL）"""

    @pytest.mark.parametrize("rel_path,func_name", HIGH_RISK_SINGLETONS)
    def test_creation_guarded_by_lock(self, rel_path, func_name):
        import re

        seg = _get_function_source(rel_path, func_name)
        assert re.search(r"with [\w\.]*[Ll]ock", seg), (
            f"{func_name} 创建段无锁守卫：并发首次访问可双创建。"
            f"参照 provider_manager 的双重检查锁定模式修复。"
        )


class TestBenignSingletonsLockGuarded:
    """结构断言：良性批同样收敛 DCL（统一模式，防构造日后获得副作用）"""

    @pytest.mark.parametrize("rel_path,func_name", BENIGN_SINGLETONS)
    def test_creation_guarded_by_lock(self, rel_path, func_name):
        import re

        seg = _get_function_source(rel_path, func_name)
        assert re.search(r"with [\w\.]*[Ll]ock", seg), (
            f"{func_name} 创建段无锁守卫：应与全量惰性单例统一 DCL 模式。"
        )


class TestConcurrentFirstAccessSingleCreation:
    """行为断言：并发首访只构造一次（键控 scope 路径）"""

    def test_keyed_scope_constructs_once_under_race(self, monkeypatch):
        import neurova.llm.multi_model_client as mmc

        monkeypatch.setattr(mmc, "_multi_model_clients", {})
        creations = []

        class SlowFakeClient:
            def __init__(self, scope=None):
                threading.Event().wait(0.05)  # 慢构造放大竞态窗口
                creations.append(scope)

        monkeypatch.setattr(mmc, "MultiModelLLMClient", SlowFakeClient)

        barrier = threading.Barrier(8)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                mmc.get_multi_model_client("user:race-t")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"并发首访抛错: {errors}"
        assert len(creations) == 1, (
            f"并发首访应只构造 1 次，实际 {len(creations)} 次（无锁双创建竞态）"
        )


class TestPublicResets:
    """semantic_search / embedding 提供公有 reset（测试隔离）"""

    def test_reset_semantic_search_exists(self):
        from neurova.cognitive_layers.memory_layer import semantic_search

        assert callable(getattr(semantic_search, "reset_semantic_search", None))
        semantic_search.reset_semantic_search()
        assert semantic_search._semantic_search is None

    def test_reset_embedding_engine_exists(self):
        from neurova import embedding

        assert callable(getattr(embedding, "reset_embedding_engine", None))
        embedding.reset_embedding_engine()
        assert embedding._embedding_engine is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
