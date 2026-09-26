# -*- coding: utf-8 -*-
"""判据 7：前缀命中率必须以 provider `cached_tokens` 计，且这条链在生产上真的闭合。

## 根因（不是"少接一根线"，是契约分了两个形状）

工单 §12.7 判据 7 与裁决 **D3** 都写明：「命中率以 provider `cached_tokens` 判定，
**不用估算口径自证**」。读侧通路看起来是现成的 —— `measure_composition` 有
`provider_usage` 形参、也实现了"优先采信 `prompt_tokens_details.cached_tokens`"。

实测两处断点，两处都是**契约层面**的：

**一、形状分裂。** 生产链路能拿到的唯一真值是
`core.usage_accounting.get_usage_accounting().last_call()` 的**归一化** payload
（`multi_model_client` 已把供应商的两种形态都归到一处）：

```
{'prompt_tokens': 1000, 'cache_read_tokens': 800, 'cache_write_tokens': 0, ...}
```

而 `composition` 只认**原始供应商形**（`prompt_tokens_details.cached_tokens`）。
把生产真值原样喂进去，读数如实落在 `cache_source='none'` / `cache_hit_rate=None`
—— 真值在手却读不出来。归一口径在 `usage_accounting`（`_extract_cache_tokens`
已把 OpenAI / Anthropic 两形合并），消费方却各认一形。

**二、生产从不喂。** `measure_composition(...)` 在 `chat_pipeline` 的调用点
**不传 `provider_usage`**（实测 grep：`neurova/` 下该形参只有定义、零生产实参）。
于是面板上的命中率永远是 `prefix_estimate`（相邻两轮公共前缀占比）——
那正是判据 7 明禁的"用估算口径自证命中率"。

时序也是这处断点的成因：快照在 **LLM 调用之前**测（"紧邻真实 LLM 请求"，
口径与发送内容一致），而本轮的 `cached_tokens` 只能**调用之后**才拿到。
故闭环形态是"先测组成 → 调 LLM → 用**本轮**真值回填同一份快照"，
而不是把上一轮的真值贴到本轮的组成上（那是形状对、内容错的假读数）。

## 判据

1. `measure_composition` 对**两个形状**都给同一结论（归一化 payload 与原始形）；
2. 回填只改命中率与其口径标记，不重算组成（组成是调用前的实测事实）；
3. 生产调用点必须真喂：`chat_pipeline` 在 LLM 调用后回填本轮 provider 真值；
4. 无真值时**不得**伪造：口径仍如实标 `prefix_estimate` / `none`。
"""

from __future__ import annotations

import inspect

import pytest

from neurova.context.composition import (
    applyProviderCacheUsage,
    get_last_composition,
    measure_composition,
    reset_composition,
)


@pytest.fixture(autouse=True)
def _isolate_composition():
    reset_composition()
    yield
    reset_composition()


def _normalizedUsage(prompt: int = 1000, cached: int = 800) -> dict:
    """生产链路真值形：`usage_accounting.last_call()` 的归一化 payload。"""
    return {
        "model": "m",
        "provider": "p",
        "prompt_tokens": prompt,
        "completion_tokens": 10,
        "total_tokens": prompt + 10,
        "estimated": False,
        "cache_read_tokens": cached,
        "cache_write_tokens": 0,
    }


class TestOneCaliberForProviderTruth:
    """两个形状必须给同一结论 —— 归一口径只有一份（教义第 6 条）。"""

    def test_normalized_payload_is_recognised(self):
        measure_composition("a-norm", [{"role": "system", "content": "固定" * 100}], None)
        comp = measure_composition(
            "a-norm",
            [{"role": "user", "content": "问"}],
            None,
            provider_usage=_normalizedUsage(),
        )
        assert comp["cache_source"] == "provider", (
            "归一化真值（usage_accounting.last_call 的形状）读不出来："
            f"cache_source={comp['cache_source']!r} —— 生产链路拿到的就是这一形"
        )
        assert comp["cache_hit_rate"] == pytest.approx(0.8)

    def test_raw_provider_shape_still_works(self):
        """原始供应商形不得回退（既有契约；反向控制：收口不是换口径）。"""
        measure_composition("a-raw", [{"role": "user", "content": "x"}], None)
        comp = measure_composition(
            "a-raw",
            [{"role": "user", "content": "y"}],
            None,
            provider_usage={
                "prompt_tokens": 1000,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
        )
        assert comp["cache_source"] == "provider"
        assert comp["cache_hit_rate"] == pytest.approx(0.8)

    def test_two_shapes_agree(self):
        """同一份真值写成两形，读数必须逐字相同（单口径的可证伪形式）。"""
        measure_composition("a-eq", [{"role": "user", "content": "1"}], None)
        normalized = measure_composition(
            "a-eq", [{"role": "user", "content": "2"}], None,
            provider_usage=_normalizedUsage(),
        )
        reset_composition()
        measure_composition("a-eq2", [{"role": "user", "content": "1"}], None)
        raw = measure_composition(
            "a-eq2", [{"role": "user", "content": "2"}], None,
            provider_usage={
                "prompt_tokens": 1000,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
        )
        assert (normalized["cache_source"], normalized["cache_hit_rate"]) == (
            raw["cache_source"], raw["cache_hit_rate"]
        ), "两个形状给出不同结论 —— 命中率口径仍是两份"


class TestBackfillKeepsMeasuredComposition:
    """回填只改命中率与口径标记：组成是调用前的实测事实，不得被重算。"""

    def test_backfill_updates_only_the_hit_rate(self):
        messages = [{"role": "system", "content": "固定" * 100}]
        before = measure_composition("a-back", messages, None)
        assert before["cache_source"] != "provider"

        applyProviderCacheUsage("a-back", None, _normalizedUsage())
        after = get_last_composition("a-back")
        assert after["cache_source"] == "provider"
        assert after["cache_hit_rate"] == pytest.approx(0.8)
        for field in ("total_tokens", "messages", "tools", "measured_at", "agent_id"):
            assert after[field] == before[field], f"回填改动了组成字段 {field}"

    def test_backfill_reaches_the_session_snapshot(self):
        """按会话隔离的环图快照（前端实际读的那一份）必须同批更新。"""
        measure_composition(
            "a-sess", [{"role": "user", "content": "hi"}], None, session_id="s-1"
        )
        assert get_last_composition("a-sess", "s-1")["cache_source"] != "provider"
        applyProviderCacheUsage("a-sess", "s-1", _normalizedUsage())
        assert get_last_composition("a-sess", "s-1")["cache_source"] == "provider"

    def test_backfill_without_a_snapshot_is_a_noop(self):
        """无快照（本轮没走到测量点）时不得凭空造一份组成出来。"""
        applyProviderCacheUsage("a-absent", None, _normalizedUsage())
        assert get_last_composition("a-absent") is None, (
            "回填在无快照时造了一份组成 —— 那是凭空编的读数"
        )

    def test_backfill_without_provider_truth_keeps_the_estimate(self):
        """无真值时必须保留诚实估算口径，不得改成 provider 也不得清空读数。"""
        measure_composition("a-nop", [{"role": "user", "content": "x"}], None, provider_usage=None)
        measure_composition("a-nop", [{"role": "user", "content": "x2"}], None)
        before = get_last_composition("a-nop")
        applyProviderCacheUsage("a-nop", None, None)
        after = get_last_composition("a-nop")
        assert after["cache_source"] == before["cache_source"], (
            "无真值时口径被改写 —— 那是把估算伪装成实测"
        )


class TestProductionWiresTheTruth:
    """生产调用点必须真喂 —— 定义了没人喂就是断点（教义第 5 条）。"""

    def test_chat_pipeline_backfills_after_the_llm_call(self):
        from neurova.agent import chat_pipeline

        source = inspect.getsource(chat_pipeline)
        assert "applyProviderCacheUsage" in source, (
            "chat_pipeline 从不回填 provider 真值 —— 面板上的命中率永远只能是"
            "prefix_estimate（判据 7 明禁的估算口径自证）"
        )

    def test_backfill_reads_the_same_truth_the_accounting_records(self):
        """回填取数必须走 `usage_accounting.last_call()`（真值唯一出处）。

        不许在 chat_pipeline 里另解析一份供应商 usage —— 那就是第二份归一口径
        （与 `_extract_cache_tokens` 重复），迟早漂移。
        """
        from neurova.agent import chat_pipeline

        source = inspect.getsource(chat_pipeline)
        assert "get_usage_accounting" in source and "last_call" in source, (
            "回填没走 usage_accounting.last_call() —— 真值出处不是那唯一一份"
        )
