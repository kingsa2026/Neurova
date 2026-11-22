# -*- coding: utf-8 -*-
"""S4 审计防篡改哈希链（红→绿判据）。

契约（拍板 D-S2 = 全量事件入链）:
- audit_logs 每行落 prev_hash / entry_hash 两列：
  entry_hash = sha256(prev_hash ‖ canonical_json(本条去哈希字段))，首条 prev_hash = 全零创世串；
- verify_audit_chain() 全表按 id 序校验，返回 (ok, first_broken_id)；
- 迁移经 core/db_migration 注册表（domain=audit_log）给既有库补两列，
  迁移前旧行两列置空，校验时按 legacy 跳过（不误报）；
- GET /api/v1/audit/integrity（admin 门）暴露校验结果。

测试用 tmp_path 独立库，不触真实数据根；单例复位同时覆盖
AuditLogger._instance 与模块级 _audit_logger 两个缓存位。
"""
import os
import sqlite3
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault(
    "NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_audit_hash_chain_0123456"
)

import neurova.security.audit_logger as audit_logger_module
from neurova.api.endpoints import audit as audit_endpoint
from neurova.security.audit_logger import (
    GENESIS_PREV_HASH,
    AuditEventType,
    AuditLogEntry,
    AuditLogger,
    AuditSeverity,
    verify_audit_chain,
)
from tests.auth_headers import overrideIdentity

MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin"}
MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user"}


def _entry(action: str, user_id: str = "alice") -> AuditLogEntry:
    return AuditLogEntry(
        event_type=AuditEventType.DATA_ACCESS,
        severity=AuditSeverity.MEDIUM,
        user_id=user_id,
        action=action,
        resource_type="memory",
        resource_id=f"m-{action}",
        details={"op": action},
    )


@pytest.fixture()
def chain_logger(tmp_path):
    """重定向审计单例到 tmp_path（同时复位类级与模块级两个缓存位）。"""
    saved_instance = AuditLogger._instance
    saved_module = audit_logger_module._audit_logger
    AuditLogger._instance = None
    audit_logger_module._audit_logger = None
    try:
        lg = AuditLogger(db_path=str(tmp_path / "audit.db"))
        yield lg
    finally:
        AuditLogger._instance = saved_instance
        audit_logger_module._audit_logger = saved_module


def _rows(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM audit_logs ORDER BY id ASC").fetchall()
    finally:
        conn.close()


def _tamper(db_path: str, sql: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


def test_writeThreeEntriesThenChainVerifies(chain_logger):
    """① 写 3 条 → 全链校验通过，且每行两列哈希齐备。"""
    for i in range(3):
        assert chain_logger.log(_entry(f"op-{i}")) is True
    ok, broken_id = verify_audit_chain()
    assert ok is True
    assert broken_id is None
    rows = _rows(chain_logger._db_path)
    assert len(rows) == 3
    for row in rows:
        assert row["prev_hash"], "prev_hash 必须落列"
        assert len(row["prev_hash"]) == 64
        assert row["entry_hash"], "entry_hash 必须落列"
        assert len(row["entry_hash"]) == 64


def test_tamperMiddleRowIsDetectedWithBreakpointId(chain_logger):
    """② 手改中间行一个字段 → 校验失败并给出断点 id。"""
    for i in range(3):
        chain_logger.log(_entry(f"op-{i}"))
    _tamper(
        chain_logger._db_path,
        "UPDATE audit_logs SET action = 'tampered' WHERE id = 2",
    )
    ok, broken_id = verify_audit_chain()
    assert ok is False
    assert broken_id == 2


def test_tamperingDetailsOrTimestampAlsoBreaks(chain_logger):
    """哈希绑定全部去哈希字段：details / timestamp 改动同样现形。"""
    chain_logger.log(_entry("op-0"))
    chain_logger.log(_entry("op-1"))
    _tamper(
        chain_logger._db_path,
        "UPDATE audit_logs SET details = '{\"op\": \"evil\"}' WHERE id = 1",
    )
    ok, broken_id = verify_audit_chain()
    assert (ok, broken_id) == (False, 1)

    _tamper(
        chain_logger._db_path,
        "UPDATE audit_logs SET details = '{\"op\": \"op-0\"}' WHERE id = 1",
    )
    _tamper(
        chain_logger._db_path,
        "UPDATE audit_logs SET timestamp = timestamp + 1 WHERE id = 2",
    )
    ok, broken_id = verify_audit_chain()
    assert (ok, broken_id) == (False, 2)


def test_chainLinksEachRowToPreviousHash(chain_logger):
    """③ 链式正确性：首条 prev=创世串，其后每条 prev=前一条 entry_hash。"""
    for i in range(3):
        chain_logger.log(_entry(f"op-{i}"))
    rows = _rows(chain_logger._db_path)
    assert rows[0]["prev_hash"] == GENESIS_PREV_HASH
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert rows[2]["prev_hash"] == rows[1]["entry_hash"]
    # 内容不同 → 哈希必不同（链指针之外还绑定本条内容）
    assert len({r["entry_hash"] for r in rows}) == len(rows)


def test_legacyRowsWithoutHashAreSkipped(chain_logger):
    """迁移前旧行（两列置空）按 legacy 跳过，不误报断链；其后新行照常入链。"""
    lg = chain_logger
    lg.log(_entry("op-0"))
    lg.log(_entry("op-1"))
    _tamper(
        lg._db_path,
        "UPDATE audit_logs SET prev_hash = NULL, entry_hash = NULL WHERE id = 1",
    )
    lg.log(_entry("op-2"))
    ok, broken_id = verify_audit_chain()
    assert ok is True
    assert broken_id is None
    rows = _rows(lg._db_path)
    assert rows[0]["entry_hash"] is None  # legacy 行保持置空
    assert rows[2]["prev_hash"] == rows[1]["entry_hash"]


def test_concurrentWritersKeepChainIntact(chain_logger):
    """并发写入（同事务取 prev）后全链仍连续：4 线程 × 15 条。"""
    lg = chain_logger
    errors = []

    def worker(worker_id: int) -> None:
        try:
            for i in range(15):
                if not lg.log(_entry(f"w{worker_id}-{i}")):
                    errors.append(f"w{worker_id}-{i} log failed")
        except Exception as exc:  # pragma: no cover - 只为把线程内故障带回主线程
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    ok, broken_id = verify_audit_chain()
    assert ok is True
    assert broken_id is None
    assert len(_rows(lg._db_path)) == 60


@pytest.fixture()
def integrity_client(chain_logger, monkeypatch):
    """admin 身份的审计路由测试端（只挂 router，不触发 lifespan）。"""
    monkeypatch.setattr(
        audit_endpoint, "get_audit_logger", lambda *a, **k: chain_logger
    )
    app = FastAPI()
    app.include_router(audit_endpoint.router, prefix="/api/v1/audit")
    overrideIdentity(app, MOCK_ADMIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_integrityEndpointReportsOkForAdmin(integrity_client, chain_logger):
    """GET /api/v1/audit/integrity：admin 可达，链完好时 ok=true。"""
    for i in range(3):
        chain_logger.log(_entry(f"op-{i}"))
    resp = integrity_client.get("/api/v1/audit/integrity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["ok"] is True
    assert body["data"]["first_broken_id"] is None


def test_integrityEndpointReportsBreakpointWhenTampered(
    integrity_client, chain_logger
):
    chain_logger.log(_entry("op-0"))
    chain_logger.log(_entry("op-1"))
    resp_pre = integrity_client.get("/api/v1/audit/integrity")
    assert resp_pre.status_code == 200
    assert resp_pre.json()["data"]["ok"] is True
    _tamper(
        chain_logger._db_path,
        "UPDATE audit_logs SET user_id = 'mallory' WHERE id = 1",
    )
    resp = integrity_client.get("/api/v1/audit/integrity")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["ok"] is False
    assert body["data"]["first_broken_id"] == 1


def test_integrityEndpointForbidsNonAdmin(chain_logger, monkeypatch):
    """非 admin 角色被既有角色门拦下（复用 require_admin 依赖）。"""
    monkeypatch.setattr(
        audit_endpoint, "get_audit_logger", lambda *a, **k: chain_logger
    )
    app = FastAPI()
    app.include_router(audit_endpoint.router, prefix="/api/v1/audit")
    overrideIdentity(app, MOCK_USER)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/audit/integrity")
    app.dependency_overrides.clear()
    assert resp.status_code == 403
