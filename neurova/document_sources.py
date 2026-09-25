"""文档入口解析：Markdown 子集 → 中间文档树

子集边界写死在 spec §6，本模块刻意不做"尽量支持"：不认识的语法按字面文本保留，
宁可原样出现在 PDF 里，也不静默丢内容。凡是发生降级（伪表格、列数不齐）都记进
`warnings`，让调用方能把"你以为得到了表格"这件事如实说回去。
"""

import re
import typing
from dataclasses import field
from html.parser import HTMLParser
from typing import NamedTuple

from neurova.document_model import Block, InlineRun, NodeKind

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
# 整行独占的图片引用才认；混在句子中间的 ![](...) 保持字面，不做行内图片
_IMAGE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)$")
_DIVIDER_RE = re.compile(r"^[-*_]{3,}$")
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

        if _DIVIDER_RE.match(line):
            flush_all()
            nodes.append(Block(NodeKind.DIVIDER))
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


# ── HTML 子集入口（工单 004）───────────────────────────────────
# 与 Markdown 共用同一棵树、同一条渲染出口：两个入口若各长一套版式行为，
# 漂移只是时间问题。

_HTML_STYLE_TAGS = {
    "b": "bold", "strong": "bold", "i": "italic", "em": "italic",
    "code": "code", "pre": "code",
}
_HTML_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
# 不进 PDF 且必须点名丢弃的标签（内容一并丢）
_HTML_DROP_TAGS = {
    "script", "style", "link", "meta", "head", "title", "iframe", "object", "form", "input",
}
# 结构上按块切分的标签；span/a 这类行内容器不切块也不报告
_HTML_BLOCK_TAGS = {
    "p", "div", "blockquote", "section", "article", "header", "footer",
    "main", "figure", "figcaption", "dl", "dt", "dd",
}
_WS_RE = re.compile(r"\s+")


class _HtmlBuilder(HTMLParser):
    """HTML 子集 → 中间树。未闭合与交叉嵌套只影响版式，不抛异常。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: typing.List[Block] = []
        self.warnings: typing.List[str] = []
        self._runs: typing.List[InlineRun] = []
        self._style = {"bold": False, "italic": False, "code": False}
        self._heading = 0
        self._list: typing.Optional[Block] = None
        self._in_item = False
        self._table: typing.Optional[dict] = None
        self._row: typing.Optional[typing.List[Block]] = None
        self._row_is_header = False
        self._in_cell = False
        self._skip = 0

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = _WS_RE.sub(" ", data)
        if not text:
            return
        self._runs.append(
            InlineRun(
                text,
                bold=self._style["bold"],
                italic=self._style["italic"],
                code=self._style["code"],
            )
        )

    def _take_runs(self) -> typing.List[InlineRun]:
        runs, self._runs = self._runs, []
        return runs or [InlineRun("")]

    def _flush_cell(self) -> None:
        if self._in_cell and self._row is not None:
            self._row.append(Block(NodeKind.PARAGRAPH, runs=self._take_runs()))
        self._in_cell = False

    def _flush_block(self) -> None:
        """闭合当前文本块：单元格 → 标题 → 列表项 → 段落。"""
        if self._in_cell:
            self._flush_cell()
            return
        text = "".join(r.text for r in self._runs)
        if self._heading:
            self.blocks.append(Block(NodeKind.HEADING, runs=self._take_runs(), level=self._heading))
            self._heading = 0
        elif not text.strip():
            self._runs = []
        elif self._in_item and self._list is not None:
            self._list.items.append(Block(NodeKind.PARAGRAPH, runs=self._take_runs()))
            self._in_item = False
        else:
            self.blocks.append(Block(NodeKind.PARAGRAPH, runs=self._take_runs()))

    def _flush_list(self) -> None:
        if self._list is not None:
            self.blocks.append(self._list)
            self._list = None

    def _push_row(self) -> None:
        if self._table is not None and self._row:
            bucket = "header" if self._row_is_header else "rows"
            self._table[bucket].append(self._row)
        self._row = None

    def _flush_table(self) -> None:
        if self._table is None:
            return
        self._flush_cell()
        self._push_row()
        headers = self._table["header"]
        self.blocks.append(
            Block(
                NodeKind.TABLE,
                header=headers[0] if headers else [],
                rows=self._table["rows"],
            )
        )
        self._table = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = (tag or "").lower()
        if tag in _HTML_DROP_TAGS:
            self._skip += 1
            self.warnings.append(f"HTML 标签 <{tag}> 不在子集内，其内容不进入 PDF")
            return
        if tag in _HTML_STYLE_TAGS:
            self._style[_HTML_STYLE_TAGS[tag]] = True
            return
        if tag in _HTML_HEADINGS:
            self._flush_block()
            self._heading = _HTML_HEADINGS[tag]
            return
        if tag in ("ul", "ol"):
            self._flush_block()
            self._flush_list()
            self._list = Block(NodeKind.LIST, ordered=(tag == "ol"))
            return
        if tag == "li":
            self._flush_block()
            if self._list is None:
                self._list = Block(NodeKind.LIST)
            self._in_item = True
            return
        if tag == "table":
            self._flush_block()
            self._flush_list()
            self._table = {"header": [], "rows": []}
            return
        if tag == "tr":
            self._flush_cell()
            self._push_row()
            self._row = []
            self._row_is_header = False
            return
        if tag in ("td", "th"):
            self._in_cell = True
            self._row_is_header = self._row_is_header or (tag == "th")
            return
        if tag == "hr":
            self._flush_block()
            self.blocks.append(Block(NodeKind.DIVIDER))
            return
        if tag == "img":
            self._flush_block()
            given = dict(attrs or {})
            self.blocks.append(
                Block(NodeKind.IMAGE, src=given.get("src", ""), alt=given.get("alt", ""))
            )
            return
        if tag in _HTML_BLOCK_TAGS or tag == "br":
            self._flush_block()

    def handle_startendtag(self, tag, attrs) -> None:
        tag = (tag or "").lower()
        if tag == "img":
            self.handle_starttag("img", attrs)
        elif tag == "br":
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if tag in _HTML_DROP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _HTML_STYLE_TAGS:
            self._style[_HTML_STYLE_TAGS[tag]] = False
            return
        if tag in _HTML_HEADINGS or tag in _HTML_BLOCK_TAGS:
            self._flush_block()
            return
        if tag == "li":
            self._flush_block()
            self._in_item = False
            return
        if tag in ("ul", "ol"):
            self._flush_block()
            self._flush_list()
            return
        if tag in ("td", "th"):
            self._flush_cell()
            return
        if tag == "tr":
            self._flush_cell()
            self._push_row()
            return
        if tag == "table":
            self._flush_table()


def parse_html(text: str) -> ParseResult:
    """HTML 子集 → 块列表。与 parse_markdown 同型，出口共用一棵树。"""
    builder = _HtmlBuilder()
    builder.feed(text or "")
    builder.close()
    builder._flush_block()
    builder._flush_list()
    builder._flush_table()
    return ParseResult(blocks=builder.blocks, warnings=builder.warnings)
