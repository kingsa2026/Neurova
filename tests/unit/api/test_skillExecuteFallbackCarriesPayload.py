"""技能执行端点降级分支读错字段（红→绿）

`registry.execute_skill()` 返回的是运行时 SkillResult（data 形状），而端点
降级分支读 `getattr(skill_result, "output", None)`——该字段在这份对象上不存在，
于是恒为 None，端点回 `result={"status": "ok"}`：**success=True 配一份编造的
空载荷**，评测台架/独立注册表拿到的"成功"里没有技能真正产出的东西。

判据：真注册表 + 真 Skill 实例走完整端点链路，响应载荷必须等于技能返回的 data。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import neurova.skills as skillsPackage
from neurova.api.auth import get_current_user
from neurova.api.endpoints import skill as skillEndpoint
from neurova.skill_system import Skill, SkillRegistry, SkillResult


class _EchoSkill(Skill):
    def __init__(self):
        super().__init__("echo_probe", "探针技能——只回显入参")

    async def execute(self, params, context=None):
        return SkillResult(success=True, data={"echo": dict(params or {})})


from neurova.api.endpoints import ENDPOINT_MODULES

# 前缀取自挂载注册表本身，避免测试与真实路径各说各话
_BASE = "/api" + next(
    p for modulePath, p, _desc in ENDPOINT_MODULES
    if modulePath == "neurova.api.endpoints.skill"
)


def _client(monkeypatch, registry):
    """把注册表接到生产装配点上（端点自己就是从这里取注册表的）。"""
    monkeypatch.setattr(skillsPackage, "get_skill_registry", lambda *a, **k: registry)
    monkeypatch.setattr(
        "neurova.api.endpoints.get_agent_instance", lambda agent_id="": None
    )
    app = FastAPI()
    app.include_router(skillEndpoint.router, prefix=_BASE)
    app.dependency_overrides[get_current_user] = lambda: None
    return TestClient(app)


def testFallbackBranchCarriesTheSkillPayload(monkeypatch):
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    client = _client(monkeypatch, registry)

    resp = client.post(f"{_BASE}/echo_probe/execute", json={"parameters": {"q": 1}})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert body["result"] == {"echo": {"q": 1}}, (
        f"降级分支没透出技能真实载荷，拿到的是：{body['result']!r}"
    )
