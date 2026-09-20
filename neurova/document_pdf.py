"""中间文档树 → PDF 字节（reportlab 出口）

本模块是全仓唯一 import reportlab 的地方：渲染库缺席只影响这一个能力，不把
依赖扩散到模型与解析层（那两层在没有 reportlab 的环境里也必须可单测）。

字体口径与字幕烧录同源（core.ffmpeg.find_cjk_font）。降级为 PDF 内置 CID 字体时
必须在返回值里说出来——CID 不嵌字体，接收方缺中文字库时看到的是方框，
那是一个"出件成功、内容不可读"的假成功。
"""

import io
import typing
from pathlib import Path
from xml.sax.saxutils import escape

from neurova.core.ffmpeg import find_cjk_font
from neurova.document_model import Block, DocSettings, InlineRun, NodeKind

EMBEDDED_FONT_NAME = "NeurovaCJK"
CID_FONT_NAME = "STSong-Light"

CID_FALLBACK_WARNING = (
    "未找到可嵌入的中文字体，已退回 PDF 内置 CID 字体 STSong-Light："
    "该路径不嵌字体，阅读器缺中文字库时中文会显示为方框。"
    "可安装系统 CJK 字体，或显式传入 font 指定字体文件。"
)

_HEADING_SIZES = {1: 18.0, 2: 15.0, 3: 13.0, 4: 12.0, 5: 11.5, 6: 11.0}
# reportlab ParagraphStyle.alignment：0 左 / 1 中 / 2 右
_ALIGNMENT = {"left": 0, "center": 1, "right": 2}


class RenderUnavailable(RuntimeError):
    """渲染库缺席：由调用方（工具层）转成结构化错误，不把 ImportError 抛给主链路。"""


def resolve_cjk_font(preferred: typing.Optional[str] = None) -> typing.Dict[str, typing.Any]:
    """字体决策：显式指定 > 探测到的系统 CJK 字体 > 内置 CID 兜底。

    显式指定的字体文件不存在时报错而不是换个字体——静默替换会让调用方以为
    自己点名的字体生效了。
    """
    if preferred:
        chosen = Path(preferred)
        if not chosen.is_file():
            raise FileNotFoundError(f"指定的字体文件不存在: {preferred}")
        return {"mode": "embedded", "name": EMBEDDED_FONT_NAME, "path": str(chosen), "embeds_font": True}

    found = find_cjk_font()
    if found is not None:
        return {"mode": "embedded", "name": EMBEDDED_FONT_NAME, "path": str(found), "embeds_font": True}
    return {"mode": "cid", "name": CID_FONT_NAME, "path": None, "embeds_font": False}


def runs_to_markup(runs: typing.Sequence[InlineRun]) -> str:
    """行内 run → Paragraph 标记文本：先转义再上样式。

    顺序很重要——先上样式再转义会把我们自己的 `<b>` 一起转义掉，
    先转义则正文里的 `<b>` 只能以字面量出现。
    """
    parts: typing.List[str] = []
    for run in runs:
        text = escape(run.text)
        if run.code:
            parts.append(f'<font face="Courier">{text}</font>')
        elif run.bold:
            parts.append(f"<b>{text}</b>")
        elif run.italic:
            parts.append(f"<i>{text}</i>")
        else:
            parts.append(text)
    return "".join(parts)


def _register_font(font: typing.Dict[str, typing.Any]) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    if font["mode"] == "cid":
        pdfmetrics.registerFont(UnicodeCIDFont(CID_FONT_NAME))
        return CID_FONT_NAME

    path = font["path"]
    # .ttc 是集族字体，不带 subfontIndex 时 reportlab 直接读不出字形
    name = (
        TTFont(font["name"], path, subfontIndex=0)
        if path.lower().endswith(".ttc")
        else TTFont(font["name"], path)
    )
    pdfmetrics.registerFont(name)
    # 单一 TTF 没有独立粗体/斜体字面，注册为同面：`<b>` 保持可读而不是丢字
    pdfmetrics.registerFontFamily(
        font["name"], normal=font["name"], bold=font["name"], italic=font["name"], boldItalic=font["name"]
    )
    return font["name"]


def _styles(base_font: str):
    from reportlab.lib.styles import ParagraphStyle

    body = ParagraphStyle("neurovaBody", fontName=base_font, fontSize=11, leading=16, spaceAfter=6)
    headings = {
        level: ParagraphStyle(
            f"neurovaH{level}", parent=body, fontName=base_font, fontSize=size, leading=size * 1.35,
            spaceBefore=10, spaceAfter=6,
        )
        for level, size in _HEADING_SIZES.items()
    }
    item = ParagraphStyle("neurovaItem", parent=body, leftIndent=14, spaceAfter=2)
    cells = {
        align: ParagraphStyle(
            f"neurovaCell{align}", parent=body, fontSize=10, leading=13, spaceAfter=0,
            wordWrap="CJK", alignment=_ALIGNMENT[align],
        )
        for align in _ALIGNMENT
    }
    return body, headings, item, cells


def _cell_texts(block: Block) -> typing.List[typing.List[str]]:
    return [[cell.text for cell in row] for row in ([block.header] + block.rows) if row]


def _column_widths(texts: typing.List[typing.List[str]], available: float) -> typing.List[float]:
    """列宽按各列最长内容成比例分配，保底 24pt。

    中文不需要按词断行（`wordWrap="CJK"` 已能逐字折行），所以宽表的首选取舍是
    折行而不是缩字号——缩字号会把整张表压成看不清的小字，那是为排版牺牲内容可读性。
    """
    cols = max((len(row) for row in texts), default=1)
    longest = [1] * cols
    for row in texts:
        for index, cell in enumerate(row[:cols]):
            longest[index] = max(longest[index], min(len(cell), 60))
    total = float(sum(longest))
    return [max(24.0, available * weight / total) for weight in longest]


def _fit_cell(cell: str, width: float, font_name: str, size: float) -> typing.Tuple[str, bool]:
    """单元格内不可断行的长串（URL / 连续符号）超列宽时截断并报告。

    能折行的交给 Paragraph 处理；只有折不动的才走到这一步。
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    longest_token = max(cell.split() or [""], key=len)
    if stringWidth(longest_token, font_name, size) <= width - 8:
        return cell, False

    budget = max(1.0, width - 8.0)
    kept = ""
    for char in cell:
        if stringWidth(kept + char, font_name, size) > budget:
            break
        kept += char
    return (kept + "…") if kept else "…", True


def _table(block: Block, cells, base_font: str, available: float, warnings: typing.List[str]):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    texts = _cell_texts(block)
    widths = _column_widths(texts, available)
    aligns = list(block.align) or ["left"] * len(texts[0])

    data, truncated_cols = [], set()
    for row_index, row in enumerate(texts):
        styled = []
        for col_index, cell in enumerate(row):
            width = widths[col_index] if col_index < len(widths) else available
            fitted, was_cut = _fit_cell(cell, width, base_font, 10.0)
            if was_cut:
                truncated_cols.add(col_index + 1)
            align = aligns[col_index] if col_index < len(aligns) else "left"
            styled.append(Paragraph(fitted, cells.get(align, cells["left"])))
        data.append(styled)

    table = Table(data, colWidths=widths, repeatRows=1 if block.header else 0)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8A8A8A")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")) if block.header else ("TOPPADDING", (0, 0), (0, 0), 2),
            ]
        )
    )
    for column in sorted(truncated_cols):
        warnings.append(f"第 {column} 列存在折不动的超长内容，已按列宽截断（可读性优先于缩字号）")
    return table


def _image(block: Block, body, available: float, warnings: typing.List[str]):
    """图片块。src 已由工具层解析成本地路径（远程图先过 persist_media）。

    读不到就退回到一行文字线索而不是整件失败——一份少了一张图的报告仍然有用，
    但少图这件事必须写进 warnings。
    """
    from pathlib import Path

    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, Paragraph

    def _skip(reason: str):
        warnings.append(f"图片已跳过（{reason}）：{block.alt or block.src}")
        return Paragraph(f"[图：{block.alt}]" if block.alt else "[图片已跳过]", body)

    try:
        if not Path(block.src).is_file():
            return _skip("文件不存在")
        width, height = ImageReader(block.src).getSize()
    except Exception as e:  # noqa: BLE001 - 任何图片格式/读取问题都不该带走整份文档
        return _skip(f"无法读取：{type(e).__name__}")

    scale = min(1.0, available / float(width)) if width else 1.0
    return Image(block.src, width=width * scale, height=height * scale)


def _story(blocks, *, headings, body, item, cells, base_font, available, warnings):
    from reportlab.platypus import Paragraph

    story = []
    for block in blocks:
        if block.kind == NodeKind.HEADING:
            story.append(Paragraph(runs_to_markup(block.runs), headings.get(block.level, headings[6])))
        elif block.kind == NodeKind.LIST:
            for index, entry in enumerate(block.items, 1):
                bullet = f"{index}. " if block.ordered else "• "
                story.append(Paragraph(bullet + runs_to_markup(entry.runs), item))
        elif block.kind == NodeKind.TABLE:
            story.append(_table(block, cells, base_font, available, warnings))
        elif block.kind == NodeKind.IMAGE:
            story.append(_image(block, body, available, warnings))
        else:
            story.append(Paragraph(runs_to_markup(block.runs), body))
    return story


def render_document(
    blocks: typing.Sequence[Block],
    settings: typing.Optional[DocSettings] = None,
    font: typing.Optional[str] = None,
) -> typing.Dict[str, typing.Any]:
    """树 → PDF 字节。空树拒收（不出空白文档，空白文档在响应里看起来像成功）。"""
    if not blocks:
        raise ValueError("文档内容为空，未出件")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate
    except ImportError as e:  # noqa: BLE001 - 可选依赖缺席要能被发现
        raise RenderUnavailable(f"PDF 渲染库不可用（需 reportlab>=4.0）: {e}") from e

    settings = settings or DocSettings()
    resolved = resolve_cjk_font(font)
    base_font = _register_font(resolved)
    body, headings, item, cells = _styles(base_font)

    buffer = io.BytesIO()
    margin = float(settings.margin_mm) * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=settings.title or None,
        author="Neurova",
    )
    warnings = [CID_FALLBACK_WARNING] if resolved["mode"] == "cid" else []
    doc.build(
        _story(
            blocks,
            headings=headings,
            body=body,
            item=item,
            cells=cells,
            base_font=base_font,
            available=A4[0] - 2 * margin,
            warnings=warnings,
        )
    )
    return {"pdf": buffer.getvalue(), "pages": doc.page, "font": resolved, "warnings": warnings}
