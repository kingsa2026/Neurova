# -*- coding: utf-8 -*-
"""P0-1/P0-2 观测底座收口测试（Issue #57）

锁定两件事：

P0-1  /metrics 单一事实源：api/app.py 的 _register_metrics_endpoint 不得再
      手工拼接 # HELP/# TYPE 文本（历史残留 46 行死代码，白跑字符串拼接且
      制造"两套事实源"错觉，维护者易改错地方）。

P0-2  连接池 / 共享线程池可测：
      - 归还连接必须回滚未提交事务（否则脏事务被下个借用者继承，WAL 下
        表现为长事务持锁）；
      - 连接创建/销毁有 counter，池 idle/active/total 与线程池线程数、
        队列深度、max_workers 有 gauge（此前全为零指标，基线不可测）。
"""
import ast
import sqlite3
from pathlib import Path

import pytest

prometheus_client = pytest.importorskip("prometheus_client")
from prometheus_client import REGISTRY  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PY = PROJECT_ROOT / "neurova" / "api" / "app.py"


def _metrics_endpoint_source() -> str:
    """取 _register_metrics_endpoint 的**代码体**（剔除 docstring）。

    docstring 里会提到"手工拼接 # HELP/# TYPE"这类历史说明，不能算作
    手拼文本本身，故按 AST 定位 docstring 行号后剔除。
    """
    src = APP_PY.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_register_metrics_endpoint":
            body = lines[node.lineno - 1 : node.end_lineno]
            doc = node.body[0]
            if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str):
                start = doc.lineno - node.lineno
                body = body[:start] + body[doc.end_lineno - node.lineno + 1 :]
            return "\n".join(body)
    raise AssertionError("api/app.py 未找到 _register_metrics_endpoint")


class TestMetricsSingleSource:
    """P0-1：/metrics 只有一条数据通路。"""

    def test_no_handwritten_prometheus_text(self):
        src = _metrics_endpoint_source()
        assert "metrics = []" not in src, "手拼指标列表死代码复活"
        assert "metrics.append(" not in src, "手拼指标 append 死代码复活"
        assert "# HELP " not in src, "手拼 # HELP 文本复活（双事实源）"
        assert "# TYPE " not in src, "手拼 # TYPE 文本复活（双事实源）"

    def test_endpoint_returns_registry_output_only(self):
        src = _metrics_endpoint_source()
        # 唯一输出通路：generate_metrics_text()
        assert "generate_metrics_text()" in src
        assert src.count("PlainTextResponse(") == 1

    def test_endpoint_refreshes_pool_gauges(self):
        src = _metrics_endpoint_source()
        assert "observe_pools()" in src, "/metrics 未刷新池 gauge"


class TestConnectionPoolRollback:
    """P0-2：归还连接清理残留事务。"""

    def _make_pool(self, tmp_path):
        from neurova.core.connection_pool import SQLiteConnectionPool

        db = tmp_path / "pool_rollback.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t(a INTEGER)")
        conn.commit()
        conn.close()
        return SQLiteConnectionPool(str(db), max_connections=2)

    def test_dirty_transaction_not_inherited(self, tmp_path):
        pool = self._make_pool(tmp_path)
        conn = pool.get_connection()
        conn.execute("INSERT INTO t VALUES (1)")
        assert conn.in_transaction is True, "前置不成立：写入后应处于事务中"
        pool.return_connection(conn)

        borrowed = pool.get_connection()
        assert borrowed.in_transaction is False, "归还未回滚：脏事务被下个借用者继承"
        rows = borrowed.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        assert rows == 0, "未提交写入不应落库"
        pool.return_connection(borrowed)
        pool.close_all()

    def test_returned_connection_is_reusable(self, tmp_path):
        pool = self._make_pool(tmp_path)
        conn = pool.get_connection()
        conn.execute("SELECT 1")
        pool.return_connection(conn)
        assert pool.pool_size == 1
        assert pool.total_count == 1
        borrowed = pool.get_connection()
        assert borrowed.execute("SELECT 1").fetchone()[0] == 1
        pool.return_connection(borrowed)
        pool.close_all()


class TestHealthCheckReleasesConnection:
    """P0-2 顺带堵漏：健康检查不得泄漏池连接。

    旧实现在 create_database_check 里 `conn = _get_db_conn()` 后从不归还，
    每轮健康检查漏一条连接，漏满 max_connections 后 get_connection 走入
    阻塞分支等 timeout（历史"健康检查卡 30s"根因）。
    """

    def test_no_deprecated_get_db_conn_in_endpoints(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[3]
            / "neurova"
            / "api"
            / "endpoints"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        assert "_get_db_conn" not in src, "健康检查退回 deprecated 且不归还连接的写法"
        assert "database_connection" in src


class TestObserveStateIsolation:
    """删死代码不得降低健壮性：单个组件取值失败不能清空其它 gauge。

    旧手拼代码里每个指标各自 try/except；收口到 observe_state 时若整体
    包一个 try，一个坏引擎就会让 /metrics 的运行态全为 0（观测面塌陷）。
    """

    class _BadEngine:
        def is_available(self):
            raise RuntimeError("engine boom")

    class _State:
        def __init__(self):
            self.agents = ["a", "b"]
            self.voice_engines = {"tts": TestObserveStateIsolation._BadEngine()}
            self.channel_manager = None

        @staticmethod
        def get_uptime():
            return 42.0

    def test_bad_engine_does_not_blank_other_gauges(self):
        from neurova.core.metrics import get_metrics

        get_metrics().observe_state(self._State())
        assert REGISTRY.get_sample_value("neurova_uptime_seconds") == 42.0
        assert REGISTRY.get_sample_value("neurova_agents_total") == 2.0
        assert REGISTRY.get_sample_value("neurova_voice_tts_available") == 0.0

    def test_observe_state_handles_none(self):
        from neurova.core.metrics import get_metrics

        get_metrics().observe_state(None)
        assert REGISTRY.get_sample_value("neurova_agents_total") == 0.0


class TestPoolMetrics:
    """P0-2：池运行态可测（此前 property 存在但无 gauge/counter）。"""

    def test_connection_created_and_closed_counters(self, tmp_path):
        from neurova.core.connection_pool import SQLiteConnectionPool

        db = str(tmp_path / "counter.db")
        pool = SQLiteConnectionPool(db, max_connections=1)
        conn = pool.get_connection()
        created = REGISTRY.get_sample_value(
            "neurova_db_connections_created_total", {"db": db}
        )
        assert created == 1.0, f"连接创建未计数: {created}"

        # 池满时归还失败（max_connections=1 且未取出）→ 走 _discard_connection
        # 此处直接 close_all 验证销毁计数
        pool.return_connection(conn)
        pool.close_all()
        closed = REGISTRY.get_sample_value(
            "neurova_db_connections_closed_total", {"db": db}
        )
        assert closed == 1.0, f"连接销毁未计数: {closed}"

    def test_pool_gauges_snapshot(self, tmp_path):
        from neurova.core.connection_pool import get_connection_pool
        from neurova.core.metrics import get_metrics

        db = str(tmp_path / "gauge.db")
        # 走全局注册表：observe_pools 抓取的就是"已注册池"集合
        pool = get_connection_pool(db, max_connections=3)
        conn = pool.get_connection()
        get_metrics().observe_pools()

        def g(state):
            return REGISTRY.get_sample_value(
                "neurova_db_pool_connections", {"db": db, "state": state}
            )

        assert g("active") == 1.0
        assert g("idle") == 0.0
        assert g("total") == 1.0

        pool.return_connection(conn)
        get_metrics().observe_pools()
        assert g("active") == 0.0
        assert g("idle") == 1.0
        pool.close_all()

    def test_thread_pool_gauges_snapshot(self):
        import time

        from neurova.core.metrics import get_metrics
        from neurova.core.thread_pool import get_thread_pool, iter_pools

        executor = get_thread_pool()
        futures = [executor.submit(time.sleep, 0.15) for _ in range(2)]
        try:
            time.sleep(0.05)
            get_metrics().observe_pools()
            threads = REGISTRY.get_sample_value(
                "neurova_thread_pool_threads", {"pool": "shared"}
            )
            assert threads and threads >= 1, f"线程数 gauge 未导出: {threads}"
            max_workers = REGISTRY.get_sample_value(
                "neurova_thread_pool_max_workers", {"pool": "shared"}
            )
            assert max_workers and max_workers >= 1
            depth = REGISTRY.get_sample_value(
                "neurova_thread_pool_queue_depth", {"pool": "shared"}
            )
            assert depth is not None, "队列深度 gauge 未导出"
            assert iter_pools(), "已建池必须出现在快照中"
        finally:
            for f in futures:
                f.result()

    def test_iter_pools_does_not_lazy_create(self):
        from neurova.core.connection_pool import iter_pools

        # 空池集合时只返回空列表，不因抓指标而建池
        assert isinstance(iter_pools(), list)

    def test_existing_pool_max_connections_conflict_warns(self, tmp_path, caplog):
        """池已存在时 max_connections 变更必须显式告警，不得静默忽略。"""
        from neurova.core.connection_pool import get_connection_pool

        db = str(tmp_path / "conflict.db")
        get_connection_pool(db, max_connections=2)
        with caplog.at_level("WARNING"):
            pool = get_connection_pool(db, max_connections=9)
        assert pool.max_connections == 2, "已存在池的 max_connections 不应热改"
        assert any(
            "max_connections" in r.getMessage() for r in caplog.records
        ), "静默忽略 max_connections 冲突（调用方会误以为限流生效）"
