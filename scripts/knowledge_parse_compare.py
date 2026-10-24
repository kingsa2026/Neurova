"""新旧文档解析影子对比：结构化流水线 vs 旧单段抽取。

用法：
    .venv/Scripts/python.exe scripts/knowledge_parse_compare.py --paths docs/README.md 文件目录

只读输入；输出每条文件的字符数/页数/块数/标题数/失败原因，供迁移前判断
切换是否损失页码/标题/召回面。不写知识库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neurova.knowledge.document_pipeline import DocumentParseError, parse_document


def _collect(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            print("SKIP 不存在: %s" % raw, file=sys.stderr)
    return files


def _one(path: Path, engine: str) -> Dict[str, Any]:
    try:
        parsed = parse_document(
            path.read_bytes(), path.name, source_path=str(path),
            engine_mode=engine,
        )
        return {
            "engine": engine,
            "ok": True,
            "chars": len(parsed.content),
            "pages": len(parsed.pages),
            "chunks": len(parsed.chunks),
            "headings": sum(
                1 for chunk in parsed.chunks
                if (chunk.get("heading_path") or [])
            ),
            "reason": "",
        }
    except DocumentParseError as exc:
        return {"engine": engine, "ok": False, "reason": exc.reason}
    except Exception as exc:  # noqa: BLE001 - 对比工具按失败记录
        return {"engine": engine, "ok": False, "reason": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", nargs="+", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    rows = []
    for path in _collect(args.paths):
        structured = _one(path, "structured")
        legacy = _one(path, "legacy")
        rows.append({
            "file": str(path),
            "structured": structured,
            "legacy": legacy,
            "chars_delta": (
                structured.get("chars", 0) - legacy.get("chars", 0)
                if structured.get("ok") and legacy.get("ok") else None
            ),
        })
    summary = {
        "files": len(rows),
        "structured_ok": sum(1 for row in rows if row["structured"]["ok"]),
        "legacy_ok": sum(1 for row in rows if row["legacy"]["ok"]),
        "both_ok": sum(
            1 for row in rows if row["structured"]["ok"] and row["legacy"]["ok"]
        ),
        "structured_only": [
            row["file"] for row in rows
            if row["structured"]["ok"] and not row["legacy"]["ok"]
        ],
        "legacy_only": [
            row["file"] for row in rows
            if row["legacy"]["ok"] and not row["structured"]["ok"]
        ],
    }
    report = {"summary": summary, "rows": rows}
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
