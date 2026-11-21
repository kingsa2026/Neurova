# -*- coding: utf-8 -*-
"""R5（参照系 ad 追平批二）：定价单元体系升级。

契约：
- provider 上报成本（provider_reported_cost_usd，如 OpenRouter usage.cost）
  优先于本地价目计算——聚合商已按真实计费折算，本地估算只作兜底；
- 价目表支持 tiered 阶梯（按 prompt_tokens 所处区间取档，如 DeepSeek
  ≤128K / >128K 双档）；无命中档位取最高档。
"""

import pytest

from neurova.llm_client import LLMProvider
from neurova.models.cost_tracking import _calculate_cost_from_usage


@pytest.fixture
def tiered_model(monkeypatch):
    """向价目表注入一个双档测试模型（用例结束自动清理）。"""
    from neurova.models.cost_tracking import PRICE_TABLES

    table = {
        "tiers": [
            {"up_to_tokens": 1000, "input": 0.001, "output": 0.002},
            {"up_to_tokens": 100000, "input": 0.01, "output": 0.02},
        ],
    }
    monkeypatch.setitem(PRICE_TABLES[LLMProvider.OPENAI], "tiered-test-model", table)
    return "tiered-test-model"


class TestProviderReportedCost:
    def test_reported_cost_wins_over_local_calc(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 500,
                 "provider_reported_cost_usd": 0.123}
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, "gpt-4o", usage) == 0.123

    def test_reported_cost_zero_is_honored(self):
        """上报 0 也是上报（聚合商促销/免费额度），不得被本地价目覆盖。"""
        usage = {"prompt_tokens": 1000, "completion_tokens": 500,
                 "provider_reported_cost_usd": 0.0}
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, "gpt-4o", usage) == 0.0

    def test_missing_reported_cost_falls_back_to_table(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, "gpt-4o", usage) > 0


class TestTieredPricing:
    def test_low_tier_selected_by_prompt_tokens(self, tiered_model):
        usage = {"prompt_tokens": 500, "completion_tokens": 100}
        # 500*0.001/1000 + 100*0.002/1000
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, tiered_model, usage) == pytest.approx(0.0005 + 0.0002)

    def test_high_tier_selected_by_prompt_tokens(self, tiered_model):
        usage = {"prompt_tokens": 5000, "completion_tokens": 100}
        # 5000*0.01/1000 + 100*0.02/1000
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, tiered_model, usage) == pytest.approx(0.05 + 0.002)

    def test_beyond_last_tier_uses_top_tier(self, tiered_model):
        usage = {"prompt_tokens": 200000, "completion_tokens": 0}
        assert _calculate_cost_from_usage(LLMProvider.OPENAI, tiered_model, usage) == pytest.approx(2.0)
