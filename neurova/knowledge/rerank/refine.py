"""Rerank 精修四连。


1. clean_passage_for_rerank —— 重排文本清洗：代码围栏/LaTeX 拆壳保留正文、
   HTML/markdown 标记剥离、链接→锚文本、图片移除、表格→逗号文本、裸 URL
   去除、空白压缩。目的：代码/表格块不再因非自然语言被 rerank 模型恒判 0
2. threshold_fallback —— 阈值降级重试：候选全低于阈值时 0.7× 降档（不低于
   floor），"全被阈值打死→空结果"改为"给出最优可用档"。
3. composite_score —— 复合分 0.6*model + 0.3*base + 0.1*source（clamp [0,1]）：
 模型分主导、召回基线保底、来源信任微调。
4. mmr_select —— MMR λ 多样性选择：λ*rel - (1-λ)*maxSim(已选)，词法 Jaccard
   相似度（零 embedding 依赖），抑制近重复块霸榜 top-K。

finalize_reranked 把四件串成出口；默认全关（保持既有 rerank 行为零回归），
semantic_search_api 的 rerank 配置按需开启：
{"method":"model","composite":true,"mmr_lambda":0.7,"threshold":0.3,"top_k":5}
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 来源信任权重
SOURCE_WEIGHTS = {"owner": 1.0, "agent": 0.95, "untrusted": 0.9, "web": 0.95, "web_search": 0.95}

_CODE_FENCE = re.compile(r"```[^\n]*\n?(.*?)```", re.S)
_LATEX_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML_TAGS = re.compile(r"<[^>]+>")
_RAW_URL = re.compile(r"https?://\S+")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s+", re.M)
_BLOCKQUOTE = re.compile(r"^\s*>\s?", re.M)
_LIST_MARKER = re.compile(r"^\s*[-*+]\s+", re.M)
_EMPH = re.compile(r"(\*\*|__|\*|_|`)")
_WS = re.compile(r"[ \t\u3000]+")


def clean_passage_for_rerank(text: Optional[str]) -> str:
    """重排前清洗：拆壳不删料——自然语言主体必须保留。"""
    if not text:
        return ""
    out = str(text)
    out = _CODE_FENCE.sub(lambda m: m.group(1), out)
    out = _LATEX_BLOCK.sub(lambda m: m.group(1), out)
    out = _HTML_TAGS.sub(" ", out)
    out = _IMAGE_MD.sub(" ", out)
    out = _LINK_MD.sub(lambda m: m.group(1), out)

    # 表格：分隔行删除；数据行 | → 逗号文本（列名丢失可接受——表头行本身    # 也是首个数据形态；rerank 只需词面相关，不需结构）
    lines: List[str] = []
    for line in out.splitlines():
        if _TABLE_SEP.match(line):
            continue
        if _TABLE_ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            lines.append(", ".join(c for c in cells if c))
        else:
            lines.append(line)
    out = "\n".join(lines)

    out = _RAW_URL.sub(" ", out)
    out = _HEADING.sub("", out)
    out = _BLOCKQUOTE.sub("", out)
    out = _LIST_MARKER.sub("", out)
    out = _EMPH.sub("", out)
    out = _WS.sub(" ", out)
    return out.strip()


def threshold_fallback(
    scored: Sequence[Tuple[Any, float]],
    threshold: float,
    floor: float = 0.3,
    factor: float = 0.7,
) -> Tuple[List[Any], float]:
    """阈值降级重试：返回 (保留 id 列表, 生效阈值)。

    threshold<=0 → 不过滤（全保留）。逐级 0.7×，不低于 floor；降到 floor
    仍无候选 → 空列表（"确实没有相关的"与"阈值过严"都如实可分）。
    """
    if not threshold or float(threshold) <= 0:
        return [i for i, _ in scored], float(threshold or 0.0)
    t = float(threshold)
    while True:
        kept = [i for i, s in scored if float(s) >= t]
        if kept or t <= floor:
            return kept, t
        t = max(floor, t * factor)


def composite_score(model: float, base: float, source: float = 1.0) -> float:
    """复合分 0.6*model + 0.3*base + 0.1*source，clamp [0,1]。"""
    s = 0.6 * float(model) + 0.3 * float(base) + 0.1 * float(source)
    return max(0.0, min(1.0, s))


def _token_set(text: str) -> frozenset:
    from neurova.knowledge.search import tokenize

    return frozenset(tokenize(text or ""))


def mmr_select(
    query: str,
    candidate_ids: List[Any],
    scores: Dict[Any, float],
    texts: Dict[Any, str],
    top_k: int = 10,
    lambda_: float = 0.7,
) -> List[Any]:
    """MMR 多样性选择。

    rel 取传入分数（composite 或模型分）；query 仅签名兼容保留（本实现以
    "候选间冗余惩罚"为多样性来源——查询相关性已在召回/重排分数里）。
    """
    if not candidate_ids:
        return []
    token_cache: Dict[Any, frozenset] = {}

    def toks(cid: Any) -> frozenset:
        if cid not in token_cache:
            token_cache[cid] = _token_set(str(texts.get(cid, "")))
        return token_cache[cid]

    selected: List[Any] = []
    remaining = list(candidate_ids)
    for _ in range(min(max(1, int(top_k)), len(candidate_ids))):
        best, best_val = None, None
        for cand in remaining:
            rel = float(scores.get(cand, 0.0))
            if selected:
                cs = toks(cand)
                div = 0.0
                for s in selected:
                    ss = toks(s)
                    union = len(cs | ss)
                    if union:
                        div = max(div, len(cs & ss) / union)
            else:
                div = 0.0
            val = lambda_ * rel - (1.0 - lambda_) * div
            if best_val is None or val > best_val:
                best, best_val = cand, val
        selected.append(best)
        remaining.remove(best)
    return selected


def finalize_reranked(
    query: str,
    reranked: List[Dict[str, Any]],
    docs: List[Dict[str, Any]],
    base_scores: Optional[Dict[int, float]] = None,
    top_k: Optional[int] = None,
    mmr_lambda: Optional[float] = None,
    use_composite: bool = False,
    threshold: Optional[float] = None,
    threshold_floor: float = 0.3,
    source_weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """rerank 出口精修管线：复合分 →（可选）阈值降级 →（可选）MMR 选取。

    全默认（use_composite=False/threshold=None/mmr_lambda=None/top_k=None）
    行为 = 原样透传 runner 结果（零回归）；每开一项只加不减。
    返回行含 model_score/base_score/composite 观测字段（composite 未启用为
    None），由调用方决定投影哪些进响应。
    """
    base_scores = base_scores or {}
    wmap = source_weights or SOURCE_WEIGHTS
    rows: List[Dict[str, Any]] = []
    for r in reranked:
        idx = int(r.get("index", 0))
        model_s = float(r.get("score", 0.0))
        base_s = float(base_scores.get(idx, 0.0))
        doc = docs[idx] if 0 <= idx < len(docs) else {}
        src_w = float(
            wmap.get(
                str(doc.get("origin") or doc.get("source") or ""), 1.0
            )
        )
        row = dict(r)
        row["model_score"] = model_s
        row["base_score"] = base_s
        row["composite"] = composite_score(model_s, base_s, src_w) if use_composite else None
        row["_text"] = str(doc.get("content") or doc.get("id") or "")
        row["_rel"] = row["composite"] if use_composite else model_s
        rows.append(row)

    if use_composite:
        rows.sort(key=lambda x: x["_rel"], reverse=True)

    if threshold is not None and rows:
        kept_ids, eff = threshold_fallback(
            [(r["index"], float(r["_rel"])) for r in rows], float(threshold), floor=threshold_floor
        )
        kept = {i for i in kept_ids}
        rows = [r for r in rows if r["index"] in kept]
        for r in rows:
            r["threshold_effective"] = eff

    if mmr_lambda is not None and len(rows) > 1:
        order = mmr_select(
            query,
            [r["index"] for r in rows],
            {r["index"]: float(r["_rel"]) for r in rows},
            {r["index"]: r["_text"] for r in rows},
            top_k=top_k or len(rows),
            lambda_=float(mmr_lambda),
        )
        by_idx = {r["index"]: r for r in rows}
        rows = [by_idx[i] for i in order]
    elif top_k is not None:
        rows = rows[: int(top_k)]

    for r in rows:
        r.pop("_text", None)
        r.pop("_rel", None)
    return rows
