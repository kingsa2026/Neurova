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
    return body, headings, item


def _story(blocks: typing.Sequence[Block], body, headings, item):
    from reportlab.platypus import Paragraph

    story = []
    for block in blocks:
        if block.kind == NodeKind.HEADING:
            style = headings.get(block.level, headings[6])
            story.append(Paragraph(runs_to_markup(block.runs), style))
        elif block.kind == NodeKind.LIST:
            for index, entry in enumerate(block.items, 1):
                bullet = f"{index}. " if block.ordered else "• "
                story.append(Paragraph(bullet + runs_to_markup(entry.runs), item))
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
    body, headings, item = _styles(base_font)

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
    doc.build(_story(blocks, headings=headings, body=body, item=item))

    warnings = [CID_FALLBACK_WARNING] if resolved["mode"] == "cid" else []
    return {"pdf": buffer.getvalue(), "pages": doc.page, "font": resolved, "warnings": warnings}
