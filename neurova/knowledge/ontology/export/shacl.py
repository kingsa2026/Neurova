"""SHACL shapes 导出（B12 L7）：形状注册表 → sh: 词汇，互操作声明。

不引第三方 SHACL 引擎（§6）；导出的是注册表里用户 shape 的镜像，
内置 6 项校验不重复导出（它们是写面判据，不是数据形状）。
"""

from __future__ import annotations

from typing import Any

from ..shapes import ShapeRegistry


def exportShaclShapes(store: Any, tenantId: str = "default") -> str:
    shapes = ShapeRegistry(store).list(tenantId=tenantId, enabledOnly=False)
    lines = [
        "@prefix sh: <http://www.w3.org/ns/shacl#> .",
        "@prefix kbg: <https://neurova.local/knowledge/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    ]
    for shape in shapes:
        subject = "kbg:shape_%s" % shape["shape_id"]
        lines.append("%s rdf:type sh:NodeShape ;" % subject)
        lines.append("  sh:targetObjectsOf kbg:%s ;"
                     % shape["target_term_id"] if shape["target_term_id"]
                     else "  sh:targetClass kbg:Term ;")
        constraint = shape["constraint"]
        kind = shape["constraint_kind"]
        if kind == "in":
            values = " ".join(str(v) for v in constraint.get("values") or [])
            lines.append("  sh:in ( %s ) ;" % values)
        elif kind == "pattern":
            lines.append("  sh:pattern %s ;" % jsonQuote(constraint.get("pattern")))
        elif kind == "minCount":
            lines.append("  sh:minCount %s ;" % constraint.get(kind))
        elif kind == "maxCount":
            lines.append("  sh:maxCount %s ;" % constraint.get(kind))
        elif kind == "class":
            lines.append("  sh:class kbg:%s ;" % constraint.get("class"))
        lines.append("  sh:severity sh:%s ;" % shape["severity"].capitalize())
        lines.append("  sh:message %s ." % jsonQuote(shape["message"]))
    return "\n".join(lines) + "\n"


def jsonQuote(text: Any) -> str:
    return '"%s"' % str(text or "").replace("\\", "\\\\").replace('"', '\\"')
