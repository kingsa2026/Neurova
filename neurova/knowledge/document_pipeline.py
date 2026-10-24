"""文档标准化流水线：格式分流 → 文字层/OCR → 清洗 → 页码/标题 → 分块。

知识导入、企微入站、网页导入共用这一条入口；聊天附件仍走
`attachment_parser.extract_attachment_text`（不强制 OCR，行为不变）。

设计边界：
- OCR 引擎按 `NEUROVA_KB_OCR_ENGINE` 选择（rapidocr|paddle|tesseract|auto，
  契约在 `ocr_engines` 单源）；不可用时如实返回 `ocr_unavailable`，不生成空知识；
- LibreOffice 只用于旧版 .doc/.ppt/.xls 转换；不可用时返回
  `legacy_office_unavailable`，不伪造文本；
- 页码/标题是结构信息，不凭正文猜测；无法确定时保留空值。
"""
from __future__ import annotations

import datetime
import io
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.attachment_parser import (
    MAX_EXTRACT_CHARS,
    extract_docx_blocks,
    extract_pdf_pages,
    extract_pptx_slides,
    extract_xls_sheets,
    extract_xlsx_sheets,
    extract_attachment_text,
)
from neurova.core.logger import get_logger
from neurova.knowledge import parser_shadow
from neurova.knowledge.ocr_engines import selectOcrEngine
from neurova.knowledge.splitter import build_entry_chunks

logger = get_logger(__name__)

OCR_MODES = ("auto", "on", "off")
LEGACY_EXTENSIONS = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PAGE_NO_RE = re.compile(r"^\s*(?:第\s*)?\d+\s*(?:页|/\s*\d+)?\s*$")


class DocumentParseError(RuntimeError):
    """带可读原因的解析失败；调用方把 reason 原样报给用户。"""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class ParsedDocument:
    doc_id: str
    source_type: str
    source_path: str
    ingest_time: str
    content: str
    metadata: Dict[str, Any]
    pages: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    parents: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "ingest_time": self.ingest_time,
            "content": self.content,
            "metadata": dict(self.metadata),
            "pages": [dict(page) for page in self.pages],
            "chunks": [dict(chunk) for chunk in self.chunks],
            "warnings": list(self.warnings),
        }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def _source_type(filename: str) -> str:
    ext = _ext(filename).lstrip(".")
    if ext in ("md", "markdown"):
        return "md"
    if ext in ("json", "yaml", "yml", "toml"):
        return "json"
    if ext in ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"):
        return "image"
    return ext or "unknown"


def _documentMetadata(data: bytes, ext: str) -> Dict[str, str]:
    """抽取文档核心属性（标题/作者/创建/修改）；失败一律空值，不猜。"""
    try:
        if ext == ".docx":
            from docx import Document

            props = Document(io.BytesIO(data)).core_properties
            def _iso(value):
                return value.isoformat() if hasattr(value, "isoformat") else str(value or "")
            return {
                "title": str(props.title or ""),
                "author": str(props.author or ""),
                "created_at": _iso(props.created),
                "modified_at": _iso(props.modified),
            }
        if ext == ".pdf":
            import fitz

            doc = fitz.open(stream=data, filetype="pdf")
            try:
                meta = doc.metadata or {}
            finally:
                doc.close()
            return {
                "title": str(meta.get("title") or ""),
                "author": str(meta.get("author") or ""),
                "created_at": str(meta.get("creationDate") or ""),
                "modified_at": str(meta.get("modDate") or ""),
            }
    except Exception:  # noqa: BLE001 - 元数据缺失不影响正文解析
        return {}
    return {}


# ── OCR ──────────────────────────────────────────────────────
# 引擎契约与选择器在 `ocr_engines` 单源（升级计划 A2）：RapidOCR/PaddleOCR/
# Tesseract 同一契约，NEUROVA_KB_OCR_ENGINE 选择，缺省 rapidocr 行为不变。


def _render_pdf_page(data: bytes, page_index: int) -> bytes:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError("ocr_render_unavailable", "PyMuPDF 未安装") from exc
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


# ── 清洗 ─────────────────────────────────────────────────────


def _clean_line(line: str) -> str:
    line = unicodedata.normalize("NFKC", line or "")
    line = "".join(
        ch for ch in line
        if ch in ("\n", "\t") or (ord(ch) >= 32 and ord(ch) != 127)
    )
    return line.rstrip()


def _clean_pages(pages: List[str]) -> List[str]:
    """清洗并去掉重复页眉/页脚；只动页首/页尾重复行，不改正文中段。"""
    cleaned = [[_clean_line(line) for line in (page or "").splitlines()] for page in pages]
    if len(cleaned) < 2:
        return ["\n".join(lines).strip() for lines in cleaned]
    threshold = max(2, int(len(cleaned) * 0.7))
    edge_counts: Dict[str, int] = {}
    for lines in cleaned:
        nonempty = [line for line in lines if line.strip()]
        for line in set(nonempty[:2] + nonempty[-2:]):
            if len(line) <= 200:
                edge_counts[line] = edge_counts.get(line, 0) + 1
    repeated = {line for line, count in edge_counts.items() if count >= threshold}
    out: List[str] = []
    for lines in cleaned:
        kept = []
        for index, line in enumerate(lines):
            edge = index < 2 or index >= len(lines) - 2
            if edge and line in repeated:
                continue
            if _PAGE_NO_RE.match(line):
                continue
            kept.append(line)
        out.append("\n".join(kept).strip())
    return out


def _clean_content(text: str) -> str:
    text = "\n".join(_clean_line(line) for line in (text or "").splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_EXTRACT_CHARS]


# ── 旧版 Office ──────────────────────────────────────────────


def legacyOfficeAvailable() -> bool:
    return bool(_officeBinary())


def _officeBinary() -> str:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _convertLegacyOffice(data: bytes, ext: str) -> Tuple[bytes, str]:
    target = LEGACY_EXTENSIONS.get(ext)
    binary = _officeBinary()
    if target is None:
        raise DocumentParseError("unsupported_format", ext)
    if not binary:
        raise DocumentParseError(
            "legacy_office_unavailable",
            "LibreOffice 未安装，无法转换 %s" % ext,
        )
    with tempfile.TemporaryDirectory(prefix="neurova-legacy-") as work:
        src = Path(work) / ("source" + ext)
        src.write_bytes(data)
        try:
            subprocess.run(
                [binary, "--headless", "--convert-to", target, "--outdir", work, str(src)],
                check=True, capture_output=True, timeout=60,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise DocumentParseError("legacy_convert_failed", str(exc)) from exc
        converted = Path(work) / ("source." + target)
        if not converted.exists():
            raise DocumentParseError("legacy_convert_failed", "converted file missing")
        return converted.read_bytes(), "." + target


# ── 结构/分块 ────────────────────────────────────────────────


def _headingStack(spans: List[Tuple[int, int, str]], position: int) -> List[str]:
    stack: List[Tuple[int, str]] = []
    for start, level, text in spans:
        if start > position:
            break
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    return [text for _level, text in stack]


def _pageFor(position: int, spans: List[Tuple[int, int]]) -> int:
    page = 1
    for index, (start, end) in enumerate(spans, start=1):
        if start <= position < end:
            return index
        if position >= end:
            page = index
    return page


def _markdownHeadingSpans(content: str) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    position = 0
    for line in (content or "").splitlines(True):
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match:
            spans.append((position, len(match.group(1)), match.group(2).strip()))
        position += len(line)
    return spans


def _chunkDocument(
    pages: List[Dict[str, Any]],
    headingSpans: List[Tuple[int, int, str]],
    pageHeading: Dict[int, List[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按页分块：块不跨页，页码/标题路径可直接回指。"""
    allChildren: List[Dict[str, Any]] = []
    allParents: List[Dict[str, Any]] = []
    pageStart = 0
    for page in pages:
        pageNo = int(page.get("page") or 1)
        body = str(page.get("text") or "")
        children, parents = build_entry_chunks(body)
        for child in children:
            localStart = int(child.get("char_start") or 0)
            globalStart = pageStart + localStart
            globalEnd = pageStart + int(child.get("char_end") or localStart)
            heading = _headingStack(headingSpans, globalStart)
            if not heading:
                heading = list(pageHeading.get(pageNo) or [])
            child["page"] = pageNo
            child["heading_path"] = heading
            child["char_start"] = globalStart
            child["char_end"] = globalEnd
            allChildren.append(child)
        for parent in parents:
            localStart = int(parent.get("char_start") or 0)
            localEnd = int(parent.get("char_end") or localStart)
            parent["page"] = pageNo
            parent["heading_path"] = list(pageHeading.get(pageNo) or [])
            parent["char_start"] = pageStart + localStart
            parent["char_end"] = pageStart + localEnd
            allParents.append(parent)
        pageStart += len(body) + 1  # content 用 "\n" 连接页
    return allChildren, allParents


def _fileTypeFor(ext: str) -> str:
    if ext in (".txt", ".md", ".markdown", ".rst", ".json", ".yaml", ".yml",
               ".toml", ".log"):
        return "text"
    return "document"


def parse_document(
    data: bytes,
    filename: str,
    *,
    source_path: str = "",
    source_type: str = "",
    ocr_mode: str = "auto",
    ocr_engine: Any = None,
    engine_mode: str = "structured",
) -> ParsedDocument:
    """结构化解析单个文档；失败抛 DocumentParseError(reason)。

    `engine_mode="legacy"` 走旧的 `attachment_parser` 抽取（无页码/OCR 编排），
    作为迁移期的运行时回退开关；默认 structured。
    """
    if not data:
        raise DocumentParseError("empty_file")
    if str(engine_mode or "").strip().lower() == "legacy":
        return _parseLegacy(data, filename, source_path=source_path,
                            source_type=source_type)
    mode = str(ocr_mode or "auto").lower()
    if mode not in OCR_MODES:
        mode = "auto"
    ext = _ext(filename)
    sourceType = source_type or _source_type(filename)
    warnings: List[str] = []
    pagesRaw: List[str] = []
    pageHeading: Dict[int, List[str]] = {}
    headingSpans: List[Tuple[int, int, str]] = []
    engine = ocr_engine
    ocrMeta: Dict[str, Any] = {}
    # 影子对比要打回**原始**输入：旧格式转换会重绑 data，先留底。
    rawInput = data
    originalExt = ext
    # 主路标注按实际分支：图片等格式在 kreuzberg 模式下仍走本管线编排。
    pipelineName = "structured"

    try:
        # .xls 直读（A7）：xlrd 可用就走直读（产出与 xlsx 同形），缺席回落 LibreOffice。
        xlsSheets = extract_xls_sheets(data) if ext == ".xls" else None
        if xlsSheets is None and ext in LEGACY_EXTENSIONS:
            # source_type 保留原始旧格式，解析按转换后的新格式走。
            data, ext = _convertLegacyOffice(data, ext)
        if parser_shadow.kreuzbergMainEnabled(ext):
            # Kreuzberg 统一抽取（拍板迁移）：内容层归 kreuzberg，本管线保留
            # 清洗/分块/标题编排；OCR 仍走引擎层（图片分支不经过这里），
            # 抽取失败诚实报错，不静默回落双主路。
            pagesRaw = [parser_shadow.kreuzbergExtract(rawInput, originalExt)]
            pipelineName = "kreuzberg"
        elif ext == ".pdf":
            pagesRaw = extract_pdf_pages(data)
            if engine is None:
                engine = selectOcrEngine()
            # 逐页：有文字层用文字层；空页/on 模式渲染 OCR
            prepared: List[str] = []
            for index in range(len(pagesRaw)):
                text = pagesRaw[index] or ""
                needOcr = mode == "on" or (mode == "auto" and not text.strip())
                if needOcr:
                    if engine is None or not engine.available():
                        if not text.strip():
                            warnings.append("page_%d:ocr_unavailable" % (index + 1))
                    else:
                        try:
                            image = _render_pdf_page(data, index)
                            ocrText, confidence, name = engine.recognize(image)
                            if ocrText:
                                text = ocrText
                                ocrMeta.setdefault("ocr_used", True)
                                ocrMeta.setdefault("ocr_engine", name)
                                ocrMeta.setdefault("_scores", []).append(confidence)
                        except DocumentParseError as exc:
                            warnings.append("page_%d:%s" % (index + 1, exc.reason))
                prepared.append(text)
            pagesRaw = prepared
        elif ext == ".docx":
            blocks = extract_docx_blocks(data)
            parts: List[str] = []
            cursor = 0
            for block in blocks:
                text = str(block.get("text") or "").strip()
                if not text:
                    continue
                if parts:
                    cursor += 1
                start = cursor
                parts.append(text)
                cursor += len(text)
                if block.get("kind") == "heading":
                    headingSpans.append((start, int(block.get("level") or 1), text))
            pagesRaw = ["\n".join(parts)]
        elif ext == ".xlsx":
            sheets = extract_xlsx_sheets(data)
            pagesRaw = [
                ("[工作表: %s]\n%s" % (sheet.get("title") or "", sheet.get("text") or "")).strip()
                for sheet in sheets
            ]
            pageHeading = {
                index: [str(sheet.get("title") or "")]
                for index, sheet in enumerate(sheets, start=1)
            }
        elif xlsSheets is not None:
            # .xls 直读：与 xlsx 分支同形消费（同一份"表格→文本"口径）。
            pagesRaw = [
                ("[工作表: %s]\n%s" % (sheet.get("title") or "", sheet.get("text") or "")).strip()
                for sheet in xlsSheets
            ]
            pageHeading = {
                index: [str(sheet.get("title") or "")]
                for index, sheet in enumerate(xlsSheets, start=1)
            }
        elif ext == ".pptx":
            slides = extract_pptx_slides(data)
            pagesRaw = [
                ("[幻灯片 %d]\n%s" % (index, text or "")).strip()
                for index, text in enumerate(slides, start=1)
            ]
            pageHeading = {index: ["幻灯片 %d" % index] for index in range(1, len(pagesRaw) + 1)}
        elif ext in _IMAGE_EXTENSIONS:
            if mode == "off":
                raise DocumentParseError("ocr_disabled_for_image")
            engine = engine or selectOcrEngine()
            if not engine.available():
                raise DocumentParseError(
                    "ocr_unavailable", "%s 未安装或不可用" % engine.name)
            text, confidence, name = engine.recognize(data)
            pagesRaw = [text]
            ocrMeta = {
                "ocr_used": True,
                "ocr_engine": name,
                "_scores": [confidence] if text else [],
            }
        else:
            text, status = extract_attachment_text(
                data, filename, _fileTypeFor(ext)
            )
            if text is None:
                raise DocumentParseError(status or "unsupported_format")
            pagesRaw = [text]
    except DocumentParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError("parse_failed:%s" % type(exc).__name__, str(exc)) from exc

    pagesClean = _clean_pages(pagesRaw)
    content = _clean_content("\n".join(pagesClean))
    if not content:
        raise DocumentParseError("no_extractable_text")
    pages = [{"page": index, "text": text, "ocr_used": bool(ocrMeta.get("ocr_used"))}
             for index, text in enumerate(pagesClean, start=1)]
    if not headingSpans:
        headingSpans = _markdownHeadingSpans(content)
    children, parents = _chunkDocument(pages, headingSpans, pageHeading)
    scores = ocrMeta.pop("_scores", [])
    core = _documentMetadata(data, ext)
    metadata = {
        "title": core.get("title") or Path(filename).stem or filename,
        "author": core.get("author", ""),
        "created_at": core.get("created_at", ""),
        "modified_at": core.get("modified_at", ""),
        "pipeline": pipelineName,
        "ocr_used": bool(ocrMeta.get("ocr_used")),
        "ocr_engine": str(ocrMeta.get("ocr_engine") or ""),
        "ocr_confidence_avg": (
            round(sum(scores) / len(scores), 4) if scores else None
        ),
        "page_count": len(pages),
        "source_filename": filename,
        "warnings": list(warnings),
    }
    # Kreuzberg 影子对比（A7）：只挂读数，不改主路任何产出；影子失败不波及解析。
    if parser_shadow.shadowEnabled():
        try:
            metadata["parser_shadow"] = parser_shadow.kreuzbergShadowCompare(
                rawInput, filename, originalExt,
                str(metadata["title"]), content)
        except Exception as exc:  # noqa: BLE001 - 影子只读数，不挡主路
            logger.debug("Kreuzberg 影子对比跳过: %s", exc)
    return ParsedDocument(
        doc_id=str(uuid.uuid4()),
        source_type=sourceType,
        source_path=source_path or filename,
        ingest_time=_now(),
        content=content,
        metadata=metadata,
        pages=pages,
        chunks=children,
        parents=parents,
        warnings=warnings,
    )


def _parseLegacy(
    data: bytes, filename: str, *, source_path: str = "", source_type: str = ""
) -> ParsedDocument:
    """迁移期回退：沿用旧的单段文本抽取，不生成页码/标题层级/OCR 编排。"""
    ext = _ext(filename)
    text, status = extract_attachment_text(data, filename, _fileTypeFor(ext))
    if text is None:
        raise DocumentParseError(status or "unsupported_format")
    pagesClean = _clean_pages([text])
    content = _clean_content("\n".join(pagesClean))
    if not content:
        raise DocumentParseError("no_extractable_text")
    pages = [{"page": 1, "text": pagesClean[0], "ocr_used": False}]
    headingSpans = _markdownHeadingSpans(content)
    children, parents = _chunkDocument(pages, headingSpans, {})
    core = _documentMetadata(data, ext)
    metadata = {
        "title": core.get("title") or Path(filename).stem or filename,
        "author": core.get("author", ""),
        "created_at": core.get("created_at", ""),
        "modified_at": core.get("modified_at", ""),
        "pipeline": "legacy",
        "ocr_used": False,
        "ocr_engine": "",
        "ocr_confidence_avg": None,
        "page_count": 1,
        "source_filename": filename,
        "warnings": ["legacy_pipeline"],
    }
    return ParsedDocument(
        doc_id=str(uuid.uuid4()),
        source_type=source_type or _source_type(filename),
        source_path=source_path or filename,
        ingest_time=_now(),
        content=content,
        metadata=metadata,
        pages=pages,
        chunks=children,
        parents=parents,
        warnings=["legacy_pipeline"],
    )
