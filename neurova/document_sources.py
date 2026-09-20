"""文档入口解析：Markdown 子集 → 中间文档树

子集边界写死在 spec §6，本模块刻意不做"尽量支持"：不认识的语法按字面文本保留，
宁可原样出现在 PDF 里，也不静默丢内容。
"""

import re
import typing

from neurova.document_model import Block, InlineRun, NodeKind

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
# 行内标记：未闭合的 `**` / `*` / 反引号不匹配，整段按字面文本保留
_INLINE_RE = re.compile(
    r"\*\*(?P<bold>[^*]+?)\*\*|\*(?P<italic>[^*]+?)\*|`(?P<code>[^`]+?)`"
)


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


def parse_markdown(text: str) -> typing.List[Block]:
    """Markdown 子集 → 块列表。空输入返回空列表（由调用方判错误，不出空白文档）。"""
    nodes: typing.List[Block] = []
    para: typing.List[str] = []
    cur_list: typing.Optional[Block] = None

    def flush_para() -> None:
        if para:
            nodes.append(Block(NodeKind.PARAGRAPH, runs=parse_inline(" ".join(para))))
            para.clear()

    def flush_list() -> None:
        nonlocal cur_list
        if cur_list is not None:
            nodes.append(cur_list)
            cur_list = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            flush_para()
            flush_list()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            flush_list()
            nodes.append(
                Block(
                    NodeKind.HEADING,
                    runs=parse_inline(heading.group(2)),
                    level=len(heading.group(1)),
                )
            )
            continue

        bullet, ordered_item = _BULLET_RE.match(line), _ORDERED_RE.match(line)
        if bullet or ordered_item:
            flush_para()
            ordered = ordered_item is not None
            if cur_list is None or cur_list.ordered != ordered:
                flush_list()
                cur_list = Block(NodeKind.LIST, ordered=ordered)
            body = (ordered_item or bullet).group(1)
            cur_list.items.append(Block(NodeKind.PARAGRAPH, runs=parse_inline(body)))
            continue

        flush_list()
        para.append(line)

    flush_para()
    flush_list()
    return nodes
