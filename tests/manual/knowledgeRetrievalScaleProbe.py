# -*- coding: utf-8 -*-
"""知识检索预筛规模基准（合成语料，不碰 data/，手工运行）。

跑法：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/knowledgeRetrievalScaleProbe.py

输出 rows / filtered / hits / ms；用于观察 category+tags 预筛前后候选集与耗时。
"""
from __future__ import annotations

import time

from neurova.knowledge.hybrid import hybrid_search_knowledge

USER = {"user_id": "1", "role": "admin"}


class ScaleRepo:
    def __init__(self, n: int):
        self.items = []
        for i in range(n):
            cat = "cat-a" if i % 2 == 0 else "cat-b"
            self.items.append({
                "knowledge_id": "k%06d" % i,
                "title": "doc-%06d" % i,
                "content": "shared alpha token%02d %s" % (i % 20, cat),
                "category": cat,
                "tags": ["x"] if i % 2 == 0 else ["y"],
                "source": "scale",
                "updated_at": float(i + 1),
                "visibility": "public",
                "owner_user_id": "1",
            })

    def _filter(self, category=None, tags=None, source=None, updated_after=None):
        out = []
        for item in self.items:
            if category and item["category"] != category:
                continue
            if tags and not all(t in item["tags"] for t in tags):
                continue
            if source and item["source"] != source:
                continue
            if updated_after is not None and item["updated_at"] < updated_after:
                continue
            out.append(item)
        return out

    def visible_items(self, user, scope="all", category=None, agent_id=None,
                      tags=None, source=None, updated_after=None):
        return [dict(i) for i in self._filter(category, tags, source, updated_after)]

    def search_visible_items(self, user, query, scope="all", category=None,
                             agent_id=None, limit=20, tags=None, source=None,
                             updated_after=None):
        return [
            dict(i, score=1.0)
            for i in self._filter(category, tags, source, updated_after)[:limit]
        ]


def main():
    print("rows\tfiltered\thits\tms")
    for n in (1_000, 10_000, 100_000):
        repo = ScaleRepo(n)
        started = time.perf_counter()
        hits = hybrid_search_knowledge(
            repo, USER, "shared alpha", limit=5,
            category="cat-a", tags=["x"], source="scale", updated_after=0,
            vector_index=None,
        )
        elapsed = (time.perf_counter() - started) * 1000
        filtered = len(repo.visible_items(
            USER, category="cat-a", tags=["x"], source="scale", updated_after=0
        ))
        print("%d\t%d\t%d\t%.1f" % (n, filtered, len(hits), elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
