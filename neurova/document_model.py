"""中间文档树（Canonical Document Tree）

文档导出的中立表示：Markdown 与 HTML 两个入口都归一到这棵树，渲染器（PDF 等）
只消费它。因此本模块刻意保持三件事之外的一无所有——纯数据 + 归一化，
不 import 任何渲染库，不碰 I/O。
"""

import typing
from dataclasses import dataclass, field
from enum import Enum


class NodeKind(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    DIVIDER = "divider"


@dataclass(frozen=True)
class InlineRun:
    """一段同风格的行内文本。样式是标志位而非标记语言，渲染器自行决定如何表达。"""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False


@dataclass
class Block:
    """块级节点。标题用 level，列表用 items（每项是一个 PARAGRAPH Block），
    段落与标题用 runs；表格用 header/rows（单元格同为 PARAGRAPH Block），
    align 是每列的水平对齐（left/center/right）。"""

    kind: NodeKind
    runs: typing.List[InlineRun] = field(default_factory=list)
    level: int = 1
    ordered: bool = False
    items: typing.List["Block"] = field(default_factory=list)
    header: typing.List["Block"] = field(default_factory=list)
    rows: typing.List[typing.List["Block"]] = field(default_factory=list)
    align: typing.List[str] = field(default_factory=list)
    src: str = ""
    alt: str = ""

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass(frozen=True)
class DocSettings:
    """渲染设置。三态要分清：None 是"没表态，用模板默认"，空串是"我要关掉它"。
    把空串也当没填，调用方就永远关不掉页脚。"""

    template: str = "report"
    title: str = ""
    header_text: typing.Optional[str] = None
    footer_text: typing.Optional[str] = None
    page_number: typing.Optional[bool] = None
    margin_mm: float = 18.0
