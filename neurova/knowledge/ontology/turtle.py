"""RDF/Turtle 导出与自解析（工单 024，G01 的可交换面）。

零新增依赖：语法只用 Turtle 的一个明确子集，写侧与读侧共用同一份定义——
"导出的文本能被自己的解析器读回"是这条链唯一的格式校验，两套语法定义迟早分叉。

用到的子集：
- `@prefix kbg: <...>` 一行；
- 主语后的 `谓词 宾语 ;` 逐行，值为 IRI 或 `"文本"@lang`；
- `#` 开头的注释行（只做分段，不参与三元组）；
- IRI 只出现 `kbg:` 前缀形与 `http(s)://` 全形。

一个文档可以装多个主语块（`serializeAll` 的全库导出就是这种形状）：每个块以
单个 ` .` 收尾，解析器遇到收尾点就把当前主语放掉。单主语的 `serialize` 输出
是它的一个块特例，往返行为不变。

不用（也解析不了，别偷偷写进去）：空白节点 `[]`、`a` 谓词简写、数值/布尔字面量、
`===`、集合、多语种同值。谓词名带点或连字符在这里都不是问题，但含 `:` 会被当 IRI。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

NAMESPACE = "https://neurova.local/knowledge/"
PREFIX_LINE = "@prefix kbg: <%s> ."
LANG = "zh"

_TOKEN = re.compile(r"\s+")
_IRI = re.compile(r"^<[^<>]+>$")
# B8 ⑧：前缀名从只认 kbg: 放宽到任意 prefix:local——导出层的标准槽位
# （rdf:type/rdfs:subClassOf/owl:inverseOf）必须能被自家解析器读回。
# 仍然拒裸词与引号形：谓词永远是 IRI，不是字符串。
_PREFIZED = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:([A-Za-z0-9_][A-Za-z0-9_.-]*)$")
_LITERAL = re.compile(r'^"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+))?$')
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}


class TurtleSyntaxError(ValueError):
    """读不回自己写出的文本，就是格式坏了——报错而不是将错就错解析。"""


def _escape(text: str) -> str:
    out = str(text)
    out = out.replace("\\", "\\\\").replace('"', '\\"')
    return out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _unescape(text: str) -> str:
    out: List[str] = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_ESCAPES.get(nxt, nxt))
            index += 2
            continue
        out.append(ch)
        index += 1
    return "".join(out)


def iri(local: str) -> str:
    return "kbg:%s" % re.sub(r"[^A-Za-z0-9_.-]", "_", str(local or "_"))


def _safePredicate(name: str) -> str:
    """术语名进 `kbg:` 之前先收字形：数据里的谓词不是我们能控的字符集。"""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "_"))
    return cleaned if re.match(r"^[A-Za-z]", cleaned) else "term_" + cleaned


def literal(text: Any) -> str:
    return '"%s"@%s' % (_escape(text), LANG)


def _subjectBlock(subject: str, rows: List[Tuple[str, str]]) -> str:
    """一个主语块：主语与首跳同行，其余逐行；以单个 ` .` 收尾（Turtle 的谓语列表形）。

    块形状只有这一份实现——`serialize` 与 `serializeAll` 各自拼自己的文档头，
    但块都从这里出，两套写法迟早分叉的病不给它发芽。
    """
    body = ["  kbg:%s %s" % (_safePredicate(predicate), value) for predicate, value in rows]
    body[0] = "%s %s" % (iri(subject), body[0].strip())
    return "\n".join(line + (" ;" if index < len(body) - 1 else " .")
                     for index, line in enumerate(body))


def serialize(subject: str, rows: List[Tuple[str, str]]) -> str:
    """主语与首跳同行，其余逐行；整段以单个 `.` 收尾（Turtle 的谓语列表形）。"""
    return "%s\n%s\n" % (PREFIX_LINE % NAMESPACE, _subjectBlock(subject, rows))


def serializeFact(store: Any, factId: str) -> str:
    """一条事实的血缘导出一份 Turtle；事实不存在直接报错，不返回空文本。"""
    from ..foundation.lineage_view import FactLineageView

    view = FactLineageView(store).trace(factId)
    if view is None:
        raise LookupError("事实不存在: %s" % factId)
    rows: List[Tuple[str, str]] = [
        # 标准形状：主体 --谓词--> 客体，谓词直接用数据里的术语名。
        (_safePredicate(view["predicate"]), literal(view["object_term"])),
        ("factId", literal(view["fact_id"])),
        ("recordKind", literal(view["record_kind"])),
        ("lifecycleStatus", literal(view["status"])),
        ("provenanceState", literal(view["provenance_state"])),
        ("recordedAt", literal(view["recorded_at"] or "")),
    ]
    if view["confidence"] is not None:
        rows.append(("confidence", literal(view["confidence"])))
    for missing in view["missing"]:
        rows.append(("missingDimension", literal(missing)))
    for hop in view["hops"]:
        if hop["kind"] == "assertion":
            rows += [
                ("assertedBy", literal("%s:%s" % (hop["actor_type"], hop["actor_id"]))),
                ("assertedStatement", literal(hop["statement_text"])),
                ("assertedAt", literal(hop["asserted_at"])),
                ("mediumRef", literal(hop["medium_ref"] or "")),
                ("activityKind", literal(hop["activity_kind"] or "")),
                ("chainSeq", literal(hop["seq"])),
                ("chainDigest", literal(hop["digest"] or "")),
            ]
        else:
            rule = hop.get("rule") or {}
            rows.append(("derivedVia", literal(rule.get("rule_id", ""))))
            for premise in hop.get("premises") or []:
                rows.append(("derivedFrom", literal(premise["fact_id"])))
                for text in premise.get("statement_texts") or []:
                    rows.append(("premiseStatement", literal(text)))
    triple = ("tripleSubject", literal(view["subject_label"]))
    return serialize(view["subject_label"] or factId, [triple] + rows)


_SECTION_TERMS = "# terms: ontology_terms (tenant=%s)"
_SECTION_RULES = "# rules: ontology_rules (tenant=%s)"
_SECTION_FACTS = "# facts: knowledge_facts (status=active AND record_kind=triple)"


def _canonicalJson(text: Any) -> str:
    """库里的 JSON 列按规范形重排（键序固定），导出两次才逐字节一致。"""
    return json.dumps(json.loads(text if isinstance(text, str) else "[]"),
                      ensure_ascii=False, sort_keys=True)


def serializeAll(store: Any, tenantId: str = "default",
                 agentId: Optional[str] = None) -> str:
    """本租户全库导出成单个 Turtle 文档（升级计划 B5，A4 互通面）。

    三段注释分段：terms（ontology_terms 全部行）→ rules（ontology_rules 全部行）
    → facts（`status='active' AND record_kind='triple'` 的全部行）。
    确定性判据：排序只来自固定 ORDER BY，时间戳与写入次序一律不进文本，
    同一库内容两次输出逐字节一致。

    facts 段的主语用 `subject_key` 而不是 canonical_label：`iri()` 会把
    IRI 之外的字符收成下划线，中文标签经这一步全塌成同一个 `kbg:_`，
    不同主体在导出里互相吞并；subject_key 是 ASCII 唯一键，IRI 安全且不撞。
    谓词与客体照数据原样走 `_safePredicate` / `literal`——谓词是数据里来的
    字符集，字形收口只有那一处。

    直接读 store 的连接与锁（与 term_registry / rule_engine / lineage_view
    同一访问形态）：导出是只读动作，表缺了就让 sqlite 报错沿调用链上抛，
    不吞、不兜底空文档。
    """
    tenant = str(tenantId or "default")
    with store._lock:
        termRows = store._conn.execute(
            "SELECT * FROM ontology_terms WHERE tenant_id = ? ORDER BY term_id",
            (tenant,)).fetchall()
        ruleRows = store._conn.execute(
            "SELECT * FROM ontology_rules WHERE tenant_id = ? ORDER BY rule_id",
            (tenant,)).fetchall()
        factSql = ("SELECT subject_key, predicate_term_id, object_term FROM knowledge_facts"
                   " WHERE tenant_id = ? AND status = 'active' AND record_kind = 'triple'")
        factParams: List[Any] = [tenant]
        if agentId:
            factSql += " AND agent_id = ?"
            factParams.append(str(agentId))
        factSql += " ORDER BY subject_key, predicate_term_id, object_term, fact_id"
        factRows = store._conn.execute(factSql, factParams).fetchall()

    lines: List[str] = [PREFIX_LINE % NAMESPACE]

    # 标准槽位前缀（B8 ⑧）：rdf/rdfs/owl/skos 固定进文档头——导出层有标准形状的
    # 语义行（subClassOf/subPropertyOf/inverseOf/rdf:type）从这里取词表；
    # skos 供外部映射断言行（G3，替换改附加）取词表。
    lines.append("@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .")
    lines.append("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
    lines.append("@prefix owl: <http://www.w3.org/2002/07/owl#> .")
    lines.append("@prefix skos: <http://www.w3.org/2004/02/skos/core#> .")

    lines.append(_SECTION_TERMS % tenant)
    for row in termRows:
        rows: List[Tuple[str, str]] = [
            ("termId", literal(row["term_id"])),
            ("kind", literal(row["kind"])),
            ("label", literal(row["label"])),
        ]
        if row["parent_term_id"]:
            rows.append(("parentTermId", iri(row["parent_term_id"])))
        if row["cardinality"] is not None:
            rows.append(("cardinality", literal(row["cardinality"])))
        for column, predicate in (
                ("domain_terms", "domainTerms"), ("range_terms", "rangeTerms"),
                ("range_kinds", "rangeKinds"), ("disjoint_with", "disjointWith"),
                ("required_props", "requiredProps")):
            rows.append((predicate, literal(_canonicalJson(row[column]))))
        if "aliases_json" in row.keys():
            rows.append(("aliases", literal(_canonicalJson(row["aliases_json"]))))
        if "external_iris_json" in row.keys():
            rows.append(("externalIris", literal(_canonicalJson(row["external_iris_json"]))))
        # G1：定义描述项——非空才出（空值零漂移，golden 稳定）
        if "definition" in row.keys() and str(row["definition"] or "").strip():
            rows.append(("definition", literal(row["definition"])))
        rows.append(("version", literal(row["version"])))
        lines.append(_subjectBlock(row["term_id"], rows))

    # B8 ⑧：标准槽位语义行——概念父类 rdfs:subClassOf、关系父属性
    # rdfs:subPropertyOf、逆关系 owl:inverseOf。G3（拍板 2026-11-10）：
    # 术语 IRI 恒为 kbg:——外部映射不再替换主体 IRI（丢本体自身标识），
    # 等价/对齐改为独立断言行（skos:exactMatch 等，宾语位才出现外部 IRI）。
    # 全 IRI 独立三元组行，逐字节确定，不进 kbg: 块（块实现是 B5 的既有判据面）。
    def _termIri(termId: str) -> str:
        return iri(termId)

    def _externalMappings(row: Any) -> list:
        if "external_iris_json" not in row.keys():
            return []
        raw = json.loads(row["external_iris_json"] or "[]")
        return raw if isinstance(raw, list) else []

    _SKOS_PREDICATES = {
        "skos_exactMatch": "skos:exactMatch",
        "skos_closeMatch": "skos:closeMatch",
        "skos_relatedMatch": "skos:relatedMatch",
    }

    lines.append("# standards")
    termsById = {str(r["term_id"]): r for r in termRows}
    for row in termRows:
        parent = str(row["parent_term_id"] or "")
        if parent and parent in termsById:
            slot = "rdfs:subClassOf" if row["kind"] == "concept" else "rdfs:subPropertyOf"
            lines.append("%s %s %s ." % (_termIri(row["term_id"]), slot,
                                         _termIri(parent)))
        inverse = str(row["inverse_of"] or "") if "inverse_of" in row.keys() else ""
        if inverse and inverse in termsById:
            lines.append("%s owl:inverseOf %s ." % (_termIri(row["term_id"]),
                                                    _termIri(inverse)))
        # G3 附加断言：外部映射独立成行（kind 闭集内 SKOS 三档；equivalentClass
        # 的类/属性分形谓词是 OWL 公理面职责，Turtle 互操作面只出 SKOS 同形）。
        for entry in _externalMappings(row):
            predicate = _SKOS_PREDICATES.get(str(entry.get("kind") or ""))
            iriValue = str(entry.get("iri") or "")
            if not predicate or not iriValue:
                continue
            lines.append("<%s> %s <%s> ." % (_termIri(row["term_id"]),
                                             predicate, iriValue))

    lines.append(_SECTION_RULES % tenant)
    for row in ruleRows:
        lines.append(_subjectBlock(row["rule_id"], [
            ("ruleId", literal(row["rule_id"])),
            ("headPredicate", literal(row["head_predicate"])),
            ("headSubjectVar", literal(row["head_subject_var"])),
            ("body", literal(_canonicalJson(row["body_json"]))),
            ("negatedPredicates", literal(_canonicalJson(row["negated_predicates"]))),
            ("stratificationLevel", literal(int(row["stratification_level"]))),
            ("enabled", literal(int(bool(row["enabled"])))),
            ("version", literal(row["version"])),
        ]))

    lines.append(_SECTION_FACTS)
    for row in factRows:
        if row["predicate_term_id"] == "is_a":
            # B8 ⑧：is_a 事实在导出层只对应实例类型（rdf:type），客体是概念术语
            # 的 kbg: IRI（G3 后外部名只出现在映射断言的宾语位）；其余关系保持
            # kbg: 块形状（B5 判据面）。
            lines.append("%s rdf:type %s ." % (iri(row["subject_key"]),
                                               _termIri(row["object_term"])))
            continue
        lines.append(_subjectBlock(row["subject_key"], [
            (_safePredicate(row["predicate_term_id"]), literal(row["object_term"])),
        ]))

    return "\n".join(lines) + "\n"


# ── 读回来 ────────────────────────────────────────────────────

def _tokenizeObjects(chunk: str) -> str:
    return chunk.strip().rstrip(";").strip()


def parseTurtle(text: str) -> List[Tuple[str, str, str]]:
    """把 `serialize` / `serializeAll` 的输出解析成 (主语, 谓词, 宾语) 三元组。

    宾语保持写出来的原文（`"..."@zh` / `kbg:x` / `<iri>`）——往返无损判的是字段，
    不是"解析器顺手替我转了类型"。形状对不上就报错：半解析出来的三元组比报错更坏。

    多主语文档（`serializeAll` 的形状）：块以单个 ` .` 收尾，收尾即放掉当前主语，
    下一个非注释行是新的主语行。`#` 注释行只做分段，跳过。单主语的 `serialize`
    输出是"末行收尾"的特例，行为不变。
    """
    out: List[Tuple[str, str, str]] = []
    subject: Optional[str] = None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("@prefix") or line.startswith("#"):
            continue
        terminated = line.endswith(".")
        parts = _splitTopLevel(line[:-1] if terminated else line.rstrip(";").strip())
        if subject is None:
            if len(parts) < 3:
                raise TurtleSyntaxError("主语行至少要有 主语/谓语/宾语，收到: %r" % line)
            subject = parts[0]
            pairs = parts[1:]
        else:
            pairs = parts
        if len(pairs) % 2:
            raise TurtleSyntaxError("谓语与宾语不成对: %r" % line)
        for index in range(0, len(pairs), 2):
            predicate, obj = pairs[index], _tokenizeObjects(pairs[index + 1])
            if not _isPredicate(predicate):
                raise TurtleSyntaxError("谓词不是 IRI: %r" % line)
            out.append((subject, predicate, obj))
        if terminated:
            subject = None
    return out


def _isPredicate(token: str) -> bool:
    return bool(_PREFIZED.match(token) or _IRI.match(token))


def _splitTopLevel(chunk: str) -> List[str]:
    """按空白切分，但引号内的空格不切——中文陈述全靠这条才读得回来。"""
    parts: List[str] = []
    buf: List[str] = []
    inString = escaped = False
    for ch in chunk:
        if inString:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                inString = False
            continue
        if ch == '"':
            inString = True
            buf.append(ch)
        elif _TOKEN.match(ch):
            if buf:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    if inString:
        raise TurtleSyntaxError("字面量引号未闭合: %r" % chunk)
    return parts


__all__ = ["NAMESPACE", "TurtleSyntaxError", "iri", "literal", "parseTurtle",
           "serialize", "serializeAll", "serializeFact", "unescapeLiteral"]


def unescapeLiteral(token: str) -> Tuple[str, str]:
    """`"文本"@lang` → (文本, lang)；不是字面量则报错。"""
    match = _LITERAL.match(token)
    if not match:
        raise TurtleSyntaxError("不是字面量: %r" % token)
    return _unescape(match.group(1)), match.group(2) or ""
