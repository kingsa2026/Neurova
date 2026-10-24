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


def shadowEnabled() -> bool:
    return str(os.environ.get(PARSER_MODE_ENV) or "").strip().lower() == SHADOW_MODE


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
