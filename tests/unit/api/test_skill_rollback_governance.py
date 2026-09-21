"""011 · 回滚与归档要有人按得动（后端切片）。

背景：`evolution/skill_experience.py` 的 `rollback_skill` / `get_archives`、
`evolution/rsi/rollback_manager.py` 的 `should_rollback` 在顶层 `neurova/`
**零生产调用方**——它们只管写状态，没人读。归档仅由 `rebuild_skill` 有界写入。

本文件钉三件事：

1. 回滚**留痕**只落 `config["revisions"]`（工单 016 硬约束：`improvements`
   那个无人读取的键已删净，不许加回来），且留痕带操作者与时间；
2. 治理面暴露 archive 读面与 rollback 写面，**未装配返 503**（不是
   `available:false` 的静默 200——那会把"没装配"读成"没有归档"）；
3. 归档为空时后端**拒绝**，不得静默成功。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

# 机制测试作用域：本文件验证归档/回滚面本身——评审闸的待审流由
# tests/unit/evolution/test_skill_review_gate.py 覆盖，故此处统一关闭闸
# （治理后默认开），否则 record_experience 进待审队列、攒不出重建阈值。
_GATE_PATCHER = None


def setUpModule():
    global _GATE_PATCHER
    import os
    from unittest.mock import patch

    _GATE_PATCHER = patch.dict(os.environ, {"NEUROVA_SKILL_REVIEW_GATE": "0"})
    _GATE_PATCHER.start()


def tearDownModule():
    if _GATE_PATCHER:
        _GATE_PATCHER.stop()


from neurova.evolution.skill_experience import (
    SkillExperienceStore,
    reset_skill_experience_store,
)


class _ArchiveSkill:
    def __init__(self, name: str = "sk_a"):
        self.name = name
        self.description = "base desc"
        self.version = "1.0.0"
        self.config: Dict[str, Any] = {}


class _ArchiveRegistry:
    def __init__(self):
        self._skills: Dict[str, Any] = {}

    def register(self, skill):
        self._skills[skill.name] = skill

    def get_skill(self, name):
        return self._skills.get(name)


class _ArchiveService:
    """真落盘：`apply_maintenance_update` 走真实 `SkillService` 语义。"""

    def __init__(self):
        self.updates: List[Dict[str, Any]] = []
        self.configs: List[Dict[str, Any]] = []

    def update_auto_skill(self, skill_id, version=None, config=None, name=None,
                          description=None, *, enforce_quality=None, **kwargs):
        self.updates.append({"skill_id": skill_id, "version": version})
        self.configs.append(dict(config or {}))
        return True


@pytest.fixture
def rolled(tmp_path):
    """造一条"已重建、有 1 份归档"的技能。"""
    reset_skill_experience_store()
    store = SkillExperienceStore(rebuild_threshold=1)
    registry = _ArchiveRegistry()
    skill = _ArchiveSkill()
    registry.register(skill)
    service = _ArchiveService()
    store.record_experience("sk_a", "guidance", registry=registry)
    assert store.rebuild_skill("sk_a", registry, skill_service=service) is True
    assert len(store.get_archives("sk_a")) == 1
    try:
        yield store, registry, skill, service
    finally:
        reset_skill_experience_store()


class TestRollbackLeavesATrace:
    def test_rollback_appends_revision_with_operator_and_time(self, rolled):
        store, registry, skill, service = rolled
        assert store.rollback_skill(
            "sk_a", registry, skill_service=service, operator="admin1"
        ) is True

        revisions = skill.config.get("revisions") or []
        assert revisions, "回滚没有留痕：配置里找不到任何修订记录"
        last = revisions[-1]
        assert last.get("trigger") == "rollback"
        assert last.get("operator") == "admin1", f"留痕没有操作者：{last}"
        assert last.get("rolled_back_at"), f"留痕没有时间：{last}"
        assert last.get("version_after") == "1.0.0"

    def test_rollback_does_not_recreate_improvements_key(self, rolled):
        """工单 016 硬约束：`improvements` 是无人读取的键，不许加回来。"""
        store, registry, skill, service = rolled
        store.rollback_skill("sk_a", registry, skill_service=service, operator="admin1")
        assert "improvements" not in skill.config, (
            "工单 016 已把 config['improvements'] 删净，回滚不得把它加回来"
        )

    def test_rollback_without_archives_is_refused(self, rolled):
        """归档为空 ⇒ 拒绝，不得静默成功（连带把 config 写脏）。"""
        store, registry, skill, service = rolled
        assert store.rollback_skill("sk_a", registry, skill_service=service) is True
        before = dict(skill.config)
        assert store.rollback_skill(
            "sk_a", registry, skill_service=service, operator="admin1"
        ) is False, "归档已空仍报成功——按钮点了没反应，且没人知道"
        assert skill.config == before, "被拒的回滚不得改动配置"


class TestGovernanceSurface:
    """治理面：归档读面 + 回滚写面。"""

    @staticmethod
    def _client(monkeypatch, context):
        """context=None 表示"治理面未装配"（真生产分支：agent 不在 state 里）。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import governance as gov_module

        app = FastAPI()
        app.include_router(gov_module.router, prefix="/api/v1/governance")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin1", "role": "admin",
        }
        monkeypatch.setattr(gov_module, "_skill_rollback_context", lambda agent_id: context)
        return TestClient(app)

    def test_archives_endpoint_lists_entries(self, monkeypatch, rolled):
        store, registry, skill, service = rolled
        client = self._client(monkeypatch, (store, registry, service))
        resp = client.get("/api/v1/governance/skills/sk_a/archives")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["skill_id"] == "sk_a"
        assert len(data["archives"]) == 1
        assert data["archives"][0]["version"] == "1.0.0"

    def test_archives_endpoint_503_when_not_wired(self, monkeypatch, rolled):
        client = self._client(monkeypatch, None)
        resp = client.get("/api/v1/governance/skills/sk_a/archives")
        assert resp.status_code == 503, (
            "治理面未装配必须返 503（先例：GET /governance/rsi/status），"
            f"静默 200 会把'没装配'读成'没有归档'：{resp.status_code} {resp.text}"
        )

    def test_rollback_endpoint_writes_trace(self, monkeypatch, rolled):
        store, registry, skill, service = rolled
        client = self._client(monkeypatch, (store, registry, service))
        resp = client.post(
            "/api/v1/governance/skills/sk_a/rollback",
            json={"operator": "admin1"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["rolled_back"] is True
        assert (skill.config.get("revisions") or [])[-1]["operator"] == "admin1"

    def test_rollback_endpoint_409_when_no_archives(self, monkeypatch, rolled):
        store, registry, skill, service = rolled
        client = self._client(monkeypatch, (store, registry, service))
        assert client.post(
            "/api/v1/governance/skills/sk_a/rollback", json={"operator": "admin1"}
        ).status_code == 200
        resp = client.post(
            "/api/v1/governance/skills/sk_a/rollback", json={"operator": "admin1"}
        )
        assert resp.status_code == 409, (
            f"归档为空必须显式拒绝（409），不得静默成功：{resp.status_code} {resp.text}"
        )
