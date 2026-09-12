"""AgentRulePage 规则落盘 + test 诚实化回归（2026-09-12 P5c）。

根因：_rules_store/_rule_logs 纯内存（重启空）；_rule_logs 全文件无写入方
（logs 页签恒空）；POST /test 是"模拟规则测试"写死 success=True（假成功）。
FE 契约 {id,condition,action,active,priority} 与 BE {rule_id,trigger,enabled} 错位。

修复：对齐 FE 字段；落盘 data/rules_api.json；test 做真实结构校验
（condition/action 缺失 → 400），每次测试写入执行日志（logs 页签真实来源）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_rules_01234567")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import rules_api


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RULES_PATH", str(tmp_path / "rules_api.json"))
    rules_api._reboot_load()
    app = FastAPI()
    app.include_router(rules_api.router, prefix="/api/v1/rules")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestRuleContract:
    def test_create_uses_frontend_fields(self, api):
        r = api.post("/api/v1/rules", json={
            "name": "夜间只读", "condition": "hour >= 22", "action": "read_only", "priority": "high",
        })
        assert r.status_code == 200, r.text
        rule = r.json()
        assert rule["id"] and rule["condition"] == "hour >= 22"
        assert rule["active"] is True

    def test_toggle_updates_active(self, api):
        rid = api.post("/api/v1/rules", json={"name": "x", "condition": "c", "action": "a"}).json()["id"]
        api.put(f"/api/v1/rules/{rid}/toggle")
        assert api.get(f"/api/v1/rules/{rid}").json()["active"] is False

    def test_persistence_across_restart(self, api):
        rid = api.post("/api/v1/rules", json={"name": "持久", "condition": "c", "action": "a"}).json()["id"]
        rules_api._reboot_load()
        got = api.get(f"/api/v1/rules/{rid}")
        assert got.status_code == 200 and got.json()["name"] == "持久"


class TestRuleTestHonest:
    def test_missing_condition_action_returns_400(self, api):
        rid = api.post("/api/v1/rules", json={"name": "空规则"}).json()["id"]
        r = api.post(f"/api/v1/rules/{rid}/test")
        assert r.status_code == 400, "结构不完整不得谎报测试通过"

    def test_valid_rule_test_logs_result(self, api):
        rid = api.post("/api/v1/rules", json={"name": "ok", "condition": "c", "action": "a"}).json()["id"]
        r = api.post(f"/api/v1/rules/{rid}/test")
        assert r.status_code == 200
        logs = api.get(f"/api/v1/rules/{rid}/logs").json()
        assert len(logs) == 1
        assert logs[0]["success"] is True
        assert logs[0]["ruleId"] == rid
        # FE ExecutionLog 契约字段
        assert {"id", "timestamp", "detail"} <= set(logs[0])

    def test_logs_survive_restart(self, api):
        rid = api.post("/api/v1/rules", json={"name": "ok", "condition": "c", "action": "a"}).json()["id"]
        api.post(f"/api/v1/rules/{rid}/test")
        rules_api._reboot_load()
        assert len(api.get(f"/api/v1/rules/{rid}/logs").json()) == 1
