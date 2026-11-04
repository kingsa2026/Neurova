"""N0：BuildSession 就绪门与交互状态机。

判据：
1. 首次创建先出问题，状态 clarifying；不 ready 不得批准；
2. 回答齐全后 ready，批准生成 batch_id；
3. secret 回答只写 SecretStore，会话 JSON 不含明文；
4. 构建中 ask 进入 blocked，回答交互恢复 building；
5. 会话可跨实例重载。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.build_mode import build_session as bs


class _FakeSecretStore:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def secretStore(monkeypatch):
    store = _FakeSecretStore()
    monkeypatch.setattr(bs, "_secretStore", lambda: store)
    return store


def _assessment(ready: bool, questions=None, checklist=None):
    return json.dumps(
        {
            "ready": ready,
            "checklist": checklist
            or {
                "goal": ready,
                "target": ready,
                "nodes": ready,
                "params": ready,
                "env": ready,
                "permissions": ready,
                "budget": ready,
                "safe_version": True,
            },
            "build_plan": {"summary": "构建广告复盘工作流"},
            "questions": questions or [],
        },
        ensure_ascii=False,
    )


def _manager(tmp_path, responses):
    calls = {"n": 0}

    def llm(prompt):
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[index]

    return bs.BuildSessionManager(store_path=str(tmp_path / "build.json"), llm_call=llm)


@pytest.mark.asyncio
async def test_createAsksThenAnswerBecomesReady(tmp_path):
    manager = _manager(
        tmp_path,
        [
            _assessment(
                False,
                [
                    {
                        "id": "q1",
                        "question": "这条流程的目标是什么？",
                        "kind": "text",
                        "why": "目标不明",
                        "impact": "决定节点组合",
                    }
                ],
            ),
            _assessment(True),
        ],
    )

    session = await manager.create("帮我搭一条广告复盘流程", "agent-x", "u1")
    assert session.status == bs.STATUS_CLARIFYING
    assert session.rounds[0]["questions"][0]["id"] == "q1"

    with pytest.raises(bs.BuildSessionError):
        manager.approve(session.session_id, "u1")

    session = await manager.answer(
        session.session_id,
        [{"id": "q1", "selected": [], "custom": "按 ACOS 复盘并给出预算建议"}],
    )
    assert session.status == bs.STATUS_READY

    approved = manager.approve(session.session_id, "u1")
    assert approved.status == bs.STATUS_APPROVED
    assert approved.batch_id.startswith("build_batch_")


@pytest.mark.asyncio
async def test_secretAnswerGoesToSecretStoreNotSession(tmp_path, secretStore):
    manager = _manager(
        tmp_path,
        [
            _assessment(
                False,
                [
                    {
                        "id": "q1",
                        "question": "请提供 Amazon Ads client secret",
                        "kind": "secret",
                        "secret_key": "NEUROVA_AMAZON_ADS_CLIENT_SECRET",
                        "why": "拉真实报表需要",
                        "impact": "没有就不能真实投放",
                    }
                ],
            ),
            _assessment(True),
        ],
    )
    session = await manager.create("接亚马逊广告", "agent-x", "u1")
    session = await manager.answer(
        session.session_id,
        [
            {
                "id": "q1",
                "secret_value": "super-secret-value",
            }
        ],
    )

    assert secretStore.values["NEUROVA_AMAZON_ADS_CLIENT_SECRET"] == "super-secret-value"
    persisted = json.dumps(session.toDict(), ensure_ascii=False)
    assert "super-secret-value" not in persisted
    saved = (tmp_path / "build.json").read_text(encoding="utf-8")
    assert "super-secret-value" not in saved
    assert session.rounds[0]["answers"][0]["configured"] is True


@pytest.mark.asyncio
async def test_buildingQuestionPausesAndAnswerResumes(tmp_path):
    manager = _manager(tmp_path, [_assessment(True)])
    session = await manager.create("搭一条流程", "agent-x", "u1")
    manager.approve(session.session_id, "u1")
    manager.markBuilding(session.session_id)

    interaction = manager.ask(
        session.session_id,
        "画布在 1440 还是 390 宽度下优先？",
        kind="choice",
        options=["1440", "390"],
        why="布局检查需要",
    )
    assert interaction["status"] == "pending"
    assert manager.get(session.session_id).status == bs.STATUS_BLOCKED

    resumed = manager.answerInteraction(
        session.session_id,
        interaction["interaction_id"],
        {"selected": ["1440"]},
    )
    assert resumed.status == bs.STATUS_BUILDING
    assert resumed.interactions[0]["answer"]["selected"] == ["1440"]


@pytest.mark.asyncio
async def test_sessionReloadsAcrossInstances(tmp_path):
    manager = _manager(tmp_path, [_assessment(True)])
    session = await manager.create("搭一条流程", "agent-x", "u1")
    manager.approve(session.session_id, "u1")

    reloaded = bs.BuildSessionManager(store_path=str(tmp_path / "build.json"))
    assert reloaded.get(session.session_id).status == bs.STATUS_APPROVED
    assert reloaded.get(session.session_id).batch_id == session.batch_id


@pytest.mark.asyncio
async def test_missingLlmFailsClosed(tmp_path):
    manager = bs.BuildSessionManager(store_path=str(tmp_path / "build.json"))
    with pytest.raises(bs.BuildSessionError) as exc:
        await manager.create("搭一条流程", "agent-x", "u1")
    assert exc.value.code == "llm_failed"
