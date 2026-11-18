"""S1 安全批（2026-11-16 审计修复）——属主门与管理员门测试。

覆盖条目：
- P1-1  console.py 聊天面（HTTP+WS）与会话操作面属主门（全命中点）；
- P1-2  agent.py 五端点（stats/switch/constitution/decision/rebuild-loop）属主门；
- P1-3  firewall.py 整 router 收 admin；
- P1-4  plugin.py 装载面（install/uninstall/load/unload/enable/disable）收 admin；
- P1-9  chat.py 附件 TODO 桩改显式 501（不谎报成功）；
- api-P2-1  skill_pool /private CRUD/push/execute 与 marketplace install/uninstall 属主门；
- §3.1-P2  neurflow 触发器/执行记录属主过滤 + SSE 匿名短路、协作模板属主、
  房间发言成员校验、shared_config 管理面收 admin。

属主口径统一复用 agent_access 单源：admin 全量；非 admin 仅属主；无主仅 admin。
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

_U1 = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
_U2 = {"user_id": "u2", "username": "bob", "role": "user", "neuser_id": "u2"}
_ROOT = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "root"}
_ANON = {"user_id": "default", "username": "default", "role": "user", "neuser_id": "default"}


class _Cfg:
    def __init__(self, owner):
        self.owner_user_id = owner


class _Agent:
    def __init__(self, agent_id, owner):
        self.agent_id = agent_id
        self.name = agent_id
        self.config = _Cfg(owner)


class _Req:
    """最小 Request 替体（端点只用 request 透传/取 id）。"""

    headers = {}

    class _S:
        user_id = "x"

    state = _S()


@pytest.fixture
def agent_state():
    """把全局 _app_state 指到测试 agents——agentOwnerById 的运行面取数源。"""
    from neurova.api.endpoints import set_app_state

    agents = {
        "mine": _Agent("mine", "u1"),
        "theirs": _Agent("theirs", "u2"),
    }
    set_app_state({"agents": agents})
    yield agents
    set_app_state(None)


# ── 通用：路由级 admin 门断言 ───────────────────────────────


def _route_dependencies(router, path: str, method: str):
    found = []
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", None) or set()):
            found.extend(getattr(route, "dependencies", []) or [])
    return found


def _hasAdminGate(router, path: str, method: str) -> bool:
    """路由依赖里存在 require_admin 的 check_role（对非 admin 身份抛 403）。"""
    for dep in _route_dependencies(router, path, method):
        fn = getattr(dep, "dependency", None)
        if fn is None:
            continue
        try:
            asyncio.run(fn(user={"user_id": "u1", "role": "user"}))
        except HTTPException as exc:
            if exc.status_code == 403:
                return True
        except TypeError:
            continue
    return False


# ── P1-1 console.py 属主门 ──────────────────────────────────


def test_console_chat_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import console as console_mod

    body = console_mod.ChatRequest(message="hi", agent_id="theirs", stream=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.post_console_chat(body=body, request=_Req(), current_user=_U1))
    assert exc.value.status_code == 403


def test_console_chat_nonexistent_agent_is_503(agent_state):
    """实例未装配 → 503（审计 §3.1-17 收口：原 200+"Echo" 是假成功）。

    S1 时期此处钉的是"不扩大拒绝面、维持 Echo 回退"；R4 依审计 §3.1-17
    把未装配从"200 假成功"改为显式 503，本用例随之改钉新契约。
    """
    from neurova.api.endpoints import console as console_mod

    body = console_mod.ChatRequest(message="hi", agent_id="ghost", stream=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.post_console_chat(body=body, request=_Req(), current_user=_U1))
    assert exc.value.status_code == 503


def test_console_ws_default_agent_gate_semantics(agent_state):
    """WS 腿同一判据：无主默认 agent 仅 admin；他人 agent 拒；属主/admin 放行。"""
    from neurova.api.endpoints import console as console_mod

    assert console_mod._agentAccessible("default", "u1", "user") is False
    assert console_mod._agentAccessible("theirs", "u1", "user") is False
    assert console_mod._agentAccessible("mine", "u1", "user") is True
    assert console_mod._agentAccessible("theirs", "root", "admin") is True


def test_console_ws_chat_leg_wires_the_gate():
    import inspect

    from neurova.api.endpoints import console as console_mod

    src = inspect.getsource(console_mod.websocket_console)
    assert "_agentAccessible" in src, "WS 腿 chat 分支必须过属主门"


def test_console_review_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import console as console_mod

    body = console_mod.ReviewRequest(content="diff text", agent_id="theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.post_console_chat_review(body=body, current_user=_U1))
    assert exc.value.status_code == 403


def _patch_session_repo(monkeypatch, agent_id: str) -> None:
    from neurova.api.endpoints import console as console_mod

    class _Repo:
        def find_session(self, session_id):
            return {"user_id": "u1", "agent_id": agent_id, "session_id": session_id}

    monkeypatch.setattr(console_mod, "get_session_repository", lambda: _Repo())


def test_console_auto_title_rejects_foreign_agent(agent_state, monkeypatch):
    from neurova.api.endpoints import console as console_mod

    _patch_session_repo(monkeypatch, "theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.auto_title_chat_session("sess1", _Req(), current_user=_U1))
    assert exc.value.status_code == 403


def test_console_delete_round_rejects_foreign_agent(agent_state, monkeypatch):
    from neurova.api.endpoints import console as console_mod

    _patch_session_repo(monkeypatch, "theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.delete_chat_round("sess1", "t1", request=_Req(), current_user=_U1))
    assert exc.value.status_code == 403


def test_console_feedback_rejects_foreign_agent(agent_state, monkeypatch):
    from neurova.api.endpoints import console as console_mod

    _patch_session_repo(monkeypatch, "theirs")
    body = console_mod.FeedbackRequest(session_id="sess1", timestamp="t1", feedback="like")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console_mod.post_chat_feedback(body=body, request=_Req(), current_user=_U1))
    assert exc.value.status_code == 403


# ── P1-2 agent.py 五端点 ────────────────────────────────────


@pytest.fixture
def agent_ep_env(agent_state, monkeypatch):
    from neurova.api.endpoints import agent as agent_ep

    monkeypatch.setattr(agent_ep, "_get_app_state", lambda: {"agents": agent_state})
    monkeypatch.setattr(agent_ep, "get_agent_from_state", lambda agent_id: agent_state.get(agent_id))
    return agent_ep


def test_agent_stats_rejects_non_owner(agent_ep_env):
    ep = agent_ep_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.get_agent_stats(_Req(), "theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_agent_stats_owner_allowed(agent_ep_env):
    ep = agent_ep_env
    resp = asyncio.run(ep.get_agent_stats(_Req(), "mine", current_user=_U1))
    assert resp.get("code") == 0


def test_switch_agent_non_admin_403(agent_ep_env):
    ep = agent_ep_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.switch_agent(_Req(), "theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_switch_agent_admin_allowed(agent_ep_env):
    ep = agent_ep_env
    resp = asyncio.run(ep.switch_agent(_Req(), "theirs", current_user=_ROOT))
    assert resp.get("code") == 0


def test_agent_decision_rejects_non_owner(agent_ep_env):
    ep = agent_ep_env
    body = ep.DecisionRequest(context="ctx")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.make_decision(_Req(), "theirs", body, current_user=_U1))
    assert exc.value.status_code == 403


def test_agent_rebuild_loop_rejects_non_owner(agent_ep_env):
    ep = agent_ep_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.rebuild_loop(_Req(), "theirs", model=None, current_user=_U1))
    assert exc.value.status_code == 403


def test_switch_escalation_chain_closed(agent_ep_env):
    """P1-2×P1-1 越权链闭环：非 admin 切不了全局默认；即便切了，WS 腿门也按属主拒。"""
    ep = agent_ep_env
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.switch_agent(_Req(), "theirs", current_user=_U1))
    assert exc.value.status_code == 403

    from neurova.api.endpoints import console as console_mod

    assert console_mod._agentAccessible("theirs", "u1", "user") is False


# ── P1-3 firewall.py 整 router 收 admin ─────────────────────


def test_firewall_router_admin_gated():
    from neurova.api.endpoints import firewall

    for path, method in (
        ("/rules", "GET"),
        ("/rules", "POST"),
        ("/rules/{rule_id}", "PUT"),
        ("/rules/{rule_id}", "DELETE"),
        ("/blocked", "GET"),
        ("/stats", "GET"),
    ):
        assert _hasAdminGate(firewall.router, path, method), f"{method} {path} 应仅管理员"


# ── P1-4 plugin.py 装载面收 admin ───────────────────────────


def test_plugin_loading_plane_admin_gated():
    from neurova.api.endpoints import plugin

    for path, method in (
        ("/{plugin_id}/install", "POST"),
        ("/{plugin_id}/uninstall", "DELETE"),
        ("/{plugin_id}/load", "POST"),
        ("/{plugin_id}/unload", "POST"),
        ("/{plugin_id}/enable", "POST"),
        ("/{plugin_id}/disable", "POST"),
    ):
        assert _hasAdminGate(plugin.router, path, method), f"{method} {path} 应仅管理员"


# ── P1-9 chat.py 附件桩显式 501 ─────────────────────────────


def test_chat_attachment_stub_returns_501():
    from neurova.api.endpoints import chat as chat_mod

    body = chat_mod.AttachmentRequest(file_path="/tmp/x.png", file_type="image")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat_mod.add_attachment(_Req(), body, current_user=_U1))
    assert exc.value.status_code == 501


# ── api-P2-1 skill_pool / marketplace 属主门 ────────────────


def test_skill_pool_private_list_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.list_private_skills(agent_id="theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_skill_pool_private_create_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    body = mod.SkillCreate(name="s1")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.create_private_skill(body=body, agent_id="theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_skill_pool_private_update_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    body = mod.SkillUpdate(description="x")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.update_private_skill("sk1", body=body, agent_id="theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_skill_pool_private_delete_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.delete_private_skill("sk1", agent_id="theirs", current_user=_U1))
    assert exc.value.status_code == 403


def test_skill_pool_push_rejects_foreign_source_and_target(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    body = mod.SkillPush(agent_id="theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.push_skill_to_agent("sk1", body=body, agent_id="mine", current_user=_U1))
    assert exc.value.status_code == 403

    body2 = mod.SkillPush(agent_id="mine")
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(mod.push_skill_to_agent("sk1", body=body2, agent_id="theirs", current_user=_U1))
    assert exc2.value.status_code == 403


def test_skill_pool_execute_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import skill_pool_api as mod

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.execute_private_skill("sk1", body={"agent_id": "theirs"}, current_user=_U1))
    assert exc.value.status_code == 403


def test_marketplace_install_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import marketplace as mp

    body = mp.SkillInstallRequest(agent_id="theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mp.install_skill(_Req(), "some-skill", body, current_user=_U1))
    assert exc.value.status_code == 403


def test_marketplace_uninstall_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints import marketplace as mp

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mp.uninstall_skill(_Req(), "some-skill", agent_id="theirs", current_user=_U1))
    assert exc.value.status_code == 403


# ── §3.1-P2 neurflow 触发器/执行记录 ────────────────────────


class _FakeStorage:
    def __init__(self, workflows=None, triggers=None, executions=None):
        self.workflows = workflows or {}
        self.triggers = triggers or {}
        self.executions = executions or {}

    def get_workflow(self, workflow_id, requester_id=None, is_admin=False, project_ids=None):
        wf = self.workflows.get(workflow_id)
        if wf is None:
            return None
        if is_admin or str(getattr(wf, "user_id", "") or "") == str(requester_id or ""):
            return wf
        return None  # deny≡404（与生产 storage 同构）

    def get_trigger(self, trigger_id):
        return self.triggers.get(trigger_id)

    def get_execution(self, execution_id):
        return self.executions.get(execution_id)


@pytest.fixture
def neurflow_env(monkeypatch):
    from neurova.api.endpoints import neurflow_api as api

    monkeypatch.setattr(api, "_requester_project_ids", lambda uid: set())
    return api


def test_neurflow_trigger_list_rejects_foreign_workflow(neurflow_env, monkeypatch):
    api = neurflow_env
    from neurova.api.endpoints import neurflow_triggers as mod

    storage = _FakeStorage(workflows={"wf1": SimpleNamespace(id="wf1", user_id="u2")})
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.list_workflow_triggers("wf1", current_user=_U1))
    assert exc.value.status_code == 404


def test_neurflow_trigger_delete_rejects_foreign_workflow(neurflow_env, monkeypatch):
    api = neurflow_env
    from neurova.api.endpoints import neurflow_triggers as mod

    storage = _FakeStorage(
        workflows={"wf1": SimpleNamespace(id="wf1", user_id="u2")},
        triggers={"trg1": SimpleNamespace(id="trg1", workflow_id="wf1")},
    )
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.delete_workflow_trigger("trg1", current_user=_U1))
    assert exc.value.status_code == 404


def test_neurflow_trigger_fire_rejects_foreign_workflow(neurflow_env, monkeypatch):
    api = neurflow_env
    from neurova.api.endpoints import neurflow_triggers as mod

    from neurova.collaboration.neurflow.models import WorkflowStatus

    storage = _FakeStorage(
        workflows={"wf1": SimpleNamespace(id="wf1", user_id="u2", status=WorkflowStatus.PUBLISHED)},
        triggers={"trg1": SimpleNamespace(id="trg1", workflow_id="wf1")},
    )
    monkeypatch.setattr(api, "_get_storage", lambda: storage)

    # 属主门必须先于派发：工作流已发布时，无门实现会真去构造执行器
    import neurova.agent.scheduler as scheduler_mod

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("属主门应先于派发触发，不应构造执行器")

    monkeypatch.setattr(scheduler_mod, "WorkflowTaskExecutor", _Boom)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.fire_trigger("trg1", body={}, current_user=_U1))
    assert exc.value.status_code == 404


def test_neurflow_executions_list_filters_by_requester(neurflow_env, monkeypatch):
    api = neurflow_env
    seen = {}

    class _S:
        def list_executions(self, workflow_id=None, status=None, user_id=None, limit=100, offset=0):
            seen["user_id"] = user_id
            return []

    monkeypatch.setattr(api, "_get_storage", lambda: _S())
    # 直调端点时 FastAPI 默认值是 Query 对象，显式传 None 走生产同一分支
    asyncio.run(api.list_executions(workflow_id=None, status=None, limit=100, offset=0, current_user=_U1))
    assert seen["user_id"] == "u1", "非 admin 执行记录列表必须按请求者过滤"

    asyncio.run(api.list_executions(workflow_id=None, status=None, limit=100, offset=0, current_user=_ROOT))
    assert seen["user_id"] is None, "admin 不过滤"


def test_neurflow_execution_detail_rejects_foreign(neurflow_env, monkeypatch):
    api = neurflow_env
    storage = _FakeStorage(executions={"ex1": SimpleNamespace(id="ex1", user_id="u2")})
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.get_execution("ex1", current_user=_U1))
    assert exc.value.status_code == 404


def test_neurflow_execution_variables_rejects_foreign(neurflow_env, monkeypatch):
    api = neurflow_env
    storage = _FakeStorage(executions={"ex1": SimpleNamespace(id="ex1", user_id="u2")})
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.get_execution_variables("ex1", current_user=_U1))
    assert exc.value.status_code == 404


def test_neurflow_execution_resume_rejects_foreign(neurflow_env, monkeypatch):
    api = neurflow_env
    storage = _FakeStorage(
        executions={"ex1": SimpleNamespace(id="ex1", user_id="u2", status="paused")}
    )
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.resume_execution("ex1", current_user=_U1))
    assert exc.value.status_code == 404


def _patch_sse_deps(monkeypatch, api, storage):
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    monkeypatch.setattr(
        api, "get_execution_event_recorder", lambda: SimpleNamespace(is_tracked=lambda eid: False)
    )
    monkeypatch.setattr(api, "get_workflow_executor", lambda: SimpleNamespace(_instances={}))


def test_neurflow_sse_admin_bypass_on_foreign_execution(neurflow_env, monkeypatch):
    """复核新增命中点 6：SSE 属主门缺 admin 通道——admin 订阅他人执行被 403。"""
    api = neurflow_env
    storage = _FakeStorage(
        executions={"ex1": SimpleNamespace(id="ex1", user_id="u2", status=None)}
    )
    _patch_sse_deps(monkeypatch, api, storage)
    resp = asyncio.run(api.stream_execution_events("ex1", after=0, current_user=_ROOT))
    assert resp is not None, "admin 应可订阅他人执行事件流"


def test_neurflow_sse_anonymous_denied_on_foreign_execution(neurflow_env, monkeypatch):
    """回归护栏：匿名/默认身份订阅他人执行必须 403（deny 方向不得回退）。"""
    api = neurflow_env
    storage = _FakeStorage(
        executions={"ex1": SimpleNamespace(id="ex1", user_id="u2", status=None)}
    )
    _patch_sse_deps(monkeypatch, api, storage)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.stream_execution_events("ex1", after=0, current_user=_ANON))
    assert exc.value.status_code == 403


# ── §3.1-P2 collaboration 模板属主 / 房间发言成员 ───────────


def _patch_collab_manager(monkeypatch, mod, project):
    monkeypatch.setattr(mod, "get_collaboration_manager", lambda: SimpleNamespace(get_project=lambda tid: project))


def test_collaboration_template_update_rejects_non_owner(monkeypatch):
    from neurova.api.endpoints import collaboration_api as mod

    project = SimpleNamespace(
        owner_id="u2", project_id="tpl1", name="n", description="d",
        metadata={}, members={}, created_at=0, updated_at=0,
    )
    _patch_collab_manager(monkeypatch, mod, project)
    body = mod.CollaborationTemplateCreate(name="hijack")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.update_collaboration_template(_Req(), "tpl1", body, current_user=_U1))
    assert exc.value.status_code == 403


def test_collaboration_template_delete_rejects_non_owner(monkeypatch):
    from neurova.api.endpoints import collaboration_api as mod

    project = SimpleNamespace(
        owner_id="u2", project_id="tpl1", name="n", description="d",
        metadata={}, members={}, created_at=0, updated_at=0,
    )
    _patch_collab_manager(monkeypatch, mod, project)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.delete_collaboration_template(_Req(), "tpl1", current_user=_U1))
    assert exc.value.status_code == 403


def test_room_message_rejects_non_member(monkeypatch):
    from neurova.api.endpoints import collaboration_room_api as mod

    project = SimpleNamespace(
        owner_id="u2", project_id="room1", members={"u2": {}, "agentA": {}}, metadata={},
    )
    _patch_collab_manager(monkeypatch, mod, project)
    body = mod.PostMessageBody(text="hello")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.post_room_message("room1", body, current_user=_U1))
    assert exc.value.status_code == 403


def test_room_message_member_allowed(monkeypatch):
    from neurova.api.endpoints import collaboration_room_api as mod

    project = SimpleNamespace(
        owner_id="u2", project_id="room1", members={"u2": {}}, metadata={},
    )
    _patch_collab_manager(monkeypatch, mod, project)

    class _Router:
        async def handle_user_message(self, *args, **kwargs):
            return None

    monkeypatch.setattr(mod, "get_room_turn_router", lambda: _Router())
    body = mod.PostMessageBody(text="hello")
    resp = asyncio.run(mod.post_room_message("room1", body, current_user=_U2))
    assert resp.get("code") == 0


# ── §3.1-P2 shared_config 管理面收 admin ────────────────────


def test_shared_config_admin_gated():
    from neurova.api.endpoints import shared_config as mod

    for path, method in (
        ("/", "PUT"),
        ("/llm-providers", "POST"),
        ("/llm-providers/{name}", "PUT"),
        ("/llm-providers/{name}", "DELETE"),
        ("/import", "POST"),
        ("/mcp-servers/{name}", "DELETE"),
    ):
        assert _hasAdminGate(mod.router, path, method), f"{method} {path} 应仅管理员"
