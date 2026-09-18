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

    def test_snapshot_cost_is_negligible(self, tmp_path):
        """启动期成本：全库 index_list+index_info 实测亚毫秒级（否则会拖慢启动）。"""
        from neurova.core.db_indexes import collect_index_snapshot

        db = _make_db(tmp_path)
        snap = collect_index_snapshot(db)
        assert snap["duration_ms"] < 250, f"索引快照过慢: {snap['duration_ms']}ms"


class TestHotQueryPlans:
    def test_whitelist_registered(self):
        from neurova.core.db_indexes import HOT_QUERIES

        assert HOT_QUERIES, "热点查询白名单为空 = 计划基线无从谈起"
        for entry in HOT_QUERIES:
            assert len(entry) == 3, "每条应为 (query_id, sql, params)"

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
