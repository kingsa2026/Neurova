"""AuditPage 空数据修复回归测试（2026-09-12 空数据页面排查）。

根因: audit.py 三个 GET/POST 端点调用 get_audit_logger() 后丢弃实例，
恒返回 []/全 0（硬编码空 stub），而 AuditLogger 的 SQLite 表有真实数据
（tool_executor / auth 链路持续写入，实测 2000+ 行）。
另前端 AuditPage 契约与后端响应形状完全错位（信封 {items,total,stats} vs 裸数组），
且前端 Export 按钮调用的 GET /audit/export 后端不存在（恒 404）。

修复契约:
- GET /api/v1/audit: 按 FE 契约返回信封 {code,message,data:{items,total,page,page_size,
  stats:{total,today,warnings}}}；支持 page/page_size/user/action/start/end 筛选；
- GET /api/v1/audit/stats: 真实统计（total_logs/unique_users/unique_actions/分布）;
- POST /api/v1/audit/search: 真实文本搜索;
- GET /api/v1/audit/export: 新增路由，返回可下载 JSON。

测试只挂 router（不触发 lifespan），AuditLogger 单例重定向 tmp_path。
"""
import datetime
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_audit_wiring_0123456")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import audit
from neurova.security.audit_logger import (
    AuditEventType,
    AuditLogEntry,
    AuditLogger,
    AuditSeverity,
)

MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin"}


@pytest.fixture()
def seeded_logger(tmp_path, monkeypatch):
    """重定向 AuditLogger 单例到 tmp_path 并播种 3 条审计记录。"""
    saved = AuditLogger._instance
    AuditLogger._instance = None
    try:
        lg = AuditLogger(db_path=str(tmp_path / "audit.db"))
        monkeypatch.setattr(audit, "get_audit_logger", lambda *a, **k: lg)
        now = time.time()
        midnight = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        lg.log(AuditLogEntry(
            event_type=AuditEventType.DATA_ACCESS, severity=AuditSeverity.HIGH,
            user_id="alice", action="memory_read", resource_type="memory",
            resource_id="m1", details={"k": 1}, timestamp=now - 1,
        ))
        lg.log(AuditLogEntry(
            event_type=AuditEventType.SYSTEM_EVENT, severity=AuditSeverity.LOW,
            user_id="bob", action="config_change", resource_type="settings",
            resource_id="theme", details={}, timestamp=midnight - 3600,
        ))
        lg.log(AuditLogEntry(
            event_type=AuditEventType.SECURITY_EVENT, severity=AuditSeverity.CRITICAL,
            user_id="alice", action="login_failed", resource_type="auth",
            resource_id="", details={"ip": "1.2.3.4"}, timestamp=now - 2,
        ))
        yield lg
    finally:
        AuditLogger._instance = saved


@pytest.fixture()
def admin_client(seeded_logger):
    app = FastAPI()
    app.include_router(audit.router, prefix="/api/v1/audit")
    app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestAuditListRealData:
    def test_returns_seeded_records_in_envelope(self, admin_client):
        r = admin_client.get("/api/v1/audit")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["total"] == 3
        assert len(data["items"]) == 3
        item = data["items"][0]
        # FE AuditRecord 契约键
        for k in ("id", "timestamp", "user", "action", "resource", "details"):
            assert k in item, f"缺键 {k}: {item}"
        # timestamp 为可解析字符串（FE new Date(ts)）
        assert isinstance(item["timestamp"], str)
        datetime.datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        # 时间倒序：today 的两条在前
        assert item["action"] in ("memory_read", "login_failed")

    def test_stats_cards_real_values(self, admin_client):
        r = admin_client.get("/api/v1/audit")
        stats = r.json()["data"]["stats"]
        assert stats["total"] == 3
        assert stats["today"] == 2          # 昨天那条不计
        assert stats["warnings"] == 2       # HIGH + CRITICAL

    def test_filter_by_user_and_action(self, admin_client):
        r = admin_client.get("/api/v1/audit", params={"user": "alice"})
        assert r.json()["data"]["total"] == 2
        r = admin_client.get("/api/v1/audit", params={"action": "config_change"})
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["user"] == "bob"

    def test_pagination(self, admin_client):
        r = admin_client.get("/api/v1/audit", params={"page": 2, "page_size": 2})
        data = r.json()["data"]
        assert data["total"] == 3
        assert len(data["items"]) == 1
        assert data["page"] == 2

    def test_date_range_filter_iso(self, admin_client):
        end = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        r = admin_client.get("/api/v1/audit", params={"end": end})
        # 只应剩昨天 config_change 一条
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["action"] == "config_change"


class TestAuditStatsEndpoint:
    def test_stats_reflect_table(self, admin_client):
        r = admin_client.get("/api/v1/audit/stats")
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["total_logs"] == 3
        assert s["unique_users"] == 2
        assert s["unique_actions"] == 3
        assert s["action_counts"].get("memory_read") == 1
        assert s["resource_type_counts"].get("memory") == 1


class TestAuditSearchEndpoint:
    def test_search_matches_text(self, admin_client):
        r = admin_client.post("/api/v1/audit/search", json={"query": "login"})
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert items[0]["action"] == "login_failed"

    def test_search_no_match(self, admin_client):
        r = admin_client.post("/api/v1/audit/search", json={"query": "zzz-nothing"})
        assert r.json() == []


class TestAuditExportEndpoint:
    def test_export_returns_json_attachment(self, admin_client):
        r = admin_client.get("/api/v1/audit/export")
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers.get("content-disposition", "")
        payload = r.json()
        assert len(payload) == 3
        assert {"event_type", "user_id", "action"} <= set(payload[0].keys())
