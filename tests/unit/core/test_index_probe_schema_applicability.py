# -*- coding: utf-8 -*-
"""EQP 探针必须先判 schema 适用性（Issue #189）：不许拿错库去试查询再吞异常。

实测噪声：启动日志里
`EQP 失败 memories_by_agent_desc @ data\\neurova_memory.db: no such table: memories`
`EQP 失败 audit_logs_recent @ ~\\.neurova\\audit.db: no such table: audit_logs`

根因不在"某个查询写错了"，而在探针**不看库的 schema 就发查询**：
`resolve_probe_paths()` 交回两个库，`HOT_QUERIES` 里既有 memories 系也有
audit_logs 系查询，于是每一对 (库, 不属于它的查询) 都必然抛
`sqlite3.OperationalError`，再被 `except sqlite3.Error` 压成一条 DEBUG。
`table_exists()` 这个现成的判据函数**全仓零调用方**——它就是为了这件事写的，
属于"定义了没人接线"的断点（协作红线：写出来没人读也算断点）。

修根因 = 发查询前按库的真实 schema 过闸：
- 表不在 → 该条判 `available=False`，理由**点名缺哪张表**（诚实形态，不是
  一句 `no such table` 原始异常）；
- 列不在 → 同理（同一根因的另一形态，放大视角一并收）；
- 不适用的查询**一条 EQP 都不发**（省掉无意义的探针，也消掉噪声）；
- 汇总口径分开："没走索引"（真问题，要告警）与"该库没这张表"（不是问题，
  不许混进 unindexed 告警）。
"""
from __future__ import annotations

import sqlite3

import pytest

prometheus_client = pytest.importorskip("prometheus_client")


def _dbWithMemoriesOnly(tmp_path) -> str:
    db = tmp_path / "memories_only.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, agent_id TEXT, neuser_id TEXT,"
        " user_id TEXT, content TEXT, temperature REAL, created_at TEXT)"
    )
    conn.execute("CREATE INDEX idx_mem_agent ON memories(agent_id)")
    conn.commit()
    conn.close()
    return str(db)


def _dbWithAuditOnly(tmp_path) -> str:
    db = tmp_path / "audit_only.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, event_type TEXT,"
        " timestamp REAL, severity TEXT)"
    )
    conn.execute("CREATE INDEX idx_event_type ON audit_logs(event_type)")
    conn.commit()
    conn.close()
    return str(db)


def _dbWithNothing(tmp_path) -> str:
    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()
    return str(db)


def _auditOnlyMemoriesMissingColumns(tmp_path) -> str:
    """memories 表存在但缺 neuser_id/user_id —— 同一根因的另一形态。"""
    db = tmp_path / "legacy_memories.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, agent_id TEXT, content TEXT)")
    conn.execute("CREATE INDEX idx_mem_agent ON memories(agent_id)")
    conn.commit()
    conn.close()
    return str(db)


def _traceEqp(monkeypatch) -> list:
    """记录所有发给 SQLite 的语句（判"有没有真的发查询"）。"""
    seen: list = []
    realConnect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = realConnect(*args, **kwargs)
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    return seen


class TestDeclaredApplicability:
    """每条热点查询都要声明它依赖哪张表/哪些列——判据一处定义。"""

    def test_everyHotQueryDeclaresItsTable(self):
        from neurova.core.db_indexes import HOT_QUERIES, hotQueryTable

        for entry in HOT_QUERIES:
            table = hotQueryTable(entry)
            assert table, f"热点查询未声明依赖表，适用性无从判定: {entry[0]}"

    def test_declaredColumnsAreChecked(self):
        from neurova.core.db_indexes import HOT_QUERIES, hotQueryColumns

        threeTier = next(e for e in HOT_QUERIES if e[0] == "memories_three_tier")
        assert {"neuser_id", "user_id"} <= set(hotQueryColumns(threeTier)), (
            "三层隔离查询未声明依赖列——缺列的老库会照发查询再吞异常"
        )


class TestInapplicableQueriesAreNotFired:
    def test_auditQueriesNotFiredAgainstMemoriesOnlyDb(self, tmp_path, monkeypatch):
        from neurova.core.db_indexes import explain_hot_queries

        db = _dbWithMemoriesOnly(tmp_path)
        seen = _traceEqp(monkeypatch)
        explain_hot_queries(db)
        fired = [s for s in seen if "EXPLAIN QUERY PLAN" in s.upper() and "audit_logs" in s]
        assert fired == [], (
            "明知该库没有 audit_logs，仍然发了这些查询（抛错再被吞成 DEBUG 噪声）:\n  "
            + "\n  ".join(fired)
        )

    def test_memoriesQueriesNotFiredAgainstAuditOnlyDb(self, tmp_path, monkeypatch):
        from neurova.core.db_indexes import explain_hot_queries

        db = _dbWithAuditOnly(tmp_path)
        seen = _traceEqp(monkeypatch)
        explain_hot_queries(db)
        fired = [s for s in seen if "EXPLAIN QUERY PLAN" in s.upper() and "FROM memories" in s]
        assert fired == [], "明知该库没有 memories，仍然发了这些查询:\n  " + "\n  ".join(fired)

    def test_noQueryAtAllAgainstADbWithNeitherTable(self, tmp_path, monkeypatch):
        from neurova.core.db_indexes import explain_hot_queries

        db = _dbWithNothing(tmp_path)
        seen = _traceEqp(monkeypatch)
        plans = explain_hot_queries(db)
        fired = [s for s in seen if s.strip().upper().startswith("EXPLAIN QUERY PLAN")]
        assert fired == [], f"空库上仍发了 EQP: {fired}"
        assert plans, "空库也要给出每条热点查询的判定（只是都 not_applicable）"
        assert all(entry["available"] is False for entry in plans)

    def test_noColumnMismatchQueryIsFired(self, tmp_path, monkeypatch):
        from neurova.core.db_indexes import explain_hot_queries

        db = _auditOnlyMemoriesMissingColumns(tmp_path)
        seen = _traceEqp(monkeypatch)
        plans = {e["query_id"]: e for e in explain_hot_queries(db)}
        threeTier = plans["memories_three_tier"]
        assert threeTier["available"] is False
        assert "neuser_id" in threeTier["reason"] or "user_id" in threeTier["reason"]
        fired = [s for s in seen if "EXPLAIN QUERY PLAN" in s.upper() and "neuser_id" in s]
        assert fired == [], f"缺列的查询仍被发出去: {fired}"


class TestReasonIsHonest:
    def test_reasonNamesTheMissingTable(self, tmp_path):
        from neurova.core.db_indexes import explain_hot_queries

        plans = {e["query_id"]: e for e in explain_hot_queries(_dbWithMemoriesOnly(tmp_path))}
        entry = plans["audit_logs_recent"]
        assert entry["available"] is False
        assert entry["reason"], "不可用必须给出理由（诚实形态），不能只留一个布尔"
        assert "audit_logs" in entry["reason"], f"理由没点名缺哪张表: {entry['reason']}"

    def test_inapplicableIsNotLoggedAsAnEqpFailure(self, tmp_path, caplog):
        """不适用的库不该产 `EQP 失败` 告警——那是噪声，会把真失败埋掉。"""
        import logging

        from neurova.core.db_indexes import explain_hot_queries

        with caplog.at_level(logging.DEBUG, logger="neurova.core.db_indexes"):
            explain_hot_queries(_dbWithMemoriesOnly(tmp_path))
        noisy = [r for r in caplog.records if "EQP 失败" in r.message]
        assert noisy == [], (
            "不适用的查询仍以「EQP 失败」形态出现——启动日志的噪声就是从这里来的："
            + "; ".join(r.message for r in noisy)
        )

    def test_genuineEqpFailureIsStillVisible(self, tmp_path, caplog):
        """反向锁：真的是 SQL 缺陷导致的失败必须留痕（不许被一并静音）。"""
        import logging

        from neurova.core import db_indexes

        db = _dbWithMemoriesOnly(tmp_path)
        original = db_indexes.HOT_QUERIES
        db_indexes.HOT_QUERIES = list(original) + [
            ("broken_probe", "SELECT this_col_does_not_exist FROM memories", ()),
        ]
        try:
            with caplog.at_level(logging.DEBUG, logger="neurova.core.db_indexes"):
                plans = {e["query_id"]: e for e in db_indexes.explain_hot_queries(db)}
        finally:
            db_indexes.HOT_QUERIES = original
        assert "broken_probe" in plans, "临时白名单未生效，判据前提失效"
        assert plans["broken_probe"]["available"] is False
        messages = [r.getMessage() for r in caplog.records]
        assert any("EQP 失败" in m for m in messages), (
            "表存在、SQL 有缺陷的查询失败了却毫无痕迹——修适用性不能顺手静音真失败"
        )


class TestBootstrapSummarySeparatesTheTwo:
    def test_summaryDoesNotCountInapplicableAsUnindexed(self, tmp_path):
        from neurova.core.db_indexes import bootstrap_index_observability

        summary = bootstrap_index_observability([_dbWithMemoriesOnly(tmp_path)])
        assert "audit_logs_recent" not in summary["unindexed"], (
            "「该库没有这张表」被算进了「没走索引」告警——假告警就是这么来的"
        )
        assert summary.get("not_applicable"), (
            "汇总未区分「不适用」这一类读数，运维看不出跳过是因为什么"
        )


class TestSummaryKeepsGenuineFailuresOutOfNotApplicable:
    """反向锁的下一层：汇总口径不许把「真失败」记成「不适用」。

    `explain_hot_queries` 对「表/列不在」与「表在但 SQL 有缺陷」两件事都会写
    `reason`。而 `bootstrap_index_observability` 此前只按 `reason` 是否非空分流
    ⇒ 真失败被归进 `not_applicable`。这与本单要修的假告警是同一类混淆，只是
    方向相反：把「SQL 写错了」读成「这库用不上这条查询」，等于把真失败抹平。
    判据必须在**生产侧**明确（`status` 字段一处定义），消费侧按它分流。
    """

    @staticmethod
    def _withBrokenProbe(tmp_path):
        import sqlite3

        db = tmp_path / "memories_with_a_broken_probe.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, agent_id TEXT, neuser_id TEXT,"
            " user_id TEXT, content TEXT, temperature REAL, created_at TEXT)"
        )
        conn.commit()
        conn.close()
        return str(db)

    def test_brokenSqlIsNotReportedAsNotApplicable(self, tmp_path):
        from neurova.core import db_indexes

        db = self._withBrokenProbe(tmp_path)
        original = db_indexes.HOT_QUERIES
        db_indexes.HOT_QUERIES = list(original) + [
            ("broken_probe", "SELECT this_col_does_not_exist FROM memories", ()),
        ]
        try:
            summary = db_indexes.bootstrap_index_observability([db])
        finally:
            db_indexes.HOT_QUERIES = original
        assert "broken_probe" not in summary["not_applicable"], (
            "表在、SQL 有缺陷的真失败被记成了「该库不适用」——真失败被抹平了。"
        )
        assert "broken_probe" in summary["eqp_failed"], (
            "真失败必须有独立读数；混进 not_applicable 让运维看不出这是 SQL 缺陷。"
        )

    def test_brokenSqlSummaryIsWarnedAbout(self, tmp_path, caplog):
        import logging

        from neurova.core import db_indexes

        db = self._withBrokenProbe(tmp_path)
        original = db_indexes.HOT_QUERIES
        db_indexes.HOT_QUERIES = list(original) + [
            ("broken_probe", "SELECT this_col_does_not_exist FROM memories", ()),
        ]
        try:
            with caplog.at_level(logging.WARNING, logger="neurova.core.db_indexes"):
                db_indexes.bootstrap_index_observability([db])
        finally:
            db_indexes.HOT_QUERIES = original
        warned = [
            r.getMessage()
            for r in caplog.records
            if "broken_probe" in r.getMessage() and r.levelno >= logging.WARNING
        ]
        assert warned, "真失败在汇总里没有任何 WARNING 级痕迹"

    def test_statusIsTheSingleDiscriminator(self, tmp_path):
        """分流判据只允许一份：`status` 由生产侧（explain_hot_queries）给出。"""
        from neurova.core.db_indexes import explain_hot_queries

        plans = {e["query_id"]: e for e in explain_hot_queries(self._withBrokenProbe(tmp_path))}
        assert plans["memories_by_agent_desc"]["status"] == "unindexed"
        assert plans["audit_logs_recent"]["status"] == "not_applicable"

    def test_statusOfASuccessfullyIndexedQuery(self, tmp_path):
        import sqlite3

        from neurova.core.db_indexes import explain_hot_queries

        db = tmp_path / "indexed.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, agent_id TEXT, neuser_id TEXT,"
            " user_id TEXT, content TEXT, temperature REAL, created_at TEXT)"
        )
        conn.execute(
            "CREATE INDEX idx_agent_created ON memories(agent_id, created_at)"
        )
        conn.commit()
        conn.close()
        plans = {e["query_id"]: e for e in explain_hot_queries(str(db))}
        assert plans["memories_by_agent_desc"]["status"] == "indexed"


class TestInapplicableReadingIsConsumed:
    """`not_applicable` 必须有生产侧读者（协作红线：写出无人读的字段即断点）。

    上一轮只把它累加进 summary，而 `bootstrap_index_observability` 的返回值在
    装配点被丢弃（`await asyncio.to_thread(bootstrap_index_observability)` 不接
    返回值）⇒ 该字段在生产里**没有任何读者**。运维因此无法回答"这条审计查询
    为什么没参与基线"——正是本单要消灭的那类断链。
    """

    def test_skippedQueriesAreReportedWithTheirReason(self, tmp_path, caplog):
        import logging

        from neurova.core.db_indexes import bootstrap_index_observability

        with caplog.at_level(logging.INFO, logger="neurova.core.db_indexes"):
            bootstrap_index_observability([_dbWithMemoriesOnly(tmp_path)])
        messages = [r.getMessage() for r in caplog.records]
        skipped = [m for m in messages if "audit_logs_recent" in m and "表" in m]
        assert skipped, (
            "不适用的查询在生产侧没有任何读数（summary 的返回值被装配点丢弃）——"
            "运维看不出跳过是因为'这库没有这张表'，字段成了只写不读的断点。\n"
            "实际日志行：\n  " + "\n  ".join(messages)
        )
