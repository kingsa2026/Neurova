# -*- coding: utf-8 -*-
"""无身份会话属主判给管理员（用户拍板 2026-11-18）。

- resolveSessionOwner 是会话属主唯一取法（§6-163 裁定甲）：显式 metadata >
  请求身份 > 管理员。第三档替代旧「空串＝共享」——空属主会话对全员可见，
  历史上因此积累大量无主测试会话（682 个 user_id 为空的 session 文件）。
- _adminOwnerId 从用户库取 role=admin 中 id 最小者（主管理员）；库故障
  诚实回落空串。消费端必须 fail-closed，不得把解析失败继续当成共享放行。
"""
from __future__ import annotations

import pytest

import neurova.post_chat_pipeline as pcp
from neurova.core.identity_context import set_request_user_id


@pytest.fixture(autouse=True)
def _cleanIdentity():
    set_request_user_id("")
    yield
    set_request_user_id("")


def test_no_identity_falls_to_admin(monkeypatch):
    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    assert pcp.resolveSessionOwner(None) == "3"
    assert pcp.resolveSessionOwner({}) == "3"


def test_explicit_metadata_owner_wins(monkeypatch):
    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    assert pcp.resolveSessionOwner({"session_owner_id": "7"}) == "7"


def test_request_identity_wins_over_admin(monkeypatch):
    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    set_request_user_id("42")
    assert pcp.resolveSessionOwner(None) == "42"
    # 显式空＝声明无属主：不回落到说话人（42），直达管理员
    assert pcp.resolveSessionOwner({"session_owner_id": ""}) == "3"


def test_adminOwnerId_prefers_lowest_id_admin():
    from neurova.auth.user_model import UserModel

    # pytest 下 UserModel() 默认落 NEUROVA_DATA_DIR 临时数据根（conftest 导入期隔离）
    model = UserModel()
    model.create_user("plain", password_hash="x", role="user")
    model.create_user("admin_b", password_hash="x", role="admin")
    model.create_user("admin_a", password_hash="x", role="admin")

    import neurova.post_chat_pipeline as pcp
    # 清缓存，强制真查库
    pcp._adminOwnerCache["id"] = ""
    pcp._adminOwnerCache["at"] = 0.0
    try:
        admins = model.list_users(role="admin")
        expected = str(min(int(u.id) for u in admins))
        assert pcp._adminOwnerId() == expected
    finally:
        pcp._adminOwnerCache["id"] = ""
        pcp._adminOwnerCache["at"] = 0.0
