"""Kreuzberg 影子解析对比（升级计划 A7）：只读数，不切主路。

已拍板迁移到 Kreuzberg 统一解析框架，但切换前必须先有影子对比（页数/标题/
正文字符量/失败原因）。影子模式（`NEUROVA_KB_PARSER=kreuzberg_shadow`）在
主路（现有 document_pipeline）照常产出之外，用 Kreuzberg 独立抽一遍同样的
输入，把两路读数挂进 `metadata["parser_shadow"]`——**主路返回逐字不变**，
影子失败只记读数不让解析失败。对比读数稳定之后，切换才有一个可审计的依据。

这里不成为第二套解析真源：影子产物不进 pages/chunks，不参与入库，
只回答"换成 Kreuzberg 会差多少"。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

PARSER_MODE_ENV = "NEUROVA_KB_PARSER"
SHADOW_MODE = "kreuzberg_shadow"
MAIN_MODE = "kreuzberg"
LEGACY_MODE = "legacy"

_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


def parserMode() -> str:
    """解析主路模式：legacy（缺省，历史行为）| kreuzberg（拍板迁移的统一抽取）
    | kreuzberg_shadow（legacy 主路 + 影子读数）。切换是环境配置动作，
    机制在此单源，调用方不各自读环境变量。"""
    return str(os.environ.get(PARSER_MODE_ENV) or LEGACY_MODE).strip().lower()


def shadowEnabled() -> bool:
    return parserMode() == SHADOW_MODE


def kreuzbergMainEnabled(ext: str) -> bool:
    """Kreuzberg 主路是否接管该格式：接管文本/表格/演示等文档格式。
    图片不走 kreuzberg——OCR 是引擎层（ocr_engines）的责任，与解析框架分层。"""
    if parserMode() != MAIN_MODE:
        return False
    return str(ext or "").lower() not in _IMAGE_EXTS


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def kreuzbergExtract(data: bytes, ext: str) -> str:
    """Kreuzberg 统一抽取：失败诚实抛错（带可读原因），不静默回落 legacy。"""
    extractor = _loadExtractor()
    mime = _MIME_BY_EXT.get(str(ext or "").lower())
    if mime is None:
        raise ValueError(
            "Kreuzberg 主路不认格式 %r（可用：%s；其余格式请切回 legacy 模式）"
            % (ext, ", ".join(sorted(k for k in _MIME_BY_EXT))))
    result = extractor(data, mime)
    content = str(getattr(result, "content", "") or "")
    if not content.strip():
        raise ValueError("Kreuzberg 抽取结果为空（%s）——扫描件请用 legacy 模式的 OCR 编排" % ext)
    return content


def _loadExtractor():
    """Kreuzberg 抽取器的唯一取点：可选依赖缺席就在这里暴露，由影子如实记录。"""
    from kreuzberg import extract_bytes_sync

    return extract_bytes_sync


def kreuzbergShadowCompare(
    data: bytes, filename: str, ext: str,
    mainTitle: str, mainContent: str,
) -> Dict[str, Any]:
    """Kreuzberg 独立抽一遍，返回对比读数；失败以 ok=False + 原因如实记录。"""
    reading: Dict[str, Any] = {"engine": "kreuzberg", "ok": False}
    try:
        extractor = _loadExtractor()

        mime = _MIME_BY_EXT.get(str(ext or "").lower(), "application/octet-stream")
        result = extractor(data, mime)
    except Exception as exc:  # noqa: BLE001 - 影子失败不是主路失败，但要留名
        reading["error"] = str(exc) or type(exc).__name__
        logger.debug("Kreuzberg 影子抽取失败（%s）: %s", filename, reading["error"])
        return reading

    shadowContent = str(getattr(result, "content", "") or "")
    meta = getattr(result, "metadata", None)
    shadowPages = None
    if isinstance(meta, dict):
        for key in ("page_count", "pages", "pdf_page_count"):
            if isinstance(meta.get(key), int):
                shadowPages = int(meta[key])
                break
    reading.update({
        "ok": True,
        "mime": mime,
        "chars": len(shadowContent),
        "main_chars": len(str(mainContent or "")),
        "pages": shadowPages,
    })
    # 标题对比：两路标题各自存在时才可比；任一缺席记 None，不硬凑一致/不一致。
    shadowTitle = ""
    if isinstance(meta, dict) and meta.get("title"):
        shadowTitle = str(meta["title"])
    reading["title_matches"] = (
        mainTitle.strip() == shadowTitle.strip()
        if (mainTitle and shadowTitle) else None)
    return reading
