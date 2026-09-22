# -*- coding: utf-8 -*-
"""B4-004 读侧预筛与转义（判据 A3/A4）。

红灯依据（改前实证，基线脚本 §4/§4b/§8）：

- `evicted_fts` 用 `unicode61` 分词器，**对中文等于没有索引**：查询 `上下文压缩` /
  `窗口预算` / `上下文` 命中 **0**（LIKE 真值分别为 4934 / 4921 / 16526）；
- LIKE 兜底直接拼 `f"%{query}%"`，`%` 与 `_` 是 LIKE 通配符：库内 3 行时
  查询 `%` 命中 **3 行**、`_` 命中 **3 行**（真值均为 0）；
- 查询长度 <3 时强行 MATCH 会得到**假阴性**（trigram 索引不到 2 字符查询）——
  漏召回比慢更糟。

契约（修复后）：判据**只有一份**（`ledger_query.buildMatchQuery` /
`ledger_query.likePattern`），读侧按长度分流、LIKE 转义 `\\` `%` `_`，
候选集超上限时降级为"最近 N 条候选内过滤"，不得整库拉回。

前像纪律：本文件不改写 004 之前的实现，只在**当前实现**上跑判据。
"""

import sqlite3

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB

# 004 的分流阈值：trigram 索引不到 <3 字符的查询（规格 §7 已知的坑第 1 条）
MATCH_MIN_LENGTH = 3

# 候选集上限初值（规格 U2 定案 2000，实施期以真实语料校准并回填读数）
CANDIDATE_LIMIT = 2000


def _seed(ledger, contents):
    ledger.beginBatch()
    for index, text in enumerate(contents):
        ledger.record(content=text, turn_id=f"t{index}", session_id="s1")
    ledger.commitBatch()


def _likeTruth(ledger, query):
    """LIKE 真值（带 ESCAPE 的转义形态）——判据的对照面，不是被测实现。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = ledger._requireConn().execute(
        "SELECT content FROM evicted_chunks"
        " WHERE user_id = ? AND agent_id = ? AND content LIKE ? ESCAPE '\\'",
        (ledger.user_id, ledger.agent_id, f"%{escaped}%"),
    ).fetchall()
    return sorted(r["content"] for r in rows)


CORPUS = [
    "上下文压缩窗口预算的实测数据：折叠阈值为 36%",
    "上下文池归档与召回路径的隔离闸口讨论",
    "窗口预算与折叠阈值：中文查询在 unicode61 下命中为零",
    "The context window budget decides whether folding triggers.",
    "JSON 工具结果：{\"tool\": \"file_read\", \"bytes\": 4096}",
    "带下划线 a_b 与百分号 100% 的库内文本",
    "群聊归档：量子项目代号 ZEPHYR-9（房间 project_roomB）",
]


class TestChunkLookupIsPrecise:
    """A3/A4：中文查询的 MATCH 命中集合 == LIKE 真值（逐条比对，不只比条数）。"""

    def _hits(self, ledger, query):
        return sorted(row["content"] for row in ledger.search(query, limit=50))

    def test_chineseQueryMatchesLikeTruth(self, tmp_path):
        """CJK 长查询的结果集合 == LIKE 真值。

        本片保证的是**查询侧**（长度分流 + 转义 + 候选集上限）不改动命中语义；
        索引侧的 CJK 能力（换 trigram 分词器）归工单 006，
        其"MATCH 命中集合 == LIKE 真值"的索引面判据在 006 的用例里。
        """
        ledger = EvictionLedgerDB(db_path=tmp_path / "cjk.db", user_id="u1", agent_id="a1")
        _seed(ledger, CORPUS)
        try:
            for query in ("上下文压缩", "窗口预算", "上下文池"):
                assert self._hits(ledger, query) == _likeTruth(ledger, query), (
                    f"查询 {query!r} 的命中集合与 LIKE 真值不等（预筛漏召回）"
                )
        finally:
            ledger.close()

    def test_englishQueryDoesNotRegress(self, tmp_path):
        ledger = EvictionLedgerDB(db_path=tmp_path / "en.db", user_id="u1", agent_id="a1")
        _seed(ledger, CORPUS)
        try:
            assert self._hits(ledger, "context window") == _likeTruth(ledger, "context window")
        finally:
            ledger.close()

    def test_shortQueryNeverReachesMatch(self, tmp_path):
        """<3 字符查询不得发出 MATCH 语句。

        trigram 索引不到 2 字符查询，强行 MATCH 会得到**假阴性**（漏召回比慢更糟）。
        这里断言的是**派发决定**（步骤集合的性质），不是耗时：整段查询期间不得出现
        `MATCH` 语句——即便当前分词器下 MATCH 恰好返回空、兜底 LIKE 也刚好答对，
        派发错了就只是在靠兜底掩盖（换成 trigram 索引立刻变成漏召回）。
        """
        statements = []
        ledger = EvictionLedgerDB(db_path=tmp_path / "short.db", user_id="u1", agent_id="a1")
        ledger._requireConn().set_trace_callback(statements.append)
        _seed(ledger, CORPUS)
        try:
            for query in ("归档", "窗口", "a_"):
                assert len(query) < MATCH_MIN_LENGTH
                statements.clear()
                assert self._hits(ledger, query) == _likeTruth(ledger, query), (
                    f"短查询 {query!r} 漏召回（<3 字符未走 LIKE 分支）"
                )
                assert not any("MATCH" in stmt.upper() for stmt in statements), (
                    f"短查询 {query!r} 走了 MATCH（trigram 下即假阴性）：{statements}"
                )
        finally:
            ledger.close()

    def test_likeMetacharactersDoNotBecomeWildcards(self, tmp_path):
        """A4：`%` / `_` 不得越权匹配（不加 ESCAPE 时实测命中全库）。"""
        ledger = EvictionLedgerDB(db_path=tmp_path / "meta.db", user_id="u1", agent_id="a1")
        _seed(ledger, CORPUS)
        try:
            for query in ("%", "_", "%_%"):
                hits = self._hits(ledger, query)
                assert hits == _likeTruth(ledger, query), (
                    f"查询 {query!r} 把用户输入当成了 LIKE 通配模式：命中 {hits}"
                )
            assert self._hits(ledger, "%") == [
                row for row in CORPUS if "%" in row
            ], "`%` 命中了不含 `%` 的文本（通配越权：未加 ESCAPE 时实测命中全库）"
            assert len(self._hits(ledger, "%")) < len(CORPUS), (
                "`%` 命中条数等于全库（通配越权）"
            )
        finally:
            ledger.close()


class TestCandidateCap:
    """超上限不得整库拉回：降级为"最近 N 条候选 + 候选内子串过滤"。"""

    def _seedMany(self, tmp_path, total=300):
        ledger = EvictionLedgerDB(db_path=tmp_path / "many.db", user_id="u1", agent_id="a1")
        _seed(ledger, [f"第{i}条：上下文压缩与窗口预算的讨论" for i in range(total)])
        return ledger

    def test_overCapQueryDegradesToBoundedCandidateSet(self, tmp_path, monkeypatch):
        """超上限时必须切到"最近 N 条 + 候选内子串过滤"——不得整库拉回。

        结构性断言（与机器速度无关）：候选集查询必须带 `LIMIT` 且其上限等于
        `CANDIDATE_LIMIT`（+1 用于判定"是否超限"）。改前该查询无上限，
        高命中查询会把整库行拉回内存再逐条过滤。
        """
        import neurova.context.eviction_ledger_db as ledgerModule

        statements = []
        monkeypatch.setattr(ledgerModule, "CANDIDATE_LIMIT", 5, raising=False)
        ledger = self._seedMany(tmp_path)
        ledger._requireConn().set_trace_callback(statements.append)
        try:
            hits = ledger.search("上下文", limit=50)
            assert hits, "降级路径给出了空集（把高命中查询整个丢掉）"
            assert all("上下文" in row["content"] for row in hits), (
                "降级路径返回了不满足子串约束的行"
            )
            bounded = [s for s in statements if "LIMIT" in s.upper() and "6" in s]
            assert bounded, (
                "候选集没有任何上限（高命中查询整库拉回）："
                f"语句={statements}"
            )
        finally:
            ledger.close()

    def test_candidateCapIsDeclared(self):
        import neurova.context.eviction_ledger_db as ledgerModule

        assert getattr(ledgerModule, "CANDIDATE_LIMIT", None) == CANDIDATE_LIMIT, (
            "候选集上限没有单一事实源（规格 U2 要求必须有上限且初值 2000）"
        )


class TestSingleSourceOfJudgement:
    """判据只此一份：查询侧不另写第二份 LIKE 转义 / 长度分流规则。

    单源落点在 `neurova.core.sql_like`（转义与短语规则），台账侧只调用它——
    台账模块自己 `f"%{query}%"` 就是第二份判据：转义规则改一处漏一处等于没改。
    """

    def test_sharedEscapeRule(self):
        from neurova.core import sql_like

        assert sql_like.likePattern("50%") == "%50\\%%"
        assert sql_like.likePattern("a_b") == "%a\\_b%"
        assert sql_like.likePattern("c:\\x") == "%c:\\\\x%"
        assert sql_like.matchQuery("上下文") == '"上下文"'
        assert sql_like.matchQuery("   ") is None, "空查询不该交给 MATCH"
        assert sql_like.shouldMatch("ab") is False
        assert sql_like.shouldMatch("abc") is True

    def test_predicateClauseCarriesEscape(self):
        """`ESCAPE` 子句也单源：`ESCAPE` 逐表达式生效，不能写在 `WHERE` 末尾。"""
        from neurova.core import sql_like

        assert sql_like.likePredicate("content") == "content LIKE ? ESCAPE '\\'"
        assert sql_like.likePredicate("content", negate=True) == (
            "content NOT LIKE ? ESCAPE '\\'"
        )
        multi = sql_like.likePredicate(("name", "description"))
        assert multi.count("ESCAPE") == 2, "多列谓词的每一列都要贴 ESCAPE"
        assert " OR " in multi

        conn = __import__("sqlite3").connect(":memory:")
        try:
            conn.execute("CREATE TABLE t(content TEXT)")
            conn.execute("INSERT INTO t VALUES ('100% done'), ('plain')")
            hits = conn.execute(
                "SELECT content FROM t WHERE " + sql_like.likePredicate("content"),
                (sql_like.likePattern("%"),),
            ).fetchall()
            assert [row[0] for row in hits] == ["100% done"], "谓词子句的 ESCAPE 未生效"
        finally:
            conn.close()

    def test_searchUsesSharedEscapeRule(self, tmp_path, monkeypatch):
        """`search` 必须经共享转义判据——拒绝第二份就地拼装。"""
        from neurova.core import sql_like

        calls = []
        realLike = sql_like.likePattern
        monkeypatch.setattr(
            sql_like, "likePattern", lambda q: (calls.append(q), realLike(q))[1]
        )
        ledger = EvictionLedgerDB(db_path=tmp_path / "shared.db", user_id="u1", agent_id="a1")
        _seed(ledger, CORPUS)
        try:
            ledger.search("a%")
            assert calls, "search 未走共享 LIKE 转义判据（存在第二份就地拼装）"
        finally:
            ledger.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
