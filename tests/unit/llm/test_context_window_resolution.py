"""
模型上下文窗口统一查询（llmrouter 层单一来源）— 2026-09-10

用户要求：上下文窗口大小按模型真实能力自动调节，而非系统写死；
收敛到 llmrouter 层。

此前断链：ContextPool.get_token_budget_for_model 的"元数据优先"路径只遍历
models/discovered_models（字符串列表，无 context_window）——真实窗口值存在
provider.model_metadata dict（服务商发现/文档维护）里从未被查询，实际恒走
过时静态表（gpt-4=32000 等旧值）。

统一入口 resolve_model_context_window 的优先级：
1. provider.model_metadata（真实元数据；4096=占位哨兵视为未知）
2. capability_detector.MODEL_PRESETS（族级预埋档案）
3. model_limits.MODEL_CONTEXT_WINDOWS（服务商文档精确表）
4. 保守默认 16000
"""
import sys
from unittest.mock import MagicMock, patch

import pytest


def _mk_pm(metadata_map):
    """构造带 model_metadata 的 provider_manager 单例替身。

    metadata_map: {model_id: context_window or None}
    """
    pm = MagicMock()
    provider = MagicMock()
    provider.model_metadata = {
        mid: ({} if w is None else {"context_window": w})
        for mid, w in metadata_map.items()
    }
    provider.models = list(metadata_map.keys())
    provider.discovered_models = []
    provider.default_model = None
    pm.providers = {"p1": provider}
    pm.list_providers.return_value = [provider]
    return pm


class TestResolveModelContextWindow:
    def test_provider_metadata_first(self):
        """真实元数据最高优先（gpt-4o 在静态表=32000 旧值，元数据 200000 应胜出）。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({"my-custom-model": 200_000})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            assert resolve_model_context_window("my-custom-model") == 200_000

    def test_metadata_placeholder_4096_treated_unknown(self):
        """元数据 4096 占位哨兵 → 视为未知，落 preset/model_limits。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({"gpt-4o": 4096})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            # gpt-4o 在 MODEL_CONTEXT_WINDOWS = 128_000
            assert resolve_model_context_window("gpt-4o") == 128_000

    def test_preset_family_fallback(self):
        """族级预埋命中：deepseek-chat（MODEL_PRESETS 65536）。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            assert resolve_model_context_window("deepseek-chat") == 65_536

    def test_model_limits_exact_table(self):
        """预埋档案命中：glm-4-flash → glm-4 族级 preset 131072。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            assert resolve_model_context_window("glm-4-flash") == 131_072  # 族级预埋 glm-4 命中（131072）

    def test_unknown_model_conservative_default(self):
        """完全未知模型 → 保守默认 16000（宁可早压缩不可撑爆）。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            assert resolve_model_context_window("totally-unknown-model-xyz") == 16_000

    def test_substring_match_for_routed_variant(self):
        """路由变体名（如 DeepSeek-V4-Flash）按子串命中元数据条目。"""
        from neurova.llm.llm_router import resolve_model_context_window

        pm = _mk_pm({"DeepSeek-V4-Flash": 131_072})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            assert resolve_model_context_window("DeepSeek-V4-Flash") == 131_072

    def test_provider_manager_failure_falls_through(self):
        """provider_manager 异常 → 不崩，走静态源。"""
        from neurova.llm.llm_router import resolve_model_context_window

        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
            side_effect=RuntimeError("boom"),
        ):
            assert resolve_model_context_window("glm-4-flash") == 131_072  # 族级预埋 glm-4 命中（131072）


class TestTokenBudgetViaUnifiedEntry:
    def test_pool_budget_uses_metadata_window(self):
        """ContextPool.get_token_budget_for_model 经统一入口吃真实元数据。"""
        from neurova.context_pool import ContextPool

        pm = _mk_pm({"DeepSeek-V4-Flash": 131_072})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            budget = ContextPool.get_token_budget_for_model("DeepSeek-V4-Flash")
        # 131072 × 0.6 = 78643，钳位内
        assert budget == int(131_072 * 0.6)

    def test_pool_budget_fallback_static_table_when_no_metadata(self):
        """无元数据时：静态源兜底（glm-4-flash → 精确表 128000 → ×0.6）。"""
        from neurova.context_pool import ContextPool

        pm = _mk_pm({})
        with patch("neurova.llm.provider_manager.get_provider_manager", return_value=pm):
            budget = ContextPool.get_token_budget_for_model("glm-4-flash")
        assert budget == int(131_072 * 0.6)  # glm-4 族级 preset


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
