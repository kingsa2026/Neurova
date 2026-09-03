"""知识文本分块器 — P0-2 RAG 分块管线（对照 Dify splitter 的递归降级策略）。

分层切分：段落（空行）→ 句子（中英句末标点/换行）→ 固定窗口硬切；
短文本单块直返（≤ max_chars 不分块，等价旧行为）。相邻块支持 overlap
（句级/硬切时把切点向前回退，块仍为原文连续切片，偏移语义干净）。

块偏移 [char_start, char_end) 恒满足 text == 原文切片，存储只需存偏移，
块正文可由 content 切片复原（条目 JSON 不存正文副本）。
"""

import re
from dataclasses import dataclass
from typing import Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP = 120

# 句末标点（中英）+ 换行——句级切分的切点候选
_SENTENCE_END = re.compile(r"[。！？；!?;\n]")
# 空行分隔的段落
_PARA_SPLIT = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    """单个分块：原文连续切片。"""

    index: int
    text: str
    char_start: int
    char_end: int


def _split_sentences(segment: str, base: int) -> List[Dict]:
    """把段落切成句单元 [{text, start, end}]；偏移相对原文。"""
    units: List[Dict] = []
    start = 0
    for m in _SENTENCE_END.finditer(segment):
        end = m.end()
        units.append({"text": segment[start:end], "start": base + start, "end": base + end})
        start = end
    if start < len(segment):
        units.append({"text": segment[start:], "start": base + start, "end": base + len(segment)})
    return [u for u in units if u["text"].strip()]


def _hard_split(text: str, base: int, max_chars: int) -> List[Dict]:
    """无切点的超长文本按固定窗口硬切。"""
    out = []
    for i in range(0, len(text), max_chars):
        piece = text[i : i + max_chars]
        out.append({"text": piece, "start": base + i, "end": base + i + len(piece)})
    return out


def _group_units(units: List[Dict], max_chars: int, overlap: int, text_ref: str) -> List[Dict]:
    """把句单元聚合为 ≤ max_chars 的块；块间按 overlap 回退切点。

    text_ref 为原文——聚合边界取首末单元偏移后直接切片，块文本
    天然含单元间分隔符（text == 原文[start:end]，无损语义）。
    """
    groups: List[List[Dict]] = []
    current: List[Dict] = []
    current_len = 0
    for unit in units:
        ulen = len(unit["text"])
        if current and current_len + ulen > max_chars:
            groups.append(current)
            # overlap：从当前组尾部回退若干句，作为下一组的开头
            carry: List[Dict] = []
            carried = 0
            if overlap > 0:
                for u in reversed(current):
                    if carried + len(u["text"]) > overlap:
                        break
                    carry.insert(0, u)
                    carried += len(u["text"])
            current = list(carry)
            current_len = carried
        current.append(unit)
        current_len += ulen
    if current:
        groups.append(current)

    out: List[Dict] = []
    for group in groups:
        if not group:
            continue
        # 用原文偏移切片（含单元间分隔符），保证 text == 原文[start:end]
        start = group[0]["start"]
        end = group[-1]["end"]
        out.append({"text": text_ref[start:end], "start": start, "end": end})
    return out


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Chunk]:
    """把文本分层切分为块。

    空白文本 → []；≤ max_chars → 单块覆盖全文。
    返回块满足：text == 原文[char_start:char_end]。
    """
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [Chunk(index=0, text=text, char_start=0, char_end=len(text))]

    # 1) 段落聚合（空行边界）
    raw_blocks: List[Dict] = []
    para_start = 0
    for m in _PARA_SPLIT.finditer(text):
        para = text[para_start : m.start()]
        if para.strip():
            raw_blocks.append({"text": para, "start": para_start, "end": m.start()})
        para_start = m.end()
    tail = text[para_start:]
    if tail.strip():
        raw_blocks.append({"text": tail, "start": para_start, "end": len(text)})

    # 2) 超长段落降级句切/硬切
    units: List[Dict] = []
    for block in raw_blocks:
        if len(block["text"]) <= max_chars:
            units.append(block)
            continue
        sentences = _split_sentences(block["text"], block["start"])
        long_sentences = [s for s in sentences if len(s["text"]) > max_chars]
        if long_sentences:
            # 句切仍超长 → 整段硬切（句结构已无可聚合空间）
            units.extend(_hard_split(block["text"], block["start"], max_chars))
        else:
            units.extend(sentences)

    # 3) 句/段聚合为块（带 overlap 回退）
    grouped = _group_units(units, max_chars, overlap, text)
    if not grouped:
        return [Chunk(index=0, text=text, char_start=0, char_end=len(text))]

    return [
        Chunk(index=i, text=g["text"], char_start=g["start"], char_end=g["end"])
        for i, g in enumerate(grouped)
    ]


def split_with_meta(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Dict[str, int]]:
    """chunk_text 的 dict 形态（入库契约：content/index/char_start/char_end）。"""
    return [
        {
            "content": c.text,
            "index": c.index,
            "char_start": c.char_start,
            "char_end": c.char_end,
        }
        for c in chunk_text(text, max_chars=max_chars, overlap=overlap)
    ]
