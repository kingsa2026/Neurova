"""切块策略注册表与单点分派（specs/2026-11-12 §9 W8）。

- 策略是**数据**（通则 2）：kind ∈ 十三种闭集，参数 schema 在登记处校验；
  摄取与 preview-chunking 同改经此一处分派——`chunk_text`/`build_entry_chunks`
  单源族地位不动（structure 缺省策略的实装仍是它们，存量零漂移）。
- 新 kind 的实装全部 stdlib：semantic/late 需要嵌入管线、proposition 需要
  LLM 客户端——这三类当前抛 `NotSupportedChunking`（诚实形态 not_supported），
  接入时在 _STRATEGY_FUNCS 挂实现即可（登记面已放行）。
- dispatchChunk(store, text, strategy=None)：
  strategy=None → 既有 chunk_text 逐字（缺省零漂移）；
  strategy={"kind": ..., "params": {...}} → 分派到对应实装。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.time_utils import nowIso as _now

logger = get_logger(__name__)

#: 十三种闭集（specs/2026-11-12 §9 W8）
CHUNK_KINDS = (
    "fixed", "sentence", "paragraph", "recursive", "markdown", "code", "table",
    "semantic", "sliding", "proposition", "parentChild", "late", "document",
)

#: 需要外部客户端的三类（接入前 not_supported 诚实形态）
_CLIENT_BACKED_KINDS = ("semantic", "late", "proposition")

_DEFAULT_MAX_CHARS = 800

_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.]?")
_PARA_RE = re.compile(r"\n\s*\n")


class NotSupportedChunking(ValueError):
    """策略登记放行、实装未接入——诚实 not_supported（不静默降级成 structure）。"""


class ChunkStrategyRegistry:
    """ontology_chunk_strategies 的唯一读写面（v48）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from .foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    def register(self, strategyId: str, tenantId: str = "default",
                 kind: str = "", params: Optional[Dict[str, Any]] = None,
                 enabled: bool = True) -> Dict[str, Any]:
        kind = str(kind or "").strip()
        if kind not in CHUNK_KINDS:
            raise ValueError(
                "kind %r 不在十三种闭集（%s）" % (kind, "/".join(CHUNK_KINDS)))
        params = dict(params or {})
        if kind == "fixed" and int(params.get("maxChars") or 0) <= 0:
            raise ValueError("fixed 策略须带正整数 maxChars")
        if kind == "sliding" and int(params.get("windowChars") or 0) <= 0:
            raise ValueError("sliding 策略须带正整数 windowChars")
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_chunk_strategies"
                " (tenant_id, strategy_id, kind, params_json, enabled,"
                "  created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (str(tenantId or "default"), str(strategyId or "").strip(), kind,
                 json.dumps(params, ensure_ascii=False), 1 if enabled else 0,
                 _now(), _now()))
        return self.get(strategyId, tenantId=tenantId) or {}

    def get(self, strategyId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM ontology_chunk_strategies"
                " WHERE tenant_id = ? AND strategy_id = ?",
                (str(tenantId or "default"), str(strategyId or "").strip())).fetchone()
        return self._hydrate(row) if row is not None else None

    def list(self, tenantId: str = "default") -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM ontology_chunk_strategies WHERE tenant_id = ?"
                " ORDER BY strategy_id", (str(tenantId or "default"),)).fetchall()
        return [self._hydrate(r) for r in rows]

    def delete(self, strategyId: str, tenantId: str = "default") -> bool:
        with self._store._lock, self._store._conn:
            cur = self._store._conn.execute(
                "DELETE FROM ontology_chunk_strategies WHERE tenant_id = ?"
                " AND strategy_id = ?", (str(tenantId or "default"),
                                         str(strategyId or "").strip()))
            return cur.rowcount > 0

    @staticmethod
    def _hydrate(row: Any) -> Dict[str, Any]:
        d = dict(row)
        d["params"] = json.loads(d.pop("params_json") or "{}")
        d["enabled"] = bool(d.get("enabled"))
        return d


# ── 各 kind 实装（stdlib，零新依赖）─────────────────────────────────

def _fixed(text: str, params: Dict[str, Any]) -> List[str]:
    maxChars = max(1, int(params.get("maxChars") or _DEFAULT_MAX_CHARS))
    return [text[i:i + maxChars] for i in range(0, len(text), maxChars)]


def _sentence(text: str, params: Dict[str, Any]) -> List[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def _paragraph(text: str, params: Dict[str, Any]) -> List[str]:
    return [p.strip() for p in _PARA_RE.split(text) if p.strip()]


def _recursive(text: str, params: Dict[str, Any]) -> List[str]:
    """分隔符递归：段落 → 句子 → 硬切，逐层直到每块 ≤ maxChars。"""
    maxChars = max(1, int(params.get("maxChars") or _DEFAULT_MAX_CHARS))
    chunks = _paragraph(text)
    if any(len(c) > maxChars for c in chunks):
        chunks = [s for c in chunks for s in _sentence(c)]
    if any(len(c) > maxChars for c in chunks):
        chunks = [s for c in chunks for s in _fixed(c, {"maxChars": maxChars})]
    return [c for c in chunks if c]


def _markdown(text: str, params: Dict[str, Any]) -> List[str]:
    """标题层级切：# 标题行起新块。"""
    out: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current:
                out.append("\n".join(current).strip())
                current = []
        current.append(line)
    if current:
        out.append("\n".join(current).strip())
    return [c for c in out if c]


def _code(text: str, params: Dict[str, Any]) -> List[str]:
    """代码围栏原子切：围栏块整体保留，围栏外走段落。"""
    fence = re.compile(r"```.*?\n(.*?)```", re.S)
    out: List[str] = []
    last = 0
    for match in fence.finditer(text):
        head = text[last:match.start()].strip()
        if head:
            out.extend(_paragraph(head))
        out.append(match.group(0))
        last = match.end()
    tail = text[last:].strip()
    if tail:
        out.extend(_paragraph(tail))
    return [c for c in out if c]


def _table(text: str, params: Dict[str, Any]) -> List[str]:
    """表格完整保留（| 行聚合为一块），其余走段落。"""
    out: List[str] = []
    tableLines: List[str] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            tableLines.append(line)
        else:
            if tableLines:
                out.append("\n".join(tableLines))
                tableLines = []
            if line.strip():
                out.append(line.strip())
    if tableLines:
        out.append("\n".join(tableLines))
    return out


def _sliding(text: str, params: Dict[str, Any]) -> List[str]:
    window = max(2, int(params.get("windowChars") or _DEFAULT_MAX_CHARS))
    step = max(1, int(params.get("stepChars") or window // 2))
    return [text[i:i + window] for i in range(0, len(text), step) if text[i:i + window]]


def _document(text: str, params: Dict[str, Any]) -> List[str]:
    return [text] if text else []


def _parentChild(text: str, params: Dict[str, Any]) -> List[str]:
    """分派到既有父子块单源（build_entry_chunks 的 children）。"""
    from .splitter import build_entry_chunks

    children, _parents = build_entry_chunks(text)
    return children


_STRATEGY_FUNCS = {
    "fixed": _fixed, "sentence": _sentence, "paragraph": _paragraph,
    "recursive": _recursive, "markdown": _markdown, "code": _code,
    "table": _table, "sliding": _sliding, "document": _document,
    "parentChild": _parentChild,
}


def dispatchChunk(store: Any, text: str,
                  strategy: Optional[Dict[str, Any]] = None) -> List[str]:
    """单点分派：strategy=None → 既有 chunk_text 逐字（缺省零漂移）；
    strategy={"kind":...} → 对应实装；client-backed 三类显式 not_supported。"""
    text = str(text or "")
    if strategy is None or not strategy.get("kind"):
        from .splitter import chunk_text

        return chunk_text(text)
    kind = str(strategy.get("kind") or "").strip()
    params = dict(strategy.get("params") or {})
    if kind not in CHUNK_KINDS:
        raise ValueError("切块 kind %r 不在十三种闭集" % kind)
    if kind in _CLIENT_BACKED_KINDS:
        raise NotSupportedChunking(
            "切块 kind %r 需要外部客户端（嵌入/LLM），实装未接入（not_supported）" % kind)
    func = _STRATEGY_FUNCS.get(kind)
    if func is None:
        raise NotSupportedChunking("切块 kind %r 实装未接入（not_supported）" % kind)
    return func(text, params)
