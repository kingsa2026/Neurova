"""upper-lite 最小上层本体（B9 L1，升级计划 §12.2）。

Entity→Continuant(Agent/Document/Concept)＋Occurrent(Event) 七类；
对齐 BFO/ISO 21838 只做 `external_iris_json` 导出映射，不整包引入、
不做运行时推理。`Concept` 是类型根（一个 concept 术语），不与
`ontology_terms.kind='concept'` 的字段值混同；`Relation` 不建成 concept 类
（避免把关系实例化），仍是 term kind，导出为 `owl:ObjectProperty`（B12）。
不新增 Role/Situation 等未点单类。

播种走 `seedMissing`（只补缺）：已登记的行一行不动——上层术语同样允许
写入方覆盖声明（label/外部映射以登记者为准）。
"""

from __future__ import annotations

from typing import Any, Dict, List

_BFO = "http://purl.obolibrary.org/obo/"

UPPER_LITE_TERMS: List[Dict[str, Any]] = [
    {"termId": "Entity", "kind": "concept", "label": "实体",
     "externalIris": {"bfo": _BFO + "BFO_0000001"},
     "identityKeys": ["canonical_label"]},
    {"termId": "Continuant", "kind": "concept", "label": "连续体",
     "parentTermId": "Entity",
     "externalIris": {"bfo": _BFO + "BFO_0000002"}},
    {"termId": "Occurrent", "kind": "concept", "label": "发生体",
     "parentTermId": "Entity",
     "externalIris": {"bfo": _BFO + "BFO_0000003"}},
    {"termId": "Agent", "kind": "concept", "label": "代理",
     "parentTermId": "Continuant"},
    {"termId": "Document", "kind": "concept", "label": "文档",
     "parentTermId": "Continuant"},
    {"termId": "Concept", "kind": "concept", "label": "概念（类型根）",
     "parentTermId": "Continuant"},
    {"termId": "Event", "kind": "concept", "label": "事件",
     "parentTermId": "Occurrent",
     "externalIris": {"bfo": _BFO + "BFO_0000015"}},
]


def seedUpperLite(registry: Any, tenantId: str = "default") -> int:
    """upper-lite 幂等播种（只补缺）。与 seedBuiltinTerms 同一 owner 纪律：
    构造期种 default 租户；非 default 租户由调用方（咽喉首跳或管理面）显式补。"""
    return registry.seedMissing(UPPER_LITE_TERMS, tenantId=tenantId)
