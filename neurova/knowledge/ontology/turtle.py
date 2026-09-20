"""RDF/Turtle 导出与自解析（工单 024，G01 的可交换面）。

零新增依赖：语法只用 Turtle 的一个明确子集，写侧与读侧共用同一份定义——
"导出的文本能被自己的解析器读回"是这条链唯一的格式校验，两套语法定义迟早分叉。

用到的子集：
- `@prefix kbg: <...>` 一行；
- 主语后的 `谓词 宾语 ;` 逐行，值为 IRI 或 `"文本"@lang`；
- IRI 只出现 `kbg:` 前缀形与 `http(s)://` 全形。

不用（也解析不了，别偷偷写进去）：空白节点 `[]`、`a` 谓词简写、数值/布尔字面量、
`===`、集合、多语种同值。谓词名带点或连字符在这里都不是问题，但含 `:` 会被当 IRI。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

NAMESPACE = "https://neurova.local/knowledge/"
PREFIX_LINE = "@prefix kbg: <%s> ."
LANG = "zh"

_TOKEN = re.compile(r"\s+")
_IRI = re.compile(r"^<[^<>]+>$")
_PREFIZED = re.compile(r"^kbg:([A-Za-z0-9_][A-Za-z0-9_.-]*)$")
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


def serialize(subject: str, rows: List[Tuple[str, str]]) -> str:
    """主语与首跳同行，其余逐行；整段以单个 `.` 收尾（Turtle 的谓语列表形）。"""
    body = ["  kbg:%s %s" % (_safePredicate(predicate), value) for predicate, value in rows]
    body[0] = "%s %s" % (iri(subject), body[0].strip())
    joined = "\n".join(line + (" ;" if index < len(body) - 1 else " .")
                       for index, line in enumerate(body))
    return "%s\n%s\n" % (PREFIX_LINE % NAMESPACE, joined)


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


# ── 读回来 ────────────────────────────────────────────────────

def _tokenizeObjects(chunk: str) -> str:
    return chunk.strip().rstrip(";").strip()


def parseTurtle(text: str) -> List[Tuple[str, str, str]]:
    """把 `serialize` 的输出解析成 (主语, 谓词, 宾语) 三元组。

    宾语保持写出来的原文（`"..."@zh` / `kbg:x` / `<iri>`）——往返无损判的是字段，
    不是"解析器顺手替我转了类型"。形状对不上就报错：半解析出来的三元组比报错更坏。
    """
    out: List[Tuple[str, str, str]] = []
    subject: Optional[str] = None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("@prefix"):
            continue
        parts = _splitTopLevel(line[:-1] if line.endswith(".") else line.rstrip(";").strip())
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
           "serialize", "serializeFact", "unescapeLiteral"]


def unescapeLiteral(token: str) -> Tuple[str, str]:
    """`"文本"@lang` → (文本, lang)；不是字面量则报错。"""
    match = _LITERAL.match(token)
    if not match:
        raise TurtleSyntaxError("不是字面量: %r" % token)
    return _unescape(match.group(1)), match.group(2) or ""
