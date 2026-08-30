"""
附件文本抽取器（R-3）

把上传附件转换为可注入 LLM 上下文的文本：
- text（txt/md/rst）/ code → 直接按 UTF-8 解码
- document：docx（python-docx 段落）、xlsx（openpyxl 单元格）、ppt/pptx（python-pptx 文本）、
  pdf（pypdf 页面文字）、csv → 表格文本化
- image / audio / video → 不抽取文本（由调用方走 vision/ASR/占位）
- 其他 → 返回 None（调用方降级为元数据占位）

所有解析失败都降级为 None（返回 (None, reason) 供日志排查），不抛异常——附件处理失败
不拖垮整轮对话。
"""

import io
import os
from typing import Optional, Tuple

MAX_EXTRACT_BYTES = 2 * 1024 * 1024  # 2MB，超限不抽取（防超大文档拖垮上下文）
MAX_EXTRACT_CHARS = 200_000  # 20 万字符上限


def _decode_text(data: bytes, filename: str) -> Optional[str]:
    text = None
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    return text[:MAX_EXTRACT_CHARS] if text else None


def _extract_docx(data: bytes) -> str:
    import docx  # lazy import：依赖缺失不阻断其他类型

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)[:MAX_EXTRACT_CHARS]


def _extract_xlsx(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"[工作表: {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                parts.append(" | ".join(cells))
            if sum(len(p) for p in parts) > MAX_EXTRACT_CHARS:
                break
    wb.close()
    return "\n".join(parts)[:MAX_EXTRACT_CHARS]


def _extract_pptx(data: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    parts = []
    for idx, slide in enumerate(prs.slides, start=1):
        parts.append(f"[幻灯片 {idx}]")
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)
        # 备注也可以抽取
        try:
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"[备注] {notes}")
        except Exception:
            pass
    return "\n".join(parts)[:MAX_EXTRACT_CHARS]


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages[:100]:  # 最多 100 页，防超大 PDF
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            parts.append(page_text)
    return "\n".join(parts)[:MAX_EXTRACT_CHARS]


def extract_attachment_text(data: bytes, filename: str, file_type: str) -> Tuple[Optional[str], str]:
    """按扩展名抽取附件文本。

    Returns:
        (text, status) —— text 为抽取结果（不可用时 None），status 为诊断原因。
    """
    if data is None or len(data) == 0:
        return None, "empty_file"
    if len(data) > MAX_EXTRACT_BYTES:
        return None, "too_large"

    ext = os.path.splitext(filename)[1].lower()

    if file_type in ("text", "code"):
        text = _decode_text(data, filename)
        return (text, "decoded") if text else (None, "decode_failed")

    if ext == ".docx":
        try:
            return _extract_docx(data), "docx"
        except Exception as e:
            return None, f"docx_error:{type(e).__name__}"
    if ext == ".xlsx":
        try:
            return _extract_xlsx(data), "xlsx"
        except Exception as e:
            return None, f"xlsx_error:{type(e).__name__}"
    if ext in (".pptx", ".ppt"):
        try:
            return _extract_pptx(data), "pptx"
        except Exception as e:
            return None, f"pptx_error:{type(e).__name__}"
    if ext == ".pdf":
        try:
            return _extract_pdf(data), "pdf"
        except Exception as e:
            return None, f"pdf_error:{type(e).__name__}"
    if ext == ".csv":
        text = _decode_text(data, filename)
        return (text, "csv") if text else (None, "csv_decode_failed")

    # 未支持的文档/二进制（doc/xls/ppt 旧格式）不抽取文本
    return None, "unsupported_format"
