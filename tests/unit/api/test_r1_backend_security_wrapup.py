# -*- coding: utf-8 -*-
"""R1 后端安全收尾（2026-11-16 审计遗留，S1 移交项）。

覆盖条目：
- neurflow 调试两端点（/executions/{id}/breakpoint、/executions/{id}/debug/resume）
  属主门——总控裁定：调试会话归属＝执行记录属主；门必须先于 _DEBUG_SESSIONS 副作用，
  未落库 execution 不得凭空建会话；
- media.py 列表面（/list、/trash、/stats/{agent_id}、/memory/{memory_id}）按上传者
  过滤（admin 全量），与读/删侧 _ownedMediaOr404 同一口径；存量无主行仅 admin 可见；
- coordination /triage/check：TriageGateError → 503（诚实暴露分诊门不可用，不落 500）；
- collaboration delete 模板：delete_project 缺 user_id 实参必 TypeError→500，修复
  调用签名恢复端点可用（属主门 S1 已在位，本档钉"实参送达 manager"）。
"""

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user

_U1 = {"user_id": "u1", "username": "alice", "role": "user"}
_U2 = {"user_id": "u2", "username": "bob", "role": "user"}
_ROOT = {"user_id": "root", "username": "root", "role": "admin"}


# ── neurflow 调试两端点属主门 ───────────────────────────────


class _ExecStorage:
    """只含 get_execution 的最小存储桩（调试两端点仅消费这一个读口）。"""

    def __init__(self, execution=None):
        self.execution = execution

    def get_execution(self, execution_id):
        if self.execution is not None and getattr(self.execution, "id", None) == execution_id:
            return self.execution
        return None


@pytest.fixture
def neurflow():
    from neurova.api.endpoints import neurflow_api as api

    api._DEBUG_SESSIONS.clear()
    yield api
    api._DEBUG_SESSIONS.clear()


class TestNeurflowDebugOwnershipGate:
    def test_breakpoint_rejects_foreign_execution(self, neurflow, monkeypatch):
        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(SimpleNamespace(id="ex1", user_id="u2")))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                api.set_breakpoints("ex1", body=api.BreakpointRequest(breakpoints=["n1"]), current_user=_U1)
            )
        assert exc.value.status_code == 404, "非属主设断点应与'不存在'同构 404"
        assert "ex1" not in api._DEBUG_SESSIONS, "属主门必须先于 _DEBUG_SESSIONS 副作用"

    def test_breakpoint_unknown_execution_creates_no_session(self, neurflow, monkeypatch):
        """S1 移交注记：set_breakpoints 此前对未落库 execution 也建会话——门先行后不再发生。"""
        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(None))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                api.set_breakpoints("ghost", body=api.BreakpointRequest(breakpoints=["n1"]), current_user=_U1)
            )
        assert exc.value.status_code == 404
        assert "ghost" not in api._DEBUG_SESSIONS, "未落库 execution 不得凭空建调试会话"

    def test_resume_rejects_foreign_execution(self, neurflow, monkeypatch):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(SimpleNamespace(id="ex1", user_id="u2")))
        session = DebugSession()
        api._DEBUG_SESSIONS["ex1"] = session
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.resume_debug_execution("ex1", body=api.ResumeRequest(), current_user=_U1))
        assert exc.value.status_code == 404, "非属主恢复调试应 404"
        assert not session.resume_event.is_set(), "404 了却把别人的调试会话恢复了"

    def test_resume_unknown_execution_404(self, neurflow, monkeypatch):
        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(None))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.resume_debug_execution("ghost", body=api.ResumeRequest(), current_user=_U1))
        assert exc.value.status_code == 404

    def test_resume_owned_execution_without_session_404(self, neurflow, monkeypatch):
        """属主、执行存在、但无调试会话——维持既有 404 语义（不误建会话）。"""
        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(SimpleNamespace(id="ex1", user_id="u1")))
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.resume_debug_execution("ex1", body=api.ResumeRequest(), current_user=_U1))
        assert exc.value.status_code == 404
        assert "ex1" not in api._DEBUG_SESSIONS

    def test_owner_and_admin_allowed(self, neurflow, monkeypatch):
        """阳性对照：属主与 admin 通道不误伤；无主（历史 default）行视为共享。"""
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        api = neurflow
        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(SimpleNamespace(id="ex1", user_id="u2")))

        r = asyncio.run(
            api.set_breakpoints("ex1", body=api.BreakpointRequest(breakpoints=["n1"]), current_user=_U2)
        )
        assert r["count"] == 1 and r["breakpoints"] == ["n1"], "属主可设断点"

        api._DEBUG_SESSIONS["ex1"] = DebugSession()
        r = asyncio.run(api.resume_debug_execution("ex1", body=api.ResumeRequest(), current_user=_ROOT))
        assert r["resumed"] is True, "admin 可恢复他人执行的调试会话"

        monkeypatch.setattr(api, "_get_storage", lambda: _ExecStorage(SimpleNamespace(id="ex0", user_id="")))
        r = asyncio.run(
            api.set_breakpoints("ex0", body=api.BreakpointRequest(breakpoints=["n0"]), current_user=_U1)
        )
        assert r["count"] == 1, "无主行视为共享（与执行记录门同口径）"


# ── media.py 列表面上传者过滤 ───────────────────────────────

from neurova.api.endpoints import media as MEDIA  # noqa: E402

_ALICE = {"user_id": "alice", "username": "alice", "role": "user"}
_BOB = {"user_id": "bob", "username": "bob", "role": "user"}
_ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
_PAYLOAD = b"\x89PNG\x0d\x0a\x1a\x0a" + bytes(range(16))


@pytest.fixture()
def media_face(tmp_path, monkeypatch):
    """与 test_s2_media_owner_gates 同构的隔离面：索引/存储根指 tmp_path，身份可切换。"""
    monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    MEDIA._media_store.clear()
    MEDIA._media_config["storage_path"] = str(tmp_path / "media_storage")
    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    who = {"v": _ALICE}
    app.dependency_overrides[get_current_user] = lambda: dict(who["v"])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, who
    app.dependency_overrides.clear()
    MEDIA._media_store.clear()


def _upload(c, name="pic.png", agent_id="ag1", memory_id=None):
    r = c.post(
        "/api/v1/media/save",
        files={"file": (name, io.BytesIO(_PAYLOAD), "image/png")},
        data={"media_type": "image", "agent_id": agent_id, **({"memory_id": memory_id} if memory_id else {})},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["media_id"]


class TestMediaListSideUploaderFilter:
    def test_list_shows_only_own_uploads(self, media_face):
        c, who = media_face
        _upload(c, "a1.png")
        _upload(c, "a2.png")
        who["v"] = _BOB
        _upload(c, "b1.png")

        who["v"] = _BOB
        data = c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]
        assert data["total"] == 1, "普通用户列表应只含本人上传"
        assert all(m["user_id"] == "bob" for m in data["media"])

        who["v"] = _ALICE
        data = c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]
        assert data["total"] == 2, "上传者本人应见自己的两行"

        who["v"] = _ADMIN
        data = c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]
        assert data["total"] == 3, "admin 全量可见"

    def test_list_ownerless_rows_admin_only(self, media_face):
        """存量无主行（user_id 为空）：普通用户不可见，仅 admin 可见（与 _ownedMediaOr404 同口径）。"""
        c, who = media_face
        mid = _upload(c)
        MEDIA._media_store[mid]["user_id"] = ""

        who["v"] = _BOB
        assert c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]["total"] == 0
        who["v"] = _ADMIN
        assert c.get("/api/v1/media/list", params={"agent_id": "ag1"}).json()["data"]["total"] == 1

    def test_trash_shows_only_own_entries(self, media_face):
        c, who = media_face
        mine = _upload(c, "mine.png")
        c.delete(f"/api/v1/media/{mine}?mode=trash")
        who["v"] = _BOB
        theirs = _upload(c, "theirs.png")
        c.delete(f"/api/v1/media/{theirs}?mode=trash")

        who["v"] = _BOB
        data = c.get("/api/v1/media/trash", params={"agent_id": "ag1"}).json()["data"]
        assert data["total"] == 1 and data["media"][0]["media_id"] == theirs

        who["v"] = _ALICE
        data = c.get("/api/v1/media/trash", params={"agent_id": "ag1"}).json()["data"]
        assert data["total"] == 1 and data["media"][0]["media_id"] == mine

    def test_stats_count_only_own_uploads(self, media_face):
        c, who = media_face
        _upload(c, "a1.png")  # 16+8=24 bytes
        _upload(c, "a2.png")
        who["v"] = _BOB
        _upload(c, "b1.png")

        who["v"] = _BOB
        data = c.get("/api/v1/media/stats/ag1").json()["data"]
        assert data["total_files"] == 1, "统计应只计本人上传"
        who["v"] = _ALICE
        data = c.get("/api/v1/media/stats/ag1").json()["data"]
        assert data["total_files"] == 2
        who["v"] = _ADMIN
        data = c.get("/api/v1/media/stats/ag1").json()["data"]
        assert data["total_files"] == 3, "admin 统计全量"

    def test_memory_media_shows_only_own(self, media_face):
        c, who = media_face
        _upload(c, "a1.png", memory_id="mem1")
        who["v"] = _BOB
        _upload(c, "b1.png", memory_id="mem1")

        who["v"] = _BOB
        data = c.get("/api/v1/media/memory/mem1").json()["data"]
        assert data["total"] == 1 and data["media"][0]["user_id"] == "bob"
        who["v"] = _ALICE
        data = c.get("/api/v1/media/memory/mem1").json()["data"]
        assert data["total"] == 1 and data["media"][0]["user_id"] == "alice"


# ── coordination /triage/check 诚实 503 ─────────────────────


class TestTriageCheckHonest503:
    @staticmethod
    def _seedOwnedSession():
        """API-09 起端点带会话属主门：直调以 _ADMIN 身份预置其名下会话。"""
        from neurova.sync.session_sync_manager import get_session_sync_manager

        get_session_sync_manager().register_or_create_session(
            session_id="conv-1", user_id=_ADMIN["user_id"], agent_id="agent_x"
        )

    def test_triage_gate_error_maps_to_503(self, monkeypatch):
        from neurova.api.endpoints import coordination_api as mod
        from neurova.llm.triage import TriageGateError

        class _BoomGate:
            async def triage_message(self, conversation_id):
                raise TriageGateError("对话历史源不可用")

        monkeypatch.setattr(mod, "get_small_brain_triage_gate", lambda: _BoomGate())
        self._seedOwnedSession()
        with pytest.raises(HTTPException) as exc:
            asyncio.run(mod.triage_message(conversation_id="conv-1", current_user=_ADMIN))
        assert exc.value.status_code == 503, "分诊门不可用应 503，而非未处理异常落 500"
        assert "分诊门" in str(exc.value.detail)

    def test_triage_check_success_shape_preserved(self, monkeypatch):
        from neurova.api.endpoints import coordination_api as mod
        from neurova.llm.triage import TriageResult

        class _OkGate:
            async def triage_message(self, conversation_id):
                return TriageResult(
                    actionable=True, reason="human waiting", confidence=0.9, conversation_hash="h1"
                )

        monkeypatch.setattr(mod, "get_small_brain_triage_gate", lambda: _OkGate())
        self._seedOwnedSession()
        out = asyncio.run(mod.triage_message(conversation_id="conv-1", current_user=_ADMIN))
        assert out == {
            "actionable": True,
            "reason": "human waiting",
            "confidence": 0.9,
            "conversation_hash": "h1",
        }, "正常分诊返回形状不得变化"


# ── collaboration delete 模板缺实参修复 ─────────────────────


class _Req:
    """最小 Request 替体（端点只取 state.request_id）。"""

    class _S:
        request_id = "req-1"

    state = _S()


class TestCollaborationDeleteTemplateSignature:
    def test_delete_passes_requester_user_id_to_manager(self, monkeypatch):
        from neurova.api.endpoints import collaboration_api as mod

        project = SimpleNamespace(owner_id="u1")
        calls = []

        class _Mgr:
            def get_project(self, template_id):
                return project

            def delete_project(self, project_id, user_id):
                calls.append((project_id, user_id))
                return True

        monkeypatch.setattr(mod, "get_collaboration_manager", lambda: _Mgr())
        resp = asyncio.run(
            mod.delete_collaboration_template(_Req(), "tpl1", current_user=dict(_U1))
        )
        assert calls == [("tpl1", "u1")], "delete_project 必须收到 (template_id, user_id) 两个实参"
        assert resp["code"] == 0, "属主删除模板应成功（原缺实参必 TypeError→500）"

    def test_delete_still_403_for_non_owner(self, monkeypatch):
        """S1 属主门不回退：非属主在到达 manager 之前就被 403。"""
        from neurova.api.endpoints import collaboration_api as mod

        project = SimpleNamespace(owner_id="u1")

        class _Mgr:
            def get_project(self, template_id):
                return project

            def delete_project(self, project_id, user_id):
                raise AssertionError("非属主不应到达 manager 删除")

        monkeypatch.setattr(mod, "get_collaboration_manager", lambda: _Mgr())
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                mod.delete_collaboration_template(_Req(), "tpl1", current_user=dict(_U2))
            )
        assert exc.value.status_code == 403


class TestCollaborationCreateTemplateBindsOwner:
    """live-verify 揭示的同链断点：建模板漏传 owner_id → 模板无主（成员含空串），
    S1 属主门对创建者本人也 403——删除模板端点对唯一合法使用者仍不可用。"""

    def test_create_passes_login_user_as_owner(self, monkeypatch):
        from neurova.api.endpoints import collaboration_api as mod

        captured = {}
        project = SimpleNamespace(
            project_id="tpl-new", name="n", description="d", metadata={},
            members={}, created_at=1.0, updated_at=1.0,
        )

        class _Mgr:
            def create_project(self, **kwargs):
                captured.update(kwargs)
                return project

            def add_project_member(self, *args, **kwargs):
                return True

        monkeypatch.setattr(mod, "get_collaboration_manager", lambda: _Mgr())
        body = mod.CollaborationTemplateCreate(name="n", description="d", workflow={})
        asyncio.run(mod.create_collaboration_template(_Req(), body, current_user=dict(_U1)))
        assert captured.get("owner_id") == "u1", "建模板必须把登录用户绑定为项目 owner"


class TestAdminDeleteForeignTemplate:
    """U1 产品拍板（2026-11-17）：admin 删他人模板 → 200 + 审计事件（管理面敏感
    操作可追溯）；无主存量模板（owner_id=""）按 admin 可见可删（与 media 无主行
    同口径）；owner 删自己的模板是普通操作，不写审计；普通非属主 403 不变（S1 门）。"""

    def _patch_manager(self, monkeypatch, project):
        from neurova.api.endpoints import collaboration_api as mod

        calls = []

        class _Mgr:
            def get_project(self, template_id):
                return project

            def delete_project(self, project_id, user_id):
                calls.append((project_id, user_id))
                return True

        monkeypatch.setattr(mod, "get_collaboration_manager", lambda: _Mgr())
        return calls

    def _patch_audit(self, monkeypatch):
        """端点内懒导入 `from neurova.security.audit_logger import get_audit_logger`
        取的是调用时模块属性——monkeypatch 模块属性即可拦截。"""
        import neurova.security.audit_logger as audit_mod

        events = []

        class _StubLogger:
            def log(self, entry):
                events.append(entry)
                return True

        monkeypatch.setattr(audit_mod, "get_audit_logger", lambda *a, **k: _StubLogger())
        return events

    def test_admin_delete_foreign_template_200_with_audit(self, monkeypatch):
        from neurova.api.endpoints import collaboration_api as mod

        project = SimpleNamespace(project_id="tpl1", owner_id="u1", name="tpl")
        self._patch_manager(monkeypatch, project)
        events = self._patch_audit(monkeypatch)

        resp = asyncio.run(
            mod.delete_collaboration_template(_Req(), "tpl1", current_user=dict(_ROOT))
        )
        assert resp["code"] == 0, "admin 删他人模板应成功（修复前 manager owner-only → 404）"
        assert len(events) == 1, "admin 删非本人模板必须写审计事件"
        assert events[0].resource_type == "collaboration_template"
        assert events[0].resource_id == "tpl1"
        assert events[0].user_id == "root"
        assert events[0].details["template_owner"] == "u1"

    def test_admin_delete_ownerless_template_with_audit(self, monkeypatch):
        from neurova.api.endpoints import collaboration_api as mod

        project = SimpleNamespace(project_id="tpl-o", owner_id="", name="orphan")
        self._patch_manager(monkeypatch, project)
        events = self._patch_audit(monkeypatch)

        resp = asyncio.run(
            mod.delete_collaboration_template(_Req(), "tpl-o", current_user=dict(_ROOT))
        )
        assert resp["code"] == 0, "admin 删无主存量模板应成功（无主行按 admin 可见可删）"
        assert len(events) == 1, "无主行也属非本人模板，删除须留审计痕迹"
        assert events[0].details["template_owner"] == ""

    def test_owner_delete_own_template_no_audit(self, monkeypatch):
        from neurova.api.endpoints import collaboration_api as mod

        project = SimpleNamespace(project_id="tpl-own", owner_id="u1", name="mine")
        self._patch_manager(monkeypatch, project)
        events = self._patch_audit(monkeypatch)

        resp = asyncio.run(
            mod.delete_collaboration_template(_Req(), "tpl-own", current_user=dict(_U1))
        )
        assert resp["code"] == 0, "owner 删自己的模板应成功（既有行为不回退）"
        assert events == [], "属主删自己的模板是普通操作，不写管理审计事件"
