# -*- coding: utf-8 -*-
"""K1 恢复面红测：检查点列表 / 恢复 API（`/v1/agents/{id}/checkpoints*`）。

红：端点不存在 → 404/ModuleNotFoundError。
绿：两轮对话 → 列表 ≥1 个 auto 快照 → 恢复到旧 ref → 会话状态回到旧点
（messages 对齐）→ 再写新消息 → pre-restore 快照存在；恢复写审计（fail-open）；
归属门沿用 agent_access 单源（非属主非 admin 403）。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_ID = "cpa1"
SESSION_ID = "sess-k1"


class _Cfg:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class _Agent:
    """最小 agent 替身（与生产同源：session_manager 是真单例）。"""

    def __init__(self, agent_id: str, session_manager):
        self.config = _Cfg(agent_id)
        self.session_manager = session_manager
        self.memory_agent = None
        self.context_orchestrator = None
        self.turn_count = 0
        self.checkpoints_enabled = True


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from neurova.session_manager import SessionManager
    from neurova.api.endpoints import set_app_state

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    # tmp_path 裸仓库不继承本仓 git config，也不吃全局身份——env 兜底，
    # 让红灯落在端点缺失/断言本身，而非环境缺 git 身份。
    monkeypatch.setenv("GIT_AUTHOR_NAME", "neurova-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "neurova-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "neurova-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "neurova-test@example.com")
    SessionManager._instance = None

    sm = SessionManager()
    agent = _Agent(AGENT_ID, sm)
    # 生产默认防抖 300s——测试里两轮对话要各留一个快照（恢复语义才有
    # 新旧之分），预挂一个防抖为 0 的 service（端点复用同一缓存实例）。
    from neurova.checkpoints.service import CheckpointService

    agent._checkpoint_service = CheckpointService(agent_id=AGENT_ID, debounce_seconds=0)
    set_app_state({"agents": {AGENT_ID: agent}})

    import neurova.security.audit_logger as auditModule

    savedInstance = auditModule.AuditLogger._instance
    savedGlobal = auditModule._audit_logger
    auditModule.AuditLogger._instance = None
    auditModule._audit_logger = None
    auditLogger = auditModule.AuditLogger(db_path=str(tmp_path / "audit.db"))
    auditModule._audit_logger = auditLogger

    yield SimpleNamespace(sm=sm, agent=agent, auditLogger=auditLogger)

    auditModule.AuditLogger._instance = savedInstance
    auditModule._audit_logger = savedGlobal
    set_app_state(None)
    SessionManager._instance = None


@pytest.fixture()
def client(env):
    from neurova.api.endpoints.agent_checkpoints_api import router
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "role": "admin",
        "username": "admin",
    }
    return TestClient(app)


def _auto_checkpoint(agent, session_id: str, user_input: str, reply: str) -> None:
    """与生产同一条写路径：ChatPipeline._auto_checkpoint。"""
    from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

    pipeline = ChatPipeline(agent)
    ctx = ChatContext(
        user_input=user_input, session_id=session_id, reply=reply, trace_id="tr-api"
    )
    asyncio.run(pipeline._auto_checkpoint(ctx))


def _turn(agent, user_input: str, reply: str) -> None:
    agent.turn_count += 1
    # P0-08：会话写侧显式声明属主（无主会话恢复会被 fail-closed 拒绝）
    agent.session_manager.add_message(
        AGENT_ID, SESSION_ID, user_input, reply, user_id="owner-1")
    _auto_checkpoint(agent, SESSION_ID, user_input, reply)


def test_checkpoint_list_and_restore_full_flow(client, env):
    sm = env.sm

    # ── 造两轮对话（每轮走真实 _auto_checkpoint 写快照）──
    _turn(env.agent, "第一问", "第一答")
    _turn(env.agent, "第二问", "第二答")

    # ── 列表：≥1 个 auto 快照，按时间降序，含时间戳与说明 ──
    resp = client.get(f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID})
    assert resp.status_code == 200, resp.text
    listing = resp.json()
    auto_refs = [item["ref"] for item in listing.get("auto", [])]
    assert len(auto_refs) >= 2, f"两轮对话应产生 ≥2 个 auto 快照：{listing}"
    assert all(item.get("timestamp") for item in listing["auto"]), "每个快照须带时间戳"
    # 降序：列表头是最新
    assert listing["auto"][0]["ref"] != listing["auto"][-1]["ref"]

    # ── 恢复到旧 ref（第一轮的快照 = 列表尾部）──
    old_ref = auto_refs[-1]
    resp = client.post(
        f"/v1/agents/{AGENT_ID}/checkpoints/{old_ref}/restore",
        json={"confirm": True},
    )
    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored.get("restored") is True

    # 会话状态回到旧点：messages 对齐（仅剩第一轮两条）
    history = sm.get_history(AGENT_ID, SESSION_ID)
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "第一问"),
        ("assistant", "第一答"),
    ], f"恢复后应回到第一轮状态：{history}"

    # pre-restore 留档在恢复时已产生
    resp = client.get(f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID})
    listing = resp.json()
    assert len(listing.get("pre_restore", [])) >= 1, "恢复必须自动留档 pre-restore"

    # ── 再写新消息：从恢复点继续生长，且新快照含恢复后的历史 ──
    _turn(env.agent, "第三问", "第三答")
    history = sm.get_history(AGENT_ID, SESSION_ID)
    assert [m["content"] for m in history] == ["第一问", "第一答", "第三问", "第三答"]

    resp = client.get(f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID})
    listing = resp.json()
    newest = listing["auto"][0]
    payload = json.loads(
        env.agent._checkpoint_service.restore_snapshot(newest["ref"])["session_json"]
    )
    assert [m["content"] for m in payload["messages"]] == [
        "第一问", "第一答", "第三问", "第三答",
    ], "恢复后的新快照必须基于恢复点继续累积，不许 resurrect 旧轮次"


def test_restore_requires_confirm(client, env):
    _turn(env.agent, "问", "答")
    refs = client.get(
        f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID}
    ).json()["auto"]
    resp = client.post(
        f"/v1/agents/{AGENT_ID}/checkpoints/{refs[0]['ref']}/restore",
        json={"confirm": False},
    )
    assert resp.status_code == 400, "未确认的恢复必须被拒绝"
    # 会话未被改动
    assert len(env.sm.get_history(AGENT_ID, SESSION_ID)) == 2


def test_restore_unknown_ref_404(client, env):
    resp = client.post(
        f"/v1/agents/{AGENT_ID}/checkpoints/refs/auto/{SESSION_ID}/99999999/restore",
        json={"confirm": True},
    )
    assert resp.status_code == 404, resp.text


def test_restore_forbidden_for_non_owner(env):
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints.agent_checkpoints_api import router

    _turn(env.agent, "问", "答")
    # 换成非属主非 admin 的身份：agent 无属主 → 仅 admin 可操作
    app = FastAPI()
    app.include_router(router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "someone-else",
        "role": "user",
        "username": "intruder",
    }
    intruder = TestClient(app)
    refs = intruder.get(
        f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID}
    )
    assert refs.status_code == 403, "无主 agent 对非 admin 必须 403"
    resp = intruder.post(
        f"/v1/agents/{AGENT_ID}/checkpoints/refs/auto/{SESSION_ID}/x/restore",
        json={"confirm": True},
    )
    assert resp.status_code == 403, "恢复他人 agent 的检查点必须 403"


def test_restore_writes_audit_event(client, env):
    _turn(env.agent, "问", "答")
    refs = client.get(
        f"/v1/agents/{AGENT_ID}/checkpoints", params={"session_id": SESSION_ID}
    ).json()["auto"]
    resp = client.post(
        f"/v1/agents/{AGENT_ID}/checkpoints/{refs[0]['ref']}/restore",
        json={"confirm": True},
    )
    assert resp.status_code == 200, resp.text

    entries = env.auditLogger.query(user_id="u1", limit=50)
    restore_events = [
        e for e in entries if "checkpoint" in str(e.action or "").lower()
    ]
    assert restore_events, "恢复这一敏感操作必须落审计（S8 同源，fail-open）"
    entry = restore_events[0]
    assert entry.resource_type == "checkpoint"
    assert SESSION_ID in json.dumps(entry.details, ensure_ascii=False, default=str)


def test_restore_preserves_explicit_session_owner(env):
    from neurova.api.endpoints.agent_checkpoints_api import _apply_restore

    env.sm.create_session(AGENT_ID, user_id="owner-1", title="原会话")
    env.sm.save_message(AGENT_ID, SESSION_ID, "user", "未来消息", user_id="owner-1")
    apply = _apply_restore(AGENT_ID, SESSION_ID)
    apply({"session_json": json.dumps({"messages": [
        {"role": "user", "content": "恢复消息"},
    ]}, ensure_ascii=False)})

    record = env.sm.get_session(AGENT_ID, SESSION_ID)
    assert record.user_id == "owner-1"
    assert record.title == "新对话"


def test_restore_assigns_emptyOwnerToPrimaryAdmin(env, monkeypatch):
    import neurova.post_chat_pipeline as pcp
    from neurova.api.endpoints.agent_checkpoints_api import _apply_restore

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    env.sm.create_session(AGENT_ID, user_id="", title="历史无主会话")
    apply = _apply_restore(AGENT_ID, SESSION_ID)
    apply({"session_json": json.dumps({"messages": [
        {"role": "user", "content": "恢复消息"},
    ]}, ensure_ascii=False)})

    assert env.sm.get_session(AGENT_ID, SESSION_ID).user_id == "3"


def test_restore_aborts_before_delete_when_owner_read_fails(env, monkeypatch):
    from neurova.api.endpoints.agent_checkpoints_api import _apply_restore

    env.sm.create_session(AGENT_ID, user_id="owner-1")
    env.sm.save_message(AGENT_ID, SESSION_ID, "user", "必须保留", user_id="owner-1")

    def unreadable(*args, **kwargs):
        raise OSError("磁盘读取失败")

    monkeypatch.setattr(env.sm, "get_session", unreadable)
    with pytest.raises(RuntimeError, match="属主"):
        _apply_restore(AGENT_ID, SESSION_ID)({"session_json": json.dumps({"messages": []})})
    assert [m["content"] for m in env.sm.get_history(AGENT_ID, SESSION_ID)] == ["必须保留"]


def test_restore_aborts_when_emptyOwnerCannotResolveAdmin(env, monkeypatch):
    import neurova.post_chat_pipeline as pcp
    from neurova.api.endpoints.agent_checkpoints_api import _apply_restore

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "")
    env.sm.create_session(AGENT_ID, user_id="")
    env.sm.save_message(AGENT_ID, SESSION_ID, "user", "必须保留", user_id="")
    with pytest.raises(RuntimeError, match="属主"):
        _apply_restore(AGENT_ID, SESSION_ID)({"session_json": json.dumps({"messages": []})})
    assert [m["content"] for m in env.sm.get_history(AGENT_ID, SESSION_ID)] == ["必须保留"]


def test_list_ungrouped_lists_all_sessions(client, env):
    """不带 session_id 时列出该 agent 全部会话的快照。"""
    sm = env.sm
    sm.add_message(AGENT_ID, "sess-other", "别会话问", "别会话答")
    _auto_checkpoint(env.agent, "sess-other", "别会话问", "别会话答")
    resp = client.get(f"/v1/agents/{AGENT_ID}/checkpoints")
    assert resp.status_code == 200, resp.text
    listing = resp.json()
    all_refs = listing.get("auto", [])
    assert any("sess-other" in item["ref"] for item in all_refs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
