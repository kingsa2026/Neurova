"""growth constitution 规则持久化 + FE 路径契约回归（2026-09-12 台账清剿 P1）。

根因:
1. FE growth.ts 增删改调 POST/PUT/DELETE /growth/constitution[/{id}]，
   BE 路由是 /growth/constitution/rules[/{id}] → 恒 404/405，宪法规则页写入必失败；
2. BE rules 读写 `agent.constitution` 内存属性（构造默认 ""，add 时 setattr 成 list）
   → 无落盘，重启即丢；GET /constitution overview 同读该幻影属性恒空；
3. POST /constitution/evaluate、POST /personality/evolve 是"TODO 未实现直返成功壳"
   （恒 is_compliant=True / 谎报进化）——假成功，改 501 诚实未实现。

修复契约:
- rules 落 data/constitution/{agent_id}.json（tmp+replace 原子写），CRUD 全落盘可回读；
- GET /constitution overview 返回持久源规则；
- evaluate/evolve → 501。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_constitution_012345")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import growth


class _FakeAgent:
    def __init__(self):
        self.personality = "md 文本"
        self.constitution = ""


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(growth, "_CONSTITUTION_DIR", str(tmp_path / "constitution"))

    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance",
                        lambda agent_id="default", *a, **k: _FakeAgent())
    app = FastAPI()
    app.include_router(growth.router, prefix="/api/v1/growth")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


class TestRulesPersistence:
    def test_add_get_roundtrip_and_disk(self, store):
        c, tmp = store
        r = c.post("/api/v1/growth/constitution/rules", params={"agent_id": "a1"},
                   json={"content": "不得虚构事实", "priority": 1})
        assert r.status_code == 200, r.text
        rule = r.json()
        assert rule["content"] == "不得虚构事实"
        f = tmp / "constitution" / "a1.json"
        assert f.exists(), "宪法未落盘"
        assert json.loads(f.read_text(encoding="utf-8"))[0]["rule_id"] == rule["rule_id"]
        got = c.get("/api/v1/growth/constitution/rules", params={"agent_id": "a1"}).json()
        assert [x["content"] for x in got] == ["不得虚构事实"]

    def test_update_and_delete_persist(self, store):
        c, tmp = store
        rid = c.post("/api/v1/growth/constitution/rules", params={"agent_id": "a1"},
                     json={"content": "v1"}).json()["rule_id"]
        r = c.put(f"/api/v1/growth/constitution/rules/{rid}", params={"agent_id": "a1"},
                  json={"content": "v2", "priority": 5})
        assert r.status_code == 200
        # 新进程视角（直读盘）
        on_disk = json.loads((tmp / "constitution" / "a1.json").read_text(encoding="utf-8"))
        assert on_disk[0]["content"] == "v2" and on_disk[0]["priority"] == 5
        assert c.delete(f"/api/v1/growth/constitution/rules/{rid}",
                        params={"agent_id": "a1"}).status_code == 200
        on_disk = json.loads((tmp / "constitution" / "a1.json").read_text(encoding="utf-8"))
        assert on_disk == []

    def test_overview_reads_persistent_source(self, store):
        c, _ = store
        c.post("/api/v1/growth/constitution/rules", params={"agent_id": "a1"},
               json={"content": "诚实优先"})
        d = c.get("/api/v1/growth/constitution", params={"agent_id": "a1"}).json()
        contents = [r["content"] for r in d["data"]["constitution"]]
        assert contents == ["诚实优先"]

    def test_update_missing_rule_404(self, store):
        c, _ = store
        r = c.put("/api/v1/growth/constitution/rules/no-such",
                  params={"agent_id": "a1"}, json={"content": "x"})
        assert r.status_code == 404

    def test_toggle_enabled_does_not_clobber_content(self, store):
        """FE toggle 只传 {enabled}：局部更新，content/priority 原样保留。"""
        c, tmp = store
        rid = c.post("/api/v1/growth/constitution/rules", params={"agent_id": "a1"},
                     json={"content": "保持原文", "priority": 7}).json()["rule_id"]
        r = c.put(f"/api/v1/growth/constitution/rules/{rid}",
                  params={"agent_id": "a1"}, json={"enabled": False})
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False
        assert r.json()["content"] == "保持原文"
        assert r.json()["priority"] == 7


class TestHonestUnimplemented:
    def test_evaluate_dead_route_removed(self, store):
        """零消费方的 TODO 假成功端点（恒 is_compliant=True）直接删除。"""
        c, _ = store
        r = c.post("/api/v1/growth/constitution/evaluate",
                   params={"agent_id": "a1", "action": "delete db"})
        assert r.status_code == 404, "未实现的评估端点不得保留成功壳"

    def test_personality_evolve_returns_501(self, store):
        c, _ = store
        r = c.post("/api/v1/growth/personality/evolve", params={"agent_id": "a1"})
        assert r.status_code == 501, "有 FE 按钮但 TODO 的端点须诚实 501"
