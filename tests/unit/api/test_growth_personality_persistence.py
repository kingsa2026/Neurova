"""AgentPersonalityPage 人格特质保存假成功修复回归（2026-09-12 空数据页面排查）。

根因: Agent.personality 实为 personality.md 文本字符串（agent_core._load_identity），
而 GET/PUT /growth/personality 要求 isinstance(agent.personality, dict)——永假 →
GET traits 恒 {}、PUT 静默 no-op 仍返 200（假成功），特质编辑整页无效。

修复契约: traits/values/沟通与决策风格拥有独立持久源
data/personality/{agent_id}.json（与 personality.md 身份文本正交），
PUT 写盘、GET 从盘回读，重启不丢。
"""
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_personality_012345")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import growth


class _FakeAgent:
    """真实 Agent 的 personality 是 personality.md 字符串（无 dict 形态）"""
    def __init__(self):
        self.personality = "你是一个温柔且富有好奇心的伙伴。"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(growth, "_PERSONALITY_DIR", str(tmp_path / "personality"))

    def _fake(agent_id="default", *a, **k):
        return _FakeAgent()
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance", _fake)

    app = FastAPI()
    app.include_router(growth.router, prefix="/api/v1/growth")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


def _path(tmp_path, agent_id="a1"):
    return Path(str(tmp_path)) / "personality" / f"{agent_id}.json"


class TestPersonalityRoundTrip:
    def test_put_traits_persist_and_read_back(self, store):
        client, tmp = store
        traits = {"openness": 0.8, "agreeableness": 0.65, "extraversion": 0.2}
        r = client.put("/api/v1/growth/personality", params={"agent_id": "a1"},
                       json={"traits": traits})
        assert r.status_code == 200, r.text
        assert r.json()["traits"] == traits
        f = _path(tmp)
        assert f.exists(), "personality JSON 未落盘"
        assert json.loads(f.read_text(encoding="utf-8"))["traits"] == traits

    def test_get_reflects_saved_traits(self, store):
        client, _ = store
        client.put("/api/v1/growth/personality", params={"agent_id": "a1"},
                   json={"traits": {"curiosity": 0.9}})
        d = client.get("/api/v1/growth/personality", params={"agent_id": "a1"}).json()
        assert d["traits"] == {"curiosity": 0.9}

    def test_survives_restart(self, store):
        """独立文件即持久源：重发 GET（模拟新进程读盘）值仍在。"""
        client, _ = store
        client.put("/api/v1/growth/personality", params={"agent_id": "a1"},
                   json={"traits": {"discipline": 0.4}, "communication_style": "direct"})
        d = client.get("/api/v1/growth/personality", params={"agent_id": "a1"}).json()
        assert d["traits"] == {"discipline": 0.4}
        assert d["communication_style"] == "direct"

    def test_partial_update_merges(self, store):
        client, _ = store
        client.put("/api/v1/growth/personality", params={"agent_id": "a1"},
                   json={"traits": {"a": 0.1}, "values": ["诚实"]})
        client.put("/api/v1/growth/personality", params={"agent_id": "a1"},
                   json={"traits": {"a": 0.2}})
        d = client.get("/api/v1/growth/personality", params={"agent_id": "a1"}).json()
        assert d["traits"] == {"a": 0.2}
        assert d["values"] == ["诚实"]

    def test_missing_agent_404(self, store, monkeypatch):
        client, _ = store
        monkeypatch.setattr("neurova.api.endpoints.get_agent_instance",
                            lambda *a, **k: None)
        r = client.put("/api/v1/growth/personality", params={"agent_id": "nope"},
                       json={"traits": {"x": 0.1}})
        assert r.status_code == 404
