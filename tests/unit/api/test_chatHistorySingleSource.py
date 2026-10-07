"""`/v1/chat/history` 两条端点必须接上真实现、与 console 面同解归属（C2）。

取证（2026-10-08 复核实状，**推翻台账旧描述**）：两条端点调的是
`agent.get_conversation_history()` / `agent.clear_conversation_history()`
（`chat.py:663/726`），而这两个方法名**全仓只出现在这四行里、没有任何实现**
（`git log --all -S "def get_conversation_history"` 零命中，来源是 `7835c367`
"pyc骨架恢复"那一批恢复出来的骨架）。于是：

- `GET /api/v1/chat/history` 对**任何人**恒回 `{"history": []}`（`hasattr` 恒 False）；
- `DELETE /api/v1/chat/history` **恒回 `code:0 / "History cleared"` 却什么都没清**
  ——§6-8「依赖缺失却报成功」那一族的又一副面孔。

所以本批要修的不是"跨租户可读"（读不出东西也就读不走东西），而是
**两条端点从来没工作过**。`test_session_ownership_single_source.py` 的 docstring
第 2 条早就把"同解"写成主张，但它的矩阵里只有 console 面的六条端点，chat 面
一条都没进——承诺与判据脱节，本文件补上那一半。

选定实现按教义第 7 条：console 面那份（`get_session_repository().get_history` +
`_find_session_target` 的归属校验）是唯一有数据、有门的实现；chat 面改指同一份，
不新造第三种口径。归属比较式仍只在 `console.py` 出现一次，既有 AST 守卫不受影响。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api import deps as deps_mod
from neurova.api.endpoints import chat as chatMod
from neurova.api.endpoints import console as consoleMod
from neurova.api.error_handlers import register_error_handlers

ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}
BOB = {"user_id": "bob", "username": "bob", "role": "user", "neuser_id": "ne-bob"}


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    """真 SessionManager（隔离落点）：alice 的会话 + 一条空属主共享会话。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    from neurova.session_repository import get_session_repository, reset_session_repository

    reset_session_repository()
    repo = get_session_repository()
    aliceSid = repo.create_session(agent_id="agent_x", user_id="alice", title="alice 的会话")
    sharedSid = repo.create_session(agent_id="agent_x", user_id="", title="共享会话")
    repo.add_message(
        agent_id="agent_x", session_id=aliceSid,
        user_content="alice 的私密问题", assistant_content="回答", user_id="alice",
    )
    return repo, aliceSid, sharedSid


@pytest.fixture
def client(sessions):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chatMod.router, prefix="/api/v1/chat")
    app.include_router(consoleMod.router, prefix="/api/v1/console")
    tc = TestClient(app)

    def asUser(identity: dict):
        # 两份同名门都在仓里（auth 严格 / deps 多收 ?access_token=），override 按
        # **对象**生效，两个都打上才不会因端点各指一份而出现"半张门没换"的假绿。
        for fn in (deps_mod.get_current_user, auth_mod.get_current_user,
                   auth_mod.get_current_user_or_default):
            tc.app.dependency_overrides[fn] = lambda: identity

    tc.as_user = asUser
    tc.repo, tc.aliceSid, tc.sharedSid = sessions
    return tc


class TestHistoryReadsRealData:
    def test_ownerGetsActualMessages(self, client):
        """红在现状行为上：`hasattr(agent, ...)` 恒 False → 恒回空表。"""
        client.as_user(ALICE)
        resp = client.get(
            "/api/v1/chat/history", params={"session_id": client.aliceSid}
        )
        assert resp.status_code == 200, resp.text
        history = resp.json()["data"]["history"]
        assert history, "归属者读自己的会话历史却拿到空表——端点根本没接上数据源"
        contents = [str(m.get("content", "")) for m in history]
        assert any("alice 的私密问题" in c for c in contents), contents

    def test_historyMatchesConsoleFaceReadings(self, client):
        """同解的另一半：两个面读同一会话必须给出同一批消息（不比数量比内容）。"""
        client.as_user(ALICE)
        chatSide = client.get(
            "/api/v1/chat/history", params={"session_id": client.aliceSid}
        ).json()["data"]["history"]
        consoleSide = client.get(
            "/api/v1/console/chat/history", params={"session_id": client.aliceSid}
        ).json()["data"]["messages"]
        assert [m.get("content") for m in chatSide] == [
            m.get("content") for m in consoleSide
        ]

    def test_sessionIdIsNowRequired(self, client):
        """`session_id` 由 Optional 收紧为必填：缺它就只能回空表，那是把
        "没给键"伪装成"没有历史"。"""
        client.as_user(ALICE)
        resp = client.get("/api/v1/chat/history")
        assert resp.status_code == 422, resp.text


class TestOwnershipSameResolution:
    @pytest.mark.parametrize("verb,path", [
        ("get", "/api/v1/chat/history?session_id=<sid>"),
        ("delete", "/api/v1/chat/history?session_id=<sid>"),
    ])
    def test_strangerRejectedOnBothVerbs(self, client, verb, path):
        path = path.replace("<sid>", client.aliceSid)
        client.as_user(BOB)
        resp = getattr(client, verb)(path)
        assert resp.status_code == 403, (
            f"{verb.upper()} {path} 对非属主返回 {resp.status_code}"
            "（应 403，与 console 面同解）"
        )

    def test_sharedSessionStillReadableByAnyone(self, client):
        """反证另一半：空属主=共享是既有语义，不许顺手关掉。"""
        client.as_user(BOB)
        resp = client.get(
            "/api/v1/chat/history", params={"session_id": client.sharedSid}
        )
        assert resp.status_code == 200, f"共享会话被误收紧：{resp.status_code} {resp.text[:120]}"


class TestClearNeverClaimsSuccessItCannotDeliver:
    def test_delete_does_not_report_cleared(self, client):
        """教义第 2 条：失败要么根修要么诚实暴露。

        仓内**没有**"清空一个会话的持久消息"的落点（`session_repository` 只有
        `delete_session` / `delete_round`），而只清 agent 内存历史会在下一轮被
        `_restore_session_history` 从文件复活——`_sync_agent_history_from_session`
        的存在就是那条 bug 的实证。所以这里断的是**不许回 code:0**，
        显式 501 并点名原因（登记台账待人裁是否补该 primitive）。
        """
        client.as_user(ALICE)
        resp = client.delete(
            "/api/v1/chat/history", params={"session_id": client.aliceSid}
        )
        assert resp.status_code == 501, (
            f"期望显式 501，实得 {resp.status_code}：{resp.text[:160]}"
        )
        # 归属者的消息一条都没少（证"没清"确实发生，而不是判据空转）
        assert client.repo.get_history(agent_id="agent_x", session_id=client.aliceSid)

    def test_identityCheckedBeforeCapability(self, client):
        """陌生账号必须拿到 403 而不是 501——先确认"这是你的会话"，再说"这件事做不到"。

        与 console `/chat/resume` 同一纪律：把身份放在状态判定之前，否则陌生人会从
        501/409 的差别里读出"这条会话存在"。
        """
        client.as_user(BOB)
        resp = client.delete(
            "/api/v1/chat/history", params={"session_id": client.aliceSid}
        )
        assert resp.status_code == 403, resp.text


class TestNoPhantomContractRemains:
    def testPhantomMethodNamesAreGone(self):
        """反向守卫：这两个名字再回到 chat.py 就是"门挂着、数据恒空"的同形回流。"""
        import inspect

        src = inspect.getsource(chatMod)
        for name in ("get_conversation_history", "clear_conversation_history"):
            assert name not in src, f"chat.py 仍引用不存在的 agent 方法：{name}"

    def testHistoryRoutesUseTheSharedSources(self):
        """读侧必须经唯一仓储、归属必须经唯一谓词（不许在 chat.py 内联比较式）。"""
        import inspect

        getSrc = inspect.getsource(chatMod.get_chat_history)
        delSrc = inspect.getsource(chatMod.clear_chat_history)
        assert "get_session_repository" in getSrc, "读历史没接上唯一仓储"
        assert "_find_session_target" in getSrc, "读历史没接上唯一归属谓词"
        assert "_find_session_target" in delSrc, "清历史没接上唯一归属谓词"
        assert "!= user_id" not in getSrc + delSrc, (
            "chat.py 内联了归属比较式——口径就会被复制成第二份"
        )


class TestOwnershipPredicateStillSingleSource:
    def test_consoleStillHoldsTheOnlyComparison(self):
        """本批不许把归属比较复制出去：整仓 `!= user_id` 的落点仍只有 console 一处。"""
        import inspect

        assert consoleMod.__name__.endswith("console")
        occurrences = inspect.getsource(consoleMod).count("!= user_id")
        assert occurrences == 1, f"console 内归属比较式变成 {occurrences} 份"
        chatOcc = inspect.getsource(chatMod).count("!= user_id")
        assert chatOcc == 0, f"chat.py 新长出 {chatOcc} 份归属比较式"
