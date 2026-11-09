"""upper-lite 最小上层本体（B9 L1，升级计划 §12.2）＋事件/时间受控词汇（B11 L3，§12.4）。

Entity→Continuant(Agent/Document/Concept)＋Occurrent(Event) 七类；
对齐 BFO/ISO 21838 只做 external_iris_json 导出映射（G3 结构化列表，bfo 前缀别名按 v39 迁移规则归 skos_exactMatch），不整包引入、
不做运行时推理。`Concept` 是类型根（一个 concept 术语），不与
`ontology_terms.kind='concept'` 的字段值混同；`Relation` 不建成 concept 类
（避免把关系实例化），仍是 term kind，导出为 `owl:ObjectProperty`（B12）。
不新增 Role/Situation 等未点单类。
事件/时间那一组（hasParticipant/hasTime＋Allen 四条）同属这一张种子表：
词汇是数据，但「哪些关系算时间关系」由这里单点定义，别处不再抄一份清单。

播种走 `seedMissing`（只补缺）：已登记的行一行不动——上层术语同样允许
写入方覆盖声明（label/外部映射以登记者为准）。
"""

from __future__ import annotations

from typing import Any, Dict, List

_BFO = "http://purl.obolibrary.org/obo/"
#: OWL-Time 只做导出映射（external_iris 列表，kind=skos_exactMatch），不引运行时时间推理。
_OWL_TIME = "https://www.w3.org/2006/time#"

UPPER_LITE_TERMS: List[Dict[str, Any]] = [
    {"termId": "Entity", "kind": "concept", "label": "实体",
     "externalIris": [{"kind": "skos_exactMatch", "iri": _BFO + "BFO_0000001"}],
     "identityKeys": ["canonical_label"]},
    {"termId": "Continuant", "kind": "concept", "label": "连续体",
     "parentTermId": "Entity",
     "externalIris": [{"kind": "skos_exactMatch", "iri": _BFO + "BFO_0000002"}]},
    {"termId": "Occurrent", "kind": "concept", "label": "发生体",
     "parentTermId": "Entity",
     "externalIris": [{"kind": "skos_exactMatch", "iri": _BFO + "BFO_0000003"}]},
    {"termId": "Agent", "kind": "concept", "label": "代理",
     "parentTermId": "Continuant"},
    {"termId": "Document", "kind": "concept", "label": "文档",
     "parentTermId": "Continuant"},
    {"termId": "Concept", "kind": "concept", "label": "概念（类型根）",
     "parentTermId": "Continuant"},
    {"termId": "Event", "kind": "concept", "label": "事件",
     "parentTermId": "Occurrent",
     "externalIris": [{"kind": "skos_exactMatch", "iri": _BFO + "BFO_0000015"}]},
    # ── 事件/时间模式（B11 L3，§12.4 设计 3）────────────────────────
    # 受控关系词汇：事件的参与者/时间，以及四条 Allen 区间关系挂在既有 `temporal`
    # 父属性之下（不另造第二组时间词汇）。OWL-Time 只作 `skos_exactMatch` 导出映射
    # ——本仓不做运行时时间推理（不引区间代数），所以这四条**不得**生成传递规则；
    # 反面判据钉在 test_eventTimePattern.py。`hasParticipant` 不声明值域：
    # 参与者可以是任何 continuant，钉死值域只会把未登记主体一律判成违规。
    {"termId": "hasParticipant", "kind": "relation", "label": "有参与者",
     "domain": ["Event"]},
    {"termId": "hasTime", "kind": "relation", "label": "有时间",
     "domain": ["Event"],
     "externalIris": [{"kind": "skos_exactMatch", "iri": _OWL_TIME + "hasTime"}]},
    {"termId": "before", "kind": "relation", "label": "在…之前",
     "parentTermId": "temporal", "domain": ["Event"], "rangeTerms": ["Event"],
     "externalIris": [{"kind": "skos_exactMatch", "iri": _OWL_TIME + "before"}]},
    {"termId": "after", "kind": "relation", "label": "在…之后",
     "parentTermId": "temporal", "domain": ["Event"], "rangeTerms": ["Event"],
     "externalIris": [{"kind": "skos_exactMatch", "iri": _OWL_TIME + "after"}]},
    {"termId": "overlaps", "kind": "relation", "label": "与…重叠",
     "parentTermId": "temporal", "domain": ["Event"], "rangeTerms": ["Event"],
     "externalIris": [{"kind": "skos_exactMatch", "iri": _OWL_TIME + "overlaps"}]},
    {"termId": "during", "kind": "relation", "label": "在…期间",
     "parentTermId": "temporal", "domain": ["Event"], "rangeTerms": ["Event"],
     "externalIris": [{"kind": "skos_exactMatch", "iri": _OWL_TIME + "during"}]},
]


def seedUpperLite(registry: Any, tenantId: str = "default") -> int:
    """upper-lite 幂等播种（只补缺）。与 seedBuiltinTerms 同一 owner 纪律：
    构造期种 default 租户；非 default 租户由调用方（咽喉首跳或管理面）显式补。"""
    return registry.seedMissing(UPPER_LITE_TERMS, tenantId=tenantId)
