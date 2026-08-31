"""
P1-1② 动态预算 — get_token_budget_for_model 接 provider 元数据测试

优先级：provider_manager 模型 context_window（× 0.6 视图安全系数）
→ 静态已知型号表 → default_budget。
只读接入（provider_manager 有用户并行改动，本侧不改其文件）。
"""

import pytest

from neurova.context_pool import ContextPool
from types import SimpleNamespace


def _fake_manager(models_by_provider):
    """构造带 discovered_models 的假 provider manager"""

    class _FakePM:
        providers = {
            pid: SimpleNamespace(discovered_models=models, models=[])
            for pid, models in models_by_provider.items()
        }

    return _FakePM()


class TestDynamicBudget:
    def test_metadata_context_window_wins(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        model = SimpleNamespace(id="gpt-mega", name="gpt-mega", context_window=200000)
        monkeypatch.setattr(
            pm_module, "get_provider_manager",
            lambda: _fake_manager({"openai": [model]}),
        )
        assert ContextPool.get_token_budget_for_model("gpt-mega") == int(200000 * 0.6)

    def test_string_model_entry_supported(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        # models 列表混存字符串条目（旧格式）——跳过不崩
        monkeypatch.setattr(
            pm_module, "get_provider_manager",
            lambda: _fake_manager({"p1": ["gpt-str"]}),
        )
        assert ContextPool.get_token_budget_for_model("gpt-str") == 16000  # 回落默认

    def test_fallback_to_known_table(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        monkeypatch.setattr(
            pm_module, "get_provider_manager",
            lambda: _fake_manager({}),  # 无元数据
        )
        assert ContextPool.get_token_budget_for_model("gpt-4") == 32000  # 静态表

    def test_fallback_to_default_when_unknown_everywhere(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        monkeypatch.setattr(
            pm_module, "get_provider_manager",
            lambda: _fake_manager({}),
        )
        assert ContextPool.get_token_budget_for_model("never-heard-of") == 16000

    def test_broken_manager_never_raises(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        def _boom():
            raise RuntimeError("pm down")

        monkeypatch.setattr(pm_module, "get_provider_manager", _boom)
        assert ContextPool.get_token_budget_for_model("gpt-4") == 32000

    def test_window_clamped_to_reasonable_range(self, monkeypatch):
        import neurova.llm.provider_manager as pm_module

        tiny = SimpleNamespace(id="tiny", name="tiny", context_window=100)
        huge = SimpleNamespace(id="huge", name="huge", context_window=100000000)
        monkeypatch.setattr(
            pm_module, "get_provider_manager",
            lambda: _fake_manager({"p": [tiny, huge]}),
        )
        assert ContextPool.get_token_budget_for_model("tiny") == 4000  # 下限
        assert ContextPool.get_token_budget_for_model("huge") == 400000  # 上限


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
