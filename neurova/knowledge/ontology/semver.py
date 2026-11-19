"""本体语义版本（B12 L8，升级计划 §12.9）：semver 判定/比较/推进。

规则：破坏性变更＝major、增术语＝minor、修标签＝patch；
存量 `vN` 形状不是 semver（只读兼容），新登记走 semver。
"""

from __future__ import annotations

import re

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def isSemver(version: str) -> bool:
    return bool(_SEMVER.match(str(version or "").strip()))


def _parts(version: str) -> tuple:
    match = _SEMVER.match(str(version or "").strip())
    if not match:
        raise ValueError("版本 %r 不是 semver 形状（X.Y.Z）" % version)
    return tuple(int(g) for g in match.groups())


def compareVersions(left: str, right: str) -> int:
    """left < right ⇒ 负数；相等 ⇒ 0；大于 ⇒ 正数。"""
    lp, rp = _parts(left), _parts(right)
    return (lp > rp) - (lp < rp)


def bumpVersion(version: str, kind: str) -> str:
    """按变更种类推进：major（破坏性）/ minor（增术语）/ patch（修标签）。"""
    major, minor, patch = _parts(version)
    if kind == "major":
        return "%d.0.0" % (major + 1)
    if kind == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if kind == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ValueError("未知版本推进种类 %r（有效值: major / minor / patch）" % kind)


# ── 版本 impact 预标注（对照研究 P2-2，2026-11-19）─────────────────────
#
# 把 `OntologyPipeline.diff()` 的结构翻译成"这条变更会要求什么后续动作"的
# 预标注（对方四态的本仓适配）。**纯展示+审批辅助**：不改 semver 判定、不改
# 流水线行为、不做任何写入。四态语义（本仓语境）：
#   - breaking：本体结构被破坏（术语删除/父链/分类特征/关系代数特征变更），
#     既有推导与导出公理可能失效；
#   - needs_remap：值域/类型/限定符口径变了——企业源映射配置要跟着改；
#   - needs_reextraction：消解口径变了（显示名/别名/身份判据）——已抽事实
#     的主体对齐可能要重跑；
#   - needs_rule_build：规则面有任何增删改。
# 定义/描述类字段变更不标 impact（patch 级装饰，不影响任何下游）。

_IMPACT_BREAKING_FIELDS = ("parent_term_id", "kind", "disjoint_with",
                           "inverse_of", "symmetric", "transitive")
_IMPACT_REMAP_FIELDS = ("datatype", "qualifier_schema", "cardinality",
                        "domain_terms", "range_terms", "range_kinds",
                        "required_props")
_IMPACT_REEXTRACTION_FIELDS = ("label", "aliases", "labels", "alt_labels",
                               "identity_keys")


def impactOfDiff(diff: dict) -> dict:
    """pipeline diff → 逐条 impact 预标注（纯函数，只读）。

    输入形如 `{"terms": {"added": [...], "removed": [...], "changed": [
    {"id","from","to"}]}, "rules": {...}}`；输出 `{"items": [...],
    "summary": {四态计数}}`。
    """
    items: list = []

    for termId in sorted(diff.get("terms", {}).get("removed") or []):
        items.append({"kind": "term", "id": str(termId), "action": "removed",
                      "impact": ["breaking"]})

    for change in sorted(diff.get("terms", {}).get("changed") or [],
                         key=lambda c: str(c.get("id") or "")):
        termId = str(change.get("id") or "")
        before = change.get("from") or {}
        after = change.get("to") or {}
        labels: list = []
        for field in _IMPACT_BREAKING_FIELDS:
            if before.get(field) != after.get(field):
                labels.append("breaking")
                break
        for field in _IMPACT_REMAP_FIELDS:
            if before.get(field) != after.get(field):
                labels.append("needs_remap")
                break
        for field in _IMPACT_REEXTRACTION_FIELDS:
            if before.get(field) != after.get(field):
                labels.append("needs_reextraction")
                break
        items.append({"kind": "term", "id": termId, "action": "changed",
                      "impact": labels})

    for termId in sorted(diff.get("terms", {}).get("added") or []):
        items.append({"kind": "term", "id": str(termId), "action": "added",
                      "impact": []})

    rulesDiff = diff.get("rules", {})
    for ruleId in sorted(rulesDiff.get("added") or []):
        items.append({"kind": "rule", "id": str(ruleId), "action": "added",
                      "impact": ["needs_rule_build"]})
    for ruleId in sorted(rulesDiff.get("removed") or []):
        items.append({"kind": "rule", "id": str(ruleId), "action": "removed",
                      "impact": ["needs_rule_build"]})
    for change in rulesDiff.get("changed") or []:
        items.append({"kind": "rule", "id": str(change.get("id") or ""),
                      "action": "changed", "impact": ["needs_rule_build"]})

    summary = {
        "breaking": sum(1 for i in items if "breaking" in i["impact"]),
        "needs_remap": sum(1 for i in items if "needs_remap" in i["impact"]),
        "needs_reextraction": sum(1 for i in items
                                  if "needs_reextraction" in i["impact"]),
        "needs_rule_build": sum(1 for i in items
                                if "needs_rule_build" in i["impact"]),
    }
    return {"items": items, "summary": summary}
