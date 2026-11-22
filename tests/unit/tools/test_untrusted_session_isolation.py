# -*- coding: utf-8 -*-
"""U17 不可信会话凭据隔离（红→绿）。

契约（实施计划 U17）：分享/来宾（untrusted）会话上下文中——凭据类工具与
"凭据卡/主机确认卡"弹卡一律 fail-closed 拒绝：返回结构化
``TOOL_UNTRUSTED_SESSION``，不弹卡、不泄凭据存在性。

判定入口 = 会话信任级检查（``untrustedSessionContext``，复用既有身份面：
user_model 的持久角色 + user_group_model 的访客组；无正向证据不判不可信）。

红（现网行为）：来宾会话触发 ssh 工具 → 照常走治理/动态干预/凭据解析链
（弹审批卡/凭据卡），没有结构化拒绝。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.core.identity_context import (  # noqa: E402
    clear_request_user_id,
    set_request_user_id,
)
from neurova.tool_executor import (  # noqa: E402
    TOOL_UNTRUSTED_SESSION_CODE,
    ToolExecutor,
    untrustedSessionContext,
    _get_approval_manager,
)


def _makeExecutor(user_id: str = "u1") -> ToolExecutor:
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id=user_id, agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


@pytest.fixture
def approvalQueueIsolated():
    am = _get_approval_manager()
    am._resetForTests()
    yield am
    am._resetForTests()


@pytest.fixture
def guestUser():
    """真实建一个 role=guest 的用户（conftest 已把数据根指到会话临时区）。"""
    from neurova.auth.user_model import UserModel

    model = UserModel()
    username = f"guest_{uuid.uuid4().hex[:10]}"
    user = model.create_user(username=username, password_hash="test", role="guest")
    yield str(user.id)
    clear_request_user_id()


@pytest.fixture
def normalUser():
    from neurova.auth.user_model import UserModel

    model = UserModel()
    username = f"normal_{uuid.uuid4().hex[:10]}"
    user = model.create_user(username=username, password_hash="test", role="user")
    yield str(user.id)
    clear_request_user_id()


class TestUntrustedSessionContext:
    def test_guestRoleUserIsUntrusted(self, guestUser):
        assert untrustedSessionContext(guestUser) is True

    def test_normalRoleUserIsTrusted(self, normalUser):
        assert untrustedSessionContext(normalUser) is False

    def test_literalGuestIdentityIsUntrusted(self):
        assert untrustedSessionContext("guest") is True

    def test_emptyIdentityIsUntrusted(self):
        assert untrustedSessionContext("") is True
        assert untrustedSessionContext(None) is True

    def test_nonNumericSyntheticIdentityIsTrusted(self):
        # default / 测试替身 / 渠道合成 id：无正向证据，不判不可信
        assert untrustedSessionContext("default") is False
        assert untrustedSessionContext("u1") is False


class TestUntrustedSessionSshGate:
    @pytest.mark.asyncio
    async def test_guestSessionSshToolStructuredRejection(
        self, monkeypatch, guestUser, approvalQueueIsolated
    ):
        """绿判据：来宾会话触发 ssh 工具 → 结构化拒绝，不弹卡、不碰凭据面。"""
        executor = _makeExecutor(user_id=guestUser)
        set_request_user_id(guestUser)

        # 凭据面一旦被触碰即失败（不泄凭据存在性的硬判据）
        def _noCredentialAccess(user_id, host):
            raise AssertionError("不可信会话不得读取凭据分桶")

        import neurova.computer_use.ssh_runner as ssh_runner

        monkeypatch.setattr(ssh_runner, "resolve_ssh_credentials", _noCredentialAccess)

        result = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": "10.255.255.1", "command": "echo hi"})

        assert result.get("error_code") == TOOL_UNTRUSTED_SESSION_CODE, (
            f"来宾会话的 ssh 工具必须结构化拒绝: {result}")
        assert result.get("success") is False
        # 不弹卡：审批队列不得出现新待批项（凭据卡/主机确认卡同源审批链）
        assert not approvalQueueIsolated.get_pending_requests(), (
            "不可信会话不得弹出审批/凭据卡")
        # 不泄凭据存在性：拒绝正文不含 host 与凭据存在性线索
        text = str(result)
        assert "10.255.255.1" not in text, "拒绝信息不得回显目标主机"
        # 判据边界：不得泄露"该主机凭据是否存在/形态"；"凭据类工具不可用"
        # 这类通用工具类名不属于存在性泄漏，不在禁列。
        for leak in ("password", "key_text", "已配置", "未配置", "存在凭据", "无凭据"):
            assert leak not in text, f"拒绝信息不得携带凭据存在性线索: {leak}"

    @pytest.mark.asyncio
    async def test_guestSessionRejectionSurvivesApprovalReplay(
        self, monkeypatch, guestUser, approvalQueueIsolated
    ):
        """审批重放（skip_governance=True）不得绕过不可信会话闸。"""
        executor = _makeExecutor(user_id=guestUser)
        set_request_user_id(guestUser)
        result = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": "10.255.255.1", "command": "echo hi"},
            skip_governance=True)
        assert result.get("error_code") == TOOL_UNTRUSTED_SESSION_CODE, (
            f"审批重放路径同样必须拒绝: {result}")

    @pytest.mark.asyncio
    async def test_trustedSessionStillReachesSshExecutor(
        self, monkeypatch, normalUser, approvalQueueIsolated
    ):
        """可信会话不受闸影响：ssh 执行体照常被分派（闸只拦不可信会话）。"""
        executor = _makeExecutor(user_id=normalUser)
        set_request_user_id(normalUser)
        reached = []

        async def _spy(params):
            reached.append("computer_ssh_exec")
            return {"success": True, "reached": True}

        monkeypatch.setattr(executor, "_execute_computer_ssh_exec", _spy)

        async def _noIntervention(tool_name, params):
            return None

        monkeypatch.setattr(executor, "_dynamicInterventionCheck", _noIntervention)

        result = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": "example-host", "command": "echo hi"})
        assert reached == ["computer_ssh_exec"], (
            f"可信会话的 ssh 调用必须照常进入执行体: {result}")
        assert result.get("error_code") != TOOL_UNTRUSTED_SESSION_CODE
