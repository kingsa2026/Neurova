# -*- coding: utf-8 -*-
"""P0-3 索引可观测（Issue #57）：索引命中从"不可测"变可测，且不持有第二套清单。

原状：
- `core/db_indexes.py` 是"12 条静态 DDL + add_indexes()"，而 `add_indexes()`
  全仓零调用方；
- 真实索引靠各模块内联 DDL 维护（全仓 155 处 CREATE INDEX），与那 12 条不构成
  单一事实源；
- 无任何 `index_list` 聚合 / `EXPLAIN QUERY PLAN` → "索引命中"物理上不可测，
  旧审计 §7 的查询计划基线至今缺失。

处置：`db_indexes.py` 改为**采集器**（不再持有索引清单），启动期采集
`index_list`/`index_info` 聚合 + 热点 EQP 白名单，结果写入 core/metrics.py。
"""
import ast
import io
import sqlite3
from pathlib import Path

import pytest

prometheus_client = pytest.importorskip("prometheus_client")
from prometheus_client import REGISTRY  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_INDEXES = PROJECT_ROOT / "neurova" / "core" / "db_indexes.py"


def _make_db(tmp_path, with_index=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "obs.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, agent_id TEXT, neuser_id TEXT,"
        " user_id TEXT, content TEXT, temperature REAL, created_at TEXT)"
    )
    if with_index:
        conn.execute("CREATE INDEX idx_mem_agent ON memories(agent_id)")
        conn.execute("CREATE INDEX idx_mem_temperature ON memories(temperature)")
    conn.commit()
    conn.close()
    return str(db)


def _fill_rows(db_path, rows: int) -> None:
    """往 memories 灌数据行——只为验证快照成本与行数无关。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executemany(
            "INSERT INTO memories (id, agent_id, content, temperature) VALUES (?, ?, ?, ?)",
            [(f"m{i}", "a1", "c", 0.5) for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


class TestCollectorNotSecondSourceOfTruth:
    """采集器不得再持有第二套索引清单。"""

    def test_no_static_index_list_constant(self):
        src = io.open(DB_INDEXES, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "INDEXES_TO_ADD":
                        raise AssertionError(
                            "INDEXES_TO_ADD 复活：静态清单与各模块内联 DDL 是两套事实源"
                        )
        assert "def collect_index_snapshot" in src

    def test_no_add_indexes_writer(self):
        """不得再有"写入索引"的能力（采集器只读）。

        按 AST 判"是否存在 CREATE INDEX 语句"而不是布尔包含：模块 docstring
        里叙述历史（"全仓 155 处 CREATE INDEX"）属说明，不是能力。
        """
        src = io.open(DB_INDEXES, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 只看作为 SQL 传入 execute 的字面量
                pass
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("execute", "executescript"):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            assert "CREATE INDEX" not in arg.value.upper(), (
                                "采集器不得建索引（那是各模块 schema 的职责）"
                            )
        assert "def add_indexes" not in src, "add_indexes 写路径复活（零调用方的死代码）"
        # PRAGMA / 只读 URI 仍是允许的
        assert "mode=ro" in src


class TestIndexSnapshot:
    def test_snapshot_reports_real_indexes(self, tmp_path):
        from neurova.core.db_indexes import collect_index_snapshot

        db = _make_db(tmp_path)
        snap = collect_index_snapshot(db)
        assert snap["available"] is True
        # PK 列的 sqlite_autoindex 也算真实索引（它就是 id 唯一性的实现），
        # 故断言"含自建两条、且列覆盖正确"而非总数恒 2
        names = {e["name"] for e in snap["tables"]["memories"]}
        assert {"idx_mem_agent", "idx_mem_temperature"} <= names
        cols = {c for e in snap["tables"]["memories"] for c in e["columns"]}
        assert {"agent_id", "temperature", "id"} <= cols

    def test_snapshot_missing_db_is_available_false(self, tmp_path):
        """库不存在按"无数据"处理，不抛错（观测面不得把启动拖下水）。"""
        from neurova.core.db_indexes import collect_index_snapshot

        snap = collect_index_snapshot(str(tmp_path / "nope.db"))
        assert snap["available"] is False
        assert snap["index_count"] == 0

    def test_snapshot_cost_does_not_scale_with_row_count(self, tmp_path, monkeypatch):
        """启动期成本只随**结构**（表/索引条数）走，不随**数据量**走。

        原判据是墙钟上界（``duration_ms < 250``）。它测不出"成本是否与数据量
        相关"（那才是"拖慢启动"的成因），却能在 CI 共享机的负载下把正确实现
        判红——误判方向还会诱导"放宽阈值换绿"。改为结构不变量：快照只发
        ``sqlite_master`` 一次 + 每表 ``index_list`` + 每索引 ``index_info``，
        与行数无关；行数放大若干倍后语句序列必须逐条相同。
        """
        from neurova.core.db_indexes import collect_index_snapshot

        def _statements(db_path):
            seen = []
            real_connect = sqlite3.connect

            def traced(*a, **k):
                conn = real_connect(*a, **k)
                conn.set_trace_callback(seen.append)
                return conn

            monkeypatch.setattr(sqlite3, "connect", traced)
            try:
                return collect_index_snapshot(db_path), seen
            finally:
                monkeypatch.setattr(sqlite3, "connect", real_connect)

        small = _make_db(tmp_path / "small")
        big = _make_db(tmp_path / "big")
        _fill_rows(big, 20000)

        snap_small, stmts_small = _statements(small)
        snap_big, stmts_big = _statements(big)

        def _normalise(stmts):
            """语句骨架：把表名/索引名抹平，只留"语句种类"序列。"""
            out = []
            for s in stmts:
                kind = s.split("(", 1)[0].strip().split("'", 1)[0].strip()
                out.append(kind)
            return out

        assert snap_small["index_count"] == snap_big["index_count"], (
            "两份库的索引条数应相同（夹具只差数据量）"
        )
        assert _normalise(stmts_big) == _normalise(stmts_small), (
            "快照发出的语句序列随数据量变化 ⇒ 启动成本与数据量挂钩：\n"
            f"  small={stmts_small}\n  big={stmts_big}"
        )

        # 更强的判据：快照只允许读**元数据**（sqlite_master 清单 + PRAGMA），
        # 一条都不许碰表数据。否则"某个查询顺手全表扫一遍"这类回归——语句条数
        # 不变、耗时却随行数线性增长——就从上面那条序列比较下溜过去。
        offenders = [
            s for s in stmts_big
            if "sqlite_master" not in s and not s.strip().upper().startswith("PRAGMA")
        ]
        assert offenders == [], (
            "快照读了元数据之外的东西（启动成本会随数据量增长，且无法解释）:\n  "
            + "\n  ".join(offenders)
        )

        # 成本结构：1 次表清单 + 每表 1 次 index_list + 每索引 1 次 index_info。
        # 逐条断言（而非只看总数），否则"多扫了一张表"这种增量会被总数掩盖。
        assert len([s for s in stmts_big if "sqlite_master" in s]) == 1, (
            f"表清单应发 1 次：{stmts_big}"
        )
        assert len([s for s in stmts_big if "index_list" in s]) == 1, (
            f"index_list 应每表 1 次（本夹具仅 memories 一张表）：{stmts_big}"
        )
        assert len([s for s in stmts_big if "index_info" in s]) == snap_big["index_count"], (
            "index_info 应每索引 1 次（与 index_count 同口径）："
            f"{snap_big['index_count']} vs {stmts_big}"
        )


class TestHotQueryPlans:
    def test_whitelist_registered(self):
        from neurova.core.db_indexes import HOT_QUERIES

        assert HOT_QUERIES, "热点查询白名单为空 = 计划基线无从谈起"
        for entry in HOT_QUERIES:
            # Issue #189 起形状为 (query_id, sql, params, 依赖表, 依赖列)：
            # 探针库既有记忆库也有审计库，"不发不属于该库的查询"必须先知道依赖。
            assert len(entry) == 5, "每条应为 (query_id, sql, params, table, columns)"
            assert entry[3], f"未声明依赖表，适用性无从判定: {entry[0]}"

    def test_detects_index_usage(self, tmp_path):
        from neurova.core.db_indexes import explain_hot_queries

        db = _make_db(tmp_path)
        plans = {e["query_id"]: e for e in explain_hot_queries(db)}
        assert plans["memories_by_agent_desc"]["indexed"] is True, "按 agent_id 查询未走索引"
        assert plans["memories_by_temperature"]["indexed"] is True, "温度 Top-N 未走索引"

    def test_detects_missing_index(self, tmp_path):
        """无索引时必须判为"未走索引"（否则告警永远不响）。"""
        from neurova.core.db_indexes import explain_hot_queries

        db = _make_db(tmp_path, with_index=False)
        plans = {e["query_id"]: e for e in explain_hot_queries(db)}
        assert plans["memories_by_agent_desc"]["available"] is True
        assert plans["memories_by_agent_desc"]["indexed"] is False

    def test_missing_table_is_unavailable_not_unindexed(self, tmp_path):
        """表不存在（库无该 schema）→ available=False，不得记成"没走索引"。

        混在一起会让告警常年误报：一个不含 audit_logs 的库会被当成"审计查询全表扫描"。
        """
        from neurova.core.db_indexes import explain_hot_queries

        db = _make_db(tmp_path)
        plans = {e["query_id"]: e for e in explain_hot_queries(db)}
        entry = plans["audit_logs_recent"]
        assert entry["available"] is False
        assert entry["indexed"] is False


class TestMetricsWiring:
    def test_bootstrap_writes_gauges(self, tmp_path):
        from neurova.core.db_indexes import bootstrap_index_observability

        db = _make_db(tmp_path)
        summary = bootstrap_index_observability([db])

        assert summary["dbs"] == 1
        assert summary["indexes"] >= 2
        assert summary["hot_queries"] > 0
        assert (
            REGISTRY.get_sample_value("neurova_db_indexes_total", {"db": db})
            == float(summary["indexes"])
        )
        assert (
            REGISTRY.get_sample_value(
                "neurova_hot_query_indexed", {"db": db, "query_id": "memories_by_agent_desc"}
            )
            == 1.0
        )

    def test_bootstrap_fail_open(self, tmp_path):
        """坏路径不得抛错（可观测不得成为启动依赖）。"""
        from neurova.core.db_indexes import bootstrap_index_observability

        summary = bootstrap_index_observability([str(tmp_path / "missing.db")])
        assert summary["dbs"] == 0

    def test_startup_hook_present(self):
        """启动装配必须真的接上，否则采集器等于死代码。"""
        src = io.open(
            PROJECT_ROOT / "neurova" / "api" / "app.py", encoding="utf-8"
        ).read()
        assert "bootstrap_index_observability" in src, "启动未装配索引采集"

    def test_metrics_declares_index_gauges(self):
        from neurova.core.metrics import get_metrics

        m = get_metrics()
        assert hasattr(m, "db_indexes_total")
        assert hasattr(m, "hot_query_indexed")

    def test_unavailable_plan_does_not_write_gauge(self):
        """available=False 的条目不得落 gauge（把"测不出"写进指标 = 假数据）。"""
        from prometheus_client import REGISTRY as R

        from neurova.core.metrics import get_metrics

        before = R.get_sample_value(
            "neurova_hot_query_indexed", {"db": "/nonexistent.db", "query_id": "q"}
        )
        get_metrics().record_hot_query_plan(
            "/nonexistent.db", "q", indexed=False, duration_ms=1.0, available=False
        )
        after = R.get_sample_value(
            "neurova_hot_query_indexed", {"db": "/nonexistent.db", "query_id": "q"}
        )
        assert before == after
