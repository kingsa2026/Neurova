"""`/api/v1/sync/*` REST 面的身份与归属收口（C3，C2 同根因扫荡扫出的另一半）。

复核实状（2026-10-08，逐条读码 + AST 复扫"取 `session_id` 却不做归属比对"的端点，
全仓 25 条中 11 条无归属校验）：`session_sync.py` 的 S-03 IDOR 修**只做了一半**——
`POST /sessions`(:286) 与 WS(:133-143) 已改成"归属以 token 主体为准"，
而同一文件的四条读/删/发面一条都没跟上：

| 路由 | 身份依赖 | 归属比对 | 实测后果 |
|---|---|---|---|
| `GET /sessions/{id}` | 有 | 无 | 外人拿到他人的 user_id / agent / 渠道清单 |
| `GET /sessions/{id}/history` | 有 | 无 | **他人消息正文全量返回** |
| `POST /sessions/{id}/messages` | 有 | 无 | 把消息写进他人会话并推送到其**活动通道** |
| `DELETE /sessions/{id}` | **无** | 无 | 匿名可杀任意会话 |
| `GET /sessions` | **无** | 无 | 匿名可按 `?user_id=` **枚举任意用户的会话表** |
| `GET /connections` | **无** | 无 | 匿名可枚举所有在线 session_id（存在性oracle） |

"匿名"这三条不是理论风险：`NEUROVA_GLOBAL_AUTH` 未设置时 `get_global_auth_mode()`
回落 `MODE_OFF`（`global_auth.py:61-63`），全局兜底中间件**不在路上**，
路由自身没有 `Depends(get_current_user)` 就是真的匿名可达。

这个 store（`SessionSyncManager` 内存 `_sessions`）与 chat 会话**共用 id 命名空间**：
`chat_pipeline.py:558-563` 用 `ctx.session_id` 调 `register_or_create_session` 注册
`UnifiedSession`，所以它不是"只在内部自嗨的另一套会话"，拿到 chat 的 session_id
就能打这里。

归属比较**不新造第二份**：复用 `console.py:1511 _check_session_ownership`
（空属主=共享那条既有语义一并跟过来）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import session_sync as syncMod
from neurova.api.error_handlers import register_error_handlers
from neurova.sync.session_sync_manager import EventType, SessionEvent
from tests.auth_headers import bearerHeaders

ALICE_SID = "c3-alice-session"
BOB_SID = "c3-bob-session"


@pytest.fixture
def client():
    """真 router + 真 SessionSyncManager（生产单例），只隔离到测试用的显式 session_id。"""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(syncMod.router, prefix="/api/v1/sync")
    manager = syncMod.get_session_sync_manager()
    for sid in (ALICE_SID, BOB_SID):
        manager._sessions.pop(sid, None)
    manager.register_or_create_session(session_id=ALICE_SID, user_id="alice", agent_id="a1")
    manager.register_or_create_session(session_id=BOB_SID, user_id="bob", agent_id="a1")
    alice = manager.get_session(ALICE_SID)
    for ev_type, content in ((EventType.USER_MESSAGE, "alice 的私密问题"),
                             (EventType.AGENT_REPLY, "回答")):
        alice.add_event(SessionEvent(
            event_type=ev_type, session_id=ALICE_SID,
            source_channel="web", payload={"content": content},
        ))
    yield TestClient(app)
    manager._sessions.pop(ALICE_SID, None)
    manager._sessions.pop(BOB_SID, None)


class TestStrangerCannotReadOrMutate:
    def test_strangerCannotReadSession(self, client):
        r = client.get(f"/api/v1/sync/sessions/{ALICE_SID}", headers=bearerHeaders("bob"))
        assert r.status_code == 403, f"外人读他人会话元数据未被拒：{r.status_code} {r.text[:140]}"

    def test_strangerCannotReadHistory(self, client):
        r = client.get(f"/api/v1/sync/sessions/{ALICE_SID}/history", headers=bearerHeaders("bob"))
        assert r.status_code == 403, f"外人读他人消息正文未被拒：{r.status_code}"
        assert "alice 的私密问题" not in r.text

    def test_strangerCannotInjectMessage(self, client):
        r = client.post(
            f"/api/v1/sync/sessions/{ALICE_SID}/messages",
            json={"content": "bob 塞进来的", "channel_type": "web"},
            headers=bearerHeaders("bob"),
        )
        assert r.status_code == 403, f"外人写入他人会话未被拒：{r.status_code} {r.text[:140]}"
        # 反证：会话里真的没多出这一条（而不是 403 与写入各管各的）
        events = syncMod.get_session_sync_manager().get_session(ALICE_SID).get_history(limit=50)
        assert not any("bob 塞进来的" in str(e.payload) for e in events)

    def test_strangerCannotEndSession(self, client):
        r = client.delete(f"/api/v1/sync/sessions/{ALICE_SID}", headers=bearerHeaders("bob"))
        assert r.status_code == 403, f"外人结束他人会话未被拒：{r.status_code}"
        assert syncMod.get_session_sync_manager().get_session(ALICE_SID) is not None


class TestOwnerKeepsWorking:
    """收紧不许把归属者挡在门外——每条都配一条属主正证。"""

    def test_ownerReadsOwnSession(self, client):
        r = client.get(f"/api/v1/sync/sessions/{ALICE_SID}", headers=bearerHeaders("alice"))
        assert r.status_code == 200, f"属主读自己被拒：{r.status_code} {r.text[:140]}"

    def test_ownerReadsOwnHistory(self, client):
        r = client.get(f"/api/v1/sync/sessions/{ALICE_SID}/history", headers=bearerHeaders("alice"))
        assert r.status_code == 200, f"属主读自己被拒：{r.status_code}"
        assert "alice 的私密问题" in r.text

    def test_ownerSendsIntoOwnSession(self, client):
        r = client.post(
            f"/api/v1/sync/sessions/{ALICE_SID}/messages",
            json={"content": "alice 自己发", "channel_type": "web"},
            headers=bearerHeaders("alice"),
        )
        assert r.status_code == 200, f"属主发消息被拒：{r.status_code} {r.text[:140]}"

    def test_ownerEndsOwnSession(self, client):
        r = client.delete(f"/api/v1/sync/sessions/{BOB_SID}", headers=bearerHeaders("bob"))
        assert r.status_code == 200, f"属主结束自己会话被拒：{r.status_code} {r.text[:140]}"


class TestAnonymousRejectedOnTheThreeThatHadNoGate:
    @pytest.mark.parametrize("verb,path", [
        ("delete", f"/api/v1/sync/sessions/{ALICE_SID}"),
        ("get", "/api/v1/sync/sessions"),
        ("get", "/api/v1/sync/connections"),
    ])
    def test_anonymous(self, client, verb, path):
        """这三条原本**连身份依赖都没有**；`NEUROVA_GLOBAL_AUTH` 默认 OFF，
        全局中间件不在路上，所以缺 `Depends(get_current_user)` 就是真匿名可达。

        DELETE 用**真实存在的会话 id**打：现状不是 404 而是 200 且真的把 alice 的
        会话结束了——用不存在的 id 打会把这条红洗成"看起来像路由没命中"。
        """
        r = getattr(client, verb)(path)
        assert r.status_code == 401, f"{verb.upper()} {path} 匿名得 {r.status_code}（应 401）"
        if verb == "delete":
            assert syncMod.get_session_sync_manager().get_session(ALICE_SID) is not None, (
                "匿名 DELETE 未被拒时会话真的会没了——这条断言盯'401 之外不留副作用'"
            )


class TestListAndConnectionsFollowTokenIdentity:
    def test_listSessionsIgnoresClientSuppliedUserId(self, client):
        """`?user_id=alice` 不再是一个可由调用方指定的过滤器。

        与 `POST /sessions:286`、WS:133 那条已修的 S-03 口径同形：**归属取 token 主体**。
        """
        r = client.get("/api/v1/sync/sessions", params={"user_id": "alice"},
                       headers=bearerHeaders("bob"))
        assert r.status_code == 200, r.text
        ids = {s.get("session_id") for s in r.json()["sessions"]}
        assert ALICE_SID not in ids, f"bob 用查询串把 alice 的会话整张表拉了出来：{ids}"
        assert BOB_SID in ids, f"bob 看不到自己的会话（收紧过头）：{ids}"

    def test_connectionsScopedToCaller(self, client):
        """这条必须有真连接才咬得住：`_ws_connections` 为空时"没泄露"是恒真的假绿。

        所以先在**生产那张表**里挂上 alice 的一条连接，再让 bob 来列——
        bob 必须看不见它，而 alice 必须仍看得见（不许把正主一起挡掉）。
        """
        import datetime
        from types import SimpleNamespace

        now = datetime.datetime.now()
        conn = SimpleNamespace(
            connection_id="c3-conn-1", channel_type="web",
            connected_at=now, last_heartbeat=now,
        )
        syncMod._ws_connections[ALICE_SID] = [conn]
        try:
            r = client.get("/api/v1/sync/connections", headers=bearerHeaders("bob"))
            assert r.status_code == 200, r.text
            ids = {c.get("session_id") for c in r.json()["connections"]}
            assert ALICE_SID not in ids, f"在线会话 id 清单泄露给外人：{ids}"

            rOwn = client.get("/api/v1/sync/connections", headers=bearerHeaders("alice"))
            ownIds = {c.get("session_id") for c in rOwn.json()["connections"]}
            assert ALICE_SID in ownIds, f"正主看不到自己的连接（收紧过头）：{ownIds}"
        finally:
            syncMod._ws_connections.pop(ALICE_SID, None)


class TestNoSecondOwnershipPredicate:
    def testSessionSyncDelegatesToTheConsolePredicate(self):
        """归属比较**不许在本文件长出第二份**。

        形态是两层，缺一不可：
        ① 四个会话面 handler 各自都要走那一道门（少一个就是一个洞）；
        ② 本文件里那句比较必须**转交** `console.py` 的唯一实现，而不是自己写
           `session.user_id != caller`——后者会让"空属主=共享"这条语义在两份实现里
           各自漂移（`test_ownershipPredicateHasOneImplementation` 只数 console.py 内部，
           单靠它拦不住"在别的文件复制一份"）。
        """
        import inspect

        src = inspect.getsource(syncMod)
        assert src.count("!= user_id") == 0, (
            "session_sync 内联了归属比较式，口径会长出第二份"
        )
        for name in ("get_session", "get_session_history", "send_message", "end_session"):
            fn = getattr(syncMod, name)
            assert "_requireSessionOwnership" in inspect.getsource(fn), (
                f"{name} 没接上归属校验"
            )
        delegate = inspect.getsource(syncMod._requireSessionOwnership)
        assert "_check_session_ownership" in delegate, (
            "_requireSessionOwnership 没有转交 console 那份唯一实现，等于自己另写一份"
        )

    def testEverySessionScopedRestRouteCarriesIdentity(self):
        """路由矩阵形态：凡路径带 session 的 REST 路由（WS 除外，它有自己的
        握手契约，由 `test_session_sync_ws_auth.py` 钉）都必须挂身份依赖。"""
        from neurova.api import auth as auth_mod
        from neurova.api import deps as deps_mod

        identities = {
            auth_mod.get_current_user,
            deps_mod.get_current_user,
            auth_mod.get_current_user_or_default,
        }
        offenders = []
        for route in syncMod.router.routes:
            methods = getattr(route, "methods", None)
            if not methods:  # WS 路由无 methods，且凭证走 query token + 握手内解析
                continue
            if "session" not in route.path and route.path != "/connections":
                continue
            calls = []
            stack = list(getattr(route, "dependencies", []) or [])
            if getattr(route, "dependant", None) is not None:
                stack.extend(route.dependant.dependencies)
            while stack:
                dep = stack.pop()
                if getattr(dep, "call", None) is not None:
                    calls.append(dep.call)
                stack.extend(getattr(dep, "dependencies", []) or [])
            if not identities.intersection(calls):
                offenders.append(f"{sorted(methods)[0]} {route.path}")
        assert not offenders, f"以下 sync REST 路由没有身份依赖：{offenders}"
