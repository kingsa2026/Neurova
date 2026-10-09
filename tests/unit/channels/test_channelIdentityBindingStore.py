# -*- coding: utf-8 -*-
"""渠道身份绑定存储的判据（工单 `2026-10-10-渠道身份绑定与群聊记忆分账` 批 1）。

只测存储与解析本身；渠道路径**尚未**接它（那是批 2），所以这里不碰 `channel_router`。
四件容易悄悄退让的事各有一格：作用域到 agent 级（裁定 ③）、多渠道可共号（裁定 ①的前提）、
解绑留痕、以及"这张表不得重新制造 `default` 共享桶"（§6-123 的成因不能由修复方再造回去）。
第 ⑦ 格是跨模块同步钉：命名空间口径与技能库 `resolve_user_key` 必须逐字同形，
否则同一个渠道用户会在技能库、记忆、审计三处变成三个人。
"""

import time

import pytest

from neurova.channels.user_identity import UserIdentityManager
from neurova.skills.skill_visibility import resolve_user_key


@pytest.fixture
def mgr(tmp_path):
    UserIdentityManager.resetInstance()
    instance = UserIdentityManager(str(tmp_path / "bindings.db"))
    yield instance
    UserIdentityManager.resetInstance()


def test_bindThenResolve(mgr):
    mgr.bindIdentity("a1", "feishu", "ou_55", "u-alice", boundBy="admin")
    assert mgr.resolveUserId("a1", "feishu", "ou_55") == "u-alice"
    assert mgr.listBindings("a1")[0]["bound_by"] == "admin"


def test_severalChannelsMayShareOneAccount(mgr):
    """裁定 ①的正向面：不同渠道的发送者绑到同一个平台账号，反查能一次看全。"""
    mgr.bindIdentity("a1", "feishu", "ou_55", "u-alice")
    mgr.bindIdentity("a1", "telegram", "tg-1", "u-alice")
    assert mgr.resolveUserId("a1", "feishu", "ou_55") == "u-alice"
    assert mgr.resolveUserId("a1", "telegram", "tg-1") == "u-alice"
    bound = mgr.boundChannelUsers("a1", "u-alice")
    assert {(b["channel_type"], b["channel_user_id"]) for b in bound} == {
        ("feishu", "ou_55"), ("telegram", "tg-1")}


def test_bindingIsScopedPerAgent(mgr):
    """裁定 ③＝agent 级：绑一次只认一个 bot，别让用户以为全局通了。"""
    mgr.bindIdentity("a1", "telegram", "tg-1", "u-alice")
    assert mgr.resolveUserId("a2", "telegram", "tg-1") is None, (
        "另一个 agent 认了这条绑定 ⇒ 作用域退化成平台级（与裁定 ③相反，"
        "且跨 agent 的身份会串用）"
    )


def test_rebindingChangesOwnerAndKeepsOneRow(mgr):
    mgr.bindIdentity("a1", "telegram", "tg-1", "u-alice")
    time.sleep(0.01)
    mgr.bindIdentity("a1", "telegram", "tg-1", "u-bob", boundBy="migrate")
    assert mgr.resolveUserId("a1", "telegram", "tg-1") == "u-bob"
    rows = mgr.listBindings("a1")
    assert len(rows) == 1, "换主应当覆盖同一行，而不是留下两条互相矛盾的绑定"
    assert rows[0]["updated_at"] >= rows[0]["created_at"]


def test_revokeKeepsTraceAndStopsResolving(mgr):
    mgr.bindIdentity("a1", "telegram", "tg-1", "u-alice")
    assert mgr.revokeBinding("a1", "telegram", "tg-1") is True
    assert mgr.resolveUserId("a1", "telegram", "tg-1") is None
    assert mgr.listBindings("a1")[0]["status"] == "revoked", (
        "解绑被物理删行就答不出「这个人以前算谁的」——审计链断在这儿"
    )
    assert mgr.revokeBinding("a1", "telegram", "tg-1") is False, "重复解绑不该报成功"


def test_defaultIdentityCannotBeBound(mgr):
    """本表不得重新制造 §6-123 的成因：把渠道发送者塞回 `default` 共享桶。"""
    for forbidden in ("default", "", "  ", "DEFAULT"):
        with pytest.raises(ValueError):
            mgr.bindIdentity("a1", "telegram", "tg-1", forbidden)
    with pytest.raises(ValueError):
        mgr.bindIdentity("", "telegram", "tg-1", "u-alice")


def test_namespaceMatchesTheSkillLibraryKey(mgr):
    """未绑定命名空间与技能库同源：同一个人不能在三处变成三个人。"""
    produced = mgr.channelNamespace("feishu", "ou_55")
    assert produced == resolve_user_key(
        channel_user_id="ou_55", channel="feishu"), (
        f"渠道命名空间与 `resolve_user_key` 分叉（{produced!r} vs "
        f"{resolve_user_key(channel_user_id='ou_55', channel='feishu')!r}）："
        "技能库按一个键分、记忆与审计按另一个键分，等于同一个人两套历史"
    )
    assert mgr.channelNamespace("", "ou_55") == "", "缺渠道时不该拼出一个可用键"
