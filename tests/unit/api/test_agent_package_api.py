# -*- coding: utf-8 -*-
"""OpenClaw 对比 #16：Claw 式 agent 应用包（agent package manifest v1）。

一清单 = 多 agent 面（配置/技能/调度任务/MCP 引用）+ provenance。
语义约定：
- 导出：GET /v1/agents/{id}/export-package → manifest v1 JSON
  * skills/cron 实时读取真实子系统（SkillService / AgentScheduler）
  * MCP 只出"引用"（server id/name/transport），env/headers/凭据脱敏
  * provenance：导出时间/来源系统/包版本，不含秘密
- 导入：POST /v1/agents/import-package → 重建 agent + 登记技能 + 导入 cron
  * agent_id 冲突 → 409（不静默覆盖）
  * manifest 非法 → 422（结构校验 fail-closed）
  * 导入失败 → 回滚（删除已建 agent 运行时与登记，不留半成品）
- 隔离：非属主导出 → 403（owner_user_id 契约对齐既有 agent 端点）
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MANIFEST_V1 = {
    "manifest_version": 1,
    "kind": "neurova.agent-package",
    "agent": {
        "name": "PackAgent",
        "description": "exported agent",
        "model": "test-model",
        "provider": "test-provider",
        "personality": "",
        "constitution": "",
    },
    "skills": [{"id": "skill-a", "name": "Skill A", "version": "1.0.0"}],
    "cron": [
        {
            "name": "daily-report",
            "action": "send_message",
            "cron_expression": "0 9 * * *",
            "parameters": {"message": "hello"},
        }
    ],
    "mcp": [{"id": "srv-1", "name": "Server One", "transport": "stdio"}],
    "provenance": {
        "exported_at": "2026-09-04T00:00:00Z",
        "source": "neurova",
        "package_version": 1,
    },
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离环境：CWD 切 tmp（agent_workspaces/data 均为 CWD 相对）。"""
    monkeypatch.chdir(tmp_path)
    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state

    reset_config_manager()
    set_app_state(None)
    yield tmp_path
    set_app_state(None)
    reset_config_manager()


@pytest.fixture()
def client():
    from neurova.api.endpoints import agent_package
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(agent_package.router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "role": "admin",
        "username": "admin",
    }
    return TestClient(app)


def _seed_runtime_agent(env: Path, agent_id: str = "packa") -> dict:
    """向 app state 塞一个假 agent（带 config 面），并落 agent_config.json。"""
    from neurova.api.endpoints import set_app_state

    ws = env / "agent_workspaces" / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    cfg_data = {
        "name": "PackAgent",
        "description": "exported agent",
        "model": "test-model",
        "provider": "test-provider",
        "personality": "",
        "constitution": "",
        "owner_user_id": "u1",
    }
    (ws / "agent_config.json").write_text(
        json.dumps(cfg_data, ensure_ascii=False), encoding="utf-8"
    )
    _aid = agent_id

    class _Cfg:
        agent_id = _aid
        name = "PackAgent"
        description = "exported agent"
        workspace_path = str(ws)
        owner_user_id = "u1"

        class llm_config:  # noqa: N801 - 模拟嵌套属性面
            model = "test-model"

        llm_provider = "test-provider"
        enable_memory = True
        personality = ""
        constitution = ""

    class _FakeAgent:
        config = _Cfg()

    set_app_state({"agents": {agent_id: _FakeAgent()}})
    return cfg_data


# ═══════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════


def test_export_returns_manifest_v1(client, env):
    _seed_runtime_agent(env)
    resp = client.get("/v1/agents/packa/export-package")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "neurova.agent-package"
    assert body["manifest_version"] == 1
    assert body["agent"]["name"] == "PackAgent"
    assert body["agent"]["model"] == "test-model"
    assert "provenance" in body and body["provenance"]["source"] == "neurova"


def test_export_404_for_unknown_agent(client, env):
    resp = client.get("/v1/agents/nope/export-package")
    assert resp.status_code == 404


def test_export_config_only_agent_reads_nested_config(client, env, monkeypatch):
    """config_only（仅登记面、无运行时）agent 导出：model/provider 嵌在
    agents.json 的 config 键下，必须读得到（防断点：dict 分支只读顶层
    会让导出面恒空）。"""
    from neurova.agent_config import get_config_manager

    get_config_manager().create_agent(
        agent_id="cfgonly",
        name="CfgAgent",
        description="config only",
        config={"model": "m-1", "provider": "p-1"},
    )
    body = client.get("/v1/agents/cfgonly/export-package").json()
    assert body["agent"]["name"] == "CfgAgent"
    assert body["agent"]["model"] == "m-1"
    assert body["agent"]["provider"] == "p-1"


def test_export_forbidden_for_non_owner(client, env):
    """三层隔离契约：非属主不得导出他人 agent（对齐 agent.py _user_can_access_agent）。"""
    _seed_runtime_agent(env)
    from neurova.api.auth import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "intruder",
        "role": "user",
        "username": "other",
    }
    resp = client.get("/v1/agents/packa/export-package")
    assert resp.status_code == 403


def test_export_redacts_mcp_secrets(client, env, monkeypatch):
    """MCP 引用面必须脱敏：env/headers/command 不出现在导出物。"""
    _seed_runtime_agent(env)

    class _Mgr:
        def list_mcp_servers(self):
            return [
                {
                    "id": "srv-1",
                    "name": "Server One",
                    "transport": "stdio",
                    "command": "/usr/local/bin/secret-agent",
                    "args": ["--token", "abc123"],
                    "env": {"API_KEY": "supersecret"},
                    "headers": {"Authorization": "Bearer xyz"},
                    "url": "http://127.0.0.1:9999/sse",
                    "enabled": True,
                    "timeout_ms": 30000,
                }
            ]

    import neurova.api.endpoints.agent_package as ap

    monkeypatch.setattr(ap, "_list_mcp_servers", lambda: _Mgr().list_mcp_servers())

    body = client.get("/v1/agents/packa/export-package").json()
    assert body["mcp"][0]["id"] == "srv-1"
    assert body["mcp"][0]["transport"] == "stdio"
    raw = json.dumps(body)
    assert "supersecret" not in raw
    assert "abc123" not in raw
    assert "secret-agent" not in raw
    assert "Bearer xyz" not in raw
    assert "env" not in body["mcp"][0]
    assert "headers" not in body["mcp"][0]


def test_export_reads_skills_from_skillservice(client, env, monkeypatch):
    """skills 实时读 SkillService(agent_id).list_skills()（真实安装面）。"""

    import neurova.api.endpoints.agent_package as ap

    class _Svc:
        def __init__(self, agent_id):
            assert agent_id == "packa"

        def list_skills(self):
            return [
                {"id": "skill-a", "name": "Skill A", "version": "1.0.0", "enabled": True},
                {"id": "skill-b", "name": "Skill B", "version": "2.1.0", "enabled": True},
            ]

    monkeypatch.setattr(ap, "_SkillService", _Svc)
    _seed_runtime_agent(env)
    body = client.get("/v1/agents/packa/export-package").json()
    assert {s["id"] for s in body["skills"]} == {"skill-a", "skill-b"}


def test_export_reads_cron_from_scheduler(client, env, monkeypatch):
    """cron 实时读 AgentScheduler.list_tasks() 并只收该 agent 的任务。"""

    import neurova.api.endpoints.agent_package as ap

    class _Task:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    monkeypatch.setattr(
        ap,
        "_list_scheduler_tasks",
        lambda: [
            _Task(
                task_id="t1",
                name="daily-report",
                action="send_message",
                agent_id="packa",
                cron_expression="0 9 * * *",
                interval_seconds=None,
                scheduled_at=None,
                parameters={"message": "hello"},
                description="",
            ),
            _Task(
                task_id="t2",
                name="other-agent-task",
                action="send_message",
                agent_id="someone-else",
                cron_expression="*/5 * * * *",
                interval_seconds=None,
                scheduled_at=None,
                parameters={},
                description="",
            ),
        ],
    )
    _seed_runtime_agent(env)
    body = client.get("/v1/agents/packa/export-package").json()
    assert len(body["cron"]) == 1
    assert body["cron"][0]["name"] == "daily-report"
    assert body["cron"][0]["cron_expression"] == "0 9 * * *"


# ═══════════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════════


def _post_import(client, manifest, agent_id="packa"):
    return client.post(
        "/v1/agents/import-package",
        json={"manifest": manifest, "agent_id": agent_id, "import_skills": False,
              "import_cron": False, "import_mcp": False},
    )


def test_import_creates_agent(client, env):
    resp = _post_import(client, MANIFEST_V1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["agent_id"] == "packa"

    # agent 真实落盘：workspace + agent_config.json + agents.json 登记
    ws = env / "agent_workspaces" / "packa"
    assert (ws / "agent_config.json").exists()
    from neurova.agent_config import get_config_manager

    assert get_config_manager().get_agent("packa") is not None


def test_import_rejects_bad_manifest(client, env):
    """manifest 结构非法 → 422 fail-closed（缺 kind/version/agent）。"""
    for broken in (
        {},
        {"kind": "neurova.agent-package"},
        {"manifest_version": 1},
        {"kind": "neurova.agent-package", "manifest_version": 1},
        {"kind": "other-kind", "manifest_version": 1, "agent": {}},
        {"kind": "neurova.agent-package", "manifest_version": 2, "agent": {}},
    ):
        resp = _post_import(client, broken)
        assert resp.status_code == 422, (broken, resp.status_code)


def test_import_conflict_409(client, env):
    _post_import(client, MANIFEST_V1)
    resp = _post_import(client, MANIFEST_V1)
    assert resp.status_code == 409


def test_import_rollback_on_failure(client, env, monkeypatch):
    """技能导入抛错 → 已建的 agent 必须回滚删除，不留半成品。"""
    import neurova.api.endpoints.agent_package as ap

    def _boom(*a, **kw):
        raise RuntimeError("skill install exploded")

    monkeypatch.setattr(ap, "_import_skills", _boom)
    resp = client.post(
        "/v1/agents/import-package",
        json={"manifest": MANIFEST_V1, "agent_id": "packa",
              "import_skills": True, "import_cron": False, "import_mcp": False},
    )
    assert resp.status_code == 500
    # 回滚断言：workspace 已删、agents.json 无登记、app state 无运行时
    assert not (env / "agent_workspaces" / "packa").exists()
    from neurova.agent_config import get_config_manager

    assert get_config_manager().get_agent("packa") is None


def test_import_cron_creates_scheduler_tasks(client, env, monkeypatch):
    created = {}

    def _fake_schedule(**kw):
        created.update(kw)

        class _T:
            task_id = "new-task"

        return _T()

    import neurova.api.endpoints.agent_package as ap

    monkeypatch.setattr(ap, "_schedule_cron_task", _fake_schedule)
    resp = client.post(
        "/v1/agents/import-package",
        json={"manifest": MANIFEST_V1, "agent_id": "packa",
              "import_skills": False, "import_cron": True, "import_mcp": False},
    )
    assert resp.status_code == 200, resp.text
    assert created["name"] == "daily-report"
    assert created["cron_expression"] == "0 9 * * *"
    assert created["agent_id"] == "packa"


def test_import_invalid_agent_id_422(client, env):
    resp = _post_import(client, MANIFEST_V1, agent_id="../evil")
    assert resp.status_code == 422


def test_import_skill_registration_failure_rolls_back(client, env, monkeypatch):
    """register_auto_skill 返回 bool（False=登记故障）——登记失败必须触发
    回滚而非静默吞掉（防回归：原实现 isinstance(result, dict) 对 bool
    恒 False，登记故障被当作成功）。"""
    import neurova.api.endpoints.agent_package as ap

    class _Svc:
        def __init__(self, agent_id):
            pass

        def get_skill_info(self, sid):
            return None  # 始终"不存在"→ 走 register 分支

        def register_auto_skill(self, **kw):
            return False  # 模拟登记故障

    monkeypatch.setattr(ap, "_SkillService", _Svc)
    resp = client.post(
        "/v1/agents/import-package",
        json={"manifest": MANIFEST_V1, "agent_id": "packa",
              "import_skills": True, "import_cron": False, "import_mcp": False},
    )
    assert resp.status_code == 500
    assert not (env / "agent_workspaces" / "packa").exists()  # 回滚三清


def test_import_idempotent_existing_skill(client, env, monkeypatch):
    """技能已存在 → 幂等成功（不回滚、计入 imported 列表）。"""
    import neurova.api.endpoints.agent_package as ap

    class _Svc:
        def __init__(self, agent_id):
            pass

        def get_skill_info(self, sid):
            return {"id": sid}  # 已存在

        def register_auto_skill(self, **kw):
            raise AssertionError("已存在时不得再调 register")

    monkeypatch.setattr(ap, "_SkillService", _Svc)
    resp = client.post(
        "/v1/agents/import-package",
        json={"manifest": MANIFEST_V1, "agent_id": "packa",
              "import_skills": True, "import_cron": False, "import_mcp": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"]["skills"] == ["skill-a"]


def test_export_import_description_roundtrip(client, env):
    """description 跨机迁移闭环（E2E 实测抓到的双断点防回归）：
    ① 导出侧——workspace 文件 description 为空时必须回查中枢登记面
      （AgentConfig 无 description 属性，登记面是描述的持久真值源）；
    ② 导入侧——hasattr(config, 'description') 恒 False 使描述静默跳过，
      必须动态 setattr 让 _save_agent_config 落盘。"""
    from neurova.agent_config import get_config_manager
    from neurova.api.endpoints import get_app_state

    # 场景①：workspace 文件与运行时 config 的描述都为空，描述只在登记面
    # （真实世界的存量形态：AgentConfig 无 description 属性 → 运行时面
    # 无此信息，登记面是唯一持久真值源）
    _seed_runtime_agent(env)
    ws_cfg_path = env / "agent_workspaces" / "packa" / "agent_config.json"
    ws_cfg = json.loads(ws_cfg_path.read_text(encoding="utf-8"))
    ws_cfg["description"] = ""
    ws_cfg_path.write_text(json.dumps(ws_cfg, ensure_ascii=False), encoding="utf-8")
    _agent = get_app_state()["agents"]["packa"]
    if hasattr(_agent.config, "description"):
        _agent.config.description = ""
    get_config_manager().create_agent(
        agent_id="packa", name="PackAgent", description="迁移描述",
        config={"model": "test-model", "provider": "test-provider"},
    )

    manifest = client.get("/v1/agents/packa/export-package").json()
    assert manifest["agent"]["description"] == "迁移描述"

    # 场景②：目标机重导入 → 描述落进新 workspace 文件
    get_config_manager().delete_agent("packa")
    resp = client.post(
        "/v1/agents/import-package",
        json={"manifest": manifest, "agent_id": "packa2",
              "import_skills": False, "import_cron": False, "import_mcp": False},
    )
    assert resp.status_code == 200, resp.text
    ws_cfg2 = json.loads(
        (env / "agent_workspaces" / "packa2" / "agent_config.json").read_text(encoding="utf-8")
    )
    assert ws_cfg2["description"] == "迁移描述", ws_cfg2
