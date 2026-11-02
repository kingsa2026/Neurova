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
    # 面自证：根被改窄时"零命中"与"真干净"同形，先量扫到了多少再谈字面量只有一处。
    scanned = len(sources)
    assert scanned >= 25, (
        f"扫描面现读 {scanned}（`neurova/context/*.py` 实测 31）——根解窄了本判据就成了空转"
    )
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


def test_sectionTitlesLiveOnlyInRulesSections():
    """批 A2：四段标题全部单源——只许在 rules_sections.py 定义，任何拼装路径
    出现第二份字面量即双源（改一处忘另一处的分叉温床，同上两个判据的根）。"""
    sources = _sources()
    scanned = len(sources)
    assert scanned >= 25, (
        f"扫描面现读 {scanned}（`neurova/context/*.py` 实测 31）——根解窄了本判据就成了空转"
    )
    for title in ("## 工具使用规则", "## 环境", "## 记忆写入规则", "## 桌面操作纪律"):
        holders = [name for name, text in sources.items() if title in text]
        assert holders == ["rules_sections.py"], (
            f"段标题「{title}」出现处 {holders}，应只在 rules_sections.py 单源定义"
        )


def test_rulesSectionToolMentionsMustBeRegistered():
    """批 A2：恒定段提及的工具名必须真实注册——防幽灵路由句（拼错的工具名
    写进规则段，模型会照着调然后失败）。工具名清单单源在
    `builtin_tools.get_registered_tool_names()`，改文案先对表。"""
    import re

    from neurova.builtin_tools import get_registered_tool_names
    from neurova.context.rules_sections import build_all_sections

    text = build_all_sections(workspace_path="")
    mentioned = sorted(set(re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text)))
    registered = set(get_registered_tool_names())
    unknown = [t for t in mentioned if t not in registered]
    assert not unknown, (
        f"恒定规则段提及了未注册的工具名: {unknown}——拼写错误或工具已更名"
    )
