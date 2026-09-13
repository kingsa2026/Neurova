# -*- coding: utf-8 -*-
"""工作区文档收集器（P0-1，Codex AGENTS.md 对齐）。

语义（docs/Neurova_Codex代码级对比_2026-09-14.md §2.3）：
- 同目录优先级：AGENTS.override.md > AGENTS.md（override 语义同 Codex）
- 收集顺序：根 → 子目录层级（os.walk topdown，目录名排序，时序稳定）
- 每段带相对路径标注（--- project-doc: <rel> ---，Codex project-doc 分隔同构）
- 总字节预算（默认 16KB）：装不下的文档整段丢弃并显式标注截断
- 噪音目录跳过；无工作区/无文档 → 返回空串（调用方零注入，system prompt 不变）

恒定性说明：本段内容随工作区文件变化，不属于 rules_sections 的"会话内字节
稳定"约束域——注入位置在 build_system_prompt 的规则段之后，与 soul/宪法
等静态前缀分层。
"""
from __future__ import annotations

import os

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DOC_FILENAMES = ("AGENTS.override.md", "AGENTS.md")
DEFAULT_MAX_BYTES = 16 * 1024
TRUNCATION_MARKER = "[工作区文档已按字节预算截断]"
_DOC_SEPARATOR = "\n\n--- project-doc: {rel} ---\n\n"
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".idea", ".vscode", "outputs", "data", "logs",
})


def _list_doc_files(directory: str) -> list:
    """单目录内的文档文件（override 优先；不存在返回空）。"""
    found = []
    for name in DOC_FILENAMES:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            found.append(path)
            break  # override 命中即停（同目录只取一份）
    return found


def collect_workspace_docs(workspace_path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """收集工作区 AGENTS.md 文档树，超出 max_bytes 截断。

    Returns:
        拼接后的文档文本（无文档/无工作区返回 ""，不产生空段）。
    """
    root = (workspace_path or "").strip()
    if not root or not os.path.isdir(root):
        return ""

    collected: list = []  # (rel_dir_display, content)
    used = 0
    truncated = False

    for dirpath, dirnames, _ in os.walk(root, topdown=True):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for path in _list_doc_files(dirpath):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                logger.warning("工作区文档读取失败(跳过): %s: %s", path, e)
                continue
            rel = os.path.relpath(dirpath, root).replace("\\", "/")
            rel_display = "" if rel == "." else rel
            header = _DOC_SEPARATOR.format(rel=rel_display or "root")
            piece = header + content.strip()
            size = len(piece.encode("utf-8", "replace"))
            remaining = max_bytes - used
            if size <= remaining:
                collected.append(piece)
                used += size
                continue
            # 装不下：标注截断；尚无任何已收文档时截取前缀（保证有内容可用），
            # 已有内容则整段丢弃（避免半段误导）
            truncated = True
            if not collected and remaining > 200:
                raw = piece.encode("utf-8", "replace")[: remaining - 200]
                collected.append(raw.decode("utf-8", errors="ignore"))
                used += remaining - 200
            break
        if truncated:
            break  # 预算耗尽，后续文档不再读取

    if not collected:
        return ""

    body = "".join(collected)
    if truncated:
        body += "\n\n" + TRUNCATION_MARKER
    return body
