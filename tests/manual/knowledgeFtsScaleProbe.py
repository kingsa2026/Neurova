# -*- coding: utf-8 -*-
"""FTS5 持久倒排规模基准（合成语料，不碰 data/，手工运行）。

跑法：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/knowledgeFtsScaleProbe.py
"""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from neurova.knowledge.fts_index import KnowledgeFtsIndex

USER = {"user_id": "1", "role": "admin"}


def _items(n: int):
    out = []
    for i in range(n):
        out.append({
            "knowledge_id": "k%06d" % i,
            "title": "doc-%06d" % i,
            "content": "shared alpha token%02d %s" % (i % 20, "cat-a" if i % 2 == 0 else "cat-b"),
            "category": "cat-a" if i % 2 == 0 else "cat-b",
            "tags": ["x"] if i % 2 == 0 else ["y"],
            "source": "scale",
            "visibility": "public",
            "owner_user_id": "1",
            "updated_at": float(i + 1),
            "lifecycle_status": "active",
            "valid_until": None,
        })
    return out


def main() -> int:
    print("rows\tbuild_ms\tdocs\tsearch_ms\thits")
    for n in (1_000, 10_000, 100_000, 1_000_000):
        root = Path(tempfile.mkdtemp(prefix="neurovaFtsScale-"))
        idx = KnowledgeFtsIndex(str(root / "fts.db"))
        started = time.perf_counter()
        idx.reconcile({"default": _items(n)})
        build_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        hits = idx.search(
            "shared alpha", USER, scope="public", category="cat-a", tags=["x"],
            limit=5,
        )
        search_ms = (time.perf_counter() - started) * 1000
        health = idx.health()
        print("%d\t%.1f\t%d\t%.1f\t%d" % (n, build_ms, health["docs"], search_ms, len(hits)))
        idx.close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
