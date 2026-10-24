"""旧知识条目按新流水线重解析并回填（默认 dry-run）。

用法：
    .venv/Scripts/python.exe scripts/knowledge_reparse_backfill.py --limit 100
    .venv/Scripts/python.exe scripts/knowledge_reparse_backfill.py --agent default --apply

只处理能按 `source_path` 找到原文件的条目；缺文件/解析失败/正文未变的条目分别计数，
不静默跳过。`--apply` 时通过 `replaceDocumentParsing` 写回，旧值进 revision 账。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neurova.knowledge.document_pipeline import DocumentParseError, parse_document
from neurova.knowledge.repository import get_knowledge_repository


def _candidates(agent: str, limit: int) -> List[Dict[str, Any]]:
    repo = get_knowledge_repository()
    agents = [agent] if agent else repo.listAgents()
    rows: List[Dict[str, Any]] = []
    for name in agents:
        for item in repo.list_knowledge(name, limit=limit):
            rows.append({"agent": name, "item": item})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--source-root", default="",
                        help="source_path 为相对名时的根目录")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    repo = get_knowledge_repository()
    stats = {
        "candidates": 0, "missing_source": 0, "parse_failed": 0,
        "unchanged": 0, "changed": 0, "applied": 0,
    }
    rows = []
    for row in _candidates(args.agent, args.limit):
        agent = str(row["agent"])
        item = row["item"]
        stats["candidates"] += 1
        source = str(item.get("source_path") or "").strip()
        path = Path(source) if source else None
        if path is not None and not path.is_file() and args.source_root:
            candidate = Path(args.source_root) / source
            if candidate.is_file():
                path = candidate
        if path is None or not path.is_file():
            stats["missing_source"] += 1
            rows.append({"knowledge_id": item.get("knowledge_id"), "status": "missing_source"})
            continue
        try:
            parsed = parse_document(
                path.read_bytes(), path.name, source_path=str(path),
                source_type=str(item.get("source_type") or ""), ocr_mode="auto",
            )
        except DocumentParseError as exc:
            stats["parse_failed"] += 1
            rows.append({"knowledge_id": item.get("knowledge_id"),
                         "status": "parse_failed", "reason": exc.reason})
            continue
        except Exception as exc:  # noqa: BLE001 - 单条失败留名
            stats["parse_failed"] += 1
            rows.append({"knowledge_id": item.get("knowledge_id"),
                         "status": "parse_failed", "reason": type(exc).__name__})
            continue
        if str(parsed.content) == str(item.get("content") or ""):
            stats["unchanged"] += 1
            rows.append({"knowledge_id": item.get("knowledge_id"), "status": "unchanged"})
            continue
        stats["changed"] += 1
        applied = False
        if args.apply:
            applied = repo.replaceDocumentParsing(
                agent, str(item.get("knowledge_id") or ""), parsed,
            )
            if applied:
                stats["applied"] += 1
        rows.append({
            "knowledge_id": item.get("knowledge_id"),
            "status": "applied" if applied else ("would_change" if not args.apply else "apply_failed"),
        })
    print(json.dumps({"apply": bool(args.apply), "stats": stats, "rows": rows},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
