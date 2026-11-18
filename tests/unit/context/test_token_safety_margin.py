"""对照批 B4：token 保证金（溢出拒收自适应抬高估算基线）。

参照系语义：provider 溢出拒收后**永久抬高**该模型的 token 估算基线，
防止同一模型被反复撞溢出（scroll/manager.py 的"拒收保证金"）。本仓
token_estimator 是纯静态估算、无模型维度——红灯钉：

1. margin 默认 1.0；recordModelOverflow 后按步进抬高、封顶 2.0；
2. estimate_tokens 带 model_id 时应用 margin（宁高估不低估，向上取整）；
3. 不带 model_id 的调用不受影响（全仓既有调用面零变化）；
4. multi_model_client 分类出 context_overflow 时接线 recordModelOverflow
   （接线条数用源码断言钉住，防接线被静默删掉）。
"""

import math

import pytest

from neurova.context.token_estimator import (
    estimate_tokens,
    getModelSafetyMargin,
    recordModelOverflow,
    resetModelSafetyMargins,
)
from neurova.llm.model_capability_cache import get_capability_cache

MODEL = "test-model/margin-check"


def setup_function(_):
    resetModelSafetyMargins()


def test_margin_defaults_to_one():
    assert getModelSafetyMargin(MODEL) == 1.0


def test_overflow_raises_margin_and_caps():
    recordModelOverflow(MODEL)
    assert getModelSafetyMargin(MODEL) == pytest.approx(1.25)
    for _ in range(10):
        recordModelOverflow(MODEL)
    assert getModelSafetyMargin(MODEL) == 2.0, "保证金必须封顶，不能无限抬高"


def test_estimate_applies_margin_only_with_model_id():
    text = "x" * 400
    base = estimate_tokens(text)
    recordModelOverflow(MODEL)  # margin=1.25
    with_margin = estimate_tokens(text, model_id=MODEL)
    assert with_margin == math.ceil(base * 1.25)
    assert estimate_tokens(text) == base, "不带 model_id 的调用面必须零变化"


def test_margin_survives_capability_cache_roundtrip():
    recordModelOverflow(MODEL)
    # 保证金经模型能力缓存单例存取——同进程内再次读取一致
    assert get_capability_cache().get(MODEL, "token_safety_margin") == pytest.approx(1.25)


def test_overflow_wiring_is_present_in_client():
    import inspect

    from neurova.llm import multi_model_client

    source = inspect.getsource(multi_model_client)
    assert "recordModelOverflow" in source, (
        "multi_model_client 必须在分类出 context_overflow 时接线 recordModelOverflow——"
        "接线被删等于保证金永远学不到溢出"
    )
    assert "context_overflow" in source
