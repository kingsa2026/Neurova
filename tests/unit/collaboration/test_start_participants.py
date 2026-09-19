"""/start 带成员写入路径回归测试。

根因：collaboration_api 曾调用不存在的 manager.add_member/remove_member（正确为
add_project_member/remove_project_member），一旦 participants 非空即 AttributeError → 500。
本测试用只暴露真实接口的假 manager 复现并锁定修复。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import collaboration_api as ca


class _FakeManager:
    """只实现 CollaborationIsolationManager 的真实成员接口，故意不提供 add_member。"""

    def __init__(self):
        self.added: list[str] = []
        self.project = SimpleNamespace(
            project_id="project_new", name="N", description="", members={}, metadata={}, owner_id="",
        )

    def create_project(self, name, description="", owner_id="", metadata=None, **kw):
        self.project.name = name
        self.project.description = description
        self.project.owner_id = owner_id
        if owner_id:
            self.project.members[owner_id] = SimpleNamespace(role="owner")
        return self.project

    def get_project(self, pid, user_id=None):
        return None

    def add_project_member(self, project_id, inviter_id, user_id, role=None):
        self.added.append(user_id)
        self.project.members[user_id] = SimpleNamespace(role="editor")
        return True

    # 故意不定义 add_member / remove_member → 若端点误用会 AttributeError


@pytest.fixture
def fake_manager(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(ca, "get_collaboration_manager", lambda: fake)
    return fake


def _request():
    req = MagicMock()
    req.state = SimpleNamespace(request_id="r1")
    return req


def test_start_with_participants_uses_add_project_member(fake_manager):
    body = ca.CollaborationStart(template_id=None, participants=["a1", "a2"], context={})
    asyncio.run(ca.start_collaboration(_request(), body, {"user_id": "u1"}))
    assert fake_manager.added == ["a1", "a2"]
    assert fake_manager.project.owner_id == "u1"  # owner 来自登录用户（缺陷2 根因）


def test_start_honors_submitted_name_from_context(fake_manager):
    # 断点修复：向导提交的名称必须生效，不得被 "Collaboration from {模板名}" 覆盖。
    body = ca.CollaborationStart(
        template_id=None, participants=[], context={"name": "我的房间", "description": "备注"}
    )
    asyncio.run(ca.start_collaboration(_request(), body, {"user_id": "u1"}))
    assert fake_manager.project.name == "我的房间"
    assert fake_manager.project.description == "备注"
