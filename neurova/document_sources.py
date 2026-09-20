"""文档入口解析：Markdown 子集 → 中间文档树

子集边界写死在 spec §6，本模块刻意不做"尽量支持"：不认识的语法按字面文本保留，
宁可原样出现在 PDF 里，也不静默丢内容。凡是发生降级（伪表格、列数不齐）都记进
`warnings`，让调用方能把"你以为得到了表格"这件事如实说回去。
"""

import re
import typing
from dataclasses import field
from typing import NamedTuple

from neurova.document_model import Block, InlineRun, NodeKind

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
# 整行独占的图片引用才认；混在句子中间的 ![](...) 保持字面，不做行内图片
_IMAGE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)$")
# 行内标记：未闭合的 `**` / `*` / 反引号不匹配，整段按字面文本保留
_INLINE_RE = re.compile(
    r"\*\*(?P<bold>[^*]+?)\*\*|\*(?P<italic>[^*]+?)\*|`(?P<code>[^`]+?)`"
)


class ParseResult(NamedTuple):
    """解析产物：块列表 + 降级说明。warnings 为空即全程无降级。"""

    blocks: typing.List[Block] = field(default_factory=list)
    warnings: typing.List[str] = field(default_factory=list)


def parse_inline(text: str) -> typing.List[InlineRun]:
    """把行内标记切成同风格的 run 序列；无标记时返回单个纯文本 run。"""
    runs: typing.List[InlineRun] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            runs.append(InlineRun(text[pos : m.start()]))
        groups = m.groupdict()
        if groups["bold"] is not None:
            runs.append(InlineRun(groups["bold"], bold=True))
        elif groups["italic"] is not None:
            runs.append(InlineRun(groups["italic"], italic=True))
        else:
            runs.append(InlineRun(groups["code"], code=True))
        pos = m.end()
    if pos < len(text):
        runs.append(InlineRun(text[pos:]))
    return runs or [InlineRun(text)]


def _para(text: str) -> Block:
    return Block(NodeKind.PARAGRAPH, runs=parse_inline(text))


def _row_cells(line: str) -> typing.List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_separator_row(cells: typing.List[str]) -> bool:
    return bool(cells) and all(_TABLE_SEP_CELL_RE.match(c.strip() or "-") for c in cells)


def _aligns(cells: typing.List[str]) -> typing.List[str]:
    out = []
    for cell in cells:
        edge = cell.strip()
        if edge.startswith(":") and edge.endswith(":"):
            out.append("center")
        elif edge.endswith(":"):
            out.append("right")
        else:
            out.append("left")
    return out


def _flush_table(buf: typing.List[str], nodes: typing.List[Block], warnings: typing.List[str]) -> None:
    """表格块。伪表格逐行降级为段落（内容不丢），并说明它为什么没成表格。"""
    if len(buf) < 2 or not _is_separator_row(_row_cells(buf[1])):
        nodes.extend(_para(line) for line in buf)
        warnings.append("发现疑似表格行但缺合法分隔行（|---|---|），已按普通段落呈现")
        return

    header = _row_cells(buf[0])
    align = _aligns(_row_cells(buf[1]))
    width = len(header)
    rows = []
    ragged = False
    for line in buf[2:]:
        cells = _row_cells(line)
        if len(cells) < width:
            ragged = True
            cells += [""] * (width - len(cells))
        elif len(cells) > width:
            ragged = True
            cells = cells[:width]
        rows.append([_para(cell) for cell in cells])

    if ragged:
        warnings.append(f"表格列数不齐，已按表头 {width} 列补齐/截断")
    nodes.append(
        Block(
            NodeKind.TABLE,
            header=[_para(cell) for cell in header],
            rows=rows,
            align=align,
        )
    )


def parse_markdown(text: str) -> ParseResult:
    """Markdown 子集 → 块列表。空输入返回空块（由调用方判错误，不出空白文档）。"""
    nodes: typing.List[Block] = []
    warnings: typing.List[str] = []
    para: typing.List[str] = []
    table: typing.List[str] = []
    cur_list: typing.Optional[Block] = None

    def flush_para() -> None:
        if para:
            nodes.append(_para(" ".join(para)))
            para.clear()

    def flush_list() -> None:
        nonlocal cur_list
        if cur_list is not None:
            nodes.append(cur_list)
            cur_list = None

    def flush_table() -> None:
        if table:
            _flush_table(list(table), nodes, warnings)
            table.clear()

    def flush_all() -> None:
        flush_para()
        flush_list()
        flush_table()

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            flush_all()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_all()
            nodes.append(
                Block(
                    NodeKind.HEADING,
                    runs=parse_inline(heading.group(2)),
                    level=len(heading.group(1)),
                )
            )
            continue

        image = _IMAGE_RE.match(line)
        if image:
            flush_all()
            nodes.append(Block(NodeKind.IMAGE, src=image.group("src"), alt=image.group("alt")))
            continue

        if line.startswith("|"):
            flush_para()
            flush_list()
            table.append(line)
            continue
        if table:
            flush_table()

        bullet, ordered_item = _BULLET_RE.match(line), _ORDERED_RE.match(line)
        if bullet or ordered_item:
            flush_para()
            ordered = ordered_item is not None
            if cur_list is None or cur_list.ordered != ordered:
                flush_list()
                cur_list = Block(NodeKind.LIST, ordered=ordered)
            body = (ordered_item or bullet).group(1)
            cur_list.items.append(_para(body))
            continue

        flush_list()
        para.append(line)

    flush_all()
    return ParseResult(blocks=nodes, warnings=warnings)
