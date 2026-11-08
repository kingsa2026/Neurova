# -*- coding: utf-8 -*-
"""PDF 元数据与 OCR 渲染面的库无关契约——PyMuPDF→pypdfium2 替换等价性护栏。

document_pipeline 的两个 fitz 触点（PDF 文字层走 pypdf、主路抽取走 kreuzberg，
均与本契约无关）：
- _render_pdf_page：2x 缩放、无透明通道、PNG、整页尺寸、非全白（有墨迹）；
- _documentMetadata(.pdf)：title/author/created_at/modified_at 取自 Info 字典原值。

夹具为手工构造的最小合法 PDF（xref 偏移程序化计算），不依赖任何 PDF 生成库；
替换前后本套必须全绿（先在 fitz 旧实现下跑绿取基线，再在 pypdfium2 下跑绿收口）。
"""

import io
import struct

from PIL import Image

from neurova.knowledge import document_pipeline as dp


def _build_pdf() -> bytes:
    """最小合法 PDF：1 页 + Helvetica 文本行 + Info 元数据（ASCII，编码确定）。"""
    content = b"BT /F1 24 Tf 72 720 Td (Neurova License Swap) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Title (Neurova Swap Contract) /Author (Test Author) "
        b"/CreationDate (D:20260101120000) /ModDate (D:20260102120000) >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (idx, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref_pos,
    )
    return bytes(out)


def test_render_page_png_at_two_x_with_ink():
    png = dp._render_pdf_page(_build_pdf(), 0)
    assert png.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1224, 1584)  # MediaBox 612x792 pt × 2
    gray = Image.open(io.BytesIO(png)).convert("L")
    darkest, _ = gray.getextrema()
    assert darkest < 200  # 文本行渲染出墨迹，非空白页


def test_pdf_metadata_contract():
    meta = dp._documentMetadata(_build_pdf(), ".pdf")
    assert meta["title"] == "Neurova Swap Contract"
    assert meta["author"] == "Test Author"
    assert meta["created_at"] == "D:20260101120000"
    assert meta["modified_at"] == "D:20260102120000"
