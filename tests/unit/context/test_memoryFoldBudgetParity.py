"""P1-6：记忆折叠的 token↔字符换算必须收口到统一估算器（红→绿）

实测现状（memories 预算 = 100，走生产装配 `_build_memory_context`）：
- 中文内容：只填到 **66%**（裁 66 字符，因为 `budget / chinese_ratio(1.5)`）；
- 英文内容：只填到约 **10%**（同样裁 66 字符，英文每字符远不到 1.5 token）；
- 同文件 `_count_tokens` 的 docstring 明写"统一入口，禁止就地近似"，预算**记账**用它、
  预算**裁剪**却用第二套固定系数——两套口径在同一个类里各说各话；
- 另有 `_truncate_text`（第三个系数 `chars_per_token = 1.5`）**零调用方**。

判据取行为：折叠产出必须落在统一估算器的预算内，且不显著欠填（欠填就是白丢可注入的
上下文质量）。换算系数的消失由源级 AST 判据守。
"""

import ast
from pathlib import Path

import pytest

from neurova.context.injector import UnifiedContextInjector
from neurova.context.models import TokenBudget
from neurova.context.token_estimator import estimate_tokens as estimateTextTokens
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
BUDGET = 100


def _fold(content: str) -> str:
    injector = UnifiedContextInjector(
        memory_manager=None, token_budget=TokenBudget(memories=BUDGET)
    )
    return injector._build_memory_context([{"content": content, "category": ""}], "提问")


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("记忆内容示例汉字" * 40, id="中文内容"),
        pytest.param("context memory sample text " * 40, id="英文内容"),
    ],
)
def testFoldFillsItsBudgetUnderTheUnifiedEstimator(content):
    """折叠不得用第二套换算系数把预算大量空置。"""
    produced = _fold(content)

    used = estimateTextTokens(produced)
    assert 0 < used <= BUDGET, f"折叠超出预算或为空：{used}"
    assert used >= BUDGET * 0.85, (
        f"内容只用了 {used}/{BUDGET} token——固定系数裁剪在浪费可注入的上下文"
    )


def testTruncationMarkerIsCountedInsideTheBudget():
    """截断标记自身的开销要算在预算里，不能事后越界。"""
    produced = _fold("记忆内容示例汉字" * 40)

    assert estimateTextTokens(produced) <= BUDGET


def testSecondConversionFactorIsRetired():
    """防回流：注入器里不得再有 token↔字符的固定系数，模型里不得再有两份比例。"""
    injectorTree = parseSource(
        (REPO_ROOT / "neurova" / "context" / "injector.py").read_text(encoding="utf-8")
    )
    attributeNames = {
        node.attr
        for node in ast.walk(injectorTree)
        if isinstance(node, ast.Attribute)
    }
    assert "chinese_ratio" not in attributeNames, "仍在用第二套 token↔字符换算比例"
    assert "_truncate_text" not in {
        node.name
        for node in ast.walk(injectorTree)
        if isinstance(node, ast.FunctionDef)
    }, "零调用方的第二份截断实现回来了"

    modelsTree = parseSource(
        (REPO_ROOT / "neurova" / "context" / "models.py").read_text(encoding="utf-8")
    )
    defined = {
        node.name
        for node in ast.walk(modelsTree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert not {"chinese_ratio", "english_ratio"} & defined, (
        "两份比例的唯一消费方已被统一估算器取代，留着就是第二套口径"
    )
