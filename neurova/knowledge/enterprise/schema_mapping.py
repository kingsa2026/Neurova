"""源库 schema 映射描述符（B14 §14.2）：R2RML 风格 JSON 子集。

编译期校验（apply 前一次判完）：模板占位符必须是已声明列；predicate 必须是
已登记 term_id；object kind 闭集；不允许任意 SQL/子查询/函数调用；qualifier
不许出现未声明列。映射按租户隔离，sourceId 租户内唯一。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .protocols import SOURCE_TYPES

#: object kind 闭集：column（列值）/template（模板拼出）/term（常量术语）/literal（常量字面量）
OBJECT_KINDS = ("column", "template", "term", "literal")

#: 变体闭集（2026-11-07 裁定 §2.3-1A）：单类型＋变体字段。编译期「给了就收口、
#: 不给不拒」——B14 时代 sql/erp_api 描述符没有变体字段，存量判据不破；
#: 工厂（registry.buildAdapter）按需强制要求。闭集随适配器批次只增不改。
VARIANT_CLOSED_SETS: Dict[str, tuple] = {
    "file": ("format", ("csv", "tsv", "json", "jsonl")),
    "sql": ("driver", ("postgresql", "mysql", "mssql", "oracle", "sqlite")),
    "erp_api": ("vendor", ("kingdee", "yongyou")),
    "chat": ("vendor", ("wecom", "wechat")),
}

_TEMPLATE_SLOT = re.compile(r"\{([A-Za-z0-9_]+)\}")

#: v34 迁移：企业源配置表（描述符/游标/启用开关）。凭据不在此表（复用 NEUROVA_KB_SECRET）。
SCHEMA_V34 = """
CREATE TABLE IF NOT EXISTS enterprise_source_configs (
    source_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    descriptor_json TEXT NOT NULL DEFAULT '{}',
    cursor TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_id)
);
"""


class MappingError(ValueError):
    """映射描述符非法：编译期一次判完，坏描述符进不了运行时。"""


def validateDescriptor(descriptor: Dict[str, Any], registry: Any,
                       tenantId: str = "default") -> None:
    """编译期校验（§14.2）。非法即 MappingError，带定位。"""
    sourceType = str(descriptor.get("sourceType") or "")
    if sourceType not in SOURCE_TYPES:
        raise MappingError(
            "sourceType %r 不在白名单（%s）" % (sourceType, " / ".join(SOURCE_TYPES)))
    if sourceType in VARIANT_CLOSED_SETS:
        field, closed = VARIANT_CLOSED_SETS[sourceType]
        variant = str(descriptor.get(field) or "")
        if variant and variant not in closed:
            raise MappingError("%s 的 %s %r 不在闭集（%s）"
                               % (sourceType, field, variant, " / ".join(closed)))
    columns = set(descriptor.get("columns") or [])
    if not columns:
        raise MappingError("映射描述符缺 columns 声明（logical table 列集）")

    subject = descriptor.get("subject") or {}
    template = str(subject.get("template") or "")
    for slot in _TEMPLATE_SLOT.findall(template):
        if slot not in columns:
            raise MappingError("subject 模板占位符 {%s} 不是已声明列" % slot)
    if not template and not subject.get("column"):
        raise MappingError("subject 缺 template 或 column")

    predicate = descriptor.get("predicate") or {}
    predicateTermId = str(predicate.get("termId") or "")
    if not predicateTermId:
        raise MappingError("predicate 缺 termId")
    if registry is not None and registry.term(predicateTermId, tenantId=tenantId) is None:
        raise MappingError("predicate %s 未登记（先登记术语再配映射）" % predicateTermId)

    obj = descriptor.get("object") or {}
    objKind = str(obj.get("kind") or "")
    if objKind not in OBJECT_KINDS:
        raise MappingError("object.kind %r 不在闭集（%s）"
                           % (objKind, " / ".join(OBJECT_KINDS)))
    if objKind == "column" and str(obj.get("column") or "") not in columns:
        raise MappingError("object.column %r 不是已声明列" % obj.get("column"))
    for slot in _TEMPLATE_SLOT.findall(str(obj.get("template") or "")):
        if slot not in columns:
            raise MappingError("object 模板占位符 {%s} 不是已声明列" % slot)
    if objKind == "term":
        termId = str(obj.get("termId") or "")
        if registry is not None and registry.term(termId, tenantId=tenantId) is None:
            raise MappingError("object.term %s 未登记" % termId)

    for key, column in (descriptor.get("qualifiers") or {}).items():
        if str(column) not in columns:
            raise MappingError("qualifier %r 的列 %r 不是已声明列" % (key, column))
    for timeKey in ("validFrom", "validUntil"):
        column = str(descriptor.get(timeKey) or "")
        if column and column not in columns:
            raise MappingError("%s 的列 %r 不是已声明列" % (timeKey, column))

    # SQL 注入面守卫：描述符任何字段不允许 SQL 关键字形状（映射里不写 SQL）。
    # 例外（C4 SQL 直连）：sourceType="sql" 的 descriptor["query"] 本来就是
    # 只读 SQL 模板，其形状由适配器构造期自守（首词白名单＋写关键词边界
    # ＋槽位强制），守卫对它豁免；其余字段（含非 sql 源的 query 字段）照旧全禁。
    blob = str(descriptor)
    if sourceType == "sql" and "query" in descriptor:
        guarded = {k: v for k, v in descriptor.items() if k != "query"}
        blob = str(guarded)
    for banned in ("SELECT ", "INSERT ", "DROP ", "DELETE ", "UPDATE ", "--", ";"):
        if banned.lower() in blob.lower():
            raise MappingError("描述符含 SQL 形状片段 %r——映射里不写 SQL" % banned.strip())


def applyMapping(descriptor: Dict[str, Any], row: Dict[str, Any],
                 registry: Any, tenantId: str = "default") -> Dict[str, Any]:
    """把一行源数据按描述符映射成 AdmissionRequest 的字段面（不落库）。

    返回 {subjectLabel, predicateTermId, objectTerm, qualifier, validFrom, validUntil}。
    object 为列且列值命中关系白名单时映射为 term 语义；未命中按字面量处理（finding 面由调用方判）。
    """
    subject = descriptor.get("subject") or {}
    template = str(subject.get("template") or "")

    def _fill(t: str) -> str:
        out = t
        for slot in _TEMPLATE_SLOT.findall(t):
            out = out.replace("{%s}" % slot, str(row.get(slot, "")))
        return out

    subjectLabel = _fill(template) if template else str(row.get(subject.get("column") or "", ""))
    predicateTermId = str((descriptor.get("predicate") or {}).get("termId") or "")

    obj = descriptor.get("object") or {}
    objKind = str(obj.get("kind") or "")
    if objKind == "column":
        objectTerm = str(row.get(str(obj.get("column") or ""), ""))
    elif objKind == "template":
        objectTerm = _fill(str(obj.get("template") or ""))
    elif objKind == "term":
        objectTerm = str(obj.get("termId") or "")
    else:
        objectTerm = str(obj.get("value") or "")

    qualifier = {key: str(row.get(column, ""))
                 for key, column in (descriptor.get("qualifiers") or {}).items()}
    return {
        "subjectLabel": subjectLabel,
        "predicateTermId": predicateTermId,
        "objectTerm": objectTerm,
        "qualifier": qualifier,
        "validFrom": str(row.get(str(descriptor.get("validFrom") or ""), "")) or None
        if descriptor.get("validFrom") else None,
        "validUntil": str(row.get(str(descriptor.get("validUntil") or ""), "")) or None
        if descriptor.get("validUntil") else None,
        # 源钟列映射（K-09，台账 §6-570 裁定 2026-11-07）：与 validFrom 同一模式——
        # 描述符声明源行里哪一列是文档创建/修改时间，不声明就是 None（裁决回退入库钟）
        "sourceCreatedAt": str(row.get(str(descriptor.get("sourceCreatedAt") or ""), "")) or None
        if descriptor.get("sourceCreatedAt") else None,
        "sourceModifiedAt": str(row.get(str(descriptor.get("sourceModifiedAt") or ""), "")) or None
        if descriptor.get("sourceModifiedAt") else None,
    }
