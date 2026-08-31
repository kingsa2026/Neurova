"""
P2-4 token 对账 + 成本核算红测

原缺陷：chat_pipeline 用 len(user_input)+len(reply) 字符长度伪造 total_tokens
（chat_pipeline.py:1551），真实 usage（LLMResponse.usage，OpenAI 返回值）从未
进入任何累计记录；无成本核算。

新语义：
- TokenUsageAccounting 单例：record(model, provider, prompt, completion)
  累计 per-model 计数；snapshot() 按模型汇总；estimate_cost 按定价目录算钱
- multi_model_client.chat 从底层 response.usage 提取真实 token 数并记账
"""

import pytest

from neurova.core.usage_accounting import TokenUsageAccounting, get_usage_accounting


class TestAccounting:
    def test_record_and_snapshot(self):
        acc = TokenUsageAccounting()
        acc.record(model="gpt-x", provider="p1", prompt_tokens=100, completion_tokens=50)
        acc.record(model="gpt-x", provider="p1", prompt_tokens=30, completion_tokens=20)
        snap = acc.snapshot()
        entry = snap["by_model"]["gpt-x"]
        assert entry["prompt_tokens"] == 130
        assert entry["completion_tokens"] == 70
        assert entry["calls"] == 2
        assert entry["total_tokens"] == 200

    def test_per_provider_split(self):
        acc = TokenUsageAccounting()
        acc.record(model="m", provider="p1", prompt_tokens=10, completion_tokens=5)
        acc.record(model="m", provider="p2", prompt_tokens=10, completion_tokens=5)
        snap = acc.snapshot()
        assert snap["by_model"]["m"]["calls"] == 2
        assert snap["total"]["calls"] == 2

    def test_thread_safety_smoke(self):
        from concurrent.futures import ThreadPoolExecutor

        acc = TokenUsageAccounting()

        def worker():
            for _ in range(50):
                acc.record(model="m", provider="p", prompt_tokens=1, completion_tokens=1)

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(lambda _: worker(), range(4)))
        assert acc.snapshot()["total"]["calls"] == 200

    def test_singleton_accessor(self):
        a1 = get_usage_accounting()
        a2 = get_usage_accounting()
        assert a1 is a2


class TestCostEstimate:
    def test_known_model_cost(self, monkeypatch):
        monkeypatch.setattr(
            TokenUsageAccounting, "_PRICING",
            {"gpt-x": {"prompt": 1e-05, "completion": 2e-05}},
        )
        acc = TokenUsageAccounting()
        acc.record(model="gpt-x", provider="p", prompt_tokens=1000, completion_tokens=500)
        cost = acc.estimate_cost("gpt-x")
        assert cost == pytest.approx(1000 * 1e-05 + 500 * 2e-05)

    def test_unknown_model_cost_zero(self):
        acc = TokenUsageAccounting()
        acc.record(model="mystery", provider="p", prompt_tokens=999, completion_tokens=999)
        assert acc.estimate_cost("mystery") == 0.0

    def test_snapshot_total_cost(self, monkeypatch):
        monkeypatch.setattr(
            TokenUsageAccounting, "_PRICING",
            {"gpt-x": {"prompt": 1e-05, "completion": 2e-05}},
        )
        acc = TokenUsageAccounting()
        acc.record(model="gpt-x", provider="p", prompt_tokens=1000, completion_tokens=500)
        snap = acc.snapshot()
        assert snap["total_cost"] == pytest.approx(1000 * 1e-05 + 500 * 2e-05)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
