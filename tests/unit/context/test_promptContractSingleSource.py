# -*- coding: utf-8 -*-
"""提示面契约单源守卫（D-6）。

立项理由（本仓可核实）：同一段契约措辞曾在两条拼装路径里各写一份——
技能目录提示语在 `_skill_catalog_section` 的两个分支重复；「行为规则」段标题在
`orchestrator.build_system_prompt` 与 `context/builder.py` 各写一份。改一处忘另一处
不会报错，只会让两条路径的 system prompt 悄悄分叉。本判据钉**代码形态**：
字面量只许存在于常量定义处，消费方必须引用常量。
"""
from __future__ import annotations

from pathlib import Path

_CTX = Path(__file__).resolve().parents[3] / "neurova" / "context"


def _sources() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in _CTX.glob("*.py")}


def test_behaviorRulesHeaderIsDeclaredOnceAndConsumedByName():
    sources = _sources()
    # 裸短语而不是带闭合引号的完整字面量：变异形态是 `"## 行为规则\n"`，
    # 带结尾引号的匹配会当场失明（本判据第一次写就这样假绿过一次）。
    holders = [name for name, text in sources.items() if "## 行为规则" in text]
    assert holders == ["rules_sections.py"], f"标题字面量出现处 {holders}，应只在单源常量里"
    for consumer in ("orchestrator.py", "builder.py"):
        assert "BEHAVIOR_RULES_HEADER" in sources[consumer], f"{consumer} 未引用单源常量"


def test_skillCatalogHintIsDeclaredOnceAndUsedByBothBranches():
    source = (_CTX / "orchestrator.py").read_text(encoding="utf-8")
    assert source.count("显式调用完整内容") == 1, "技能目录提示语有自己的第二份字面量"
    assert source.count("SKILL_CATALOG_HINT") >= 3, (
        "常量至少应被两条分支各引用一次（定义 1 处 + 使用 2 处）"
    )
