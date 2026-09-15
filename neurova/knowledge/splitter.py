"""09-15）

分层切分：段落（空行）→ 句子（中英句末标点/换行）→ 固定窗口硬切；
短文本单块直返（≤ max_chars 不分块，等价旧行为）。相邻块支持 overlap
（句级/硬切时把切点向前回退，块仍为原文连续切片，偏移语义干净）。

P0#2 精修：
- 英文句界须跟空白：ASCII `.?!;` 仅在
  后随空白时是句子边界；中文 。！？； 与换行行为不变。
- 代码围栏保护：``` fenced block ≤ max_chars 时作为原子单元（旧实现把
  围栏内的 \n 当句界，围栏被逐行切碎）；超限围栏不保护（降级硬切，
- 表格表头再注入：跨块 GFM 表格的续块经 table_header_contexts 拿到
  context_header（表头行原文）。Content 保持逐字原文切片——表头只影响
  索引输入拼接（build_index_content），不篡改块正文与偏移不变式。
- build_index_content(title, content, context_header) 是索引输入的**唯一
  preview 与生产各写一份拼接逻辑必然分叉）。

块偏移 [char_start, char_end) 恒满足 text == 原文切片，存储只需存偏移，
块正文可由 content 切片复原（条目 JSON 不存正文副本）。
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP = 120
# P1#6 父子分块——索引进子块（细命中），LLM 消费父块（完整上下文）。
CHILD_MAX_CHARS = 384

# 句末标点：中文。！？； 与换行恒为边界；ASCII .?!; 须后随空白# 
_SENTENCE_END = re.compile(r"[。！？；\n]|[.?!;](?=[^\S\n])")
# 空行分隔的段落
_PARA_SPLIT = re.compile(r"\n\s*\n")
# 代码围栏（``` … ```，含 ```` 更长的围栏）——保护区间
_FENCE = re.compile(r"(`{3,})[^\n]*\n.*?\n?\1", re.S)
# GFM 表格行与分隔行（表头再注入用）
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")


@dataclass
class Chunk:
    """单个分块：原文连续切片 + 可选上下文头（表头再注入）。"""

    index: int
    text: str
    char_start: int
    char_end: int
    context_header: str = ""


def build_index_content(title: str, content: str, context_header: str = "") -> str:
    """索引输入唯一组装函数：标题 + 上下文头 + 块正文（跳过空段）。

    rebuild/增量索引、chunk 级 preview、向量索引拼接必须全部走本函数，
 否则重索引无法字节级复现索引输入。
    """
    parts = [p for p in (str(title or ""), str(context_header or ""), str(content or "")) if p]
    return "\n".join(parts)


def _protected_spans(text: str) -> List[Tuple[int, int]]:
    """代码围栏保护区间 [(start, end)]，去重叠并排序。"""
    spans: List[Tuple[int, int]] = []
    last_end = 0
    for m in _FENCE.finditer(text):
        if m.start() >= last_end:
            spans.append((m.start(), m.end()))
            last_end = m.end()
    return spans


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


def _free_region_units(text: str, lo: int, hi: int, max_chars: int) -> List[Dict]:
    """保护区间之外的自由段：段落 → 句子 → 硬切 降级为单元。"""
    region = text[lo:hi]
    if not region.strip():
        return []
    blocks: List[Dict] = []
    para_start = 0
    for m in _PARA_SPLIT.finditer(region):
        para = region[para_start : m.start()]
        if para.strip():
            blocks.append({"text": para, "start": lo + para_start, "end": lo + m.start()})
        para_start = m.end()
    tail = region[para_start:]
    if tail.strip():
        blocks.append({"text": tail, "start": lo + para_start, "end": hi})

    units: List[Dict] = []
    for block in blocks:
        if len(block["text"]) <= max_chars:
            units.append(block)
            continue
        sentences = _split_sentences(block["text"], block["start"])
        long_sentences = [s for s in sentences if len(s["text"]) > max_chars]
        if long_sentences:
            units.extend(_hard_split(block["text"], block["start"], max_chars))
        else:
            units.extend(sentences)
    return units


def _group_units(units: List[Dict], max_chars: int, overlap: int, text_ref: str) -> List[Dict]:
    """把单元聚合为 ≤ max_chars 的块；块间按 overlap 回退切点。

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
    """把文本分层切分为块（代码围栏为原子单元，≤ max_chars 不被切碎）。

    空白文本 → []；≤ max_chars → 单块覆盖全文。
    返回块满足：text == 原文[char_start:char_end]。
    """
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [Chunk(index=0, text=text, char_start=0, char_end=len(text))]

    # 1) 保护区间（代码围栏，长度超限者不保护→留在自由区降级硬切）
    atomic = [(s, e) for (s, e) in _protected_spans(text) if e - s <= max_chars]

    # 2) 自由区按 段落→句子→硬切 出单元；原子段整体为一个单元
    units: List[Dict] = []
    pos = 0
    for s, e in atomic:
        units.extend(_free_region_units(text, pos, s, max_chars))
        units.append({"text": text[s:e], "start": s, "end": e})
        pos = e
    units.extend(_free_region_units(text, pos, len(text), max_chars))

    # 3) 聚合为块（带 overlap 回退）
    grouped = _group_units(units, max_chars, overlap, text)
    if not grouped:
        return [Chunk(index=0, text=text, char_start=0, char_end=len(text))]

    chunks = [
        Chunk(index=i, text=g["text"], char_start=g["start"], char_end=g["end"])
        for i, g in enumerate(grouped)
    ]
    headers = table_header_contexts(text, chunks)
    for c in chunks:
        c.context_header = headers.get(c.index, "")
    return chunks


def _scan_tables(text: str) -> List[Tuple[int, int, int, str]]:
    """GFM 表格块扫描 → [(table_start, body_start, table_end, header_line)]。

    body_start = 分隔行（|---|）起点：块起点 ≥ body_start 即为"续块"
    （表头与分隔行不在块内），需要再注入表头。
    """
    lines: List[Tuple[int, int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        lines.append((pos, pos + len(line), line.rstrip("\n")))
        pos += len(line)
    tables = []
    i = 0
    while i + 1 < len(lines):
        s, _, l1 = lines[i]
        ns, ne, l2 = lines[i + 1]
        if _TABLE_ROW.match(l1) and _TABLE_SEP.match(l2):
            j = i + 1
            while j < len(lines) and _TABLE_ROW.match(lines[j][2]):
                j += 1
            tables.append((s, ns, lines[j - 1][1], l1.strip()))
            i = j
        else:
            i += 1
    return tables


def table_header_contexts(text: str, chunks: List[Chunk]) -> Dict[int, str]:
    """块索引 → 该块续写的表格表头（多表以换行拼接）。

    仅当块起点落在某表 body 区内且块内确有表格行时注入（列内容真实
 延续表头
    在本场景以"块含表格行"近似）。
    """
    tables = _scan_tables(text)
    if not tables:
        return {}
    out: Dict[int, str] = {}
    for c in chunks:
        heads = []
        for ts, body_start, te, header in tables:
            if c.char_end <= ts or c.char_start >= te:
                continue  # 与本表无交集
            if c.char_start < body_start:
                continue  # 首块自带表头，不注入
            if not any(_TABLE_ROW.match(ln) for ln in c.text.splitlines()):
                continue
            if header not in heads:
                heads.append(header)
        if heads:
            out[c.index] = "\n".join(heads)
    return out


def split_with_meta(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Dict[str, object]]:
    """chunk_text 的 dict 形态（入库契约：content/index/char_start/char_end/context_header）。"""
    return [
        {
            "content": c.text,
            "index": c.index,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "context_header": c.context_header,
        }
        for c in chunk_text(text, max_chars=max_chars, overlap=overlap)
    ]


def build_entry_chunks(
    text: str,
    parent_max: int = DEFAULT_MAX_CHARS,
    child_max: int = CHILD_MAX_CHARS,
    parent_overlap: int = 0,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """父子分块单源构造（P1#6）：返回 (children, parents)，均入库形态。

    - 父块 = chunk_text(text, parent_max, parent_overlap)——默认相邻父块无
 重叠；
    - 子块 = 对每个父块再 chunk_text(child_max, child_max//5)，偏移平移回
      原文绝对坐标（子块 parent_index 指向来源父块；表头注入在父块局部
      检测后随偏移平移，不变式与表头语义都不破坏）；
    - 全文 ≤ child_max 时退化为单父单子（children 与 split_with_meta 兼容
      超集：多 parent_index 键，旧读取方无感）。

    索引/检索只消费 children；父块文本经 repository._parent_context_text
    在命中回映时提供给 LLM。
    """
    if not text or not text.strip():
        return [], []
    parents = chunk_text(text, parent_max, parent_overlap)
    if not parents:
        return [], []
    child_overlap = max(0, child_max // 5)
    children: List[Dict[str, object]] = []
    parent_metas: List[Dict[str, object]] = []
    for pi, p in enumerate(parents):
        parent_metas.append(
            {
                "index": pi,
                "content": p.text,
                "char_start": p.char_start,
                "char_end": p.char_end,
            }
        )
        kids = (
            [Chunk(index=0, text=p.text, char_start=0, char_end=len(p.text))]
            if len(p.text) <= child_max
            else chunk_text(p.text, child_max, child_overlap)
        )
        hdrs = table_header_contexts(p.text, kids)
        for ch in kids:
            children.append(
                {
                    "content": ch.text,
                    "index": len(children),
                    "char_start": p.char_start + ch.char_start,
                    "char_end": p.char_start + ch.char_end,
                    "context_header": hdrs.get(ch.index, ""),
                    "parent_index": pi,
                }
            )
    return children, parent_metas
