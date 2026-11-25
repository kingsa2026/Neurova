"""P0-08：会话读取必须保留属主，空属主归主管理员且不得放行。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from neurova.session_manager import SessionManager
from neurova.session_repository import get_session_repository, reset_session_repository


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    reset_session_repository()
    yield get_session_repository()
    reset_session_repository()


def test_getSessionMapsDiskOwnerAndTitle(repo):
    sid = repo.create_session(agent_id="agent-x", user_id="owner-1", title="磁盘标题")
    record = repo.get_session("agent-x", sid)
    assert record.user_id == "owner-1"
    assert record.title == "磁盘标题"


def test_emptyOwnerResolvesPrimaryAdminAcrossReadPaths(repo, monkeypatch):
    import neurova.post_chat_pipeline as pcp

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    sid = repo.create_session(agent_id="agent-x", user_id="", title="历史无主会话")

    assert repo.get_session("agent-x", sid).user_id == "3"
    assert repo.find_session(sid)["user_id"] == "3"
    assert repo.list_sessions(agent_id="agent-x", user_id="bob") == []
    admin_rows = repo.list_sessions(agent_id="agent-x", user_id="3")
    assert [row["session_id"] for row in admin_rows] == [sid]
    assert admin_rows[0]["user_id"] == "3"

    monkeypatch.setattr(repo, "_summaries_via_sidecar", lambda dirs, uid: None)
    scanned = repo.list_sessions(agent_id="agent-x", user_id="3")
    assert scanned == admin_rows


def test_unresolvedEmptyOwnerIsNotVisibleToOrdinaryUser(repo, monkeypatch):
    import neurova.post_chat_pipeline as pcp

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "")
    sid = repo.create_session(agent_id="agent-x", user_id="", title="无主历史")
    assert repo.list_sessions(agent_id="agent-x", user_id="bob") == []
    assert repo.find_session(sid)["user_id"] == ""


def test_consoleOwnershipResolvesEmptyOwnerToPrimaryAdmin(monkeypatch):
    from neurova.api.endpoints import console as consoleMod
    import neurova.post_chat_pipeline as pcp

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    consoleMod._check_session_ownership({"user_id": ""}, "3")
    with pytest.raises(HTTPException) as denied:
        consoleMod._check_session_ownership({"user_id": ""}, "bob")
    assert denied.value.status_code == 403


def test_consoleOwnershipFailsClosedWithoutRequesterOrResolvedOwner(monkeypatch):
    from neurova.api.endpoints import console as consoleMod
    import neurova.post_chat_pipeline as pcp

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "")
    for target, requester in (({"user_id": ""}, "bob"), ({"user_id": "owner-1"}, "")):
        with pytest.raises(HTTPException) as denied:
            consoleMod._check_session_ownership(target, requester)
        assert denied.value.status_code == 403


def test_consoleOwnershipStillAllowsExplicitOwner(monkeypatch):
    from neurova.api.endpoints import console as consoleMod
    import neurova.post_chat_pipeline as pcp

    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "3")
    consoleMod._check_session_ownership({"user_id": "owner-1"}, "owner-1")
    with pytest.raises(HTTPException):
        consoleMod._check_session_ownership({"user_id": "owner-1"}, "bob")
