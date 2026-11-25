# -*- coding: utf-8 -*-
"""首页/统计的会话计数必须按调用者 user_id 分桶

三条现行面（政策：匿名共享 default 桶可以接受，但会话与记忆按 user_id 隔离）：

1. `home.py:51 _real_conversation_count()` → `count_sessions()` **不带 user_id**；
   `home.py:183 _aggregate_daily()` → `list_sessions()` 同样不带。
   `/home/*` 的路由级门是 `get_current_user`（严格），所以任何已登录用户都能在
   首页看到**全体用户**的会话总数与按天活跃数。
2. `stats.py:176 GET /api/v1/stats/agents` 连门都没有，且按全体会话分组聚合。
   补 `get_current_user_or_default` 而不是新加硬门——保住"匿名可达"的既有行为，
   匿名只落 default 桶。
3. 身份线程：`APIRouter(dependencies=[Depends(f)])` 只执行不返回，端点里拿不到
   调用者身份——这正是本仓身份批反复踩过的"门在、值没接过来"。所以修法必须把
   依赖的**返回值**接进端点，再往下透传到计数函数。

读侧规则按 AGENTS.md §3：空属主归主管理员（role=admin 中 id 最小者），
不得对普通用户或匿名调用方可见。期望值只含调用者自己的会话。

装配口径与 `tests/integration/test_memory_route_authorization.py` 一致：真 router、
真依赖、真 SessionManager（`NEUROVA_SESSIONS_DIR` 隔离），只 override 依赖的返回身份。
夹具故意拆成"先播种 / 再起 app"两段——计数面有不依赖 app 的直接判据，
它们也必须吃到同一份隔离目录（否则会在进程里读到真实会话库去数，隔离就破了）。
"""

import inspect
import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.endpoints import home as homeMod
from neurova.api.endpoints import stats as statsMod
from neurova.api.error_handlers import register_error_handlers

ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}
BOB = {"user_id": "bob", "username": "bob", "role": "user", "neuser_id": "ne-bob"}
ANON = {"user_id": "default", "username": "default", "role": "user", "neuser_id": "default"}

# alice 2 条 + bob 1 条 + 空属主 1 条（只归主管理员 3）= 全体 4
TOTAL_ALL = 4
PER_USER = 2
PRIMARY_ADMIN = "3"


@pytest.fixture
def seededRepo(tmp_path, monkeypatch):
    """隔离的真实 SessionManager：4 条会话，属主分别为 alice/bob/空。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    from neurova.session_repository import get_session_repository, reset_session_repository

    reset_session_repository()
    import neurova.post_chat_pipeline as pcp
    monkeypatch.setattr(pcp, "_adminOwnerId", lambda: PRIMARY_ADMIN)
    repo = get_session_repository()
    for owner, title in (
        ("alice", "alice 的会话一"),
        ("alice", "alice 的会话二"),
        ("bob", "bob 的会话"),
        ("", "历史无主会话"),
    ):
        repo.create_session(agent_id="agent_x", user_id=owner, title=title)
    assert repo.count_sessions() == TOTAL_ALL, "播种失败：隔离目录里条数不对"
    return repo


@pytest.fixture
def client(seededRepo):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(homeMod.router, prefix="/api/v1")
    app.include_router(statsMod.router, prefix="/api/v1/stats")
    tc = TestClient(app)

    def asUser(identity: typing.Optional[dict]):
        tc.app.dependency_overrides.clear()
        if identity is not None:
            tc.app.dependency_overrides[get_current_user] = lambda: identity
            tc.app.dependency_overrides[get_current_user_or_default] = lambda: identity

    tc.as_user = asUser
    tc.repo = seededRepo
    return tc


def _agentConversationTotal(payload: typing.Any) -> int:
    """`/stats/agents` 返回裸 list（stats.py:219 `return results`），逐桶求和。"""
    assert isinstance(payload, list), f"响应形态与端点契约不符，判据要跟着改：{type(payload)}"
    return sum(int(item.get("conversations", 0) or 0) for item in payload)


def test_homeConversationCountExcludesOtherUsers(client):
    """/home/data 的 total_conversations 只含 alice 自己的 2 条，不含历史无主会话。"""
    client.as_user(ALICE)
    resp = client.get("/api/v1/home/data")
    assert resp.status_code == 200, resp.text
    got = resp.json()["quick_stats"]["total_conversations"]
    assert got == PER_USER, f"首页会话数未按 user_id 分桶（alice 应为 {PER_USER}，全体是 {TOTAL_ALL}）：{got}"


def test_homeTrendsExcludeOtherUsers(client):
    """/home/trends 的按天会话数同样不得把他人会话计进来。"""
    client.as_user(ALICE)
    resp = client.get("/api/v1/home/trends?days=7")
    assert resp.status_code == 200, resp.text
    series = resp.json()["conversation_trend"]["data"]
    assert sum(series) == PER_USER, f"趋势按全体会话聚合了：{sum(series)}（应 {PER_USER}）"


def test_twoUsersSeeDifferentCounts(client):
    """同一份库里两人各自计数互不穿透，且都不等于全体。"""
    client.as_user(ALICE)
    aliceCount = client.get("/api/v1/home/data").json()["quick_stats"]["total_conversations"]
    client.as_user(BOB)
    bobCount = client.get("/api/v1/home/data").json()["quick_stats"]["total_conversations"]
    assert (aliceCount, bobCount) == (PER_USER, 1), f"alice={aliceCount} bob={bobCount}"


def test_primaryAdminSeesOwnerlessSession(client):
    """历史无主会话只归主管理员，不向普通用户或匿名调用方泄露。"""
    client.as_user({"user_id": PRIMARY_ADMIN, "username": "admin", "role": "admin", "neuser_id": "3"})
    resp = client.get("/api/v1/home/data")
    assert resp.status_code == 200, resp.text
    assert resp.json()["quick_stats"]["total_conversations"] == 1


def test_agentsStatsAreUserScoped(client):
    """`/stats/agents` 按调用者分桶，bob 只看到自己的 1 条。"""
    client.as_user(BOB)
    resp = client.get("/api/v1/stats/agents")
    assert resp.status_code == 200, resp.text
    total = _agentConversationTotal(resp.json())
    assert total == 1, f"/stats/agents 未按调用者分桶（bob 应 1）：{total}"


def test_agentsStatsAllowAnonymousCaller(client):
    """匿名回落 default 桶是既有行为，但历史无主会话不属于 default。"""
    client.as_user(None)
    resp = client.get("/api/v1/stats/agents")
    assert resp.status_code == 200, f"匿名不该被硬拒：{resp.status_code} {resp.text[:120]}"
    assert _agentConversationTotal(resp.json()) == 0, "匿名不得看到历史无主会话"


def test_countFunctionsThemselvesTakeUserId(seededRepo):
    """计数函数自身也按同一属主口径分桶，空属主只计入主管理员。"""
    assert seededRepo.count_sessions(user_id="alice") == PER_USER
    assert seededRepo.count_sessions(user_id="bob") == 1
    assert seededRepo.count_sessions(user_id=PRIMARY_ADMIN) == 1
    assert seededRepo.count_sessions() == TOTAL_ALL, "不带 user_id 时仍该是全体"
    aliceRows = seededRepo.list_sessions(user_id="alice")
    adminRows = seededRepo.list_sessions(user_id=PRIMARY_ADMIN)
    assert len(aliceRows) == PER_USER
    assert all(row["user_id"] == "alice" for row in aliceRows)
    assert len(adminRows) == 1 and adminRows[0]["user_id"] == PRIMARY_ADMIN

    assert "user_id" in inspect.signature(homeMod._real_conversation_count).parameters, (
        "_real_conversation_count 仍无条件统计全体会话"
    )
    assert "user_id" in inspect.signature(homeMod._aggregate_daily).parameters, (
        "_aggregate_daily 仍无条件聚合全体会话"
    )
