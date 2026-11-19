"""R4 收尾修复批（2026-11-16 审计 P2 清偿）——门控与诚实化契约测试。

覆盖：
- §3.1-7  logs DELETE 收 admin；§3.1-8  scheduler 任务 agent_id 属主门；
- §3.1-9  推送令牌注销绑属主；§3.1-10 share_tool 死功能面退役；
- §3.1-11 memory_timeline 恒空面 → 501；§3.1-14 WS 密钥不再硬编码；
- §3.1-15 pairing cancel/status 属主门；§3.1-16 浏览器状态分用户+限量；
- §3.1-17 console 未装配 503 + 重放尾 TTL 复活；§3.1-18 模拟状态标注；
- §3.1-19 访问日志 query 脱敏；
- §3.4-1 进化/TDD/人工输入桩诚实失败；§3.4-3 小艺渠道契约修复；
- §3.4-4 三模板节点类型全注册；§3.4-5 qqbot 令牌掩码；
- §3.4-6 wechat 签名恒时比较；§3.4-7 安装门 fail-closed；
- §3.4-9 AgentSkillManager 零消费方法退役；§3.4-11 计算节点属主/管理员门；
- §3.4-12 evolution 降级读数 + 渠道会话隔离键前缀；
- §3.5-4 出网/沙箱同步调用下沉；§3.5-5 FunASREngine 可导出；
- §3.5-7 qclaw app_secret Fernet 加密；§3.5-8 告警通道如实记状态；
- §3.5-9 CostTracker(pg) 退役；§3.5-11 防火墙 fail-closed；
- §3.5-12 aigc 服务层真实身份；url_guard 合一单源。
"""

import asyncio
import inspect
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_U1 = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
_U2 = {"user_id": "u2", "username": "bob", "role": "user", "neuser_id": "u2"}


class _Cfg:
    def __init__(self, owner):
        self.owner_user_id = owner


class _Agent:
    def __init__(self, agent_id, owner):
        self.agent_id = agent_id
        self.name = agent_id
        self.config = _Cfg(owner)


class _Req:
    headers = {}

    class _S:
        user_id = "x"

    state = _S()


@pytest.fixture
def agent_state():
    from neurova.api.endpoints import set_app_state

    agents = {
        "mine": _Agent("mine", "u1"),
        "theirs": _Agent("theirs", "u2"),
    }
    set_app_state({"agents": agents})
    yield agents
    set_app_state(None)


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


# ── §3.1-7 logs 清空收 admin ─────────────────────────────────────────────


def test_logs_delete_admin_gated():
    from neurova.api.endpoints.logs import router

    assert _hasAdminGate(router, "", "DELETE"), "DELETE /api/v1/logs 必须收管理员门"


# ── §3.1-8 scheduler 任务 agent_id 属主门 ────────────────────────────────


def test_scheduler_create_task_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints.scheduler import TaskCreate, create_task

    body = TaskCreate(name="t", action="noop", agent_id="theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_task(request=_Req(), body=body, current_user=_U1))
    assert exc.value.status_code == 403


def test_scheduler_update_task_rejects_foreign_agent(agent_state):
    from neurova.api.endpoints.scheduler import TaskUpdate, update_task

    body = TaskUpdate(agent_id="theirs")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(update_task(request=_Req(), task_id="t1", body=body, current_user=_U1))
    assert exc.value.status_code == 403


def test_scheduler_create_task_allows_own_agent(agent_state, monkeypatch):
    """阳性对照：属主 agent 的任务通过属主门、继续走正常创建路径
    （调度器以最小替身承接，门后逻辑非本条目范围）。"""
    from neurova.api.endpoints import scheduler as sched_mod

    class _Task:
        task_id = "t1"
        name = "t"
        description = ""
        scheduled_at = None
        interval_seconds = None
        cron_expression = None
        agent_id = "mine"
        action = "noop"
        status = "pending"
        created_at = time.time()
        updated_at = time.time()
        last_run_at = None
        next_run_at = None
        run_count = 0
        max_runs = None

    class _StubScheduler:
        def schedule_task(self, **kwargs):
            return _Task()

        def get_statistics(self):
            return {"is_running": True}  # 已在跑：ensure_scheduler_running 直通

    monkeypatch.setattr(sched_mod, "get_scheduler", lambda: _StubScheduler())

    from neurova.api.endpoints.scheduler import TaskCreate, create_task

    body = TaskCreate(name="t", action="noop", agent_id="mine")
    resp = asyncio.run(create_task(request=_Req(), body=body, current_user=_U1))
    assert resp.agent_id == "mine"


# ── §3.1-9 推送令牌注销绑属主 ────────────────────────────────────────────


def test_mobile_push_delete_binds_owner(monkeypatch, tmp_path):
    from fastapi import FastAPI as _App
    from fastapi.testclient import TestClient as _Client

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import mobile_push
    from neurova.notifications import push_store

    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    push_store.upsert_token("u1", "android", "tok-a", "dev-1")

    app = _App()
    app.include_router(mobile_push.router, prefix="/mobile")
    client = _Client(app)
    app.dependency_overrides[get_current_user] = lambda: dict(_U2)

    resp = client.delete("/mobile/push-tokens/dev-1")
    assert resp.status_code == 404, "他人设备注销必须 404（防枚举）"
    assert len(push_store.list_tokens_for_user("u1")) == 1

    app.dependency_overrides[get_current_user] = lambda: dict(_U1)
    resp = client.delete("/mobile/push-tokens/dev-1")
    assert resp.status_code == 200
    assert push_store.list_tokens_for_user("u1") == []


# ── §3.1-10 share_tool 死功能面退役 ──────────────────────────────────────


def test_share_tool_routes_retired():
    from neurova.api.endpoints.tool_layers import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/tools/share" not in paths, "share_tool 写入面已退役，不得复活"
    assert "/tools/shared-with-me" not in paths


# ── §3.1-11 memory_timeline 恒空面 → 501 ─────────────────────────────────


def test_memory_timeline_endpoints_are_501():
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints.memory_timeline_api import router

    app = FastAPI()
    app.include_router(router, prefix="/memory-timeline")
    app.dependency_overrides[get_current_user] = lambda: dict(_U1)
    client = TestClient(app, raise_server_exceptions=False)

    for path in ("/memory-timeline/recent", "/memory-timeline/stats"):
        resp = client.get(path)
        assert resp.status_code == 501, path
        assert "未实现" in resp.json()["detail"]
    resp = client.get("/memory-timeline/range", params={"start": "2026-01-01", "end": "2026-01-02"})
    assert resp.status_code == 501
    resp = client.get("/memory-timeline/grouped")
    assert resp.status_code == 501


# ── §3.1-14 WS 密钥不再硬编码 ────────────────────────────────────────────


def test_ws_secret_not_hardcoded():
    from neurova.api.endpoints import mobile_pairing as mp

    assert not hasattr(mp, "_DEFAULT_WS_SECRET"), "硬编码默认密钥必须移除"
    src = inspect.getsource(mp)
    assert "neurova-ws-secret-key-2026" not in src, "开发密钥字面量不得留在源码"
    # 开发形态：每进程随机密钥（两次取值同进程一致，但不是源码常量）
    s1 = mp._get_ws_secret()
    s2 = mp._get_ws_secret()
    assert s1 and s1 == s2
    assert s1 != "neurova-ws-secret-key-2026"


# ── §3.1-15 pairing cancel/status 属主门 ─────────────────────────────────


def _pairing_client(monkeypatch, as_user: str):
    from neurova.api.endpoints import mobile_pairing as mp

    mp._pairing_codes.clear()
    mp.resetDeviceRegistry()
    app = FastAPI()
    app.include_router(mp.router, prefix="/mobile")

    async def _uid():
        return as_user

    app.dependency_overrides[mp._get_current_user_id] = _uid
    return TestClient(app), mp


def test_pairing_cancel_rejects_foreign_user(monkeypatch):
    client, mp = _pairing_client(monkeypatch, as_user="u2")
    mp._pairing_codes["123456"] = {
        "code": "123456", "user_id": "u1", "status": "pending",
        "expires_at": time.time() + 300, "pairing_id": "p1",
    }
    resp = client.post("/mobile/pairing/cancel", json={"code": "123456"})
    assert resp.status_code == 404, "非属主撤码与码不存在同形 404"
    assert mp._pairing_codes["123456"]["status"] == "pending", "他人配对码不得被撤"


def test_pairing_status_rejects_foreign_user(monkeypatch):
    client, mp = _pairing_client(monkeypatch, as_user="u2")
    mp._pairing_codes["123456"] = {
        "code": "123456", "user_id": "u1", "status": "pending",
        "expires_at": time.time() + 300, "pairing_id": "p1",
    }
    resp = client.get("/mobile/pairing/status/123456")
    assert resp.status_code == 404, "非属主读状态与码不存在同形 404"


# ── §3.1-16 浏览器状态分用户 + 限量 ──────────────────────────────────────


def test_browser_state_isolated_and_bounded():
    from neurova.api.endpoints import computer as computer_mod

    computer_mod._browser_state.clear()
    computer_mod._browser_state_order.clear()

    computer_mod._recordBrowserNavigate("u1", "https://a.example.com")
    computer_mod._recordBrowserNavigate("u2", "https://b.example.com")

    assert computer_mod._browserStateFor("u1")["url"] == "https://a.example.com"
    assert computer_mod._browserStateFor("u2")["url"] == "https://b.example.com"
    assert computer_mod._browserStateFor("u1")["history"] == ["https://a.example.com"]

    for i in range(computer_mod._BROWSER_HISTORY_LIMIT + 10):
        computer_mod._recordBrowserNavigate("u1", f"https://p{i}.example.com")
    assert len(computer_mod._browserStateFor("u1")["history"]) == computer_mod._BROWSER_HISTORY_LIMIT

    # 用户数 LRU 封顶
    for i in range(computer_mod._BROWSER_STATE_MAX_USERS + 5):
        computer_mod._browserStateFor(f"bulk{i}")
    assert len(computer_mod._browser_state) <= computer_mod._BROWSER_STATE_MAX_USERS


# ── §3.1-17 console 重放尾 TTL 复活 ──────────────────────────────────────


def test_replay_tail_ttl_check_is_alive():
    from neurova.api.endpoints import console as console_mod

    sid = "sess-ttl"
    console_mod._replay_buffers[sid] = {
        "events": [(0, {"type": "chunk", "content": "x"})],
        "next_seq": 1,
        "last_active": time.time() - console_mod._REPLAY_BUFFER_TTL_SECONDS - 5,
    }
    try:
        assert console_mod._get_replay_tail(sid, 0) == [], "过期缓冲必须判空（原 TTL 判断恒假）"
    finally:
        console_mod._replay_buffers.pop(sid, None)


def test_console_echo_fake_success_removed():
    from neurova.api.endpoints import console as console_mod

    src = inspect.getsource(console_mod)
    assert 'f"Echo: {body.message}"' not in src, "agent 未装配回 200+Echo 是假成功，必须 503"


# ── §3.1-18 模拟状态显式标注 ─────────────────────────────────────────────


def test_agent_status_simulated_flag():
    from neurova.api.endpoints.agent_enhancement import AgentStatus, get_agent_status

    class _Req2:
        headers = {}
        state = type("_S", (), {"request_id": "r"})()

    resp = asyncio.run(get_agent_status(request=_Req2(), agent_id="no-such-agent"))
    assert resp.simulated is True, "无 get_status 的占位读数必须标 simulated"
    # 模型默认 False：真实读数不带模拟标记
    assert AgentStatus(agent_id="x").simulated is False


# ── §3.1-19 访问日志 query 脱敏 ──────────────────────────────────────────


def test_redact_query_masks_tokens_keeps_plain():
    from neurova.api.middleware import redactQuery

    q = "access_token=abc123&foo=bar&api_key=zzz&x=1"
    out = redactQuery(q)
    assert "abc123" not in out and "zzz" not in out
    assert "foo=bar" in out and "x=1" in out
    assert "<masked:" in out
    assert redactQuery("") == ""


# ── §3.4-1 进化/TDD/人工输入桩诚实失败 ───────────────────────────────────


def test_evolution_evaluate_optimize_not_implemented():
    from neurova.collaboration.neurflow.builtin import exec_evolution

    ctx = {"evolution": object()}
    for mode in ("evaluate", "optimize"):
        res = asyncio.run(exec_evolution({"mode": mode}, ctx))
        assert res["status"] == "failed", mode
        assert "not_implemented" in str(res.get("error"))


def test_tdd_node_not_implemented():
    from neurova.collaboration.neurflow.builtin import exec_tdd

    res = asyncio.run(exec_tdd({"test_spec": "x", "implementation_prompt": "y"}, {}))
    assert res["status"] == "failed"
    assert "not_implemented" in str(res.get("error"))


# ── §3.4-3 小艺渠道契约修复 ──────────────────────────────────────────────


def test_xiaoyi_factory_and_signature_use_extra():
    from neurova.channels.xiaoyi import XiaoYiAdapter, create_xiaoyi_adapter

    adapter = create_xiaoyi_adapter("ak", "sk", "agent-1")
    assert adapter.config.channel_type == "xiaoyi"
    assert adapter.config.extra.get("secret_key") == "sk"
    # 签名生成此前读 self.config.config（AttributeError）——现走 extra 必须出签名
    headers = adapter._generate_signature("GET", "wss://example.com/ws")
    assert headers.get("Authorization", "").startswith("SDK-HMAC-SHA256")


def test_xiaoyi_send_message_not_connected_is_false():
    from neurova.channels.xiaoyi import XiaoYiAdapter

    adapter = XiaoYiAdapter()
    adapter.authenticated = True
    adapter._connected = False
    assert asyncio.run(adapter.send_message("hi")) is False, "未连接发送必须如实失败"


# ── §3.4-4 三模板节点类型全注册 ──────────────────────────────────────────


def test_template_node_types_all_registered():
    """全部内置模板引用的节点类型必须在启动装配面可解析。

    注册源共三处（app.py 启动时全部挂上）：builtin.BUILTIN_EXECUTORS、
    drama_nodes、commerce_nodes。审计 §3.4-4 点名的 7 个类型此前三处皆无，
    现已补进 builtin；本测试钉住"模板引用 ⇒ 可解析"不再出现新缺口。
    """
    from neurova.collaboration.neurflow import commerce_nodes, drama_nodes
    from neurova.collaboration.neurflow.builtin import BUILTIN_EXECUTORS
    from neurova.collaboration.neurflow.templates import get_template_registry

    registered = set(BUILTIN_EXECUTORS)
    for pack in (drama_nodes, commerce_nodes):
        for attr in dir(pack):
            value = getattr(pack, attr)
            if isinstance(value, dict) and all(str(k).startswith("builtin:") for k in value):
                registered |= set(value)

    registry = get_template_registry()
    missing = []
    for template in registry.list_templates():
        for node in template.nodes:
            if node.type not in registered:
                missing.append((template.id, node.id, node.type))
    assert not missing, f"模板引用了未注册节点类型（实例化必失败）: {missing}"


# ── §3.4-5 qqbot 令牌掩码 / §3.4-6 wechat 恒时比较 ───────────────────────


def test_qqbot_config_masks_access_token():
    import inspect

    from neurova.channels.qqbot import QQBotAdapter

    src = inspect.getsource(QQBotAdapter.get_channel_config)
    assert '"***"' in src, "access_token 回显必须掩码（对照 base.py 掩码约定）"


def test_wechat_signature_uses_constant_time_compare():
    import inspect

    from neurova.channels.wechat_auth import WeChatAuthMixin

    src = inspect.getsource(WeChatAuthMixin.verify_signature)
    assert "compare_digest" in src, "签名比较必须恒时（hmac.compare_digest）"


# ── §3.4-7 安装门 fail-closed ────────────────────────────────────────────


def test_install_gate_blocks_when_registry_unavailable(monkeypatch):
    import neurova.skills.permissions as permissions_mod
    import neurova.builtin_tools as bt

    def _boom():
        raise RuntimeError("registry broken")

    monkeypatch.setattr(permissions_mod, "tools_for_categories", lambda *a, **k: set())
    monkeypatch.setattr(bt, "get_registered_tool_names", _boom, raising=False)

    from neurova.skills.skill_install_gate import validate_permissions_for_install

    result = validate_permissions_for_install({"tools": {"allow": ["any_tool"]}})
    assert result["blocked"] is True
    assert any("注册表不可用" in e for e in result["errors"])


# ── §3.4-9 AgentSkillManager 零消费方法退役 ──────────────────────────────


def test_agent_skill_manager_retired_methods():
    from neurova.skills.agent_skill_manager import AgentSkillManager

    assert not hasattr(AgentSkillManager, "acquire_skill")
    assert not hasattr(AgentSkillManager, "suggest_skills_for_task")


# ── §3.4-11 计算节点属主/管理员门 ────────────────────────────────────────


def test_computer_manager_owner_or_admin(monkeypatch, tmp_path):
    from neurova.collaboration.computer_manager import ComputerManager
    from neurova.models.computer import Computer

    mgr = ComputerManager(data_dir=str(tmp_path / "cm"))
    comp = mgr.create_computer(
        name="c1", owner_user_id="u1", company_id="corp",
    )
    assert comp is not None

    # 属主放行
    assert mgr.get_computer(comp.computer_id, user_id="u1") is not None
    # 他人（查无此人的数字 id → 非管理员）拒绝：公司后缀伪装不再放行
    assert mgr.get_computer(comp.computer_id, user_id="99999999") is None
    # 邮件形态的后缀旁路被移除
    assert mgr.get_computer(comp.computer_id, user_id="intruder@corp") is None


# ── §3.4-12 evolution 降级读数 + 渠道会话隔离键 ──────────────────────────


def test_evolution_module_load_failures_accessor():
    import neurova.evolution as evo

    failures = evo.moduleLoadFailures()
    assert isinstance(failures, dict)
    if not failures:
        assert evo.EvolutionOrchestrator is not None


def test_channel_scope_id_keeps_agent_prefix():
    from neurova.channels.manager import ChannelManager
    from neurova.channels.base import ChannelAdapter, ChannelConfig, ChannelMessage

    class _Stub(ChannelAdapter):
        channel_type = "stub"

        def __init__(self):
            super().__init__(ChannelConfig(channel_type="stub"))

        async def connect(self):
            return True

        async def disconnect(self):
            return None

        async def send_message(self, message, chat_id=None, **kwargs):
            return True

        def is_connected(self):
            return True

    mgr = ChannelManager.get_instance()
    adapter = _Stub()
    adapter.share_session_in_group = False
    mgr.register_adapter(adapter, agent_id="agentB")
    try:
        msg = ChannelMessage(
            channel_type="stub", message_id="m1", sender_id="s1",
            sender_name="s", content="hi", chat_id="group9",
            metadata={"agent_id": "agentB"},
        )
        scope = mgr.resolve_session_scope_id(msg)
        assert scope.startswith("agentB:"), f"非 default 实例私聊键丢了 agent 前缀: {scope}"
        assert scope == "agentB:group9:s1"
    finally:
        mgr._agent_adapters.pop(("agentB", "stub"), None)
        mgr._adapters.pop("stub", None)


# ── §3.5-4 同步阻塞调用下沉线程 ──────────────────────────────────────────


def test_sandbox_and_browser_use_to_thread():
    import neurova.computer_use.browser_manager as bm
    import neurova.sandbox.exec_sandbox as sandbox

    sandbox_src = inspect.getsource(sandbox)
    assert "asyncio.to_thread" in sandbox_src, "沙箱非 docker 路径必须下沉线程"
    nav_src = inspect.getsource(bm.ScraplingBackend.navigate)
    assert "asyncio.to_thread" in nav_src, "Scrapling 同步 fetch 必须下沉线程"


# ── §3.5-5 FunASREngine 可导出 ───────────────────────────────────────────


def test_asr_exports_funasr_engine():
    from neurova.asr import FunASREngine  # noqa: F401 - 原形 import 即 ImportError

    from neurova.asr import __all__ as asr_all

    assert "FunASREngine" in asr_all


# ── §3.5-6 用户更新日志只记字段名 ────────────────────────────────────────


def test_user_model_update_log_only_field_names():
    import inspect

    from neurova.auth.user_model import UserModel

    src = inspect.getsource(UserModel.update_user)
    assert "fields=%s" in src, "更新日志只记字段名"
    assert "kwargs)" not in src.split("fields=%s")[-1].split("\n")[0], "不得整包落 kwargs"


# ── §3.5-7 qclaw app_secret Fernet 加密 ─────────────────────────────────


def test_qclaw_secret_encrypted_at_rest(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.auth.qclaw_binding_model import QClawBindingModel

    model = QClawBindingModel()
    assert model.encryption_key, "不传密钥时必须自动解析默认密钥"

    encrypted = model._encrypt_secret("super-secret-app-secret")
    assert encrypted != "super-secret-app-secret"
    assert not encrypted.startswith("c3VwZXI"), "不得再是 Base64 可逆编码（Fernet 令牌形态）"

    decrypted = model._decrypt_secret(encrypted)
    assert decrypted == "super-secret-app-secret"
    # 旧 Base64 行仍可读（向后兼容）
    import base64 as _b64

    legacy = _b64.b64encode(b"legacy-secret").decode()
    assert model._decrypt_secret(legacy) == "legacy-secret"


# ── §3.5-8 告警通道如实记状态 ────────────────────────────────────────────


def test_cost_budget_alert_channel_status_honest():
    from neurova.models.cost_budget import (
        AlertChannel,
        AlertConfig,
        AlertLevel,
        BudgetManager,
        BudgetScope,
    )
    from decimal import Decimal

    mgr = BudgetManager()
    config = AlertConfig(
        level=AlertLevel.WARNING,
        percentage=Decimal("75.00"),
        channels=[AlertChannel.LOG, AlertChannel.SLACK, AlertChannel.EMAIL],
        message_template="usage {percentage}%",
    )
    mgr._send_alert(config, BudgetScope.AGENT, "agent-1", Decimal("80"))
    entry = mgr.get_alert_history(1)[0]
    status = entry["channel_status"]
    assert status["log"] == "sent"
    assert status["slack"] == "not_implemented"
    assert status["email"] == "not_implemented"


# ── §3.5-9 CostTracker(pg 形态) 退役 ─────────────────────────────────────


def test_cost_tracker_retired():
    import neurova.models.cost_tracking as ct

    assert not hasattr(ct, "CostTracker"), "PostgreSQL 形态 CostTracker 已退役"
    assert not hasattr(ct, "get_cost_tracker")
    assert not hasattr(ct, "reset_cost_tracker")
    # 在役入口仍在
    assert hasattr(ct, "record_llm_cost") and hasattr(ct, "track_llm_call")


# ── §3.5-11 防火墙校验 fail-closed ───────────────────────────────────────


def test_mcp_firewall_fail_closed():
    from neurova.tool_layers.mcp_client import MCPToolClient

    client = object.__new__(MCPToolClient)
    client._user_id = "u1"

    class _BrokenFirewall:
        def check_permission(self, *a, **k):
            raise RuntimeError("internal firewall bug")

    client._firewall = _BrokenFirewall()
    with pytest.raises(PermissionError):
        asyncio.run(client._check_firewall("some_tool", user_id="u1"))


# ── §3.5-12 aigc 服务层真实身份 ──────────────────────────────────────────


def test_aigc_services_no_hardcoded_admin_bypass():
    import inspect

    import neurova.aigc_studio.services as services

    src = inspect.getsource(services)
    assert 'get_project(pid, "admin"' not in src, "服务层不得硬编码管理员旁路取项目"


# ── url_guard 合一单源 ───────────────────────────────────────────────────


def test_url_guard_single_source_and_semantics(monkeypatch):
    import importlib.util

    import neurova.security.url_guard as guard

    # 旧第二份实现已退役
    assert importlib.util.find_spec("neurova.knowledge.url_guard") is None

    # knowledge 域兼容 API 落在单源上
    assert guard.validate_public_http_url("https://example.com/x") is True
    assert guard.validate_public_http_url("http://localhost/x") is False
    assert guard.validate_public_http_url("http://127.0.0.1/x") is False
    assert guard.validate_public_http_url("http://169.254.169.254/meta") is False
    assert guard.validate_public_http_url("ftp://example.com") is False
    # 信任名单：内网 MCP 合法目标
    assert guard.validate_public_http_url("http://mcp.internal:8123/x", trusted_hosts={"mcp.internal"}) is True
    # IPv4-mapped IPv6 环回不得绕过
    assert guard.validate_public_http_url("http://[::ffff:127.0.0.1]/x") is False
    # DNS 解析失败 fail-closed——不依赖真 DNS：本机 DNS 可能对任意域名做
    # wildcard 应答（实测 .invalid 也被解析到 198.18.0.156），真解析会让这条
    # 环境相关断言假红；mock 精确触发 fail-closed 分支本身。
    import socket as _socket

    def _failResolve(host, *args, **kwargs):
        raise _socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(_socket, "getaddrinfo", _failResolve)
    assert guard.validate_public_http_url("http://nonexistent-host-r4.invalid/x") is False


# ── 新执行器最小行为（§3.4-4 配套） ─────────────────────────────────────


def test_web_scrape_blocks_ssrf_target():
    from neurova.collaboration.neurflow.builtin import exec_web_scrape

    res = asyncio.run(exec_web_scrape({"url": "http://127.0.0.1:9527/"}, {}))
    assert res["status"] == "failed"
    assert "SSRF" in str(res.get("error")) or "禁止" in str(res.get("error"))


def test_doc_write_rejects_path_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.collaboration.neurflow.builtin import exec_doc_write

    res = asyncio.run(exec_doc_write({"content": "x", "format": "md", "file_name": "../escape.md"}, {}))
    assert res["status"] == "failed"

    ok = asyncio.run(exec_doc_write({"content": "hello", "format": "md", "file_name": "out.md"}, {}))
    assert ok["status"] == "success"
    assert (tmp_path / "data" / "neurflow_outputs" / "out.md").exists()
