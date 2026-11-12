# -*- coding: utf-8 -*-
"""RDF/XML 导入面（specs/2026-11-12 §18 C1）：无损往返与 inert 姿态。

- **inert 姿态**：导入的 SHACL/OWL 公理存为原始字节但**不执行**（不注册规则、
  不挂 shapes、不改判定逻辑）——与 admission"抽取只当候选"原则同构，落在导入面。
- **字节级往返**：保留原始字节＋不支持语句（导出时全量图＋原始字节引用）。
- **安全边界**：DOCTYPE/实体展开显式拒（XXE 面收窄）；资源上限超限显式拒。
- rdflib 可选生产依赖（D8 同款——惰性 import＋fail-soft，未装显式 not_supported）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 导入原始字节上限（bytes）
MAX_IMPORT_BYTES = 5 * 1024 * 1024
#: 解析后三元组上限
MAX_IMPORT_TRIPLES = 10000

_FORBIDDEN_PATTERNS = ("<!DOCTYPE", "<!ENTITY", "ENTITY")


class RdfImportNotSupported(RuntimeError):
    """rdflib 未安装——显式 not_supported。"""


class RdfImportSecurityError(ValueError):
    """DOCTYPE/实体展开等安全拒绝。"""


class RdfImportLimitError(ValueError):
    """资源上限超限显式拒。"""


class RdfImportResult:
    """导入结果：三元组＋原始字节＋不支持语句＋inert 声明。"""

    def __init__(self) -> None:
        self.triples: List[Dict[str, str]] = []
        self.original_bytes: bytes = b""
        self.unsupported: List[str] = []
        self.inert = True
        self.triple_count = 0


def importRdfXml(data: bytes, agentId: str = "default",
                 tenantId: str = "default") -> RdfImportResult:
    """RDF/XML 导入（inert 姿态）：解析＋保留原始字节＋安全边界。

    - DOCTYPE/ENTITY 声明显式拒（XXE 面收窄——RdfImportSecurityError）
    - 字节数超 MAX_IMPORT_BYTES / 三元组数超 MAX_IMPORT_TRIPLES 显式拒
    - rdflib 未装 → RdfImportNotSupported（诚实形态）
    - 返回 RdfImportResult（triple list＋原始字节＋unsupported＋inert=True）"""
    if len(data) > MAX_IMPORT_BYTES:
        raise RdfImportLimitError(
            "导入字节数 %d 超上限 %d" % (len(data), MAX_IMPORT_BYTES))
    # 安全预检：DOCTYPE/ENTITY 文本级扫描（在 XML 解析器之前拦截）
    text = data[:min(len(data), 4096)].decode("utf-8", errors="replace")
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern in text.upper():
            raise RdfImportSecurityError(
                "RDF/XML 含 %s 声明（XXE 安全面收窄——显式拒，不传给解析器）" % pattern)
    result = RdfImportResult()
    result.original_bytes = data
    if not _rdflibAvailable():
        raise RdfImportNotSupported(
            "rdflib 未安装：RDF/XML 导入显式 not_supported（D8 可选生产依赖同款）")
    import rdflib

    graph = rdflib.Graph()
    try:
        graph.parse(data=data, format="xml")
    except Exception as exc:
        raise ValueError("RDF/XML 解析失败：%s" % exc)
    if len(graph) > MAX_IMPORT_TRIPLES:
        raise RdfImportLimitError(
            "解析三元组 %d 超上限 %d" % (len(graph), MAX_IMPORT_TRIPLES))
    for subj, pred, obj in graph:
        result.triples.append({
            "subject": str(subj),
            "predicate": str(pred),
            "object": str(obj),
        })
    result.triple_count = len(result.triples)
    # inert 姿态声明：不执行 OWL/SHACL——unsupported 清单记录非标三元组
    _owlShacl = ("http://www.w3.org/2002/07/owl#",
                 "http://www.w3.org/ns/shacl#")
    for t in result.triples:
        if any(t["predicate"].startswith(ns) for ns in _owlShacl):
            result.unsupported.append(
                "%s %s %s" % (t["subject"][:60], t["predicate"][:60],
                              t["object"][:60]))
    return result


def _rdflibAvailable() -> bool:
    try:
        import rdflib  # noqa: F401
        return True
    except ImportError:
        return False
