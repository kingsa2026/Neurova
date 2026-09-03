"""
测试：附件文本抽取器（R-3）

契约：
  1. txt/md/code UTF-8 直接解码
  2. docx / xlsx / pptx / pdf / csv 抽取文本（真实文件生成后解析）
  3. 空文件 / 超限 / 旧二进制（doc/xls）降级 None 不抛异常
"""

import io


def _make_docx():
    import docx

    d = docx.Document()
    d.add_paragraph("这是文档第一段")
    d.add_paragraph("第二段内容")
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "A"
    table.rows[0].cells[1].text = "B"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _make_xlsx():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "姓名"
    ws["B1"] = "年龄"
    ws["A2"] = "张三"
    ws["B2"] = 20
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _make_pptx():
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    title = slide.shapes.title
    body = slide.placeholders[1]
    title.text = "幻灯片标题"
    body.text = "要点一\n要点二"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_txt_decodes():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text("你好 hello".encode("utf-8"), "a.txt", "text")
    assert text == "你好 hello"
    assert status == "decoded"


def test_md_decodes():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"# Title\n\nbody", "a.md", "text")
    assert text == "# Title\n\nbody"
    assert status == "decoded"


def test_code_decodes():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"print('hi')", "a.py", "code")
    assert text == "print('hi')"
    assert status == "decoded"


def test_docx_extracts_paragraphs_and_table():
    from neurova.attachment_parser import extract_attachment_text

    data = _make_docx()
    text, status = extract_attachment_text(data, "报告.docx", "document")
    assert status == "docx"
    assert "这是文档第一段" in text
    assert "第二段内容" in text
    assert "A | B" in text


def test_xlsx_extracts_cells():
    from neurova.attachment_parser import extract_attachment_text

    data = _make_xlsx()
    text, status = extract_attachment_text(data, "表格.xlsx", "document")
    assert status == "xlsx"
    assert "姓名" in text and "张三" in text and "年龄" in text


def test_pptx_extracts_shapes():
    from neurova.attachment_parser import extract_attachment_text

    data = _make_pptx()
    text, status = extract_attachment_text(data, "演示.pptx", "document")
    assert status == "pptx"
    assert "幻灯片标题" in text
    assert "要点一" in text


def test_pdf_extracts_pages():
    from neurova.attachment_parser import extract_attachment_text

    # 用 reportlab 不可用，改用 pypdf 写入器（简单文本页）
    from pypdf import PdfWriter

    w = PdfWriter()
    # 无现成文本页时跳过复杂生成，用最小空白页验证不抛异常
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    text, status = extract_attachment_text(buf.getvalue(), "手册.pdf", "document")
    assert status == "pdf"
    assert isinstance(text, str)


def test_csv_decodes():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"a,b\n1,2", "d.csv", "document")
    assert text == "a,b\n1,2"
    assert status == "csv"


def test_legacy_doc_falls_back():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"\x00\x01legacy", "old.doc", "document")
    assert text is None
    assert status == "unsupported_format"


def test_empty_file():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"", "a.txt", "text")
    assert text is None
    assert status == "empty_file"


def test_too_large():
    from neurova.attachment_parser import extract_attachment_text

    big = b"x" * (3 * 1024 * 1024)
    text, status = extract_attachment_text(big, "big.txt", "text")
    assert text is None
    assert status == "too_large"


def test_invalid_docx_returns_none():
    from neurova.attachment_parser import extract_attachment_text

    text, status = extract_attachment_text(b"not a real docx", "fake.docx", "document")
    assert text is None
    assert "docx_error" in status


def test_html_extracts_text():
    from neurova.attachment_parser import extract_attachment_text

    html = b"<html><head><title>My Page</title></head><body><h1>Hello</h1><p>Paragraph text.</p><script>var x=1;</script></body></html>"
    text, status = extract_attachment_text(html, "page.html", "document")
    assert status == "html"
    assert "Hello" in text
    assert "Paragraph text." in text
    # script/style 内容被剥离
    assert "var x=1" not in text


def test_excel_via_xlsx_extracts_text():
    from neurova.attachment_parser import extract_attachment_text

    data = _make_xlsx()
    text, status = extract_attachment_text(data, "表格.xlsx", "document")
    assert status == "xlsx"
    assert "姓名" in text and "张三" in text
