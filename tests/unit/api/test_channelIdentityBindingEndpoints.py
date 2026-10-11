# -*- coding: utf-8 -*-
"""渠道身份绑定端点判据（工单 2026-10-10 批 4，§6-127 裁定 ①②③）。

守的是四件可被随手改坏的事：

1. **归属只能来自登录态**——发码端点即使 body 里带了 `user_id` 也不认（否则任何登录用户
   可把别人的渠道身份挂到第三方账号下，从此读走那个人的记忆归属，不可逆）；
2. 门沿用本仓既有口径（`default` 无主 ⇒ 仅 admin；有主 ⇒ 属主或 admin），不新造第二道门；
3. **没有"指定账号去绑"的入口**：归属只从登录态取，替他人绑定那条路整体不存在（负向门）；
4. 路由字面量 `identity/bindings` 不被 `/{channel_type}` 吞掉（§6-126 那条"把故障折成
   不存在"的形态，在这里会以 404 "Channel 'identity' not configured" 出现）。

绑定表与码表都指到临时库/内存库：判据不写真实 `data/`。
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_identity_binding")

# 注意：override 的键必须是**端点文件实际 Depends 的那个对象**（neurova.api.auth 那份严格门）。
# `neurova.api.deps.get_current_user` 是同名别名（可回退 ?access_token=），打错对象会静默不生效，
# 于是判据看着绿、其实整条门没跑（见 tests/unit/api/test_identity_gate_single_source.py）。
from neurova.api.auth import get_current_user as strictIdentityGate
from neurova.api.endpoints import set_app_state
from neurova.api.endpoints import channel_config as cc
from neurova.channels import identity_binding
from neurova.channels.user_identity import UserIdentityManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "ne-root"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "ne-u1"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "ne-u2"}

BASE = "/channel-configs"


def _agentWithOwner(agent_id, owner):
    from types import SimpleNamespace

    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from neurova.auth.verification_code import VerificationCodeModel

    codes = VerificationCodeModel(":memory:")
    monkeypatch.setattr(
        "neurova.auth.verification_code.get_verification_code_model", lambda: codes)

    UserIdentityManager.resetInstance()
    bindings = UserIdentityManager(str(tmp_path / "bindings_api.db"))

    set_app_state({"agents": {
        "default": _agentWithOwner("default", None),
        "kai": _agentWithOwner("kai", "u1"),
    }})
    app = FastAPI()
    app.include_router(cc.router)
    app.dependency_overrides[strictIdentityGate] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app, bindings
    app.dependency_overrides.clear()
    set_app_state(None)
    bindings.close()
    UserIdentityManager.resetInstance()


def _as(app, identity):
    app.dependency_overrides[strictIdentityGate] = lambda: dict(identity)


class TestReadGate:
    def test_strangerCannotReadDefaultBindings(self, env):
        client, app, _ = env
        _as(app, STRANGER)

        r = client.get(f"{BASE}/identity/bindings", params={"agent_id": "default"})

        assert r.status_code == 403, r.text
        assert "无权" in r.json()["detail"], r.text

    def test_ownerReadsOwnAgent(self, env):
        client, app, bindings = env
        bindings.bindIdentity("kai", "feishu", "ou_9", "u1", neuserId="ne-u1", boundBy="admin")
        _as(app, OWNER)

        r = client.get(f"{BASE}/identity/bindings", params={"agent_id": "kai"})

        assert r.status_code == 200, r.text
        rows = r.json()["bindings"]
        assert [row["channel_user_id"] for row in rows] == ["ou_9"], rows

    def testLiteralPathIsNotSwallowedByChannelTypeRoute(self, env):
        """`identity/bindings` 必须命中绑定端点，而不是被 `/{channel_type}` 折成 404。"""
        client, app, _ = env
        _as(app, STRANGER)

        r = client.get(f"{BASE}/identity/bindings")

        detail = str(r.json().get("detail", ""))
        assert "not configured" not in detail, (r.status_code, detail)
        assert r.status_code == 403, (r.status_code, r.text)


class TestIssueCode:
    def test_codeCarriesCallerAndRoundTripsThroughChannel(self, env):
        """网页发码 → 渠道里那句"绑定 XXXX" → 绑定归属＝发码时的登录账号（完整闭环）。"""
        client, app, bindings = env
        _as(app, OWNER)

        r = client.post(f"{BASE}/identity/bindings/code",
                        json={"agent_id": "kai", "channel_type": "feishu"})

        assert r.status_code == 200, r.text
        payload = r.json()
        assert len(payload["code"]) == identity_binding.CODE_LENGTH
        assert identity_binding.parseBindCommand(payload["command"]) == payload["code"], (
            "端点回给前端的提示语与渠道解析正则不同源")

        outcome = identity_binding.consumeBindingCode(
            "kai", "feishu", "ou_77", payload["code"])

        assert outcome["ok"] is True, outcome
        assert bindings.resolveTurnIdentity("kai", "feishu", "ou_77") == {
            "user_id": "u1", "neuser_id": "ne-u1", "bound": "true"}

    def test_bodyUserIdIsIgnored(self, env):
        """报文里塞 `user_id` 不改归属——归属只认登录态（否则可把渠道身份挂到别人名下）。"""
        client, app, bindings = env
        _as(app, OWNER)

        r = client.post(f"{BASE}/identity/bindings/code", json={
            "agent_id": "kai", "channel_type": "feishu",
            "user_id": "victim", "neuser_id": "ne-victim"})

        assert r.status_code == 200, r.text
        assert r.json()["bound_user_id"] == "u1", r.text

        identity_binding.consumeBindingCode("kai", "feishu", "ou_77", r.json()["code"])

        assert bindings.resolveUserId("kai", "feishu", "ou_77") == "u1"
        assert "victim" not in str(bindings.listBindings("kai")), bindings.listBindings("kai")

    def test_codeForForeignAgentStillGated(self, env):
        client, app, _ = env
        _as(app, STRANGER)

        r = client.post(f"{BASE}/identity/bindings/code",
                        json={"agent_id": "kai", "channel_type": "feishu"})

        assert r.status_code == 403, r.text


class TestRevoke:
    def test_noRouteBindsSomeoneElsesAccount(self, env):
        """不存在"指定账号去绑"的入口：`/identity/bindings` 上 POST 不被允许（405）。

        这条是负向门。曾经有过一个手工绑端点（admin 可指定任意账号），它有两个问题：
        一是把"谁算这个渠道身份的主人"交给点面板的人，二是替他人绑时 `neuser_id`
        只能靠猜——而记忆隔离键是 `(neuser_id, user_id)` 一对，猜错就是同一个人两份记忆。
        归属只能来自登录态（发码即本人），所以那条路整体删掉，不复出。

        读数取 **405 而非 404**：这条路径本身在（GET/DELETE 都在），只是不给 POST——
        拿 404 当"入口不存在"的读数会把"路径存在但不接受此方法"与"路由没了"混成一样，
        后者才是 §6-126 点名的"把故障折成不存在"。
        """
        client, app, bindings = env
        _as(app, ADMIN)

        r = client.post(f"{BASE}/identity/bindings", json={
            "agent_id": "kai", "channel_type": "feishu",
            "channel_user_id": "ou_9", "user_id": "someone-else"})

        assert r.status_code == 405, r.text
        assert bindings.resolveUserId("kai", "feishu", "ou_9") is None, "被拒的方法不得留下副作用"

    def test_revokeRoundTrip(self, env):
        client, app, bindings = env
        bindings.bindIdentity("default", "feishu", "ou_9", "root", neuserId="ne-root")

        r = client.delete(f"{BASE}/identity/bindings", params={
            "agent_id": "default", "channel_type": "feishu", "channel_user_id": "ou_9"})

        assert r.status_code == 200, r.text
        assert bindings.resolveUserId("default", "feishu", "ou_9") is None
        assert bindings.listBindings("default")[0]["status"] == "revoked"

        again = client.delete(f"{BASE}/identity/bindings", params={
            "agent_id": "default", "channel_type": "feishu", "channel_user_id": "ou_9"})
        assert again.status_code == 404, again.text

    def test_strangerCannotRevokeForeignAgent(self, env):
        client, app, bindings = env
        bindings.bindIdentity("kai", "feishu", "ou_9", "u1", neuserId="ne-u1")
        _as(app, STRANGER)

        r = client.delete(f"{BASE}/identity/bindings", params={
            "agent_id": "kai", "channel_type": "feishu", "channel_user_id": "ou_9"})

        assert r.status_code == 403, r.text
        assert bindings.resolveUserId("kai", "feishu", "ou_9") == "u1", "门在副作用之前"


class TestObservedReadSurface:
    """批 6 的两面读接口：观察到的发送者 + 我的绑定。刻意不新增任何写入口。"""

    def test_observed_lists_senders_and_their_current_owner(self, env):
        client, app, bindings = env
        bindings.observeSender("kai", "feishu", "ou_9", displayName="张三")
        bindings.observeSender("kai", "feishu", "ou_10")
        bindings.bindIdentity("kai", "feishu", "ou_9", "u1", neuserId="ne-u1")
        _as(app, OWNER)

        r = client.get(f"{BASE}/identity/observed", params={"agent_id": "kai"})

        assert r.status_code == 200, r.text
        rows = {row["channel_user_id"]: row for row in r.json()["senders"]}
        assert set(rows) == {"ou_9", "ou_10"}
        assert rows["ou_9"]["bound_user_id"] == "u1" and rows["ou_9"]["display_name"] == "张三"
        assert rows["ou_10"]["bound_user_id"] is None

    def test_observed_can_narrow_by_channel(self, env):
        client, app, bindings = env
        bindings.observeSender("kai", "feishu", "ou_9")
        bindings.observeSender("kai", "telegram", "tg_1")
        _as(app, OWNER)

        r = client.get(f"{BASE}/identity/observed",
                       params={"agent_id": "kai", "channel_type": "telegram"})

        assert [row["channel_user_id"] for row in r.json()["senders"]] == ["tg_1"]

    def test_observed_is_gated_like_the_rest(self, env):
        client, app, _ = env
        _as(app, STRANGER)

        r = client.get(f"{BASE}/identity/observed", params={"agent_id": "default"})

        assert r.status_code == 403, r.text

    def test_listing_observed_grants_no_binding_authority(self, env):
        """负向门：把某人列进观察面**不产生**归属变化——绑定只有渠道内带码那一条路。"""
        client, app, bindings = env
        bindings.observeSender("kai", "feishu", "ou_stranger", displayName="李四")
        _as(app, ADMIN)

        listed = client.get(f"{BASE}/identity/observed", params={"agent_id": "kai"}).json()["senders"]

        assert [row for row in listed if row["channel_user_id"] == "ou_stranger"]
        assert bindings.resolveTurnIdentity("kai", "feishu", "ou_stranger")["user_id"] == (
            "ch:feishu:ou_stranger"), "列进面板就等于改归属，面板就成了越权入口"

    def test_mine_returns_callers_bindings_not_others(self, env):
        client, app, bindings = env
        bindings.bindIdentity("kai", "feishu", "ou_9", "u1", neuserId="ne-u1")
        bindings.bindIdentity("kai", "telegram", "tg_1", "u2", neuserId="ne-u2")
        _as(app, OWNER)

        r = client.get(f"{BASE}/identity/bindings/mine", params={"agent_id": "kai"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == "u1", "读的是登录态，不是报文说的谁"
        assert [(b["channel_type"], b["channel_user_id"]) for b in body["bindings"]] == [
            ("feishu", "ou_9")]
