# -*- coding: utf-8 -*-
"""P1-4 迁移守卫（Issue #57 + ADR 0014「池只管短连接」）

三条契约：

1. **常驻连接不得进池**：`_persist_conn` / `PersistDbStore._conn` /
   `cognitive_storage_engine._db` 等自持连接是为写放大做的刻意优化，
   收编进池会破坏"连接内多步 + 自己 commit"的事务语义，且池的归还强 rollback。
2. **动态路径 / 探针 / 只读 URI 不进池**：池按 db_path 注册且不回收，
   把它们池化会让池注册表无界增长（比每次 connect/close 更差）。
3. **短连接迁移点成对借用/归还**：池化后漏归还 = `_created_count` 只增不减，
   漏满 max_connections 即阻塞取连接（P0-2 的"健康检查卡 30s"同形状）。
"""
import ast
import io
import sqlite3
from pathlib import Path

import pytest

prometheus_client = pytest.importorskip("prometheus_client")
from prometheus_client import REGISTRY  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

# 明示"自持常驻连接"的类/模块：其 _conn 字段与对象同生命周期
RESIDENT_CONN_FILES = [
    "neurova/mem_core.py",
    "neurova/core/aigc_usage.py",
    "neurova/core/annotation_store.py",
    "neurova/core/usage_history.py",
    "neurova/core/agent_run_store.py",
    "neurova/security/desktop_audit.py",
    "neurova/knowledge/ingest_queue.py",
    "neurova/evolution/job_queue.py",
    "neurova/channels/channel_ingress_queue.py",
    "neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py",
    "neurova/cognitive_layers/memory_layer/temporal_knowledge_graph.py",
    "neurova/cognitive_layers/memory_layer/modules/emotion_module.py",
    "neurova/cognitive_layers/memory_layer/attachment_manager.py",
    "neurova/cognitive_layers/meta_cognition_layer/ledger.py",
    "neurova/collaboration/neurflow/storage.py",
    "neurova/aigc_studio/store.py",
    "neurova/skills/experience_knowledge_base.py",
    "neurova/memory/pending_memory.py",
    "neurova/auth/invitation_code.py",
    "neurova/auth/verification_code.py",
]

# 非池化（有意为之）：动态路径 / 健康探针 / 只读 URI
NON_POOLED_BY_DESIGN = [
    ("neurova/api/endpoints/home.py", "动态 glob 路径（agent_workspaces/*/memory/*.db）"),
    ("neurova/context/eviction_ledger_db.py", "per-user+agent 库文件，路径数无界"),
    ("neurova/api/endpoints/monitor.py", "健康探针（轻量独立、不与业务争连接）"),
    ("neurova/llm/generators/retention.py", "file:...?mode=ro 只读 URI"),
]


def _src(rel):
    return io.open(PROJECT_ROOT / rel, encoding="utf-8").read()


class TestResidentConnectionsStayOutOfPool:
    @pytest.mark.parametrize("rel", RESIDENT_CONN_FILES)
    def test_no_pooled_short_connection(self, rel):
        src = _src(rel)
        assert "get_short_connection" not in src, (
            f"{rel} 引入了池化短连接。自持常驻连接是为写放大做的刻意优化"
            f"（ADR 0014），收编进池会破坏事务语义 + 被池的归还 rollback 清掉"
        )
        assert "short_transaction" not in src, f"{rel} 不应改用池化短事务"

    def test_memory_manager_keeps_resident_conn(self):
        """memory_layer/manager.py 的 _persist_conn 必须是自持 sqlite3.connect。

        该文件**同时**存在"常驻连接"与"兜底短连接"两种：兜底可池化，
        常驻必须保留。这条守卫钉住常驻那一侧没被一起改掉。
        """
        src = _src("neurova/cognitive_layers/memory_layer/manager.py")
        assert "self._persist_conn = sqlite3.connect(" in src, (
            "_persist_conn 被改成池连接：常驻连接的 WAL/synchronous=NORMAL/"
            "busy_timeout 自持配置与池的共享语义不兼容"
        )


class TestNonPooledByDesign:
    @pytest.mark.parametrize("rel,reason", NON_POOLED_BY_DESIGN)
    def test_still_uses_bare_connect(self, rel, reason):
        src = _src(rel)
        assert "sqlite3.connect(" in src, f"{rel} 的裸连接被移除（{reason}）"
        assert "get_short_connection" not in src, (
            f"{rel} 不应池化：{reason}——池按 db_path 注册且不回收，"
            f"无界路径会撑爆池注册表"
        )


class TestShortConnectionSitesPaired:
    """迁移点的借用/归还必须配对（漏归还 = 阻塞取连接）。"""

    MIGRATED = [
        "neurova/security/audit_logger.py",
        "neurova/security/approval_manager.py",
        "neurova/security/rbac.py",
        "neurova/security/compliance_reporter.py",
        "neurova/planning/planning_tool.py",
        "neurova/core/provider_usage.py",
        "neurova/api/endpoints/files_api.py",
        "neurova/auth/user_model.py",
        "neurova/auth/qclaw_binding_model.py",
    ]

    @pytest.mark.parametrize("rel", MIGRATED)
    def test_uses_pool(self, rel):
        src = _src(rel)
        assert ("get_short_connection" in src or "short_transaction" in src
                or "short_connection" in src or "PooledConnection" in src), (
            f"{rel} 未接入池（P1-4 迁移未生效）"
        )

    @pytest.mark.parametrize(
        "rel",
        [
            "neurova/security/audit_logger.py",
            "neurova/planning/planning_tool.py",
            "neurova/core/provider_usage.py",
            "neurova/api/endpoints/files_api.py",
        ],
    )
    def test_no_unpaired_get_without_release(self, rel):
        """显式借用（非委托句柄）的调用点必须有归还有径。"""
        src = _src(rel)
        if "PooledConnection" in src:
            pytest.skip("委托句柄自动归还")
        gets = src.count("get_short_connection(")
        releases = src.count("release_short_connection(")
        if "short_transaction(" in src or "short_connection(" in src:
            # 上下文形态：借款与归还都在谓词里，按定义配对
            return
        assert releases >= gets, (
            f"{rel}: 借用 {gets} 次但归还入口只有 {releases} 处（漏归还即阻塞取连接）"
        )


class TestPoolRuntimeBehavior:
    """运行时行为：归属校验、重复归还防护、异常路径不泄漏。"""

    def _pool(self, tmp_path, max_conn=2):
        from neurova.core.connection_pool import SQLiteConnectionPool

        db = tmp_path / "p.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE t(a INTEGER)")
        c.commit()
        c.close()
        return SQLiteConnectionPool(str(db), max_connections=max_conn)

    def test_foreign_connection_is_not_adopted(self, tmp_path):
        """别的库的连接不得被本池收下（跨库串用）。"""
        pool = self._pool(tmp_path)
        other = sqlite3.connect(str(tmp_path / "other.db"))
        assert pool.return_connection(other) is False, "非本池连接被收下 = 跨库串用"
        assert pool.pool_size == 0
        other.close()
        pool.close_all()

    def test_double_return_is_ignored(self, tmp_path):
        """同一连接归还两次不得在队列里留下两条（两个借用者拿到同一连接）。"""
        pool = self._pool(tmp_path)
        conn = pool.get_connection()
        assert pool.return_connection(conn) is True
        assert pool.return_connection(conn) is True  # 幂等吞掉
        assert pool.pool_size == 1, "重复归还把同一连接塞进队列两次"
        first = pool.get_connection()
        second = pool.get_connection()
        assert first is not second, "两个借用者拿到同一条连接（并发读写错乱）"
        pool.return_connection(first)
        pool.return_connection(second)
        pool.close_all()

    def test_active_count_tracks_checkout(self, tmp_path):
        pool = self._pool(tmp_path)
        assert pool.active_count == 0
        conn = pool.get_connection()
        assert pool.active_count == 1
        pool.return_connection(conn)
        assert pool.active_count == 0
        pool.close_all()

    def test_short_transaction_commits_on_success(self, tmp_path):
        from neurova.core.database import short_transaction

        db = str(tmp_path / "tx.db")
        with short_transaction(db) as conn:
            conn.execute("CREATE TABLE t(a INTEGER)")
        with short_transaction(db) as conn:
            conn.execute("INSERT INTO t VALUES (1)")
        with short_transaction(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        from neurova.core.database import close_all_pools

        close_all_pools()

    def test_short_transaction_rolls_back_on_error(self, tmp_path):
        from neurova.core.database import short_transaction

        db = str(tmp_path / "tx2.db")
        with short_transaction(db) as conn:
            conn.execute("CREATE TABLE t(a INTEGER)")

        class Boom(RuntimeError):
            pass

        with pytest.raises(Boom):
            with short_transaction(db) as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                raise Boom()

        with short_transaction(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0, (
                "异常路径未回滚（脏写入落库）"
            )
        from neurova.core.database import close_all_pools

        close_all_pools()

    def test_no_exhaustion_after_repeated_migrated_calls(self, tmp_path):
        """反复调用迁移后的高频路径不得耗尽池（max=2 时任何漏归还都会立刻暴露）。"""
        import os

        from neurova.core import connection_pool as cp
        from neurova.core.database import close_all_pools

        close_all_pools()
        cp._pools.clear()

        db = str(tmp_path / "audit.db")
        from neurova.security.audit_logger import (
            AuditEventType,
            AuditLogEntry,
            AuditLogger,
            AuditSeverity,
        )

        AuditLogger._instance = None
        logger = AuditLogger(db_path=db)
        cp.get_connection_pool(db, max_connections=2)
        for i in range(25):
            logger.log(AuditLogEntry(
                event_type=AuditEventType.SYSTEM_EVENT,
                severity=AuditSeverity.LOW,
                action=f"a{i}",
            ))
        logger.query(limit=5)
        logger.get_statistics()
        logger.get_by_id(1)
        logger.archive_old_logs(0)
        logger.cleanup()

        pool = dict(cp.iter_pools())[db]
        assert pool.total_count <= 2, f"池连接数失控: {pool.total_count}"
        assert pool.active_count == 0, f"有连接未归还: {pool.active_count}"
        close_all_pools()

    def test_pragma_baseline_is_restored_on_return(self, tmp_path):
        """借用者改过的连接级 PRAGMA 必须在归还时复原。

        池是跨调用方复用的：A 把 busy_timeout 改小、把 foreign_keys 关掉，
        B 就会拿到弱化配置（外键关闭 = 写入绕过校验，静默数据风险）。
        这是"自持常驻连接不进池"的一条理由（ADR 0014），池必须自己兜住。
        """
        pool = self._pool(tmp_path)
        conn = pool.get_connection()
        expected = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(expected) > 0, "池连接无 busy_timeout 基线"

        conn.execute("PRAGMA busy_timeout=1")
        conn.execute("PRAGMA foreign_keys=OFF")
        pool.return_connection(conn)

        reused = pool.get_connection()
        assert reused.execute("PRAGMA busy_timeout").fetchone()[0] == expected
        assert reused.execute("PRAGMA foreign_keys").fetchone()[0] == 1, (
            "foreign_keys 被上个借用者关掉后未复原（写入绕过外键校验）"
        )
        pool.return_connection(reused)
        pool.close_all()

    def test_pooled_handle_returns_connection(self, tmp_path):
        """PooledConnection：close() 即归还，未 close 由 __del__ 兜底。"""
        from neurova.core import connection_pool as cp
        from neurova.core.database import close_all_pools
        from neurova.core.pooled_connection import PooledConnection

        close_all_pools()
        cp._pools.clear()
        db = str(tmp_path / "wrapped.db")
        cp.get_connection_pool(db, max_connections=1)

        handle = PooledConnection(db)
        handle.execute("CREATE TABLE t(a INTEGER)")
        handle.execute("INSERT INTO t VALUES (1)")
        assert handle.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        pool = dict(cp.iter_pools())[db]
        assert pool.active_count == 1
        handle.close()
        assert pool.active_count == 0
        handle.close()  # 幂等
        close_all_pools()
