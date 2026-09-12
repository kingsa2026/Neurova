"""firewall 端点契约与持久化修复回归（2026-09-12 台账清剿 P3）。

根因（放大视角三处同族）：
1. `get_firewall()` 生产从不传 config_path → AgentFirewall._load/_save 早退，
   经 API 增删的规则只活在内存，重启即丢（"保存真实落盘"维度）；
2. PUT /rules/rate_limit_minute|hour：rule_id 切分后 rule_type="rate" 不命中
   ip/path 分支 → 静默 no-op 仍返 200 回显（假成功）；DELETE 同型谎报 deleted；
3. POST rate_limit 分支靠 `"minute" in body.name.lower()` 判断，名字不含关键字
   静默不写仍返 200（假成功）；GET /rules 不含 allowed_ips（POST allow 写了读不回）；
   enabled_only 查询参数收了从未使用。

修复契约：持久化默认 data/firewall.json（NEUROVA_FIREWALL_PATH 隔离）；
rate 规则 PUT 真更新 / DELETE 400；POST rate 无关键字/非数字 → 400；
GET 含 ip_allow_* 白名单规则。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_firewall_0123456")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import firewall as FW
from neurova.core import firewall as FIRE

MOCK_USER = {"user_id": "u1", "username": "u1", "role": "admin"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_FIREWALL_PATH", str(tmp_path / "firewall.json"))
    FIRE.reset_firewall()
    app = FastAPI()
    app.include_router(FW.router, prefix="/api/v1/firewall")
    app.dependency_overrides[get_current_user] = lambda: dict(MOCK_USER)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    FIRE.reset_firewall()


class TestPersistence:
    def test_created_rule_written_to_disk(self, client):
        c, tmp = client
        r = c.post("/api/v1/firewall/rules", json={
            "name": "block bot ip", "rule_type": "ip", "action": "block", "value": "1.2.3.4",
        })
        assert r.status_code == 200, r.text
        f = tmp / "firewall.json"
        assert f.exists(), "规则未落盘"
        saved = json.loads(f.read_text(encoding="utf-8"))
        assert "1.2.3.4" in saved["global"]["blocked_ips"]

    def test_survives_process_restart(self, client, tmp_path, monkeypatch):
        c, tmp = client
        c.post("/api/v1/firewall/rules", json={
            "name": "block path", "rule_type": "path", "action": "block", "value": "/data/secret",
        })
        FIRE.reset_firewall()  # 模拟重启：单例重建应从盘加载
        rules = c.get("/api/v1/firewall/rules").json()
        assert any(r["value"] == "/data/secret" for r in rules)


class TestRateRulesHonest:
    def test_put_rate_rule_actually_updates(self, client):
        c, _ = client
        r = c.put("/api/v1/firewall/rules/rate_limit_minute", json={
            "name": "rate limit per minute", "rule_type": "rate_limit",
            "action": "limit", "value": "90",
        })
        assert r.status_code == 200, r.text
        # 重读 GET 必须是新值（不再 no-op）
        rules = c.get("/api/v1/firewall/rules").json()
        rate = next(x for x in rules if x["rule_id"] == "rate_limit_minute")
        assert rate["value"] == "90"

    def test_delete_rate_rule_rejected_400(self, client):
        c, _ = client
        r = c.delete("/api/v1/firewall/rules/rate_limit_hour")
        assert r.status_code == 400

    def test_post_rate_without_keyword_is_400(self, client):
        """旧 bug：名字不含 minute/hour 静默不写仍 200。"""
        c, _ = client
        r = c.post("/api/v1/firewall/rules", json={
            "name": "每日限额", "rule_type": "rate_limit", "action": "limit", "value": "120",
        })
        assert r.status_code == 400
        assert r.json()["detail"]


class TestReadSymmetry:
    def test_allowed_ips_visible_in_rules(self, client):
        c, _ = client
        c.post("/api/v1/firewall/rules", json={
            "name": "allow office ip", "rule_type": "ip", "action": "allow", "value": "10.0.0.5",
        })
        rules = c.get("/api/v1/firewall/rules").json()
        allow = [r for r in rules if r["rule_id"] == "ip_allow_10.0.0.5"]
        assert allow, "POST allow 写入后 GET 不可见（读写不对称）"
        assert allow[0]["action"] == "allow"

    def test_enabled_only_filter_applied(self, client):
        c, _ = client
        r = c.get("/api/v1/firewall/rules", params={"enabled_only": True})
        assert r.status_code == 200
        assert all(x["enabled"] for x in r.json())
