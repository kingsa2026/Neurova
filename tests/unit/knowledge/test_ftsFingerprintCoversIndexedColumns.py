# -*- coding: utf-8 -*-
"""FTS 的跳过决策必须覆盖「索引行真正存着、也真正拿来过滤的那些列」（§6-460 仍开① 的定性）。

定性证据（现读代码，不是推测）：

- `repository.py:777`（`_syncEntryGovernance`）把条目的 `source` 改成**断言的 medium_ref**
  （`entry_ledger.py:120-127`：取该事实最近一条断言），**不刷新 `updated_at`**；
- `fts_index.py:225` 的检索按 `d.source = ?` 过滤，可 `fts_index.py:77` 的指纹里根本没有 `source`。

⇒ 生产序列：一次启动里条目 source 被治理层改写成新值，而时间戳与正文长度都没动 →
`_upsertDoc` 判「指纹未变」直接 return False → docs 表永久留着旧 source →
任何按来源过滤的检索（`hybrid.py:307` 把 `source` 一路透传进来）都查不到这条本该命中的条目。

指纹的形状是**手抄的第二份字段清单**：写行的 UPDATE/INSERT 列了 13 个字段，指纹只列了 5 个。
所以判据钉的是「行跟着条目走」这件事，而不是「source 这一列恰好在名单里」——后者会放过下一个新列。

格3 是反向控制（今天就该绿）：未变的条目**不许**被重写，否则每次 reconcile 全表重算，
倒排索引的增量就没了。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.fts_index import KnowledgeFtsIndex
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "user": "user"}


def _item(**over):
    """一条与仓库投影同形的条目（字段取自 repository 实际写进索引行的那些）。"""
    item = {
        "knowledge_id": "k1",
        "title": "量子指南",
        "content": "quantum computing guide",
        "category": "tech",
        "tags": ["ai"],
        "visibility": "public",
        "owner_user_id": "1",
        "tenant_id": "default",
        "shared_with": [],
        "source": "web",
        "updated_at": 1700000000.0,
        "lifecycle_status": "active",
        "valid_until": "",
    }
    item.update(over)
    return item


def _rows(idx, kid="k1"):
    return idx._conn.execute(
        "SELECT source, visibility, category, tags_json, updated_at, fingerprint"
        " FROM knowledge_fts_docs WHERE doc_id = ?", (kid,)
    ).fetchone()


class TestStaleIndexedColumnIsNotLeftBehind:
    def test_sourceOnlyChangeIsWrittenIntoTheIndexRow(self, tmp_path):
        """只改 source（时间戳、正文长度都不动）⇒ 索引行必须跟着改。"""
        idx = KnowledgeFtsIndex(str(tmp_path / "fts.db"))
        idx.reconcile({"default": [_item()]})
        assert _rows(idx)["source"] == "web"

        idx.reconcile({"default": [_item(source="feishu:doc-9")]})

        assert _rows(idx)["source"] == "feishu:doc-9", (
            "条目 source 已变而索引行仍是旧值——指纹没覆盖它，_upsertDoc 早退了"
        )

    def test_searchBySourceFilterFindsTheRewrittenEntry(self, tmp_path):
        """按来源过滤的检索必须看得见新来源（这是用户侧的实际故障形态）。"""
        idx = KnowledgeFtsIndex(str(tmp_path / "fts.db"))
        idx.reconcile({"default": [_item()]})
        assert [h["id"] for h in idx.search("quantum", ALICE, source="web")] == ["k1"]

        idx.reconcile({"default": [_item(source="feishu:doc-9")]})

        assert [h["id"] for h in idx.search("quantum", ALICE, source="feishu:doc-9")] == ["k1"], (
            "按新来源过滤查不到——docs.source 是脏列"
        )
        assert idx.search("quantum", ALICE, source="web") == [], (
            "旧来源仍命中说明索引行没跟着条目走"
        )

    def test_unchangedEntryIsNotRewritten(self, tmp_path):
        """反向控制：什么都没改时第二次 reconcile 不许重写（增量必须还是增量）。"""
        idx = KnowledgeFtsIndex(str(tmp_path / "fts.db"))
        items = [_item()]
        idx.reconcile({"default": items})
        fpBefore = _rows(idx)["fingerprint"]

        second = idx.reconcile({"default": [dict(items[0])]})

        assert second["changed"] == 0, "等值条目被重算——增量失效，大语料下每轮全表重写"
        assert _rows(idx)["fingerprint"] == fpBefore


class TestGovernanceRewriteIsReachable:
    """端到端：走真 repository + 真 KnowledgeFactStore，证这条链在生产路上。"""

    def test_assertionAddedBetweenRunsMovesTheSearchFilter(self, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge(
            "default", title="量子指南", content="quantum computing guide",
            category="tech", source="web", visibility="public", owner_user_id="1",
            knowledge_id="k-feishu",
        )
        # 第一轮物化索引行（此时 source 由治理层从断言 medium_ref 派生）
        first = [h["id"] for h in repo.ftsSearch("quantum", ALICE)]
        assert first == ["k-feishu"], "第一轮就该命中——夹具本身没跑通"
        sourceInRow = repo._ensureFts()._conn.execute(
            "SELECT source FROM knowledge_fts_docs WHERE doc_id = ?", (first[0],)
        ).fetchone()["source"]

        # 真生产 API：给这条目的事实补一条**新断言**，medium_ref 换成飞书文档
        # （`entry_ledger._mediumOf` 取最近一条断言 ⇒ 下一轮治理同步会把条目 source 改写）
        store = KnowledgeFactStore(repo._narrative_db_path)
        facts = store.activeNarrativeFacts("default")
        assert len(facts) == 1, f"夹具应只留一条叙事事实，现读 {len(facts)} 条"
        assert store.insertAssertion(
            facts[0]["fact_id"], "user", "u1", "feishu:doc-9", "同一结论的第二处陈述",
            "asrt-feishu-9")
        store.close()

        # 第二个进程：载入时治理把条目 source 改成最近断言的 medium_ref，而 updated_at 不动
        repo2 = KnowledgeRepository(str(tmp_path / "kb"))
        entry = repo2._items.get("default", [])
        moved = next(i for i in entry if str(i.get("knowledge_id")) == first[0])
        assert moved["source"] == "feishu:doc-9", (
            f"治理层没把 source 改成最近断言的 medium_ref（现读 {moved['source']!r}）"
            "——本条前提变了，缺陷形态要重新定性"
        )

        hit = [h["id"] for h in repo2.ftsSearch("quantum", ALICE, source="feishu:doc-9")]
        assert hit == [first[0]], (
            f"条目 source 已是 feishu:doc-9（原 {sourceInRow!r}），按新来源过滤却查不到——"
            "docs.source 是脏列"
        )
