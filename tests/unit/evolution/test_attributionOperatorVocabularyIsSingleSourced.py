# -*- coding: utf-8 -*-
"""反思算子词表必须是**一份**定义（M-E 前半；AGENTS.md 教义第 6 条 / §2 双源条款）。

## 实测的双源

`cognitive_layers/meta_cognition_layer/self_model.py` 的反思循环里逐字写了五个算子名
（`drift`/`sequence`/`contrast`/`calibration`/`budget`），而
`evolution/skill_attribution.py:38` 又抄了一份 `_KNOWN_OPERATORS = {...}` 当技能归因的闸门
（唯一读点是 :164 的 `operator not in _KNOWN_OPERATORS`）。两份各自演进时，
**加第五个算子的人只会改自己那一份**：反思侧产出新算子教训，归因侧一律判"未知算子"丢弃——
红的是 neither：两边都绿，教训静默不落技能库。这正是"两边都留着、加个同步脚本"被明禁的形状。

## 处置

词表单点落在 `self_model.OPERATORS`（产出的那一侧才是它的定义者），
归因侧改为**调用时**从单点取（不许 import 期把值抄成快照——那样单点变更另一侧照样不生效，
比手抄更隐蔽）。`skill_attribution` 里每个算子的经验文本模板仍留本地：那是**内容**不是**词表**
（模板缺项有兜底文本），本守卫只禁"词表形状"的第二次定义。

## 判据五格

1. 跨文件等值：归因侧认的集合 == `self_model.OPERATORS`。
2. 单点变更**当场两处同生效**（正向注入一个新算子名）——证不是 import 期快照。
3. 反向钉：`skill_attribution.py` 里不得再出现算子词表形状的字面集合定义
   （≥3 个算子名同现的 set/tuple/list 字面量），模板字典键不算。
4. 词表不是空名单：每个名字都必须有对应实装 `_op_<name>`（`calibration` 的签名例外要在
   循环里有适配，缺适配即红）。
5. 行为不回归：未知算子的教训仍被归因闸门拒掉；模板缺项走兜底文本、不抛。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from tests.ast_scan import parseSource

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_ATTRIBUTION_PY = PROJECT_ROOT / "neurova" / "evolution" / "skill_attribution.py"
SELF_MODEL_PY = PROJECT_ROOT / "neurova" / "cognitive_layers" / "meta_cognition_layer" / "self_model.py"

OPERATOR_NAMES = {"drift", "sequence", "contrast", "calibration", "budget"}


def _operatorsAcceptedByAttributionGate() -> set:
    """归因闸门实际认下的算子集合（走真实判定函数，不读常量抄本）。"""
    import neurova.evolution.skill_attribution as sa

    known = getattr(sa, "_knownOperators", None)
    assert callable(known), "归因侧没有从单点取词表的入口（仍在用自己那份手抄集合）"
    return set(known())


class TestOperatorVocabularyHasOneDefinition:
    def test_1_attributionGateAcceptsExactlyTheSingleSourceNames(self):
        from neurova.cognitive_layers.meta_cognition_layer.self_model import OPERATORS

        assert set(OPERATORS) == OPERATOR_NAMES, f"单点词表漂了：{set(OPERATORS)}"
        assert _operatorsAcceptedByAttributionGate() == set(OPERATORS), (
            "归因侧认的算子与单点不等值——两份定义还在各自演进"
        )

    def test_2_singleSourceChangeTakesEffectBothSides(self, monkeypatch):
        """往单点加一个新算子名，归因闸门必须**当场**认它。

        这一格专杀"import 期抄成快照"的假收口：`from x import OPERATORS` 把值绑死在
        导入那一刻，单点再怎么改另一侧都不动——比手抄更难发现，因为它看起来是引用单点。
        """
        import neurova.cognitive_layers.meta_cognition_layer.self_model as sm

        monkeypatch.setattr(sm, "OPERATORS", tuple(sm.OPERATORS) + ("brand_new_operator",),
                            raising=False)
        accepted = _operatorsAcceptedByAttributionGate()
        assert "brand_new_operator" in accepted, (
            "单点加了算子而归因侧不认——取值发生在 import 期（快照），单点是假的"
        )

    def test_3_noSecondVocabularyLiteralInAttributionModule(self):
        tree = parseSource(SKILL_ATTRIBUTION_PY.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
                names = {
                    elt.value for elt in node.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    and elt.value in OPERATOR_NAMES
                }
                if len(names) >= 3:
                    offenders.append(f":{node.lineno} {sorted(names)}")
        assert not offenders, (
            f"归因模块里仍留算子词表的第二份字面定义 {offenders}（模板字典的键不算，"
            "那是内容不是词表）"
        )

    def test_4_everyNameInVocabularyHasAnImplementation(self):
        from neurova.cognitive_layers.meta_cognition_layer.self_model import OPERATORS, SelfModelEngine

        missing = []
        for name in OPERATORS:
            if not callable(getattr(SelfModelEngine, f"_op_{name}", None)):
                missing.append(name)
        assert not missing, f"词表里有名字没有实装 `_op_<name>`：{missing}（空名单比没名单更坏）"
        source = SELF_MODEL_PY.read_text(encoding="utf-8")
        assert "OPERATORS" in source and "for op_name in OPERATORS" in source.replace(
            "for op_name, op in (", "for op_name in OPERATORS"), (
            "反思循环没有从单点取名字（仍在逐字写五对名字-实现）"
        )

    def test_5_unknown_operator_still_refused_and_template_falls_back(self):
        import neurova.evolution.skill_attribution as sa

        # 未知算子：闸门必须照旧拒（单点收口不许顺手放宽）
        assert "not_a_real_operator" not in _operatorsAcceptedByAttributionGate()
        # 模板缺项：走兜底文本，不 KeyError
        content = sa._guidance_content("some_tool", "brand_new_operator")
        assert isinstance(content, str) and "some_tool" in content, (
            f"新算子无模板时应落兜底文本，实得 {content!r}"
        )
