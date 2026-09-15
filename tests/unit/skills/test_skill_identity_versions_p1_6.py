"""P1-6 技能身份与版本真数据（OpenSpace .skill_id/版本 DAG 最小移植）

两件事：
1. manifest 条目带 identity（稳定身份+revision 链）与 version_history
   （线性 parent 边，有界 20）——安装@1/import、注册@1/auto、version 变化
   追加 @n+1 挂 parent；
2. skill_version_api 的 _VERSIONS_STORE 硬编码假数据 / 内存 dict 换真源：
   市场最新版读 catalog（market_store），安装态读 SkillService manifest，
   /update 走真实 MarketImporter(force) 通道。前端零消费方，但假数据留在
   路由上就是下一个"页面按想象契约写"事故的种子。
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.skills.skill_service import SkillService


@pytest.fixture
def svc(tmp_path):
    return SkillService(agent_id="id-t", skills_dir=str(tmp_path / "skills"))


def _install_clean(svc, tmp_src, skill_id):
    src = tmp_src / skill_id
    src.mkdir(parents=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}), encoding="utf-8"
    )
    assert svc.install_skill(str(src))["success"] is True


# ── manifest 身份/修订链 ───────────────────────────────────


def test_install_creates_birth_revision(svc, tmp_path):
    _install_clean(svc, tmp_path, "imp1")
    info = svc.get_skill_info("imp1")
    assert info["identity"]["revision_id"] == "imp1@1"
    assert info["identity"]["origin"] == "import"
    assert info["version_history"][0]["parent_revision_id"] is None


def test_register_auto_skill_birth_revision(svc):
    svc.register_auto_skill("a1", name="a1")
    info = svc.get_skill_info("a1")
    assert info["identity"]["revision_id"] == "a1@1"
    assert info["identity"]["origin"] == "auto"


def test_version_bump_appends_child_revision(svc):
    svc.register_auto_skill("a1", name="a1")
    svc.update_auto_skill("a1", version="1.0.1")
    info = svc.get_skill_info("a1")
    assert info["identity"]["revision_id"] == "a1@2"
    hist = info["version_history"]
    assert [h["revision_id"] for h in hist] == ["a1@1", "a1@2"]
    assert hist[1]["parent_revision_id"] == "a1@1"


def test_config_only_update_no_new_revision(svc):
    svc.register_auto_skill("a1", name="a1")
    svc.update_auto_skill("a1", config={"x": 1})
    info = svc.get_skill_info("a1")
    assert len(info["version_history"]) == 1
    assert info["identity"]["revision_id"] == "a1@1"


def test_revision_history_bounded(svc):
    svc.register_auto_skill("a1", name="a1")
    for i in range(30):
        svc.update_auto_skill("a1", version=f"1.0.{i + 1}")
    info = svc.get_skill_info("a1")
    assert len(info["version_history"]) == 20
    # 链保持连续：最后一条 parent 指向前一条
    hist = info["version_history"]
    assert hist[-1]["parent_revision_id"] == hist[-2]["revision_id"]


# ── skill_version_api 真数据源 ─────────────────────────────


def _api_mod():
    import neurova.api.endpoints.skill_version_api as mod

    return mod


def test_check_real_sources(monkeypatch):
    mod = _api_mod()
    monkeypatch.setattr(
        mod, "_latest_market_version", lambda skill_id: "1.3.0"
    )
    monkeypatch.setattr(mod, "_installed_version", lambda skill_id: "1.2.0")
    resp = asyncio.run(
        mod.check_version_update(
            mod.VersionCheckRequest(skill_id="web-search", current_version="")
        )
    )
    data = resp["data"]
    assert data["current_version"] == "1.2.0"
    assert data["latest_version"] == "1.3.0"
    assert data["has_update"] is True


def test_check_unknown_skill_404(monkeypatch):
    from fastapi import HTTPException

    mod = _api_mod()
    monkeypatch.setattr(mod, "_latest_market_version", lambda skill_id: None)
    monkeypatch.setattr(mod, "_installed_version", lambda skill_id: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.check_version_update(mod.VersionCheckRequest(skill_id="ghost9")))
    assert exc.value.status_code == 404


def test_no_hardcoded_fake_store():
    mod = _api_mod()
    src = open(mod.__file__, encoding="utf-8").read()
    assert "_VERSIONS_STORE:" not in src and "_VERSIONS_STORE :" not in src, "假版本表定义必须移除（注释提及不算）"
    assert '"code-interpreter"' not in src, "硬编码演示技能必须移除"


def test_check_all_from_installed(monkeypatch):
    mod = _api_mod()
    monkeypatch.setattr(
        mod,
        "_installed_skills",
        lambda: [{"skill_id": "web-search", "version": "1.2.0", "changelog": ""}],
    )
    monkeypatch.setattr(mod, "_latest_market_version", lambda s: "1.3.0")
    resp = asyncio.run(mod.check_all_versions_on_startup())
    skills = resp["data"]["skills"]
    assert skills[0]["skill_id"] == "web-search"
    assert skills[0]["latest_version"] == "1.3.0"
    assert resp["data"]["total"] == 1


def test_update_uses_real_importer(monkeypatch):
    mod = _api_mod()
    calls = {}

    class _FakeTask:
        status = "completed"
        error = None

    class _FakeImporter:
        def import_skill(self, skill_id, version=None, force=False):
            calls.update(skill_id=skill_id, version=version, force=force)
            return _FakeTask()

    monkeypatch.setattr(mod, "get_market_importer", lambda: _FakeImporter())
    monkeypatch.setattr(mod, "_latest_market_version", lambda s: "2.0.0")
    req = SimpleNamespace(state=SimpleNamespace(user_id="u1"))
    resp = asyncio.run(
        mod.manual_update_skill(mod.UpdateSkillRequest(skill_id="web-search"), req)
    )
    assert calls == {"skill_id": "web-search", "version": "2.0.0", "force": True}
    assert resp["data"]["new_version"] == "2.0.0"


def test_update_unavailable_returns_error(monkeypatch):
    mod = _api_mod()
    monkeypatch.setattr(mod, "get_market_importer", lambda: None)
    req = SimpleNamespace(state=SimpleNamespace(user_id="u1"))
    resp = asyncio.run(
        mod.manual_update_skill(mod.UpdateSkillRequest(skill_id="any"), req)
    )
    assert resp["code"] != 0 or resp.get("data", {}).get("updated") in (None, [], False)
