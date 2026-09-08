# -*- coding: utf-8 -*-
"""Plans API 契约测试（/api/v1/plans —— ZCode 计划模式对齐）。

覆盖：
1. 鉴权 —— 匿名 401；非 agent 属主 403；agent 不存在 404；
2. 会话生命周期 —— start（首轮问题）→ answers（出计划）→ decision approve
   （execute_prompt 含计划全文）/ reject；
3. 归属隔离 —— 用户 B 读用户 A 的会话 404；
4. 计划文档 —— 列表、预览（MD 渲染数据源）、路径穿越 400；
5. LLM 桥 —— 未配置 503、调用失败 500。
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.plan_mode import PlanDocStore, PlanSessionManager

QUESTIONS_R1 = {
    "done": False,
    "questions": [
        {
            "id": "q1",
            "question": "目标平台是什么？",
            "options": [{"label": "Web", "description": "浏览器端"}],
            "multi": False,
            "allow_custom": True,
        }
    ],
}
PLAN_RESULT = {"title": "重构登录模块", "markdown": "# 计划：重构登录模块\n1. 梳理现状\n"}

ANSWERS = [{"id": "q1", "selected": ["Web"], "custom": ""}]


def _fake_llm_factory(script):
    import json as _json

    calls = {"n": 0}

    async def fake_llm(prompt: str) -> str:
        item = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return _json.dumps(item, ensure_ascii=False)
        return item

    return fake_llm


def _fake_agent(owner="u1", llm_ok=True):
    agent = MagicMock()
    agent.config.owner_user_id = owner
    if not llm_ok:
        agent.llm_client = None
    return agent


def _make_client(user=None, tmp=None):
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import plans as plans_mod

    app = FastAPI()
    app.include_router(plans_mod.router, prefix="/plans")
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    manager = PlanSessionManager(ttl_seconds=3600)
    store = PlanDocStore(base_dir=str(tmp))
    return plans_mod, client, manager, store


def _wire(plans_mod, manager, store, agent, script):
    patches = [
        patch.object(plans_mod, "_get_agent", return_value=agent),
        patch.object(plans_mod, "_get_session_manager", return_value=manager),
        patch.object(plans_mod, "_get_doc_store", return_value=store),
        patch.object(plans_mod, "_build_llm_bridge", return_value=_fake_llm_factory(script)),
    ]
    return patches


@pytest.fixture()
def env(tmp_path):
    plans_mod, client, manager, store = _make_client(
        user={"user_id": "u1", "role": "user"}, tmp=tmp_path
    )
    agent = _fake_agent()
    return plans_mod, client, manager, store, agent


class TestAuthAndAccess:
    def test_anonymous_gets_401(self):
        plans_mod, client, _, _ = _make_client(user=None)
        resp = client.post("/plans/sessions", json={"agent_id": "default", "request": "需求"})
        assert resp.status_code == 401

    def test_agent_not_found_404(self, env):
        plans_mod, client, manager, store, _ = env
        for p in _wire(plans_mod, manager, store, _fake_agent(), [QUESTIONS_R1]):
            p.start()
            p.stop()
        from unittest.mock import patch as _p

        with _p.object(plans_mod, "_get_agent", return_value=None):
            resp = client.post("/plans/sessions", json={"agent_id": "ghost", "request": "需求"})
        assert resp.status_code == 404

    def test_non_owner_gets_403(self, env):
        plans_mod, client, manager, store, _ = env
        # agent 属主是 someone-else，u1 是普通用户 → 403
        with patch.object(plans_mod, "_get_agent", return_value=_fake_agent(owner="someone-else")), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.post("/plans/sessions", json={"agent_id": "default", "request": "需求"})
        assert resp.status_code == 403

    def test_admin_bypasses_owner_check(self, env, tmp_path):
        plans_mod, _, manager, store, _ = env
        _, admin_client, _, _ = _make_client(
            user={"user_id": "admin1", "role": "admin"}, tmp=tmp_path
        )
        agent = _fake_agent(owner="someone-else")
        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store), \
             patch.object(plans_mod, "_build_llm_bridge", return_value=_fake_llm_factory([QUESTIONS_R1])):
            resp = admin_client.post("/plans/sessions", json={"agent_id": "default", "request": "需求"})
        assert resp.status_code == 200


class TestSessionLifecycle:
    def _start(self, plans_mod, client, manager, store, agent, script):
        patches = _wire(plans_mod, manager, store, agent, script)
        with patches[0], patches[1], patches[2], patches[3]:
            resp = client.post("/plans/sessions", json={"agent_id": "default", "request": "重构登录模块"})
        return resp

    def test_start_returns_first_round_questions(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [QUESTIONS_R1])
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        sess = body["data"]["session"]
        assert sess["status"] == "asking"
        assert sess["rounds"][0]["questions"][0]["id"] == "q1"
        assert sess["request"] == "重构登录模块"

    def test_llm_unconfigured_503(self, env):
        plans_mod, client, manager, store, _ = env
        with patch.object(plans_mod, "_get_agent", return_value=_fake_agent(llm_ok=False)), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.post("/plans/sessions", json={"agent_id": "default", "request": "需求"})
        assert resp.status_code == 503

    def test_llm_failure_500(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [RuntimeError("boom")])
        assert resp.status_code == 500

    def test_full_cycle_answers_then_approve(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [QUESTIONS_R1, PLAN_RESULT])
        sid = resp.json()["data"]["session"]["session_id"]

        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store), \
             patch.object(plans_mod, "_build_llm_bridge", return_value=_fake_llm_factory([PLAN_RESULT])):
            resp2 = client.post(f"/plans/sessions/{sid}/answers", json={"answers": ANSWERS})
        assert resp2.status_code == 200
        sess = resp2.json()["data"]["session"]
        assert sess["status"] == "awaiting_approval"
        assert sess["document"]["name"].endswith(".md")
        assert sess["document"]["rel_path"].startswith("docs/plan/")

        with patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp3 = client.post(f"/plans/sessions/{sid}/decision", json={"action": "approve"})
        assert resp3.status_code == 200
        data = resp3.json()["data"]
        assert data["session"]["status"] == "approved"
        assert "重构登录模块" in data["execute_prompt"]
        assert "梳理现状" in data["execute_prompt"]

    def test_reject_decision(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [QUESTIONS_R1, PLAN_RESULT])
        sid = resp.json()["data"]["session"]["session_id"]
        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store), \
             patch.object(plans_mod, "_build_llm_bridge", return_value=_fake_llm_factory([PLAN_RESULT])):
            client.post(f"/plans/sessions/{sid}/answers", json={"answers": ANSWERS})
            resp2 = client.post(f"/plans/sessions/{sid}/decision", json={"action": "reject"})
        assert resp2.json()["data"]["session"]["status"] == "rejected"

    def test_other_users_session_is_404(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [QUESTIONS_R1])
        sid = resp.json()["data"]["session"]["session_id"]
        # 用户 B 的客户端
        _, client_b, _, _ = _make_client(user={"user_id": "u2", "role": "user"})
        resp2 = client_b.get(f"/plans/sessions/{sid}")
        assert resp2.status_code == 404

    def test_empty_answers_rejected_400(self, env):
        plans_mod, client, manager, store, agent = env
        resp = self._start(plans_mod, client, manager, store, agent, [QUESTIONS_R1])
        sid = resp.json()["data"]["session"]["session_id"]
        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store), \
             patch.object(plans_mod, "_build_llm_bridge", return_value=_fake_llm_factory([QUESTIONS_R1])):
            resp2 = client.post(f"/plans/sessions/{sid}/answers", json={"answers": [], "supplement": " "})
        assert resp2.status_code == 400

    def test_unknown_session_404(self, env):
        plans_mod, client, manager, store, _ = env
        with patch.object(plans_mod, "_get_session_manager", return_value=manager), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.get("/plans/sessions/ghost")
        assert resp.status_code == 404


class TestPlanDocuments:
    def test_list_and_preview(self, env):
        plans_mod, client, manager, store, agent = env
        saved = store.save(agent_id="default", title="重构登录模块", content=PLAN_RESULT["markdown"])

        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.get("/plans/documents", params={"agent_id": "default"})
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()["data"]["documents"]]
        assert saved["name"] in names

        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp2 = client.get(f"/plans/documents/{saved['name']}", params={"agent_id": "default"})
        assert resp2.status_code == 200
        data = resp2.json()["data"]
        assert data["content"] == PLAN_RESULT["markdown"]
        assert data["rel_path"] == saved["rel_path"]

    def test_traversal_name_400(self, env):
        plans_mod, client, manager, store, agent = env
        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.get("/plans/documents/..%2Fx.md", params={"agent_id": "default"})
        assert resp.status_code == 400

    def test_missing_document_404(self, env):
        plans_mod, client, manager, store, agent = env
        with patch.object(plans_mod, "_get_agent", return_value=agent), \
             patch.object(plans_mod, "_get_doc_store", return_value=store):
            resp = client.get(
                "/plans/documents/20260101-000000-ghost.md", params={"agent_id": "default"}
            )
        assert resp.status_code == 404
