# -*- coding: utf-8 -*-
"""渠道自助绑定流程判据（工单 2026-10-10 批 4）。

这格要守的是**码的语义**，不是码的算法——发码/验码都复用 `auth/verification_code`
（§6-127 裁定 ②：不另造第二套码）。本文件只问四件事：

1. 一张码只生效一次（否则截图流传出去的码就是长期通行证）；
2. 码**不跨 agent、不跨渠道**（裁定 ③＝绑定作用域是 agent 级；跨了就把隔离键打通）；
3. 要绑成谁只从码里取，渠道身份只从消息发送者取——**两条都不接受入站自带**
   （否则外部报文可自带 `user_id`，把别人的渠道身份改写到第三方账号下）；
4. 过期/错码/无账号各返回点名原因，不静默"没绑上"。
"""
from __future__ import annotations

import pytest

from neurova.channels import identity_binding
from neurova.channels.identity_binding import (
    boundAccount,
    consumeBindingCode,
    issueBindingCode,
    listBindings,
    manualBind,
    parseBindCommand,
    revoke,
)
from neurova.channels.user_identity import UserIdentityManager


@pytest.fixture
def codes(monkeypatch):
    """把码表指到内存库：判据不得往真实 `data/verification_codes.db` 写一行。"""
    from neurova.auth.verification_code import VerificationCodeModel

    model = VerificationCodeModel(":memory:")
    monkeypatch.setattr(
        "neurova.auth.verification_code.get_verification_code_model", lambda: model)
    yield model


@pytest.fixture
def bindings(tmp_path):
    UserIdentityManager.resetInstance()
    mgr = UserIdentityManager(str(tmp_path / "bindings_flow.db"))
    yield mgr
    mgr.close()
    UserIdentityManager.resetInstance()


class TestParseBindCommand:
    """只有"整条消息就是一句绑定指令"才拦截——聊天里提到绑定码不得被吃掉。"""

    @pytest.mark.parametrize("text,expected", [
        ("绑定 123456", "123456"),
        ("bind 123456", "123456"),
        ("BIND  001234", "001234"),
        ("  绑定 123456  ", "123456"),
    ])
    def test_recognisesForms(self, text, expected):
        assert parseBindCommand(text) == expected, text

    @pytest.mark.parametrize("text", [
        "绑定 12",                    # 位数不足
        "绑定 123456 谢谢",            # 尾部还有话＝不是纯指令
        "帮我绑定一下账号",             # 没码
        "绑定 abc123",                # 非数字
        "",
        None,
    ])
    def test_rejectsNonCommands(self, text):
        assert parseBindCommand(text) is None, text

    def test_bindCommandTextRoundTrips(self):
        """发码文案与解析正则同源：`parseBindCommand(bindCommandText(码))` 必须回原码。

        端点把 `command` 字段直接显示给网页，若哪天正则收紧（比如改长度）而文案没跟，
        用户照着提示发过去就永远绑不上——这格就是拦那一刀的。
        """
        for raw in ("123456", "001234", "999999"):
            assert parseBindCommand(identity_binding.bindCommandText(raw)) == raw


class TestBindingCodeFlow:
    def test_roundTripBindsSenderToPlatformAccount(self, codes, bindings):
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1", displayName="Alice")
        outcome = consumeBindingCode("a1", "feishu", "ou_9", code)

        assert outcome["ok"] is True, outcome
        assert bindings.resolveTurnIdentity("a1", "feishu", "ou_9") == {
            "user_id": "u-alice", "neuser_id": "ne-1", "bound": "true"}
        row = listBindings("a1")[0]
        assert row["bound_by"] == "bind-code"
        assert row["display_name"] == "Alice"

    def test_codeIsSingleUse(self, codes, bindings):
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1")
        assert consumeBindingCode("a1", "feishu", "ou_9", code)["ok"] is True

        second = consumeBindingCode("a1", "feishu", "ou_8", code)

        assert second == {"ok": False, "reason": "code_invalid_or_expired"}, second
        assert boundAccount("a1", "feishu", "ou_8") is None, "第二次使用不得留下绑定"

    def test_wrongCodeBindsNobody(self, codes, bindings):
        issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1")

        outcome = consumeBindingCode("a1", "feishu", "ou_9", "000000")

        assert outcome["ok"] is False, outcome
        assert boundAccount("a1", "feishu", "ou_9") is None

    def test_expiredCodeIsRefused(self, codes, bindings):
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1", ttl=-1)

        outcome = consumeBindingCode("a1", "feishu", "ou_9", code)

        assert outcome == {"ok": False, "reason": "code_invalid_or_expired"}, outcome

    def test_codeDoesNotCrossAgent(self, codes, bindings):
        """裁定 ③：作用域是 agent 级——给 a1 发的码在 a2 渠道里用不掉。"""
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1")

        assert consumeBindingCode("a2", "feishu", "ou_9", code)["ok"] is False
        assert boundAccount("a2", "feishu", "ou_9") is None
        assert consumeBindingCode("a1", "feishu", "ou_9", code)["ok"] is True, "原 agent 仍可用"

    def test_codeDoesNotCrossChannel(self, codes, bindings):
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1")

        assert consumeBindingCode("a1", "telegram", "tg_9", code)["ok"] is False
        assert boundAccount("a1", "telegram", "tg_9") is None

    def test_accountComesFromCodeAndChannelIdentityFromSender(self, codes, bindings):
        """安全边界：码里只带"绑成哪个平台账号"，被绑的渠道身份永远是**发消息的那个人**。

        码被人看到 → 只会把看到码的人自己绑上去，不会把第三方渠道身份改写到别人名下。
        """
        code = issueBindingCode("a1", "feishu", "u-alice", neuserId="ne-1")

        consumeBindingCode("a1", "feishu", "ou_intruder", code)

        assert boundAccount("a1", "feishu", "ou_intruder") == "u-alice"
        assert boundAccount("a1", "feishu", "ou_9") is None, "不该有别人的格子被改写"

    def test_codeWithoutAccountReasonsExplicitly(self, codes):
        """码有效但 metadata 里没有账号 ⇒ 点名 `code_without_account`，不假装绑定成功。

        这条存在的理由：码表与 `verification_codes` 共用，若将来别的入口在同一 target 下
        发了不带归属的码，静默成功会把"绑上了"写进用户嘴里、而表里一行都没有。
        """
        from neurova.auth.verification_code import VerificationType

        bare = codes.create_code(
            target=identity_binding.targetFor("a1", "feishu"),
            code_type=VerificationType.BIND_CHANNEL,
            metadata=None,
        )

        outcome = consumeBindingCode("a1", "feishu", "ou_9", bare)

        assert outcome == {"ok": False, "reason": "code_without_account"}, outcome

    def test_noPendingCodeReasonsExplicitly(self, codes):
        outcome = consumeBindingCode("a1", "feishu", "ou_9", "123456")

        assert outcome == {"ok": False, "reason": "no_pending_code"}, outcome


class TestRevokeAndManual:
    def test_manualBindRecordsBoundBy(self, codes, bindings):
        manualBind("a1", "feishu", "ou_9", "u-bob", neuserId="ne-2", boundBy="admin@console")

        row = listBindings("a1")[0]
        assert row["user_id"] == "u-bob"
        assert row["bound_by"] == "admin@console", "手工绑要留操作者痕迹（与码绑区分开）"

    def testRevokeKeepsTraceAndFallsBackToNamespace(self, codes, bindings):
        manualBind("a1", "feishu", "ou_9", "u-bob", neuserId="ne-2")

        assert revoke("a1", "feishu", "ou_9") is True
        assert boundAccount("a1", "feishu", "ou_9") is None
        assert bindings.resolveTurnIdentity("a1", "feishu", "ou_9")["bound"] == "false", (
            "解绑后必须回落到渠道专属命名空间，不是 default 共享桶")
        assert listBindings("a1")[0]["status"] == "revoked", "留痕：答得出这人以前算谁的"

    def testRevokeUnknownBindingReturnsFalse(self, codes, bindings):
        assert revoke("a1", "feishu", "ou_never") is False
