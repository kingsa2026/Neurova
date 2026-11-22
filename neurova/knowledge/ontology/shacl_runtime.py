"""SHACL 运行时校验（升级卡 U1）：形状单源 → pyshacl 求值 → 违规解释。

三档开关 `NEUROVA_ONTOLOGY_SHACL_RUNTIME=off|shadow|enforce`（默认 off）：
- **off**：完全不跑（零开销，既有写入路径行为不变）；
- **shadow**：跑并告警，不拒写；
- **enforce**：在准入咽喉段 3 后半拒写 sh:Violation 级违规（warning/info
  级只记录不拦截——严重级由形状注册时的三态声明带到 sh:severity）。

形状单源：`ShapeRegistry` → `export/shacl.exportShaclShapes`（与导出面
逐字节同源，这里不重排任何形状语义）；数据图：`turtle.serializeAll`
同一序列化出口按主体邻域圈定（subjectKeys + 候选行），不做全库校验。

pyshacl 惰性 import＋fail-soft：依赖已入 requirements.txt（install.py 与
桌面端首启链自动安装）；旧环境未装时显式 `supported=False` 诚实降级，
不炸写入面，也不假装"校验通过"。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MODE_ENV = "NEUROVA_ONTOLOGY_SHACL_RUNTIME"
_VALID_MODES = ("off", "shadow", "enforce")
_SH = "http://www.w3.org/ns/shacl#"


def shaclMode() -> str:
    """当前 SHACL 运行时档位；非法值告警后按 off 处理（不炸写入面）。"""
    raw = str(os.environ.get(_MODE_ENV, "off") or "off").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning("SHACL 档位 %r 非法（有效值 %s），按 off 处理",
                       raw, "/".join(_VALID_MODES))
        return "off"
    return raw


def _importPyshacl():
    """惰性 import pyshacl（可选依赖：requirements.txt 已声明，首启自动安装）。"""
    import pyshacl  # noqa: F401  # 第三方可选依赖：点名豁免（形态同 sparql_query 的 rdflib）

    return pyshacl


def _loadGraph(ttl: str):
    import rdflib  # 随 pyshacl 传递可用

    graph = rdflib.Graph()
    graph.parse(data=ttl, format="turtle")
    return graph


def _parseViolations(resultsGraph: Any) -> List[Dict[str, str]]:
    """把 pyshacl 的 results graph 读成结构化违规清单（无结果→空表）。"""
    import rdflib

    out: List[Dict[str, str]] = []
    for node in resultsGraph.subjects(rdflib.RDF.type, rdflib.URIRef(_SH + "ValidationResult")):
        def _v(pred: str) -> str:
            value = resultsGraph.value(node, rdflib.URIRef(_SH + pred))
            return str(value) if value is not None else ""

        out.append({
            "focusNode": _v("focusNode"),
            "path": _v("resultPath"),
            "value": _v("value"),
            "message": _v("resultMessage"),
            "severity": (_v("resultSeverity").rsplit("#", 1)[-1] or "Violation"),
            "component": _v("sourceConstraintComponent").rsplit("#", 1)[-1],
        })
    return out


def validateShapesRuntime(store: Any, tenantId: str = "default", *,
                          agentId: Optional[str] = None, mode: Optional[str] = None,
                          dataGraphTtl: Optional[str] = None,
                          subjectKeys: Optional[List[str]] = None,
                          extraFacts: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """跑一次 SHACL 校验，返回结构化报告（纯只读，不写任何表）。

    dataGraphTtl 缺省时按 subjectKeys(+extraFacts) 圈定主体邻域子图；
    两者都缺省则全库投影（REST dry-run 面用）。形状图恒走
    `exportShaclShapes`——运行时与导出是同一份形状文档（单一事实源）。
    """
    mode = mode or shaclMode()
    base: Dict[str, Any] = {"supported": True, "mode": mode, "conforms": True,
                            "violations": [], "text": ""}
    if mode == "off":
        base["skipped"] = True
        return base
    try:
        pyshacl = _importPyshacl()
    except ImportError as exc:
        return {"supported": False, "mode": mode,
                "reason": "pyshacl 未安装：%s（依赖已入 requirements.txt，首启链自动补齐）" % exc,
                "conforms": True, "violations": [], "text": ""}

    from .export.shacl import exportShaclShapes
    from . import turtle as turtleExport

    shapesTtl = exportShaclShapes(store, tenantId)
    if not any(line.startswith("kbg:shape_") for line in shapesTtl.splitlines()):
        base["note"] = "无已注册用户形状"
        return base
    if dataGraphTtl is None:
        dataGraphTtl = turtleExport.serializeAll(
            store, tenantId=tenantId, agentId=agentId,
            subjectKeys=subjectKeys, extraFacts=extraFacts)

    dataGraph = _loadGraph(dataGraphTtl)
    shapesGraph = _loadGraph(shapesTtl)
    conforms, resultsGraph, resultsText = pyshacl.validate(
        data_graph=dataGraph, shacl_graph=shapesGraph, inference="none")
    return {"supported": True, "mode": mode, "conforms": bool(conforms),
            "violations": _parseViolations(resultsGraph),
            "text": str(resultsText or "")}


def admissionShaclCheck(store: Any, request: Any, subjectKey: Optional[str]) -> List[str]:
    """准入咽喉段 3 后半的 SHACL 闸：enforce 档返回拒写理由，其余档返回 []。

    shadow 档逐条告警不拒写；pyshacl 缺席时告警并放行（fail-soft——依赖由
    首启链补齐，不因环境缺件冻结写入面）。只判三元组事实；叙述/条目类
    record_kind 不进形状语义。
    """
    mode = shaclMode()
    if mode == "off":
        return []
    if str(getattr(request, "recordKind", "") or "") != "triple":
        return []
    tenantId = str(getattr(request, "tenantId", "") or "default")
    agentId = str(getattr(request, "agentId", "") or "") or None
    report = validateShapesRuntime(
        store, tenantId, agentId=agentId, mode=mode,
        subjectKeys=[str(subjectKey or "")] if subjectKey else None,
        extraFacts=([{"subject_key": str(subjectKey or ""),
                      "predicate_term_id": str(getattr(request, "predicateTermId", "") or ""),
                      "object_term": str(getattr(request, "objectTerm", "") or "")}]
                    if subjectKey else None))
    if not report.get("supported"):
        logger.warning("SHACL enforce 档因依赖缺位降级放行：%s", report.get("reason"))
        return []
    blocking = [v for v in report.get("violations", []) if v.get("severity") == "Violation"]
    if mode == "shadow":
        for item in blocking:
            logger.warning("SHACL shadow 违规（不拒写）：subject=%s %s %s",
                           subjectKey, item.get("message"), item.get("value"))
        return []
    return ["%s: %s（focus=%s value=%s）" % (
        v.get("component") or "Violation",
        v.get("message") or v.get("component") or "形状违规",
        v.get("focusNode"), v.get("value")) for v in blocking]
