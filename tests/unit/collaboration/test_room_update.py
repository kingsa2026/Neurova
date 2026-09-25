"""PUT /rooms/{id} 编辑端点单元测试：鉴权(admin/owner/成员) + 改名/描述/应答者 + 成员增删。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import collaboration_room_api as ra


class _FakeManager:
    def __init__(self, project):
        self.project = project
        self.updates = None
        self.added = []
        self.removed = []

    def get_project(self, pid, user_id=None):
        return self.project if pid == self.project.project_id else None

    def update_project(self, project_id, user_id, updates):
        self.updates = updates
        return self.project

    def add_project_member(self, project_id, inviter_id, user_id, role=None):
        self.added.append(user_id)
        return True

    def remove_project_member(self, project_id, remover_id, user_id):
        self.removed.append(user_id)
        return True


def _project(owner="u1", members=("u1", "a1")):
    return SimpleNamespace(
        project_id="project_x", owner_id=owner, name="N", description="d",
        members={m: SimpleNamespace(role="owner" if m == owner else "editor") for m in members},
        metadata={},
    )


@pytest.fixture
def patch_manager(monkeypatch):
    def _apply(project):
        fake = _FakeManager(project)
        monkeypatch.setattr(ra, "get_collaboration_manager", lambda: fake)
        return fake
    return _apply


def _body(**kw):
    return ra.UpdateRoomBody(**kw)


def test_owner_updates_name_and_responder(patch_manager):
    fake = patch_manager(_project())
    asyncio.run(ra.update_room("project_x", _body(name="新名", responder_agent_id="a1"), {"user_id": "u1", "role": "user"}))
    assert fake.updates["name"] == "新名"
    assert fake.updates["metadata"]["responder_agent_id"] == "a1"


def test_admin_not_member_can_edit(patch_manager):
    fake = patch_manager(_project(owner="u1", members=("u1",)))
    asyncio.run(ra.update_room("project_x", _body(description="x"), {"user_id": "admin9", "role": "admin"}))
    assert fake.updates["description"] == "x"


def test_non_member_non_admin_forbidden(patch_manager):
    patch_manager(_project(owner="u1", members=("u1", "a1")))
    with pytest.raises(HTTPException) as e:
        asyncio.run(ra.update_room("project_x", _body(name="y"), {"user_id": "stranger", "role": "user"}))
    assert e.value.status_code == 403


def test_member_diff_adds_and_removes(patch_manager):
    # 现有成员 u1(owner), a1；期望成员 u1, a2 → 移除 a1、新增 a2
    fake = patch_manager(_project(owner="u1", members=("u1", "a1")))
    asyncio.run(ra.update_room("project_x", _body(members=["u1", "a2"]), {"user_id": "u1", "role": "user"}))
    assert fake.added == ["a2"]
    assert fake.removed == ["a1"]  # owner u1 永不被移除
