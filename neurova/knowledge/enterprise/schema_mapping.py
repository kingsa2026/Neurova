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

#: 值变换链闭集（对照研究 P2-1，2026-11-19）：对 object 的**派生值**依次应用；
#: 纯函数、无 IO——映射里仍不写任何可执行逻辑。
VALUE_TRANSFORMS = ("upper", "lower", "trim", "collapse_ws")

#: object 取值缺失策略（对照研究 P2-1，2026-11-19）：keep（缺省=现行为，空串照旧）/
#: skip（整行跳过，摄取链如实记 finding）/ report（照常返回并带 objectMissing 标记）。
MISSING_POLICIES = ("keep", "skip", "report")

#: 变体闭集（2026-11-07 裁定 §2.3-1A）：单类型＋变体字段。编译期「给了就收口、
#: 不给不拒」——B14 时代 sql/erp_api 描述符没有变体字段，存量判据不破；
#: 工厂（registry.buildAdapter）按需强制要求。闭集随适配器批次只增不改。
def _sqlDriverNames() -> tuple:
    """从 connectors_sql._DRIVER_MODULES 派生驱动名闭集（dataification 单源）。"""
    try:
        from .connectors_sql import _DRIVER_MODULES
        return tuple(_DRIVER_MODULES.keys())
    except Exception:
        return ("postgresql", "mysql", "mssql", "oracle", "sqlite")


def _erpVendorNames() -> tuple:
    """从 connectors_erp.ERP_VENDOR_ADAPTERS 派生 vendor 闭集（dataification 单源）。"""
    try:
        from .connectors_erp import ERP_VENDOR_ADAPTERS
        return tuple(ERP_VENDOR_ADAPTERS.keys())
    except Exception:
        return ("kingdee", "yongyou")


VARIANT_CLOSED_SETS: Dict[str, tuple] = {
    "file": ("format", ("csv", "tsv", "json", "jsonl")),
    # W11 dataification：driver 闭集从 connectors_sql._DRIVER_MODULES 派生（单源）
    "sql": ("driver", tuple(_sqlDriverNames())),
    # W11 dataification：vendor 闭集从 connectors_erp.ERP_VENDOR_ADAPTERS 派生（单源）
    "erp_api": ("vendor", tuple(_erpVendorNames())),
    # U-conn 扩展批修正：http_pull / unity_catalog / snowflake / sap_odata 的旧
    # 条目把「url/base_url 的值」拿去对「kind 名闭集」做成员判定——任何可保存的
    # 真实描述符（url=https://…）都会被拒（实测复现）。这四类没有可枚举变体，
    # 必填字段由适配器自身 health/fetch 判缺，故不进变体闭集；「可枚举变体」
    # 机制只保留给 sql.driver / erp_api.vendor / file.format / chat.vendor。
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
    if sourceType == "chat" and not str(descriptor.get("agentId") or "").strip():
        raise MappingError("chat 源必须声明 agentId（来源实例边界），拒绝无边界全表读取")
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
    # 值变换链（P2-1）：只对派生值（column/template）有意义；常量对象（term/literal）
    # 的身份是声明的，变换会破坏术语语义——编译期就拒。
    transforms = list(obj.get("transform") or [])
    if transforms:
        if objKind not in ("column", "template"):
            raise MappingError(
                "object.transform 只适用于 column/template 派生值，%r 常量对象不变换"
                % objKind)
        for name in transforms:
            if name not in VALUE_TRANSFORMS:
                raise MappingError(
                    "object.transform %r 不在闭集（%s）"
                    % (name, " / ".join(VALUE_TRANSFORMS)))
    # object 取值缺失策略（P2-1）：缺省 keep=现行为，存量描述符零漂移
    missingPolicy = str(descriptor.get("missing") or "keep")
    if missingPolicy not in MISSING_POLICIES:
        raise MappingError(
            "missing %r 不在闭集（%s）" % (missingPolicy, " / ".join(MISSING_POLICIES)))
    if objKind == "term":
        termId = str(obj.get("termId") or "")
        if registry is not None and registry.term(termId, tenantId=tenantId) is None:
            raise MappingError("object.term %s 未登记" % termId)

    # 正文分档（批 C7c，方案 §14-C 裁定）：存档面聊天正文进条目链
    # （ChatChannelAdapter.writeArchiveEntries），facts 只承结构化断言——
    # text 列配进 object（column 或模板）即十万级行灌 facts，不可逆，编译期就拒。
    if (str(descriptor.get("sourceType") or "") == "chat"
            and str(descriptor.get("chatSource") or "") == "archive"):
        if objKind == "column" and str(obj.get("column") or "") == "text":
            raise MappingError(
                "存档面聊天正文按分档裁定进条目链，不得配进 facts object——"
                "object 请配 chat_id/sender/sent_at/media_ref 类结构化列"
                "（正文由 writeArchiveEntries 承接）")
        if "text" in _TEMPLATE_SLOT.findall(str(obj.get("template") or "")):
            raise MappingError(
                "存档面 object 模板不得引用 {text}（正文分档进条目链，方案 §14-C）")

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


def _applyTransforms(value: str, transforms: List[Any]) -> str:
    """对派生值依次应用变换链（P2-1，纯函数；闭集见 VALUE_TRANSFORMS）。"""
    out = str(value or "")
    for name in transforms:
        if name == "upper":
            out = out.upper()
        elif name == "lower":
            out = out.lower()
        elif name == "trim":
            out = out.strip()
        elif name == "collapse_ws":
            out = " ".join(out.split())
    return out


def applyMapping(descriptor: Dict[str, Any], row: Dict[str, Any],
                 registry: Any, tenantId: str = "default"):
    """把一行源数据按描述符映射成 AdmissionRequest 的字段面（不落库）。

    返回 {subjectLabel, predicateTermId, objectTerm, qualifier, validFrom, validUntil}。
    object 为列且列值命中关系白名单时映射为 term 语义；未命中按字面量处理（finding 面由调用方判）。

    missing 策略（P2-1）：object（column/template）派生值为空时——keep（缺省）
    照旧返回；skip 返回 None（调用方跳过该行并如实记 finding）；report 照常
    返回但带 `objectMissing: True` 标记，去留由调用方定。
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
    transforms = list(obj.get("transform") or [])
    if objKind == "column":
        objectTerm = str(row.get(str(obj.get("column") or ""), ""))
    elif objKind == "template":
        objectTerm = _fill(str(obj.get("template") or ""))
    elif objKind == "term":
        objectTerm = str(obj.get("termId") or "")
    else:
        objectTerm = str(obj.get("value") or "")
    if transforms:
        objectTerm = _applyTransforms(objectTerm, transforms)

    missingPolicy = str(descriptor.get("missing") or "keep")
    if (missingPolicy in ("skip", "report") and objKind in ("column", "template")
            and not str(objectTerm or "").strip()):
        if missingPolicy == "skip":
            return None
        # report：照常返回，缺失事实交调用方定夺（不吞行、不假装正常）
        flagged = True
    else:
        flagged = False

    qualifier = {key: str(row.get(column, ""))
                 for key, column in (descriptor.get("qualifiers") or {}).items()}
    result = {
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
    if flagged:
        result["objectMissing"] = True
    return result
