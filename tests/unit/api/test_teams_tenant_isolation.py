# -*- coding: utf-8 -*-
"""A5 红灯：teams_api 租户隔离 + 外部成员 executor 字段契约测试。

直接调用端点协程（绕过 HTTP 层），身份字典形态与 JWT 依赖一致。
覆盖：租户戳印、读限同租户（跨租户 404 不泄露）、写限同租户+属主/admin、
executor 外部成员仅 admin、permission_mode 校验、存量无租户团队回落 default。
"""
import asyncio

import pytest

from neurova.api.endpoints import teams_api
from neurova.api.endpoints.teams_api import (
    MemberBatchAdd,
    NeuacpExecutorSpec,
    TeamCreate,
    TeamUpdate,
)


def user(uid, tenant="default", role="user"):
    return {"user_id": uid, "username": uid, "role": role, "tenant_id": tenant}


@pytest.fixture(autouse=True)
def cleanStore():
    teams_api._teams_store.clear()
    yield
    teams_api._teams_store.clear()


def makeTeam(uid, tenant, name="团队"):
    return asyncio.run(teams_api.create_team(TeamCreate(name=name), user(uid, tenant)))


def test_createTeamStampsTenantAndOwner():
    view = makeTeam("u1", "t1", "甲队")
    assert view.tenant_id == "t1"
    assert view.owner_id == "u1"


def test_listFiltersByTenant():
    makeTeam("u1", "t1", "甲一")
    makeTeam("u2", "t1", "甲二")
    makeTeam("u3", "t2", "乙一")
    listed = asyncio.run(teams_api.list_teams(user("u1", "t1")))
    assert {t.name for t in listed} == {"甲一", "甲二"}


def test_crossTenantGetReturns404():
    team = makeTeam("u1", "t1", "甲队")
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.get_team(team.id, user("u3", "t2")))
    assert "404" in str(exc.value)


def test_crossTenantWriteRejected():
    team = makeTeam("u1", "t1", "甲队")
    outsider = user("u3", "t2")
    # 跨租户一律 404（不泄露团队存在性），读/写同口径
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.update_team(team.id, TeamUpdate(name="改"), outsider))
    assert "404" in str(exc.value)
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.delete_team(team.id, outsider))
    assert "404" in str(exc.value)
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["x"]), outsider))
    assert "404" in str(exc.value)


def test_sameTenantNonOwnerWriteRejected():
    team = makeTeam("u1", "t1", "甲队")
    colleague = user("u2", "t1")
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.update_team(team.id, TeamUpdate(name="改"), colleague))
    assert "403" in str(exc.value)
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["x"]), colleague))
    assert "403" in str(exc.value)


def test_ownerAndSameTenantAdminCanWrite():
    team = makeTeam("u1", "t1", "甲队")
    updated = asyncio.run(teams_api.update_team(team.id, TeamUpdate(name="改名"), user("u1", "t1")))
    assert updated.name == "改名"
    updated = asyncio.run(teams_api.update_team(team.id, TeamUpdate(name="管理员改"), user("admin1", "t1", role="admin")))
    assert updated.name == "管理员改"


def test_adminFromOtherTenantCannotWrite():
    team = makeTeam("u1", "t1", "甲队")
    # 跨租户 admin 也 404（同租户前提优先，不泄露存在性）
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.update_team(team.id, TeamUpdate(name="越权"), user("admin2", "t2", role="admin")))
    assert "404" in str(exc.value)


def test_executorMemberRequiresAdmin():
    team = makeTeam("u1", "t1", "甲队")
    spec = NeuacpExecutorSpec(kind="acp", tool="opencode", command=["opencode", "acp"], cwd="E:/ws/demo")
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["ext-1"], executor=spec), user("u1", "t1")))
    assert "403" in str(exc.value)
    view = asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["ext-1"], prompt="负责编码", executor=spec), user("admin1", "t1", role="admin")))
    entry = [m for m in view.members_detail if m["user_id"] == "ext-1"][0]
    assert entry["executor"]["command"] == ["opencode", "acp"]
    assert entry["executor"]["cwd"] == "E:/ws/demo"
    assert entry["executor"]["permission_mode"] == "chain"


def test_executorPermissionModeValidated():
    team = makeTeam("u1", "t1", "甲队")
    spec = NeuacpExecutorSpec(kind="acp", command=["x"], cwd="E:/ws", permission_mode="wild")
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["ext-1"], executor=spec), user("admin1", "t1", role="admin")))
    assert "422" in str(exc.value)


# ── F1 线乙：能力声明配置期闸（打开前拒绝，违规 422） ─────────────────────


def test_executorSpecViolatingCapabilityRejected422():
    team = makeTeam("u1", "t1", "甲队")
    admin = user("admin1", "t1", role="admin")
    # transport 非法：pigeon 不在 opencode 声明 transports（stdio/ssh）内
    bad_transport = NeuacpExecutorSpec(
        kind="acp", tool="opencode", transport="pigeon", command=["opencode", "acp"], cwd="E:/ws/demo"
    )
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["ext-t"], executor=bad_transport), admin))
    assert "422" in str(exc.value)
    # plugin + auto 拒：plugin 家无运行中审批交互，auto 无意义
    plugin_auto = NeuacpExecutorSpec(
        kind="plugin", tool="zcode", command=["zcode"], cwd="E:/ws/demo", permission_mode="auto"
    )
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["ext-a"], executor=plugin_auto), admin))
    assert "422" in str(exc.value)
    # 被拒成员不得入名册
    view = asyncio.run(teams_api.get_team(team.id, admin))
    assert all(m["user_id"] not in ("ext-t", "ext-a") for m in view.members_detail)


def test_removeMemberGatedByTenant():
    team = makeTeam("u1", "t1", "甲队")
    asyncio.run(teams_api.add_members(team.id, MemberBatchAdd(members=["m1"]), user("u1", "t1")))
    # 跨租户 404（不泄露）；同租户属主可移除
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.remove_member(team.id, "m1", user("u3", "t2")))
    assert "404" in str(exc.value)
    result = asyncio.run(teams_api.remove_member(team.id, "m1", user("u1", "t1")))
    assert result["code"] == 0


def test_legacyTeamWithoutTenantFallsBackToDefault():
    teams_api._teams_store["legacy"] = {
        "id": "legacy", "name": "存量团队", "owner_id": "default",
        "members_detail": [], "created_at": 0, "updated_at": 0,
    }
    with pytest.raises(Exception) as exc:
        asyncio.run(teams_api.get_team("legacy", user("u1", "t1")))
    assert "404" in str(exc.value)
    view = asyncio.run(teams_api.get_team("legacy", user("u9", "default")))
    assert view.tenant_id == "default"
