"""growth 域端点响应 envelope 一致性契约（2026-09-16 契约收口）。

根因审计：growth 域 23 端点中 13 个返回 {code, message, data}（含 /personality、
/motivation、/capabilities、overview），9 个同族端点返回裸对象/裸数组：
  GET/POST /reflection、GET/POST /questions、GET/POST /proactive、
  GET /constitution/rules、POST /constitution/rules、PUT /constitution/rules/{id}
前端 axios 拦截器返回裸 body，消费方被迫在 consumer 侧写
`Array.isArray(raw) ? raw : raw?.data` / `res?.data ?? res` 兜底——
同一响应两种解包方式并存，正是 personality 档案恒空那类契约错位的温床。

本文件钉死契约：growth 域全部数据端点统一 envelope。
其他域（channels/sleep 等）不在本契约内。
"""
import os
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_growth_env_012345")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import growth as growth_api


class _FakeAgent:
    """最小 agent 桩：全部管理器缺位——同时覆盖"未装配诚实空值"分支"""

    def __init__(self):
        self.personality = "md 文本"
        self.constitution = ""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 2026-09-16 拆分后持久层常量住叶子模块（import 时值绑定，须 patch 真身）
    monkeypatch.setattr("neurova.api.endpoints.personality_persistence.PERSONALITY_DIR", str(tmp_path / "personality"))
    monkeypatch.setattr("neurova.api.endpoints.constitution_persistence.CONSTITUTION_DIR", str(tmp_path / "constitution"))
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance",
                        lambda agent_id="default", *a, **k: _FakeAgent())
    app = FastAPI()
    app.include_router(growth_api.router, prefix="/api/v1/growth")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _assert_envelope(body, status_code=200):
    """growth 域统一 envelope 契约：与同文件 2026-09-16 personality/motivation 先例同形
    （含 request_id 追踪——本代码库横切约定），顶层必须且仅需这 4 键"""
    assert status_code == 200
    assert isinstance(body, dict), f"必须是 envelope 对象，实际: {str(body)[:200]}"
    assert set(body.keys()) == {"code", "message", "data", "request_id"}, f"envelope 键错位: {sorted(body.keys())}"
    assert body["code"] == 0
    assert isinstance(body["message"], str)
    assert isinstance(body["request_id"], str) and body["request_id"]


class TestReflectionEnvelope:
    def test_get_returns_envelope_with_empty_list(self, client):
        r = client.get("/api/v1/growth/reflection", params={"agent_id": "a1"})
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"] == [], "未装配时如实返回空列表"

    def test_post_returns_envelope_with_created_item(self, client):
        r = client.post(
            "/api/v1/growth/reflection",
            params={"agent_id": "a1"},
            json={"reflection_type": "general", "content": "手动反思", "insights": [], "confidence": 0.5},
        )
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"]["content"] == "手动反思"


class TestQuestionsEnvelope:
    def test_get_returns_envelope_with_empty_list(self, client):
        r = client.get("/api/v1/growth/questions", params={"agent_id": "a1"})
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"] == []

    def test_post_returns_envelope_with_created_item(self, client):
        r = client.post(
            "/api/v1/growth/questions",
            params={"agent_id": "a1"},
            json={"question_type": "curiosity", "question": "问题X", "priority": 0},
        )
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"]["question"] == "问题X"


class TestProactiveEnvelope:
    def test_get_returns_envelope_with_empty_list(self, client):
        r = client.get("/api/v1/growth/proactive", params={"agent_id": "a1"})
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"] == [], "引擎未装配时如实返回空列表"

    def test_post_without_engine_is_honest_400(self, client):
        """诚实化契约保持：引擎未装配 → 400 错误，不返回任何成功壳"""
        r = client.post(
            "/api/v1/growth/proactive",
            params={"agent_id": "a1"},
            json={"action_type": "communication", "content": "c"},
        )
        assert r.status_code == 400, "引擎未装配必须诚实报错"


class TestConstitutionRulesEnvelope:
    def test_get_returns_envelope_with_empty_list(self, client):
        r = client.get("/api/v1/growth/constitution/rules", params={"agent_id": "a1"})
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"] == []
    def test_post_returns_envelope_with_created_rule(self, client):
        r = client.post(
            "/api/v1/growth/constitution/rules",
            params={"agent_id": "a1"},
            json={"content": "规则Y", "priority": 2},
        )
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"]["content"] == "规则Y"

    def test_put_returns_envelope_with_updated_rule(self, client):
        rid = client.post(
            "/api/v1/growth/constitution/rules",
            params={"agent_id": "a1"},
            json={"content": "v1"},
        ).json()["data"]["rule_id"]
        r = client.put(f"/api/v1/growth/constitution/rules/{rid}",
                       params={"agent_id": "a1"}, json={"content": "v2"})
        _assert_envelope(r.json(), r.status_code)
        assert r.json()["data"]["content"] == "v2"


class TestFamilyUniformity:
    """已是 envelope 的旧端点也不得游离在家族形态外（request_id 全域齐备）"""

    def test_legacy_envelopes_carry_request_id(self, client):
        for path in (
            "/api/v1/growth/reflection/stats",
            "/api/v1/growth/personality/traits",
            "/api/v1/growth/constitution",
            "/api/v1/growth/motivation",
            "/api/v1/growth/personality",
            "/api/v1/growth/capabilities",
        ):
            body = client.get(path, params={"agent_id": "a1"}).json()
            assert set(body.keys()) == {"code", "message", "data", "request_id"}, f"{path} 键错位: {sorted(body.keys())}"

    def test_questions_next_envelope_uniform(self, client):
        body = client.get("/api/v1/growth/questions/next", params={"agent_id": "a1"}).json()
        assert set(body.keys()) == {"code", "message", "data", "request_id"}
        assert body["data"] is None, "未装配时如实 data=null"
