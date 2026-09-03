# -*- coding: utf-8 -*-
"""会话自动标题契约测试（2026-09-03）。

需求：不要默认对话名（新对话/新建对话）——首轮完成后用语义概括自动填充。

契约：
1. `neurova.session_title.generate_semantic_title` 永不抛错：LLM 成功→清洗后
   标题；LLM 失败/超时/无客户端 → 回退首条用户消息截断；
2. `fallback_title` 去 markdown/网址/代码后截断；
3. 端点 POST /api/v1/console/chat/sessions/{id}/auto-title：
   - 会话不存在 → 404；无用户消息 → 400；他人会话 → 403；
   - 生成标题并 rename 持久化，返回 {session_id, title}。
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.session_repository import SessionRepository

# ── 测试替身 ───────────────────────────────────────────────


class _FakeRepo(SessionRepository):
    """最小可插拔仓库：只实现本测试用到的接口。"""

    def __init__(self, sessions=None, messages=None):
        self._sessions = sessions or []
        self._messages = messages or []
        self.renamed: list[tuple] = []  # (agent_id, session_id, title)

    def list_sessions(self, agent_id="", user_id=""):
        return self._sessions

    def get_history(self, agent_id, session_id, max_messages=0):
        return self._messages

    def rename_session(self, agent_id, session_id, title):
        self.renamed.append((agent_id, session_id, title))
        return True

    def create_session(self, agent_id, user_id="", title=""):
        raise NotImplementedError

    def save_message(self, agent_id, session_id, role, content, metadata=None):
        raise NotImplementedError

    def delete_session(self, agent_id, session_id):
        raise NotImplementedError

    def get_session(self, agent_id, session_id):
        raise NotImplementedError

    def archive_session(self, agent_id, session_id):
        raise NotImplementedError

    def unarchive_session(self, agent_id, session_id):
        raise NotImplementedError

    def list_archived_sessions(self, agent_id="", user_id=""):
        raise NotImplementedError

    def delete_round(self, agent_id, session_id, timestamp):
        raise NotImplementedError

    def update_message_metadata(self, agent_id, session_id, timestamp, metadata_patch, role=None):
        raise NotImplementedError

    def get_round(self, agent_id, session_id, timestamp):
        raise NotImplementedError


def _message(role: str, content: str) -> dict:
    return {"role": role, "content": content, "timestamp": "2026-09-03T00:00:00Z"}


# ── 生成器契约 ─────────────────────────────────────────────


def test_fallback_title_strips_markdown_and_truncates():
    from neurova.session_title import fallback_title

    content = "看 https://a.b/c 这个 `code` 和 **bold** 很重要的一长句话要通过二十个字符的限制考验"
    title = fallback_title(content)
    assert "https" not in title and "`" not in title and "**" not in title
    assert len(title) <= 20


def test_generate_semantic_title_uses_llm_and_cleans(monkeypatch):
    import neurova.session_title as st
    from neurova.llm import multi_model_client as mmc

    calls = {"prompt": ""}

    class _FakeLLM:
        async def chat(self, messages, **kwargs):
            calls["prompt"] = messages[-1]["content"]
            resp = types.SimpleNamespace(content='“汽车是什么”')
            return {"success": True, "response": resp}

    monkeypatch.setattr(mmc, "get_multi_model_client", lambda scope=None: _FakeLLM())

    import asyncio

    title = asyncio.run(st.generate_semantic_title("汽车是什么？"))
    assert title == "汽车是什么"
    assert "标题助手" in calls["prompt"]


def test_generate_semantic_title_false_success_falls_back(monkeypatch):
    import asyncio

    import neurova.session_title as st
    from neurova.llm import multi_model_client as mmc

    class _FakeLLM:
        async def chat(self, messages, **kwargs):
            return {"success": False, "error": "no key"}

    monkeypatch.setattr(mmc, "get_multi_model_client", lambda scope=None: _FakeLLM())
    title = asyncio.run(st.generate_semantic_title("只用一句话回答：火箭燃料是什么？"))
    assert "火箭燃料" in title


def test_generate_semantic_title_uses_injected_agent_client():
    """注入会话 agent 的 llm_client（带 provider/model 上下文）时优先使用。"""
    import asyncio
    import types

    import neurova.session_title as st

    class _AgentClient:
        async def chat(self, messages, **kwargs):
            return types.SimpleNamespace(content='量子计算入门')

    title = asyncio.run(st.generate_semantic_title("什么是量子计算？", "量子计算……", llm=_AgentClient()))
    assert title == "量子计算入门"


def test_generate_semantic_title_llm_raise_falls_back(monkeypatch):
    import asyncio

    import neurova.session_title as st
    from neurova.llm import multi_model_client as mmc

    class _BrokenLLM:
        async def chat(self, messages, **kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr(mmc, "get_multi_model_client", lambda scope=None: _BrokenLLM())
    title = asyncio.run(st.generate_semantic_title("讲一个关于大海的短故事"))
    assert "大海" in title


# ── 端点契约 ───────────────────────────────────────────────


@pytest.fixture()
def repo():
    # user_id 留空 = 共享语义（与 delete 端点测试口径一致），匿名请求可命中
    return _FakeRepo(
        sessions=[{"session_id": "s1", "agent_id": "a1", "user_id": "", "title": "新对话"}],
        messages=[_message("user", "汽车是什么？"), _message("assistant", "汽车是一种交通工具。")],
    )


@pytest.fixture()
def client(repo, monkeypatch):
    from neurova.api.endpoints import console as console_api

    monkeypatch.setattr(console_api, "get_session_repository", lambda: repo)
    app = FastAPI()
    app.include_router(console_api.router, prefix="/api/v1/console")
    return TestClient(app)


def test_auto_title_403_for_foreign_user(monkeypatch):
    from neurova.api.endpoints import console as console_api

    foreign_repo = _FakeRepo(
        sessions=[{"session_id": "s1", "agent_id": "a1", "user_id": "u2", "title": "新对话"}],
        messages=[_message("user", "私有内容")],
    )
    monkeypatch.setattr(console_api, "get_session_repository", lambda: foreign_repo)
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "u1"
        return await call_next(request)

    app.include_router(console_api.router, prefix="/api/v1/console")
    client = TestClient(app)
    resp = client.post("/api/v1/console/chat/sessions/s1/auto-title")
    assert resp.status_code == 403


def _patch_title(monkeypatch, title: str):
    import neurova.session_title as st

    async def fake_generate(*a, **kw):
        return title

    monkeypatch.setattr(st, "generate_semantic_title", fake_generate)


def test_auto_title_404_when_session_missing(client, monkeypatch, repo):
    resp = client.post("/api/v1/console/chat/sessions/nope/auto-title")
    assert resp.status_code == 404


def test_auto_title_400_when_no_user_message(client, monkeypatch):
    from neurova.api.endpoints import console as console_api

    console_api.get_session_repository = lambda: _FakeRepo(
        sessions=[{"session_id": "s1", "agent_id": "a1", "user_id": "", "title": "新对话"}],
        messages=[],
    )
    resp = client.post("/api/v1/console/chat/sessions/s1/auto-title")
    assert resp.status_code == 400


def test_auto_title_renames_with_semantic_title(client, monkeypatch, repo):
    _patch_title(monkeypatch, "汽车是什么")
    resp = client.post("/api/v1/console/chat/sessions/s1/auto-title")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["session_id"] == "s1"
    assert body["data"]["title"] == "汽车是什么"
    assert repo.renamed == [("a1", "s1", "汽车是什么")]
