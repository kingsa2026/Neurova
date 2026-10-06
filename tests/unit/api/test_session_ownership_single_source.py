# -*- coding: utf-8 -*-
"""会话归属判据必须只有一处实现，且各端点同解

两条缺陷（同根因：一条规则被复制成多份，于是各端点各自漂移）：

1. 归属判据在 `console.py` 里写了三份——`_check_session_ownership`（1351）、
   `_find_session_target` 内联一份（1473-1475）、`delete_chat_session` /
   `rename_chat_session` / `auto_title_chat_session` 各再内联一份。
   教义第 6 条：口径只允许一处定义。
2. `chat.py` 的 `GET/DELETE /history` 只校验 **agent 归属**，`session_id` 参数
   从不比对会话属主——同一份会话在两个面上两套门，一个是"会话属主"、
   一个是"agent 可达"。本文件把"同解"钉成断言，不做推测。

判据写成矩阵：bob 用自己的身份，从每一条会话面端点去碰 alice 的会话，
都必须 403；alice 自己必须照常 200（收紧不许把归属者挡在门外）。
空属主的共享会话必须对两人都可达——那是既有语义，不在本批改动范围。
"""

import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api import deps as deps_mod
from neurova.api.endpoints import console as consoleMod
from neurova.api.error_handlers import register_error_handlers

ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}
BOB = {"user_id": "bob", "username": "bob", "role": "user", "neuser_id": "ne-bob"}


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """真 SessionManager（隔离目录）：alice 的会话 + 一条空属主共享会话。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    from neurova.session_repository import get_session_repository, reset_session_repository

    reset_session_repository()
    repo = get_session_repository()
    aliceSid = repo.create_session(agent_id="agent_x", user_id="alice", title="alice 的会话")
    sharedSid = repo.create_session(agent_id="agent_x", user_id="", title="共享会话")
    repo.add_message(agent_id="agent_x", session_id=aliceSid,
                     user_content="alice 的私密问题", assistant_content="r", user_id="alice")
    return repo, aliceSid, sharedSid


@pytest.fixture
def client(sessions):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(consoleMod.router, prefix="/api/v1/console")
    tc = TestClient(app)

    def asUser(identity: dict):
        # 本仓有**两份** get_current_user 实现（auth.py:415 与 deps.py:38，后者额外吃
        # ?access_token=），console 用 deps 那份——override 必须打在端点真正依赖的
        # 函数对象上，否则依赖不会被替换（这是 dependency_overrides 最常见的假绿入口）。
        for fn in (deps_mod.get_current_user, auth_mod.get_current_user,
                   auth_mod.get_current_user_or_default):
            tc.app.dependency_overrides[fn] = lambda: identity

    tc.as_user = asUser
    tc.repo, tc.aliceSid, tc.sharedSid = sessions
    return tc


def _bobOnlyPaths(sid: str) -> typing.List[tuple]:
    """(method, path, body) —— 全部以"会话属主"为归属键的端点。"""
    return [
        ("get", f"/api/v1/console/chat/history?session_id={sid}", None),
        ("delete", f"/api/v1/console/chat/sessions/{sid}", None),
        ("put", f"/api/v1/console/chat/sessions/{sid}", {"title": "劫持改名"}),
        ("post", f"/api/v1/console/chat/sessions/{sid}/auto-title", None),
        ("post", f"/api/v1/console/chat/sessions/{sid}/pin", {"pinned": True}),
        ("post", f"/api/v1/console/chat/sessions/{sid}/archive", None),
    ]


@pytest.mark.parametrize("verb,path,body", _bobOnlyPaths("<sid>"))
def test_bobCannotTouchAlicesSessionViaAnyEndpoint(client, verb, path, body):
    """bob 从任一会话端点碰 alice 的会话都必须 403——一条例外就是口径漂移。"""
    path = path.replace("<sid>", client.aliceSid)
    client.as_user(BOB)
    resp = getattr(client, verb)(path, json=body) if body is not None else getattr(client, verb)(path)
    assert resp.status_code == 403, (
        f"{verb.upper()} {path} 对非属主返回 {resp.status_code}（应 403）：{resp.text[:140]}"
    )


def test_bobCanReadSharedSession(client):
    """反证另一半：空属主的共享会话必须仍对 bob 可达（既有语义，不许顺手关掉）。"""
    client.as_user(BOB)
    resp = client.get(f"/api/v1/console/chat/history?session_id={client.sharedSid}")
    assert resp.status_code == 200, f"共享会话被误收紧：{resp.status_code} {resp.text[:120]}"


def test_ownerStillManagesOwnSession(client):
    """收紧不得把归属者自己挡在门外。"""
    client.as_user(ALICE)
    resp = client.put(f"/api/v1/console/chat/sessions/{client.aliceSid}", json={"title": "自己改"})
    assert resp.status_code == 200, f"归属者改名被拒：{resp.status_code} {resp.text[:140]}"
    resp = client.delete(f"/api/v1/console/chat/sessions/{client.aliceSid}")
    assert resp.status_code == 200, f"归属者删除被拒：{resp.status_code} {resp.text[:140]}"


def test_ownershipPredicateHasOneImplementation(client):
    """判据单源：归属比较式在 console.py 里只许出现一次。

    钉**代码形态**（那句 `target_user_id != user_id` 的比较），不钉函数名——
    复制一份同样逻辑但换个变量名，就绕过了只钉名字的守卫。
    """
    import inspect

    src = inspect.getsource(consoleMod)
    occurrences = src.count("!= user_id")
    assert occurrences == 1, (
        f"会话归属判据被复制成 {occurrences} 份，各端点会各自漂移；"
        "应收口到 _check_session_ownership 一处调用"
    )
